#ifndef SWARM_ADAPTER_STRATEGY_SAFETY_ENVELOPE_H
#define SWARM_ADAPTER_STRATEGY_SAFETY_ENVELOPE_H

#include "swarm_adapter/contract/envelope.h"
#include "swarm_adapter/contract/topic_policy.h"
#include "swarm_adapter/strategy/features.h"

#include <array>
#include <vector>

namespace swarm_adapter::strategy {

/// 单个消息类别允许调整的范围。写死在本机，联邦端无法修改。
struct ClassBounds {
    double min_rate_scale{1.0};
    double max_rate_scale{1.0};
    int max_compression_level{};
    bool reliable_required{};
    double min_rate_hz{};
};

/// 本地安全边界：联邦权重只能在白名单内挑选通信动作。
class SafetyEnvelope {
public:
    /// 默认边界：健康度、任务指令永远 Reliable 且不降频；位姿频率有下限。
    SafetyEnvelope();

    void set_bounds(MessageClass message_class, const ClassBounds& bounds);
    [[nodiscard]] const ClassBounds& bounds(MessageClass message_class) const;

    [[nodiscard]] bool allows(MessageClass message_class, const CommAction& action) const;

    /// 该类别下所有允许的候选动作（离散网格）。
    [[nodiscard]] std::vector<CommAction> candidates(MessageClass message_class) const;

    /// 把动作作用到基准配置上，并执行频率下限。动作必须先通过 allows()。
    [[nodiscard]] TopicPolicy apply(
        MessageClass message_class,
        const TopicPolicy& base,
        const CommAction& action) const;

private:
    std::array<ClassBounds, kMessageClassCount> bounds_{};
};

}  // namespace swarm_adapter::strategy

#endif
