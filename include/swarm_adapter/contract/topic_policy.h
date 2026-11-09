#ifndef SWARM_ADAPTER_CONTRACT_TOPIC_POLICY_H
#define SWARM_ADAPTER_CONTRACT_TOPIC_POLICY_H

#include <cstddef>
#include <cstdint>

namespace swarm_adapter {

enum class Reliability : std::uint8_t {
    BestEffort = 0,
    Reliable = 1,
};

/// 单个消息类别的通信配置。这是联邦策略唯一允许调整的对象：
/// 策略只能改这里的字段，不能写任何状态估计（滤波器）内部量。
struct TopicPolicy {
    Reliability reliability{Reliability::BestEffort};
    std::size_t history_depth{1};
    double target_rate_hz{};
    std::int64_t deadline_ms{};
    std::uint8_t priority{};
    int compression_level{};
};

}  // namespace swarm_adapter

#endif
