#ifndef SWARM_ADAPTER_STRATEGY_RECORDS_H
#define SWARM_ADAPTER_STRATEGY_RECORDS_H

#include "swarm_adapter/contract/envelope.h"
#include "swarm_adapter/contract/reason_code.h"
#include "swarm_adapter/strategy/features.h"
#include "swarm_adapter/strategy/policy_gate.h"

#include <cstdint>

namespace swarm_adapter::strategy {

enum class NetworkModeTag : std::uint8_t { Healthy = 0, Constrained = 1, Critical = 2 };

enum class DecisionSource : std::uint8_t {
    LocalRule = 0,
    FederatedPolicy = 1,
};

/// 表 1：链路观测（输入特征）。
struct LinkObservationRecord {
    std::uint64_t record_id{};
    std::int64_t time_ns{};
    std::uint32_t robot_id{};
    MessageClass message_class{MessageClass::Pose};
    NetworkModeTag network_mode{NetworkModeTag::Healthy};
    LinkFeatures features;
};

/// 表 2：配置决策（动作）。decision_id 是与效果回执配对的唯一键。
struct ConfigDecisionRecord {
    std::uint64_t decision_id{};
    std::int64_t time_ns{};
    std::uint32_t robot_id{};
    MessageClass message_class{MessageClass::Pose};
    LinkFeatures features;
    CommAction action;
    DecisionSource source{DecisionSource::LocalRule};
    std::uint64_t policy_version{};
};

/// 表 3：效果回执（标签）。trainable = false 的样本不进训练集。
struct OutcomeRecord {
    std::uint64_t decision_id{};
    std::int64_t time_ns{};
    Outcome outcome;
    std::int64_t clock_uncertainty_ns{};
    bool trainable{};
};

/// 表 4：策略版本。
struct PolicyVersionRecord {
    std::int64_t time_ns{};
    GateEvent event;
};

/// 训练样本 = 决策 + 回执（按 decision_id 配对）。
struct TrainingSample {
    ConfigDecisionRecord decision;
    OutcomeRecord outcome;
};

const char* network_mode_tag_name(NetworkModeTag mode) noexcept;
const char* decision_source_name(DecisionSource source) noexcept;

}  // namespace swarm_adapter::strategy

#endif
