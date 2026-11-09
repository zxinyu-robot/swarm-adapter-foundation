#ifndef SWARM_ADAPTER_STRATEGY_POLICY_MODEL_H
#define SWARM_ADAPTER_STRATEGY_POLICY_MODEL_H

#include "swarm_adapter/contract/reason_code.h"
#include "swarm_adapter/strategy/features.h"

#include <cstdint>
#include <string>

namespace swarm_adapter::strategy {

/// 联邦端下发的策略权重：一个线性效用模型 utility ≈ w · phi(x, a)。
/// policy_version 单调递增；round_id 为联邦训练轮次号。
struct PolicyWeights {
    std::uint64_t policy_version{};
    std::uint64_t round_id{};
    FeatureVector weights{};
};

bool valid(const PolicyWeights& policy) noexcept;

double predict_utility(
    const PolicyWeights& policy,
    const LinkFeatures& link,
    const CommAction& action);

/// 读取策略文件（格式见 docs/contracts.md「策略文件」）。
/// @return Ok / IoError / InvalidInput。失败时 out 不变。
ReasonCode load_policy_file(const std::string& path, PolicyWeights& out);

/// 原子写策略文件（先写临时文件再 rename）。
ReasonCode save_policy_file(const std::string& path, const PolicyWeights& policy);

}  // namespace swarm_adapter::strategy

#endif
