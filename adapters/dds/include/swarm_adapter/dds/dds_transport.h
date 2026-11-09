#ifndef SWARM_ADAPTER_DDS_DDS_TRANSPORT_H
#define SWARM_ADAPTER_DDS_DDS_TRANSPORT_H

#include "swarm_adapter/adapter/transport.h"

#include <dds/dds.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <map>
#include <string>
#include <unordered_set>
#include <vector>

namespace swarm_adapter::dds {

/// TopicPolicy 中落到 DDS QoS 的部分。target_rate_hz 由发送端节流，
/// compression_level 由编码层负责，二者不进 DDS QoS。
struct DdsQosSpec {
    bool reliable{};
    std::int32_t history_depth{1};
    std::int64_t deadline_ns{};  ///< 0 表示不设 deadline
    std::int32_t transport_priority{};
    std::int64_t lifespan_ns{};  ///< 来自信封 ttl_ms；0 表示不过期
};

bool operator<(const DdsQosSpec& a, const DdsQosSpec& b) noexcept;
bool operator==(const DdsQosSpec& a, const DdsQosSpec& b) noexcept;

DdsQosSpec map_qos(const TopicPolicy& policy, std::int64_t ttl_ms) noexcept;

/// 调用方负责 dds_delete_qos。
dds_qos_t* make_qos(const DdsQosSpec& spec);

/// 每类消息一个 DDS topic，例如 "swarm_adapter_v1_keyframe"。
std::string topic_name(MessageClass message_class);

/// 跨机比较用的墙钟（CLOCK_REALTIME），单位 ns。
std::int64_t wall_clock_ns() noexcept;

struct ReceivedMessage {
    MessageEnvelope envelope;
    std::uint64_t decision_id{};
    std::int64_t receive_time_ns{};
    std::vector<std::byte> payload;
};

/// 一个 DDS domain participant。domain 和网络配置由 CYCLONEDDS_URI 决定。
class DdsParticipant {
public:
    explicit DdsParticipant(dds_domainid_t domain = DDS_DOMAIN_DEFAULT);
    ~DdsParticipant();
    DdsParticipant(const DdsParticipant&) = delete;
    DdsParticipant& operator=(const DdsParticipant&) = delete;

    [[nodiscard]] bool ok() const noexcept { return handle_ > 0; }
    [[nodiscard]] dds_entity_t handle() const noexcept { return handle_; }

private:
    dds_entity_t handle_;
};

/// Transport 的 CycloneDDS 实现。每个 (消息类, QoS) 组合缓存一个 writer：
/// DDS 的可靠性等 QoS 在 writer 创建后不可改，切换策略时改用另一个 writer，
/// 已匹配的 writer 不重建，避免重新发现造成丢包。线程安全：否。
class DdsTransport final : public Transport {
public:
    explicit DdsTransport(DdsParticipant& participant);
    ~DdsTransport() override;
    DdsTransport(const DdsTransport&) = delete;
    DdsTransport& operator=(const DdsTransport&) = delete;

    ReasonCode publish(const MessageEnvelope& envelope, const TopicPolicy& policy,
                       fusion::ByteView payload) override;
    ReasonCode publish(const MessageEnvelope& envelope, const TopicPolicy& policy,
                       fusion::ByteView payload, std::uint64_t decision_id);

    /// 返回该 (消息类, QoS) writer 当前匹配的 reader 数；writer 不存在时先创建。负数表示出错。
    std::int64_t matched_readers(MessageClass message_class, const DdsQosSpec& spec);

private:
    struct WriterKey {
        MessageClass message_class;
        DdsQosSpec spec;
        bool operator<(const WriterKey& other) const noexcept;
    };

    dds_entity_t topic(MessageClass message_class);
    dds_entity_t writer(MessageClass message_class, const DdsQosSpec& spec);

    dds_entity_t participant_;
    std::array<dds_entity_t, 7> topics_{};
    std::map<WriterKey, dds_entity_t> writers_;
};

/// 订阅一类消息。同时开 Reliable 和 BestEffort 两个 reader：BestEffort reader
/// 能匹配两种 writer，Reliable reader 负责 Reliable writer 的重传；按 (robot_id, sequence) 去重。
/// 线程安全：否。
class DdsReceiver {
public:
    DdsReceiver(DdsParticipant& participant, MessageClass message_class,
                std::int32_t history_depth = 256);
    ~DdsReceiver();
    DdsReceiver(const DdsReceiver&) = delete;
    DdsReceiver& operator=(const DdsReceiver&) = delete;

    [[nodiscard]] bool ok() const noexcept { return reliable_ > 0 && best_effort_ > 0; }

    /// 阻塞至多 timeout_ns 等待数据，然后取走所有新样本。返回追加到 out 的条数。
    std::size_t take(std::vector<ReceivedMessage>& out, std::int64_t timeout_ns);

private:
    std::size_t drain(dds_entity_t reader, std::vector<ReceivedMessage>& out);
    bool remember(std::uint32_t robot_id, std::uint64_t sequence);

    dds_entity_t topic_{};
    dds_entity_t reliable_{};
    dds_entity_t best_effort_{};
    dds_entity_t waitset_{};
    std::unordered_set<std::uint64_t> seen_;
    std::deque<std::uint64_t> seen_order_;
};

}  // namespace swarm_adapter::dds

#endif
