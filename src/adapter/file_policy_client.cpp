#include "swarm_adapter/adapter/federated_client.h"

#include <cmath>
#include <utility>

namespace swarm_adapter {

FilePolicyClient::FilePolicyClient(std::string policy_path)
    : policy_path_(std::move(policy_path)) {}

std::optional<strategy::PolicyWeights> FilePolicyClient::poll_global_policy() {
    strategy::PolicyWeights policy;
    last_error_ = strategy::load_policy_file(policy_path_, policy);
    if (last_error_ != ReasonCode::Ok || policy.policy_version <= last_version_) {
        return std::nullopt;
    }
    last_version_ = policy.policy_version;
    return policy;
}

ReasonCode FilePolicyClient::submit_round_summary(const RoundSummary& summary) {
    if (summary.round_id == 0 || !std::isfinite(summary.mean_utility)) {
        return ReasonCode::InvalidInput;
    }
    last_summary_ = summary;
    return ReasonCode::Ok;
}

}  // namespace swarm_adapter
