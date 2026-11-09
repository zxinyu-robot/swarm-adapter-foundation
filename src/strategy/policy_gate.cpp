#include "swarm_adapter/strategy/policy_gate.h"

#include <cmath>
#include <stdexcept>

namespace swarm_adapter::strategy {

const char* gate_state_name(GateState state) noexcept {
    switch (state) {
        case GateState::LocalRules: return "local_rules";
        case GateState::Shadow: return "shadow";
        case GateState::Active: return "active";
    }
    return "unknown";
}

PolicyGate::PolicyGate(PolicyGateConfig config) : config_(config) {
    if (config_.shadow_min_samples == 0 || config_.rollback_window == 0 ||
        !std::isfinite(config_.max_mse_without_baseline) ||
        !std::isfinite(config_.shadow_tolerance) || config_.shadow_tolerance < 0.0 ||
        !std::isfinite(config_.rollback_mse) || config_.rollback_mse <= 0.0) {
        throw std::invalid_argument("invalid policy gate config");
    }
}

ReasonCode PolicyGate::propose(const PolicyWeights& candidate) {
    if (!valid(candidate)) {
        return ReasonCode::InvalidInput;
    }
    if (candidate.policy_version <= max_seen_version_) {
        return ReasonCode::StalePolicyVersion;
    }
    max_seen_version_ = candidate.policy_version;
    candidate_ = candidate;
    candidate_stats_ = {};
    active_shadow_stats_ = {};
    state_ = GateState::Shadow;
    return ReasonCode::Ok;
}

std::optional<GateEvent> PolicyGate::observe(
    const LinkFeatures& link,
    const CommAction& executed,
    double observed_utility) {
    if (!valid(link) || !valid(executed) || !std::isfinite(observed_utility)) {
        return std::nullopt;
    }

    if (active_) {
        const double error = predict_utility(*active_, link, executed) - observed_utility;
        active_window_stats_.count += 1;
        active_window_stats_.sum_squared_error += error * error;
        if (candidate_) {
            active_shadow_stats_.count += 1;
            active_shadow_stats_.sum_squared_error += error * error;
        }
    }

    if (candidate_) {
        const double error =
            predict_utility(*candidate_, link, executed) - observed_utility;
        candidate_stats_.count += 1;
        candidate_stats_.sum_squared_error += error * error;
        if (candidate_stats_.count >= config_.shadow_min_samples) {
            const double candidate_mse = candidate_stats_.mse();
            const double active_mse = active_shadow_stats_.mse();
            const bool accepted =
                active_ ? candidate_mse <= active_mse * (1.0 + config_.shadow_tolerance)
                        : candidate_mse <= config_.max_mse_without_baseline;
            GateEvent event{candidate_->policy_version, candidate_->round_id,
                            GateState::Active, ReasonCode::Ok, candidate_mse, active_mse};
            if (accepted) {
                previous_ = active_;
                active_ = candidate_;
                active_window_stats_ = {};
                state_ = GateState::Active;
            } else {
                event.reason = ReasonCode::ShadowRejected;
                state_ = active_ ? GateState::Active : GateState::LocalRules;
                event.state = state_;
            }
            candidate_.reset();
            return event;
        }
    }

    if (active_ && !candidate_ &&
        active_window_stats_.count >= config_.rollback_window) {
        const double window_mse = active_window_stats_.mse();
        active_window_stats_ = {};
        if (window_mse > config_.rollback_mse) {
            GateEvent event{active_->policy_version, active_->round_id,
                            GateState::LocalRules, ReasonCode::RolledBack, 0.0, window_mse};
            active_ = previous_;
            previous_.reset();
            state_ = active_ ? GateState::Active : GateState::LocalRules;
            event.state = state_;
            return event;
        }
    }
    return std::nullopt;
}

const PolicyWeights* PolicyGate::active() const noexcept {
    return active_ ? &*active_ : nullptr;
}

const PolicyWeights* PolicyGate::candidate() const noexcept {
    return candidate_ ? &*candidate_ : nullptr;
}

}  // namespace swarm_adapter::strategy
