#ifndef SWARM_ADAPTER_ADAPTER_FEDERATED_CLIENT_H
#define SWARM_ADAPTER_ADAPTER_FEDERATED_CLIENT_H

#include "swarm_adapter/contract/reason_code.h"
#include "swarm_adapter/strategy/policy_model.h"

#include <cstdint>
#include <optional>
#include <string>

namespace swarm_adapter {

/// 本轮本地训练的汇总指标。原始记录不上传。
struct RoundSummary {
    std::uint64_t round_id{};
    std::uint64_t policy_version{};
    std::uint64_t num_samples{};
    double mean_utility{};
};

/// 联邦框架适配接口。联邦端只有建议权：拿到的权重必须先过 PolicyGate。
class FederatedClient {
public:
    virtual ~FederatedClient() = default;
    /// 有新的全局策略时返回，否则 nullopt。不阻塞。
    virtual std::optional<strategy::PolicyWeights> poll_global_policy() = 0;
    virtual ReasonCode submit_round_summary(const RoundSummary& summary) = 0;
};

/// 以文件为边界的实现：Python 端 Flower 客户端把全局策略写成策略文件，
/// 本类轮询读取；新版本号大于已读版本才返回。
class FilePolicyClient final : public FederatedClient {
public:
    explicit FilePolicyClient(std::string policy_path);
    std::optional<strategy::PolicyWeights> poll_global_policy() override;
    ReasonCode submit_round_summary(const RoundSummary& summary) override;

    [[nodiscard]] ReasonCode last_error() const noexcept { return last_error_; }
    [[nodiscard]] const RoundSummary& last_summary() const noexcept { return last_summary_; }

private:
    std::string policy_path_;
    std::uint64_t last_version_{};
    ReasonCode last_error_{ReasonCode::Ok};
    RoundSummary last_summary_{};
};

}  // namespace swarm_adapter

#endif
