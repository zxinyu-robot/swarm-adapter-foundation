#include "swarm_adapter/strategy/comm_selector.h"

#include <algorithm>
#include <limits>

namespace swarm_adapter::strategy {
namespace {

CommAction clamp_to(const ClassBounds& b, CommAction action) {
    action.rate_scale = std::clamp(action.rate_scale, b.min_rate_scale, b.max_rate_scale);
    action.compression_level = std::clamp(action.compression_level, 0, b.max_compression_level);
    if (b.reliable_required) {
        action.reliable = true;
    }
    return action;
}

}  // namespace

Selection select_action(
    MessageClass message_class,
    const LinkFeatures& link,
    const CommAction& local_default,
    const PolicyGate& gate,
    const SafetyEnvelope& envelope) {
    const PolicyWeights* policy = gate.active();
    if (policy != nullptr && valid(link)) {
        Selection best{{}, DecisionSource::FederatedPolicy, policy->policy_version};
        double best_utility = -std::numeric_limits<double>::infinity();
        for (const CommAction& candidate : envelope.candidates(message_class)) {
            const double utility = predict_utility(*policy, link, candidate);
            if (utility > best_utility) {
                best_utility = utility;
                best.action = candidate;
            }
        }
        if (best_utility > -std::numeric_limits<double>::infinity()) {
            return best;
        }
    }
    return {clamp_to(envelope.bounds(message_class), local_default),
            DecisionSource::LocalRule, 0};
}

}  // namespace swarm_adapter::strategy
