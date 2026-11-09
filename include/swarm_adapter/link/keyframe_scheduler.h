#ifndef SWARM_ADAPTER_LINK_KEYFRAME_SCHEDULER_H
#define SWARM_ADAPTER_LINK_KEYFRAME_SCHEDULER_H

#include <cstdint>

namespace swarm_adapter::link {

class KeyframeScheduler {
public:
    explicit KeyframeScheduler(double force_uncertainty = 0.80);

    bool should_publish(
        std::int64_t timestamp_ns,
        double pose_uncertainty,
        bool loop_closure_candidate,
        double target_rate_hz);

    void reset() noexcept;

private:
    double force_uncertainty_;
    std::int64_t last_observation_ns_{-1};
    std::int64_t last_publish_ns_{-1};
};

}  // namespace swarm_adapter::link

#endif
