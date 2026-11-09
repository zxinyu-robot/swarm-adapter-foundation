#include "swarm_adapter/link/adaptive_qos.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace swarm_adapter::link {
namespace {

bool valid_ratio(double value) {
    return std::isfinite(value) && value >= 0.0 && value <= 1.0;
}

}  // namespace

AdaptiveQosController::AdaptiveQosController(AdaptiveQosConfig config)
    : config_(std::move(config)) {
    if (!valid_ratio(config_.healthy_loss_max) ||
        !valid_ratio(config_.healthy_queue_max) ||
        !valid_ratio(config_.critical_loss_min) ||
        !valid_ratio(config_.critical_queue_min) ||
        config_.healthy_latency_max_ms < 0.0 ||
        config_.critical_latency_min_ms <= config_.healthy_latency_max_ms ||
        config_.critical_loss_min <= config_.healthy_loss_max ||
        config_.critical_queue_min <= config_.healthy_queue_max ||
        config_.transition_confirmation_samples == 0) {
        throw std::invalid_argument("invalid adaptive QoS config");
    }
}

QosDecision AdaptiveQosController::update(
    const LinkMetrics& metrics,
    const FusionDemand& demand) {
    if (!valid_ratio(metrics.packet_loss_ratio) ||
        !valid_ratio(metrics.queue_fill_ratio) ||
        !std::isfinite(metrics.one_way_latency_ms) ||
        !std::isfinite(metrics.jitter_ms) ||
        !std::isfinite(metrics.available_bandwidth_mbps) ||
        metrics.one_way_latency_ms < 0.0 || metrics.jitter_ms < 0.0 ||
        metrics.available_bandwidth_mbps < 0.0 ||
        !valid_ratio(demand.pose_uncertainty)) {
        throw std::invalid_argument("invalid link metrics or fusion demand");
    }

    const NetworkMode candidate = classify(metrics);
    if (candidate == mode_) {
        pending_mode_ = mode_;
        pending_samples_ = 0;
    } else if (candidate != pending_mode_) {
        pending_mode_ = candidate;
        pending_samples_ = 1;
        if (pending_samples_ >= config_.transition_confirmation_samples) {
            mode_ = pending_mode_;
            pending_samples_ = 0;
        }
    } else {
        ++pending_samples_;
        if (pending_samples_ >= config_.transition_confirmation_samples) {
            mode_ = pending_mode_;
            pending_samples_ = 0;
        }
    }

    return policy(demand);
}

NetworkMode AdaptiveQosController::classify(
    const LinkMetrics& metrics) const {
    if (metrics.packet_loss_ratio >= config_.critical_loss_min ||
        metrics.one_way_latency_ms >= config_.critical_latency_min_ms ||
        metrics.queue_fill_ratio >= config_.critical_queue_min) {
        return NetworkMode::Critical;
    }
    if (metrics.packet_loss_ratio <= config_.healthy_loss_max &&
        metrics.one_way_latency_ms <= config_.healthy_latency_max_ms &&
        metrics.queue_fill_ratio <= config_.healthy_queue_max) {
        return NetworkMode::Healthy;
    }
    return NetworkMode::Constrained;
}

QosDecision AdaptiveQosController::policy(
    const FusionDemand& demand) const {
    QosDecision decision;
    decision.mode = mode_;
    decision.pose = {
        Reliability::BestEffort,
        1,
        mode_ == NetworkMode::Healthy ? 30.0 :
            (mode_ == NetworkMode::Constrained ? 20.0 : 10.0),
        100,
        240,
    };
    decision.health = {
        Reliability::Reliable,
        10,
        2.0,
        500,
        255,
    };

    switch (mode_) {
        case NetworkMode::Healthy:
            decision.keyframe = {Reliability::Reliable, 8, 10.0, 200, 180};
            decision.submap = {Reliability::Reliable, 2, 1.0, 1'000, 120};
            decision.compression_level = 0;
            break;
        case NetworkMode::Constrained:
            decision.keyframe = {Reliability::Reliable, 4, 5.0, 400, 210};
            decision.submap = {Reliability::BestEffort, 1, 0.2, 2'000, 80};
            decision.compression_level = 3;
            break;
        case NetworkMode::Critical:
            decision.keyframe = {Reliability::BestEffort, 1, 2.0, 1'000, 230};
            decision.submap = {Reliability::BestEffort, 1, 0.0, 5'000, 40};
            decision.compression_level = 6;
            decision.defer_submaps = true;
            break;
    }

    if (demand.pose_uncertainty >= 0.70 &&
        mode_ != NetworkMode::Critical) {
        decision.keyframe.target_rate_hz =
            std::min(15.0, decision.keyframe.target_rate_hz * 1.5);
        decision.keyframe.priority = 230;
    }
    if (demand.loop_closure_candidate) {
        decision.keyframe.reliability = Reliability::Reliable;
        decision.keyframe.priority = 245;
    }
    if (demand.mission_critical) {
        decision.keyframe.reliability = Reliability::Reliable;
        decision.keyframe.priority = 250;
        decision.health.priority = 255;
    }
    return decision;
}

std::string_view AdaptiveQosController::name(NetworkMode mode) noexcept {
    switch (mode) {
        case NetworkMode::Healthy:
            return "healthy";
        case NetworkMode::Constrained:
            return "constrained";
        case NetworkMode::Critical:
            return "critical";
    }
    return "unknown";
}

std::string_view AdaptiveQosController::name(
    Reliability reliability) noexcept {
    return reliability == Reliability::Reliable ? "reliable" : "best_effort";
}

}  // namespace swarm_adapter::link
