#ifndef SWARM_ADAPTER_CONTRACT_ENVELOPE_H
#define SWARM_ADAPTER_CONTRACT_ENVELOPE_H

#include <cstddef>
#include <cstdint>
#include <string>

namespace swarm_adapter {

/// 消息类别。与 envelope.proto 的 MessageClass 一一对应。
enum class MessageClass : std::uint8_t {
    Pose = 0,
    Health = 1,
    Keyframe = 2,
    Submap = 3,
    Mission = 4,
    LearningUpdate = 5,
    Directive = 6,
};

constexpr std::size_t kMessageClassCount = 7;

/// 统一信封：任何跨机数据都必须带这些字段。
///
/// - 时间：source_time_ns 为发送端单调对齐时钟（纳秒），接收端需经时钟偏差校正。
/// - 配对：多条数据之间按 map_version 配对，不按时间配对；map_version == 0 表示未知，接收端拒收。
/// - 有效期：ttl_ms 从 source_time_ns 起算，超过即过期。
struct MessageEnvelope {
    std::uint32_t robot_id{};
    std::uint32_t session_id{};
    std::uint64_t sequence{};
    std::int64_t source_time_ns{};
    MessageClass message_class{MessageClass::Pose};
    std::string frame_id;
    std::uint64_t map_version{};
    double confidence{};
    double uncertainty{};
    std::int64_t ttl_ms{};
    std::uint64_t payload_bytes{};
};

const char* message_class_name(MessageClass value) noexcept;

}  // namespace swarm_adapter

#endif
