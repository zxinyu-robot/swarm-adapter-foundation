#ifndef SWARM_ADAPTER_STRATEGY_POLICY_GATE_H
#define SWARM_ADAPTER_STRATEGY_POLICY_GATE_H

#include "swarm_adapter/contract/reason_code.h"
#include "swarm_adapter/strategy/policy_model.h"

#include <cstddef>
#include <cstdint>
#include <optional>

namespace swarm_adapter::strategy {

enum class GateState : std::uint8_t {
    LocalRules = 0,  ///< 没有生效的联邦策略，用本地规则。
    Shadow = 1,      ///< 有候选策略在旁路比对，仍按当前策略执行。
    Active = 2,      ///< 联邦策略生效。
};

const char* gate_state_name(GateState state) noexcept;

struct PolicyGateConfig {
    /// 旁路比对至少需要的真实样本数。
    std::size_t shadow_min_samples{50};
    /// 没有现行策略时，候选策略的预测误差（MSE）上限。
    double max_mse_without_baseline{0.05};
    /// 候选策略误差可以比现行策略高出的比例。
    double shadow_tolerance{0.0};
    /// 生效后滚动窗口误差超过此值即回滚。
    double rollback_mse{0.10};
    std::size_t rollback_window{50};
};

/// 一次状态变化事件，供写入「策略版本」表。
struct GateEvent {
    std::uint64_t policy_version{};
    std::uint64_t round_id{};
    GateState state{GateState::LocalRules};
    ReasonCode reason{ReasonCode::Ok};
    double candidate_mse{};
    double active_mse{};
};

/// 联邦策略的准入门：候选 → 旁路比对 → 生效 / 拒绝 → 回滚。
///
/// 旁路比对的含义：候选策略只计算不执行，用它预测「实际执行的动作」的效果，
/// 和真实回执比较误差；误差不比现行策略差才生效。
/// 线程安全：否，由调用方串行调用。
class PolicyGate {
public:
    explicit PolicyGate(PolicyGateConfig config = {});

    /// 提交候选策略。版本不大于已知最大版本 → StalePolicyVersion；
    /// 权重非法 → InvalidInput；成功进入 Shadow（会替换上一个候选）。
    ReasonCode propose(const PolicyWeights& candidate);

    /// 喂入一条真实执行样本，可能触发生效、拒绝或回滚。
    /// @return 若状态发生变化，返回事件。
    std::optional<GateEvent> observe(
        const LinkFeatures& link,
        const CommAction& executed,
        double observed_utility);

    [[nodiscard]] GateState state() const noexcept { return state_; }
    [[nodiscard]] const PolicyWeights* active() const noexcept;
    [[nodiscard]] const PolicyWeights* candidate() const noexcept;

private:
    struct Stats {
        std::size_t count{};
        double sum_squared_error{};
        [[nodiscard]] double mse() const {
            return count == 0 ? 0.0 : sum_squared_error / static_cast<double>(count);
        }
    };

    PolicyGateConfig config_;
    GateState state_{GateState::LocalRules};
    std::optional<PolicyWeights> active_;
    std::optional<PolicyWeights> previous_;
    std::optional<PolicyWeights> candidate_;
    std::uint64_t max_seen_version_{};
    Stats candidate_stats_;
    Stats active_shadow_stats_;
    Stats active_window_stats_;
};

}  // namespace swarm_adapter::strategy

#endif
