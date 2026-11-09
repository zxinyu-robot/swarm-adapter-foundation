#ifndef SWARM_ADAPTER_STRATEGY_COMM_SELECTOR_H
#define SWARM_ADAPTER_STRATEGY_COMM_SELECTOR_H

#include "swarm_adapter/strategy/policy_gate.h"
#include "swarm_adapter/strategy/records.h"
#include "swarm_adapter/strategy/safety_envelope.h"

#include <cstdint>

namespace swarm_adapter::strategy {

struct Selection {
    CommAction action;
    DecisionSource source{DecisionSource::LocalRule};
    std::uint64_t policy_version{};
};

/// 选择通信动作：有生效的联邦策略时，在安全边界的候选中取预测效用最高者；
/// 否则使用本地规则给出的默认动作（同样必须在安全边界内，否则截到边界内）。
Selection select_action(
    MessageClass message_class,
    const LinkFeatures& link,
    const CommAction& local_default,
    const PolicyGate& gate,
    const SafetyEnvelope& envelope);

}  // namespace swarm_adapter::strategy

#endif
