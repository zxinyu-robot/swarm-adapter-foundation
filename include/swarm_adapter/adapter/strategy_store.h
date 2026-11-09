#ifndef SWARM_ADAPTER_ADAPTER_STRATEGY_STORE_H
#define SWARM_ADAPTER_ADAPTER_STRATEGY_STORE_H

#include "swarm_adapter/contract/reason_code.h"
#include "swarm_adapter/strategy/records.h"

#include <cstdint>
#include <vector>

namespace swarm_adapter {

/// 端侧轻量策略库接口。原始记录不出机器人；联邦客户端只读取训练样本。
/// 线程安全由实现说明。
class StrategyStore {
public:
    virtual ~StrategyStore() = default;

    virtual ReasonCode append(const strategy::LinkObservationRecord& record) = 0;
    /// decision_id 重复 → Duplicate。
    virtual ReasonCode append(const strategy::ConfigDecisionRecord& record) = 0;
    /// 找不到对应决策 → MissingReference；同一决策重复回执 → Duplicate。
    virtual ReasonCode append(const strategy::OutcomeRecord& record) = 0;
    virtual ReasonCode append(const strategy::PolicyVersionRecord& record) = 0;

    /// 返回 policy_version 在 [min_version, max_version] 内、可训练的配对样本。
    [[nodiscard]] virtual std::vector<strategy::TrainingSample> samples(
        std::uint64_t min_version,
        std::uint64_t max_version) const = 0;

    /// 淘汰 time_ns 早于 cutoff_ns 的记录，返回淘汰条数。
    virtual std::size_t evict_older_than(std::int64_t cutoff_ns) = 0;
};

}  // namespace swarm_adapter

#endif
