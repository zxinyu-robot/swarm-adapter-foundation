#include "swarm_adapter/link/keyframe_scheduler.h"

#include <cmath>
#include <stdexcept>

namespace swarm_adapter::link {

KeyframeScheduler::KeyframeScheduler(double force_uncertainty)
    : force_uncertainty_(force_uncertainty) {
    if (!std::isfinite(force_uncertainty_) ||
        force_uncertainty_ < 0.0 || force_uncertainty_ > 1.0) {
        throw std::invalid_argument("force uncertainty must be in [0, 1]");
    }
}

bool KeyframeScheduler::should_publish(
    std::int64_t timestamp_ns,
    double pose_uncertainty,
    bool loop_closure_candidate,
    double target_rate_hz) {
    if (timestamp_ns < 0 || timestamp_ns < last_observation_ns_ ||
        !std::isfinite(pose_uncertainty) ||
        pose_uncertainty < 0.0 || pose_uncertainty > 1.0 ||
        !std::isfinite(target_rate_hz) || target_rate_hz < 0.0) {
        throw std::invalid_argument("invalid keyframe scheduling input");
    }
    last_observation_ns_ = timestamp_ns;

    const bool forced =
        loop_closure_candidate || pose_uncertainty >= force_uncertainty_;
    if (last_publish_ns_ < 0) {
        if (target_rate_hz <= 0.0 && !forced) {
            return false;
        }
        last_publish_ns_ = timestamp_ns;
        return true;
    }
    if (timestamp_ns == last_publish_ns_) {
        return false;
    }
    if (forced) {
        last_publish_ns_ = timestamp_ns;
        return true;
    }
    if (target_rate_hz <= 0.0) {
        return false;
    }

    const auto period_ns =
        static_cast<std::int64_t>(1'000'000'000.0 / target_rate_hz);
    if (timestamp_ns - last_publish_ns_ >= period_ns) {
        last_publish_ns_ = timestamp_ns;
        return true;
    }
    return false;
}

void KeyframeScheduler::reset() noexcept {
    last_observation_ns_ = -1;
    last_publish_ns_ = -1;
}

}  // namespace swarm_adapter::link
