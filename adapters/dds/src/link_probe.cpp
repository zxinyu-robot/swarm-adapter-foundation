#include "swarm_adapter/dds/link_probe.h"

#include "swarm_adapter/link/clock_offset_estimator.h"
#include "swarm_adapter/link/freshness.h"
#include "swarm_adapter/strategy/ring_strategy_store.h"
#include "swarm_adapter/strategy/safety_envelope.h"
#include "swarm_link.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <map>
#include <mutex>
#include <random>
#include <thread>
#include <vector>

namespace swarm_adapter::dds {
namespace {

using Clock = std::chrono::steady_clock;
using strategy::CommAction;
using strategy::LinkFeatures;
using strategy::Outcome;

constexpr const char* kClockRequestTopic = "swarm_adapter_v1_clock_req";
constexpr const char* kClockReplyTopic = "swarm_adapter_v1_clock_rep";
constexpr const char* kFeedbackTopic = "swarm_adapter_v1_feedback";
constexpr std::int64_t kPingPeriodNs = 200'000'000;
constexpr auto kFeedbackPeriod = std::chrono::milliseconds(250);

/// 辅助 topic 的 reader/writer 及其 topic 句柄，析构时释放。
class AuxEndpoints {
public:
    explicit AuxEndpoints(dds_entity_t participant) : participant_(participant) {}
    ~AuxEndpoints() {
        for (auto it = entities_.rbegin(); it != entities_.rend(); ++it) {
            dds_delete(*it);
        }
    }
    AuxEndpoints(const AuxEndpoints&) = delete;
    AuxEndpoints& operator=(const AuxEndpoints&) = delete;

    dds_entity_t topic(const dds_topic_descriptor_t* desc, const char* name) {
        return keep(dds_create_topic(participant_, desc, name, nullptr, nullptr));
    }
    dds_entity_t reader(dds_entity_t topic, std::int32_t depth) {
        return endpoint(topic, depth, true);
    }
    dds_entity_t writer(dds_entity_t topic, std::int32_t depth) {
        return endpoint(topic, depth, false);
    }

private:
    dds_entity_t endpoint(dds_entity_t topic, std::int32_t depth, bool is_reader) {
        DdsQosSpec spec;
        spec.reliable = true;
        spec.history_depth = depth;
        dds_qos_t* qos = make_qos(spec);
        const dds_entity_t e = is_reader ? dds_create_reader(participant_, topic, qos, nullptr)
                                         : dds_create_writer(participant_, topic, qos, nullptr);
        dds_delete_qos(qos);
        return keep(e);
    }
    dds_entity_t keep(dds_entity_t e) {
        if (e > 0) {
            entities_.push_back(e);
        }
        return e;
    }
    dds_entity_t participant_;
    std::vector<dds_entity_t> entities_;
};

template <typename T, std::size_t N>
std::size_t take_plain(dds_entity_t reader, T (&buffer)[N]) {
    void* ptrs[N];
    dds_sample_info_t infos[N];
    for (std::size_t i = 0; i < N; ++i) {
        ptrs[i] = &buffer[i];
    }
    const dds_return_t n = dds_take(reader, ptrs, infos, N, static_cast<std::uint32_t>(N));
    std::size_t valid = 0;
    for (dds_return_t i = 0; i < n; ++i) {
        if (infos[i].valid_data) {
            buffer[valid++] = buffer[i];
        }
    }
    return valid;
}

dds_entity_t waitset_on(dds_entity_t participant, dds_entity_t reader) {
    const dds_entity_t ws = dds_create_waitset(participant);
    dds_set_status_mask(reader, DDS_DATA_AVAILABLE_STATUS);
    dds_waitset_attach(ws, reader, reader);
    return ws;
}

strategy::NetworkModeTag mode_for(double loss) {
    if (loss < 0.05) {
        return strategy::NetworkModeTag::Healthy;
    }
    return loss < 0.15 ? strategy::NetworkModeTag::Constrained
                       : strategy::NetworkModeTag::Critical;
}

struct WindowStat {
    CommAction action;
    std::uint32_t sent{};
    std::uint64_t bytes{};
};

}  // namespace

int run_probe_tx(DdsParticipant& participant, const ProbeConfig& config, ProbeSummary& summary,
                 std::FILE* log) {
    summary = {};
    const dds_entity_t pp = participant.handle();
    DdsTransport transport(participant);
    AuxEndpoints aux(pp);
    const dds_entity_t req_reader =
        aux.reader(aux.topic(&swarm_adapter_dds_ClockPing_desc, kClockRequestTopic), 64);
    const dds_entity_t rep_writer =
        aux.writer(aux.topic(&swarm_adapter_dds_ClockPing_desc, kClockReplyTopic), 64);
    const dds_entity_t fb_reader =
        aux.reader(aux.topic(&swarm_adapter_dds_LinkFeedback_desc, kFeedbackTopic), 1);
    if (req_reader <= 0 || rep_writer <= 0 || fb_reader <= 0) {
        return 2;
    }

    std::atomic<bool> stop{false};
    std::thread clock_service([&] {
        const dds_entity_t ws = waitset_on(pp, req_reader);
        swarm_adapter_dds_ClockPing pings[16];
        while (!stop.load()) {
            dds_attach_t triggered[1];
            dds_waitset_wait(ws, triggered, 1, DDS_MSECS(100));
            const std::int64_t t2 = wall_clock_ns();
            const std::size_t n = take_plain(req_reader, pings);
            for (std::size_t i = 0; i < n; ++i) {
                if (pings[i].reply) {
                    continue;
                }
                swarm_adapter_dds_ClockPing reply = pings[i];
                reply.t2_ns = t2;
                reply.reply = true;
                reply.t3_ns = wall_clock_ns();
                dds_write(rep_writer, &reply);
            }
        }
        dds_delete(ws);
    });

    const strategy::SafetyEnvelope envelope;
    std::vector<CommAction> actions;
    for (const CommAction& a : envelope.candidates(config.message_class)) {
        if (a.compression_level == 0) {
            actions.push_back(a);
        }
    }
    TopicPolicy base;
    base.reliability = Reliability::BestEffort;
    base.history_depth = 8;
    base.target_rate_hz = config.base_rate_hz;
    base.deadline_ms = config.deadline_ms;
    base.priority = 1;

    int rc = actions.empty() ? 2 : 0;
    if (rc == 0) {
        const auto match_deadline =
            Clock::now() + std::chrono::duration_cast<Clock::duration>(
                               std::chrono::duration<double>(config.match_timeout_s));
        for (const CommAction& a : actions) {
            const DdsQosSpec spec =
                map_qos(envelope.apply(config.message_class, base, a), config.ttl_ms);
            while (transport.matched_readers(config.message_class, spec) < 1 &&
                   Clock::now() < match_deadline) {
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
            }
        }
        if (Clock::now() >= match_deadline) {
            std::fprintf(log, "tx: warning: not all writers matched a reader\n");
        }
    }

    strategy::RingStrategyStore store(4096);
    std::mt19937_64 rng(config.seed);
    const std::vector<std::byte> payload(config.payload_bytes, std::byte{0x5a});
    std::map<std::uint64_t, WindowStat> stats;
    std::map<std::uint64_t, swarm_adapter_dds_LinkFeedback> feedback;
    LinkFeatures features{};
    std::uint64_t sequence = 0;
    const double budget_bytes =
        config.base_rate_hz * static_cast<double>(config.payload_bytes) * config.window_s;
    double delivered_sum = 0.0;
    double on_time_sum = 0.0;

    auto drain_feedback = [&] {
        swarm_adapter_dds_LinkFeedback buffer[32];
        std::size_t n = 0;
        while ((n = take_plain(fb_reader, buffer)) > 0) {
            for (std::size_t i = 0; i < n; ++i) {
                feedback[buffer[i].decision_id] = buffer[i];
            }
        }
    };

    auto finalize = [&](std::uint64_t decision_id) {
        drain_feedback();
        const WindowStat& st = stats[decision_id];
        const auto fb = feedback.find(decision_id);
        const bool have = fb != feedback.end();
        const double sent = static_cast<double>(st.sent);
        Outcome outcome;
        if (st.sent > 0 && have) {
            outcome.delivered_ratio = std::min(1.0, fb->second.received / sent);
            outcome.on_time_ratio = std::min(1.0, fb->second.on_time / sent);
        }
        outcome.bandwidth_ratio = budget_bytes > 0 ? static_cast<double>(st.bytes) / budget_bytes : 0;
        const bool trainable = have && fb->second.clock_synchronized;
        store.append(strategy::OutcomeRecord{decision_id, wall_clock_ns(), outcome,
                                             have ? fb->second.clock_uncertainty_ns : 0,
                                             trainable});
        const double mean_age_ns = have ? static_cast<double>(fb->second.mean_age_ns) : 0.0;
        features.packet_loss_ratio = 1.0 - outcome.delivered_ratio;
        features.latency_s = mean_age_ns / 1e9;
        features.queue_fill_ratio = 0.0;
        features.age_ratio = std::min(strategy::kMaxAgeRatio,
                                      mean_age_ns / (static_cast<double>(config.deadline_ms) * 1e6));
        ++summary.outcomes;
        summary.trainable += trainable ? 1 : 0;
        delivered_sum += outcome.delivered_ratio;
        on_time_sum += outcome.on_time_ratio;
        std::fprintf(log,
                     "window %3llu rate_scale=%.2f reliable=%d sent=%u delivered=%.3f "
                     "on_time=%.3f mean_age_ms=%.2f utility=%.3f trainable=%d\n",
                     static_cast<unsigned long long>(decision_id), st.action.rate_scale,
                     st.action.reliable ? 1 : 0, st.sent, outcome.delivered_ratio,
                     outcome.on_time_ratio, mean_age_ns / 1e6,
                     strategy::outcome_utility(outcome), trainable ? 1 : 0);
        std::fflush(log);
    };

    for (std::uint64_t w = 1; rc == 0 && w <= config.windows; ++w) {
        const CommAction action = actions[rng() % actions.size()];
        const TopicPolicy policy = envelope.apply(config.message_class, base, action);
        const std::int64_t now = wall_clock_ns();
        store.append(strategy::LinkObservationRecord{w, now, config.robot_id, config.message_class,
                                                     mode_for(features.packet_loss_ratio),
                                                     features});
        store.append(strategy::ConfigDecisionRecord{w, now, config.robot_id, config.message_class,
                                                    features, action,
                                                    strategy::DecisionSource::LocalRule, 0});
        WindowStat& st = stats[w];
        st.action = action;
        const auto interval = std::chrono::duration_cast<Clock::duration>(
            std::chrono::duration<double>(1.0 / std::max(0.1, policy.target_rate_hz)));
        const auto start = Clock::now();
        const auto end = start + std::chrono::duration_cast<Clock::duration>(
                                     std::chrono::duration<double>(config.window_s));
        for (auto next = start; next < end; next += interval) {
            std::this_thread::sleep_until(next);
            MessageEnvelope env;
            env.robot_id = config.robot_id;
            env.session_id = 1;
            env.sequence = ++sequence;
            env.source_time_ns = wall_clock_ns();
            env.message_class = config.message_class;
            env.frame_id = "map";
            env.map_version = 1;
            env.confidence = 1.0;
            env.ttl_ms = config.ttl_ms;
            env.payload_bytes = payload.size();
            if (transport.publish(env, policy, fusion::ByteView(payload.data(), payload.size()),
                                  w) == ReasonCode::Ok) {
                ++st.sent;
                st.bytes += payload.size();
            }
        }
        if (w > 1) {
            finalize(w - 1);
        }
    }
    if (rc == 0 && config.windows > 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1500));
        finalize(config.windows);
    }
    stop.store(true);
    clock_service.join();

    if (summary.outcomes > 0) {
        summary.mean_delivered = delivered_sum / static_cast<double>(summary.outcomes);
        summary.mean_on_time = on_time_sum / static_cast<double>(summary.outcomes);
    }
    if (rc == 0 && !config.records_dir.empty() &&
        store.flush_segment(config.records_dir, summary.segment_path) != ReasonCode::Ok) {
        rc = 3;
    }
    return rc;
}

int run_probe_rx(DdsParticipant& participant, const ProbeConfig& config, std::FILE* log) {
    const dds_entity_t pp = participant.handle();
    DdsReceiver receiver(participant, config.message_class);
    AuxEndpoints aux(pp);
    const dds_entity_t req_writer =
        aux.writer(aux.topic(&swarm_adapter_dds_ClockPing_desc, kClockRequestTopic), 64);
    const dds_entity_t rep_reader =
        aux.reader(aux.topic(&swarm_adapter_dds_ClockPing_desc, kClockReplyTopic), 64);
    const dds_entity_t fb_writer =
        aux.writer(aux.topic(&swarm_adapter_dds_LinkFeedback_desc, kFeedbackTopic), 1);
    if (!receiver.ok() || req_writer <= 0 || rep_reader <= 0 || fb_writer <= 0) {
        return 2;
    }

    std::mutex clock_mutex;
    link::ClockOffsetEstimator clock(31, config.clock_max_deviation_ns);
    const link::FreshnessEvaluator freshness(config.clock_max_deviation_ns);
    std::atomic<bool> stop{false};
    std::thread pinger([&] {
        const dds_entity_t ws = waitset_on(pp, rep_reader);
        swarm_adapter_dds_ClockPing replies[16];
        std::uint64_t ping_id = 0;
        while (!stop.load()) {
            swarm_adapter_dds_ClockPing ping{};
            ping.robot_id = config.robot_id;
            ping.ping_id = ++ping_id;
            ping.t1_ns = wall_clock_ns();
            dds_write(req_writer, &ping);
            const std::int64_t until = ping.t1_ns + kPingPeriodNs;
            for (std::int64_t now = wall_clock_ns(); now < until && !stop.load();
                 now = wall_clock_ns()) {
                dds_attach_t triggered[1];
                dds_waitset_wait(ws, triggered, 1, until - now);
                const std::int64_t t4 = wall_clock_ns();
                const std::size_t n = take_plain(rep_reader, replies);
                for (std::size_t i = 0; i < n; ++i) {
                    const auto& r = replies[i];
                    if (!r.reply) {
                        continue;
                    }
                    const std::int64_t rtt = (t4 - r.t1_ns) - (r.t3_ns - r.t2_ns);
                    std::lock_guard<std::mutex> lock(clock_mutex);
                    clock.observe(r.t3_ns, t4, std::max<std::int64_t>(0, rtt));
                }
            }
        }
        dds_delete(ws);
    });

    struct Acc {
        std::uint32_t received{};
        std::uint32_t on_time{};
        std::uint64_t bytes{};
        std::int64_t age_sum_ns{};
    };
    std::map<std::uint64_t, Acc> acc;
    std::vector<ReceivedMessage> messages;
    const auto start = Clock::now();
    auto last_rx = start;
    auto last_feedback = start;
    auto last_log = start;
    bool seen_any = false;
    std::size_t total = 0;

    auto estimate = [&] {
        std::lock_guard<std::mutex> lock(clock_mutex);
        return clock.estimate();
    };
    auto publish_feedback = [&](const link::ClockEstimate& est) {
        std::size_t emitted = 0;
        for (auto it = acc.rbegin(); it != acc.rend() && emitted < 4; ++it, ++emitted) {
            swarm_adapter_dds_LinkFeedback fb{};
            fb.robot_id = config.robot_id;
            fb.decision_id = it->first;
            fb.received = it->second.received;
            fb.on_time = it->second.on_time;
            fb.bytes = it->second.bytes;
            fb.mean_age_ns = it->second.received > 0 ? it->second.age_sum_ns / it->second.received : 0;
            fb.clock_uncertainty_ns = est.median_absolute_deviation_ns;
            fb.clock_synchronized = est.synchronized;
            dds_write(fb_writer, &fb);
        }
    };

    for (;;) {
        messages.clear();
        receiver.take(messages, DDS_MSECS(20));
        const auto now = Clock::now();
        const link::ClockEstimate est = estimate();
        for (const ReceivedMessage& m : messages) {
            link::FreshnessSample sample;
            freshness.evaluate(m.envelope, m.receive_time_ns, est, config.deadline_ms, sample);
            Acc& a = acc[m.decision_id];
            ++a.received;
            a.on_time += sample.on_time ? 1 : 0;
            a.bytes += m.payload.size();
            a.age_sum_ns += sample.age_ns;
        }
        if (!messages.empty()) {
            seen_any = true;
            last_rx = now;
            total += messages.size();
        }
        if (now - last_feedback >= kFeedbackPeriod) {
            publish_feedback(est);
            last_feedback = now;
        }
        if (now - last_log >= std::chrono::seconds(5)) {
            std::fprintf(log, "rx: samples=%zu clock_offset_ms=%.3f clock_mad_ms=%.3f synced=%d\n",
                         total, static_cast<double>(est.offset_ns) / 1e6,
                         static_cast<double>(est.median_absolute_deviation_ns) / 1e6,
                         est.synchronized ? 1 : 0);
            std::fflush(log);
            last_log = now;
        }
        const double elapsed = std::chrono::duration<double>(now - start).count();
        const double idle = std::chrono::duration<double>(now - last_rx).count();
        if ((seen_any && idle > config.rx_idle_exit_s) ||
            (!seen_any && elapsed > 4.0 * config.match_timeout_s) ||
            (config.rx_max_duration_s > 0 && elapsed > config.rx_max_duration_s)) {
            break;
        }
    }
    publish_feedback(estimate());
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    stop.store(true);
    pinger.join();
    std::fprintf(log, "rx: done samples=%zu decisions=%zu\n", total, acc.size());
    return seen_any ? 0 : 1;
}

}  // namespace swarm_adapter::dds
