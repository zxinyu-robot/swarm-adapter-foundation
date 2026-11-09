#ifndef SWARM_ADAPTER_STRATEGY_RING_STRATEGY_STORE_H
#define SWARM_ADAPTER_STRATEGY_RING_STRATEGY_STORE_H

#include "swarm_adapter/adapter/strategy_store.h"

#include <cstddef>
#include <deque>
#include <string>
#include <unordered_map>
#include <unordered_set>

namespace swarm_adapter::strategy {

/// 固定容量的内存环形缓冲 + 只追加的 JSONL 分段文件。零依赖。
///
/// - 每张表容量独立，满了淘汰最旧记录。
/// - flush_segment() 把自上次 flush 以来的新记录追加写成一个新分段文件，
///   Python 端 swarm_adapter.records 读取它做本地训练。
/// - 线程安全：否，由调用方串行调用。
class RingStrategyStore final : public StrategyStore {
public:
    explicit RingStrategyStore(std::size_t capacity_per_table = 4096);

    ReasonCode append(const LinkObservationRecord& record) override;
    ReasonCode append(const ConfigDecisionRecord& record) override;
    ReasonCode append(const OutcomeRecord& record) override;
    ReasonCode append(const PolicyVersionRecord& record) override;

    [[nodiscard]] std::vector<TrainingSample> samples(
        std::uint64_t min_version,
        std::uint64_t max_version) const override;

    std::size_t evict_older_than(std::int64_t cutoff_ns) override;

    /// 写出分段文件 <directory>/segment_<序号>.jsonl。无新记录时不写文件。
    /// @param written_path 输出实际写入的路径（未写入时为空）。
    ReasonCode flush_segment(const std::string& directory, std::string& written_path);

    [[nodiscard]] std::size_t observation_count() const noexcept { return observations_.size(); }
    [[nodiscard]] std::size_t decision_count() const noexcept { return decisions_.size(); }
    [[nodiscard]] std::size_t outcome_count() const noexcept { return outcomes_.size(); }
    [[nodiscard]] std::size_t policy_event_count() const noexcept { return policy_events_.size(); }

private:
    void drop_oldest_decision();

    std::size_t capacity_;
    std::deque<LinkObservationRecord> observations_;
    std::deque<ConfigDecisionRecord> decisions_;
    std::unordered_map<std::uint64_t, OutcomeRecord> outcomes_;
    std::deque<PolicyVersionRecord> policy_events_;
    std::unordered_set<std::uint64_t> decision_ids_;
    std::deque<std::string> pending_lines_;
    std::uint64_t next_segment_{1};
};

}  // namespace swarm_adapter::strategy

#endif
