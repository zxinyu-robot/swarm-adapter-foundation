#include "swarm_adapter/dds/dds_transport.h"

#include "swarm_link.h"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <tuple>

namespace swarm_adapter::dds {
namespace {

constexpr std::size_t kRememberedSequences = 65536;
constexpr std::uint32_t kTakeBatch = 64;

auto tie(const DdsQosSpec& s) {
    return std::tie(s.reliable, s.history_depth, s.deadline_ns, s.transport_priority,
                    s.lifespan_ns);
}

MessageClass to_class(std::uint8_t value) {
    return static_cast<MessageClass>(value);
}

}  // namespace

bool operator<(const DdsQosSpec& a, const DdsQosSpec& b) noexcept { return tie(a) < tie(b); }
bool operator==(const DdsQosSpec& a, const DdsQosSpec& b) noexcept { return tie(a) == tie(b); }

DdsQosSpec map_qos(const TopicPolicy& policy, std::int64_t ttl_ms) noexcept {
    DdsQosSpec spec;
    spec.reliable = policy.reliability == Reliability::Reliable;
    spec.history_depth = static_cast<std::int32_t>(std::max<std::size_t>(1, policy.history_depth));
    spec.deadline_ns = policy.deadline_ms > 0 ? policy.deadline_ms * 1'000'000 : 0;
    spec.transport_priority = policy.priority;
    spec.lifespan_ns = ttl_ms > 0 ? ttl_ms * 1'000'000 : 0;
    return spec;
}

dds_qos_t* make_qos(const DdsQosSpec& spec) {
    dds_qos_t* qos = dds_create_qos();
    dds_qset_reliability(qos, spec.reliable ? DDS_RELIABILITY_RELIABLE : DDS_RELIABILITY_BEST_EFFORT,
                         DDS_MSECS(100));
    dds_qset_history(qos, DDS_HISTORY_KEEP_LAST, spec.history_depth);
    dds_qset_durability(qos, DDS_DURABILITY_VOLATILE);
    dds_qset_deadline(qos, spec.deadline_ns > 0 ? spec.deadline_ns : DDS_INFINITY);
    dds_qset_transport_priority(qos, spec.transport_priority);
    dds_qset_lifespan(qos, spec.lifespan_ns > 0 ? spec.lifespan_ns : DDS_INFINITY);
    return qos;
}

std::string topic_name(MessageClass message_class) {
    return std::string("swarm_adapter_v1_") + message_class_name(message_class);
}

std::int64_t wall_clock_ns() noexcept {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

DdsParticipant::DdsParticipant(dds_domainid_t domain)
    : handle_(dds_create_participant(domain, nullptr, nullptr)) {}

DdsParticipant::~DdsParticipant() {
    if (handle_ > 0) {
        dds_delete(handle_);
    }
}

bool DdsTransport::WriterKey::operator<(const WriterKey& other) const noexcept {
    if (message_class != other.message_class) {
        return message_class < other.message_class;
    }
    return spec < other.spec;
}

DdsTransport::DdsTransport(DdsParticipant& participant) : participant_(participant.handle()) {}

DdsTransport::~DdsTransport() {
    for (const auto& entry : writers_) {
        dds_delete(entry.second);
    }
    for (dds_entity_t t : topics_) {
        if (t > 0) {
            dds_delete(t);
        }
    }
}

dds_entity_t DdsTransport::topic(MessageClass message_class) {
    const auto index = static_cast<std::size_t>(message_class);
    if (index >= topics_.size()) {
        return -1;
    }
    if (topics_[index] <= 0) {
        topics_[index] = dds_create_topic(participant_, &swarm_adapter_dds_LinkSample_desc,
                                          topic_name(message_class).c_str(), nullptr, nullptr);
    }
    return topics_[index];
}

dds_entity_t DdsTransport::writer(MessageClass message_class, const DdsQosSpec& spec) {
    const WriterKey key{message_class, spec};
    const auto found = writers_.find(key);
    if (found != writers_.end()) {
        return found->second;
    }
    const dds_entity_t t = topic(message_class);
    if (t <= 0) {
        return t;
    }
    dds_qos_t* qos = make_qos(spec);
    const dds_entity_t w = dds_create_writer(participant_, t, qos, nullptr);
    dds_delete_qos(qos);
    if (w > 0) {
        writers_.emplace(key, w);
    }
    return w;
}

std::int64_t DdsTransport::matched_readers(MessageClass message_class, const DdsQosSpec& spec) {
    const dds_entity_t w = writer(message_class, spec);
    if (w <= 0) {
        return -1;
    }
    dds_publication_matched_status_t status{};
    if (dds_get_publication_matched_status(w, &status) != DDS_RETCODE_OK) {
        return -1;
    }
    return status.current_count;
}

ReasonCode DdsTransport::publish(const MessageEnvelope& envelope, const TopicPolicy& policy,
                                 fusion::ByteView payload) {
    return publish(envelope, policy, payload, 0);
}

ReasonCode DdsTransport::publish(const MessageEnvelope& envelope, const TopicPolicy& policy,
                                 fusion::ByteView payload, std::uint64_t decision_id) {
    if (envelope.map_version == 0) {
        return ReasonCode::UnknownMapVersion;
    }
    const dds_entity_t w = writer(envelope.message_class, map_qos(policy, envelope.ttl_ms));
    if (w <= 0) {
        return ReasonCode::IoError;
    }
    swarm_adapter_dds_LinkSample sample{};
    sample.robot_id = envelope.robot_id;
    sample.message_class = static_cast<std::uint8_t>(envelope.message_class);
    sample.session_id = envelope.session_id;
    sample.seq_no = envelope.sequence;
    sample.decision_id = decision_id;
    sample.source_time_ns = envelope.source_time_ns;
    sample.map_version = envelope.map_version;
    sample.confidence = envelope.confidence;
    sample.uncertainty = envelope.uncertainty;
    sample.ttl_ms = envelope.ttl_ms;
    sample.frame_id = const_cast<char*>(envelope.frame_id.c_str());
    sample.payload._maximum = static_cast<std::uint32_t>(payload.size());
    sample.payload._length = static_cast<std::uint32_t>(payload.size());
    sample.payload._buffer = reinterpret_cast<std::uint8_t*>(const_cast<std::byte*>(payload.data()));
    sample.payload._release = false;
    return dds_write(w, &sample) == DDS_RETCODE_OK ? ReasonCode::Ok : ReasonCode::IoError;
}

DdsReceiver::DdsReceiver(DdsParticipant& participant, MessageClass message_class,
                         std::int32_t history_depth) {
    const dds_entity_t p = participant.handle();
    topic_ = dds_create_topic(p, &swarm_adapter_dds_LinkSample_desc,
                              topic_name(message_class).c_str(), nullptr, nullptr);
    if (topic_ <= 0) {
        return;
    }
    DdsQosSpec spec;
    spec.history_depth = history_depth;
    spec.reliable = true;
    dds_qos_t* qos = make_qos(spec);
    reliable_ = dds_create_reader(p, topic_, qos, nullptr);
    spec.reliable = false;
    dds_delete_qos(qos);
    qos = make_qos(spec);
    best_effort_ = dds_create_reader(p, topic_, qos, nullptr);
    dds_delete_qos(qos);

    waitset_ = dds_create_waitset(p);
    for (dds_entity_t reader : {reliable_, best_effort_}) {
        if (reader > 0) {
            dds_set_status_mask(reader, DDS_DATA_AVAILABLE_STATUS);
            dds_waitset_attach(waitset_, reader, reader);
        }
    }
}

DdsReceiver::~DdsReceiver() {
    for (dds_entity_t e : {waitset_, reliable_, best_effort_, topic_}) {
        if (e > 0) {
            dds_delete(e);
        }
    }
}

bool DdsReceiver::remember(std::uint32_t robot_id, std::uint64_t sequence) {
    const std::uint64_t key = (static_cast<std::uint64_t>(robot_id) << 40U) ^ sequence;
    if (!seen_.insert(key).second) {
        return false;
    }
    seen_order_.push_back(key);
    if (seen_order_.size() > kRememberedSequences) {
        seen_.erase(seen_order_.front());
        seen_order_.pop_front();
    }
    return true;
}

std::size_t DdsReceiver::drain(dds_entity_t reader, std::vector<ReceivedMessage>& out) {
    std::size_t added = 0;
    for (;;) {
        void* samples[kTakeBatch] = {nullptr};
        dds_sample_info_t infos[kTakeBatch];
        const dds_return_t n = dds_take(reader, samples, infos, kTakeBatch, kTakeBatch);
        if (n <= 0) {
            break;
        }
        const std::int64_t now = wall_clock_ns();
        for (dds_return_t i = 0; i < n; ++i) {
            if (!infos[i].valid_data) {
                continue;
            }
            const auto* s = static_cast<const swarm_adapter_dds_LinkSample*>(samples[i]);
            if (!remember(s->robot_id, s->seq_no)) {
                continue;
            }
            ReceivedMessage msg;
            msg.envelope.robot_id = s->robot_id;
            msg.envelope.session_id = s->session_id;
            msg.envelope.sequence = s->seq_no;
            msg.envelope.source_time_ns = s->source_time_ns;
            msg.envelope.message_class = to_class(s->message_class);
            msg.envelope.frame_id = s->frame_id != nullptr ? s->frame_id : "";
            msg.envelope.map_version = s->map_version;
            msg.envelope.confidence = s->confidence;
            msg.envelope.uncertainty = s->uncertainty;
            msg.envelope.ttl_ms = s->ttl_ms;
            msg.envelope.payload_bytes = s->payload._length;
            msg.decision_id = s->decision_id;
            msg.receive_time_ns = now;
            const auto* bytes = reinterpret_cast<const std::byte*>(s->payload._buffer);
            msg.payload.assign(bytes, bytes + s->payload._length);
            out.push_back(std::move(msg));
            ++added;
        }
        dds_return_loan(reader, samples, n);
        if (n < static_cast<dds_return_t>(kTakeBatch)) {
            break;
        }
    }
    return added;
}

std::size_t DdsReceiver::take(std::vector<ReceivedMessage>& out, std::int64_t timeout_ns) {
    if (!ok()) {
        return 0;
    }
    if (timeout_ns > 0) {
        dds_attach_t triggered[2];
        dds_waitset_wait(waitset_, triggered, 2, timeout_ns);
    }
    std::size_t added = drain(reliable_, out);
    added += drain(best_effort_, out);
    return added;
}

}  // namespace swarm_adapter::dds
