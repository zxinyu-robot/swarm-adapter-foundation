#include "check.h"
#include "swarm_adapter/dds/link_probe.h"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <thread>

using namespace swarm_adapter;
using namespace swarm_adapter::dds;

namespace {

void test_qos_mapping() {
    TopicPolicy policy;
    policy.reliability = Reliability::Reliable;
    policy.history_depth = 5;
    policy.target_rate_hz = 10.0;
    policy.deadline_ms = 150;
    policy.priority = 3;
    policy.compression_level = 6;
    const DdsQosSpec spec = map_qos(policy, 500);
    expect(spec.reliable, "reliable maps to RELIABLE");
    expect(spec.history_depth == 5, "history depth");
    expect(spec.deadline_ns == 150'000'000, "deadline in ns");
    expect(spec.transport_priority == 3, "priority -> transport_priority");
    expect(spec.lifespan_ns == 500'000'000, "ttl -> lifespan");

    TopicPolicy best_effort;
    best_effort.history_depth = 0;
    const DdsQosSpec be = map_qos(best_effort, 0);
    expect(!be.reliable && be.history_depth == 1, "best effort, depth clamped to 1");
    expect(be.deadline_ns == 0 && be.lifespan_ns == 0, "no deadline, no lifespan");
}

void test_round_trip() {
    DdsParticipant participant;
    expect(participant.ok(), "participant");
    DdsReceiver receiver(participant, MessageClass::Submap);
    expect(receiver.ok(), "receiver");
    DdsTransport transport(participant);
    TopicPolicy policy;
    policy.reliability = Reliability::Reliable;
    policy.history_depth = 32;

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (transport.matched_readers(MessageClass::Submap, map_qos(policy, 0)) < 1 &&
           std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    MessageEnvelope env;
    env.robot_id = 7;
    env.session_id = 3;
    env.message_class = MessageClass::Submap;
    env.frame_id = "map";
    env.map_version = 42;
    env.confidence = 0.9;
    env.ttl_ms = 0;
    MessageEnvelope bad = env;
    bad.map_version = 0;
    expect(transport.publish(bad, policy, fusion::ByteView{}) == ReasonCode::UnknownMapVersion,
           "map_version 0 rejected before the wire");

    constexpr int kCount = 20;
    for (int i = 1; i <= kCount; ++i) {
        env.sequence = static_cast<std::uint64_t>(1000 + i);
        env.source_time_ns = wall_clock_ns();
        const std::string payload = "submap-" + std::to_string(i);
        expect(transport.publish(env, policy, fusion::ByteView::of(payload), 99) == ReasonCode::Ok,
               "publish");
    }
    std::vector<ReceivedMessage> got;
    const auto until = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (got.size() < kCount + 1 && std::chrono::steady_clock::now() < until) {
        receiver.take(got, DDS_MSECS(100));
    }
    std::size_t probe_messages = 0;
    for (const ReceivedMessage& m : got) {
        if (m.envelope.sequence > 1000) {
            ++probe_messages;
            const std::string text(reinterpret_cast<const char*>(m.payload.data()), m.payload.size());
            expect(text == "submap-" + std::to_string(m.envelope.sequence - 1000), "payload intact");
            expect(m.envelope.robot_id == 7 && m.envelope.session_id == 3, "ids");
            expect(m.envelope.map_version == 42 && m.envelope.frame_id == "map", "map fields");
            expect(m.decision_id == 99, "decision id");
            expect(m.receive_time_ns >= m.envelope.source_time_ns, "receive after send");
        }
    }
    expect(probe_messages == kCount, "every message exactly once across both readers");
}

void test_probe_loopback() {
    char dir_template[] = "/tmp/swarm_probe_XXXXXX";
    const char* dir = mkdtemp(dir_template);
    expect(dir != nullptr, "temp dir");

    ProbeConfig config;
    config.robot_id = 11;
    config.message_class = MessageClass::Keyframe;
    config.base_rate_hz = 50.0;
    config.payload_bytes = 512;
    config.window_s = 0.6;
    config.windows = 4;
    config.match_timeout_s = 5.0;
    config.rx_idle_exit_s = 1.5;
    config.rx_max_duration_s = 20.0;
    config.records_dir = dir;

    int rx_rc = -1;
    std::thread rx([&] {
        DdsParticipant participant;
        rx_rc = run_probe_rx(participant, config, stderr);
    });
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    DdsParticipant participant;
    ProbeSummary summary;
    const int tx_rc = run_probe_tx(participant, config, summary, stderr);
    rx.join();

    expect(tx_rc == 0 && rx_rc == 0, "probe roles succeed");
    expect(summary.outcomes == config.windows, "one outcome per window");
    expect(summary.mean_delivered > 0.8, "loopback delivers");
    expect(summary.trainable >= 1, "clock synchronised on loopback");
    std::ifstream segment(summary.segment_path);
    expect(segment.good(), "segment written");
    std::string line;
    std::size_t lines = 0;
    while (std::getline(segment, line)) {
        ++lines;
    }
    expect(lines >= 3 * config.windows, "observation + decision + outcome per window");
}

}  // namespace

int main() {
    test_qos_mapping();
    test_round_trip();
    test_probe_loopback();
    std::puts("dds_tests passed");
    return 0;
}
