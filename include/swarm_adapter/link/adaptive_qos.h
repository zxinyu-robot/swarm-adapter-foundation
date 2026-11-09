#ifndef SWARM_ADAPTER_LINK_ADAPTIVE_QOS_H
#define SWARM_ADAPTER_LINK_ADAPTIVE_QOS_H

#include "swarm_adapter/contract/topic_policy.h"

#include <cstddef>
#include <string_view>

namespace swarm_adapter::link {

enum class NetworkMode {
    Healthy,
    Constrained,
    Critical,
};

struct LinkMetrics {
    double packet_loss_ratio{};
    double one_way_latency_ms{};
    double jitter_ms{};
    double queue_fill_ratio{};
    double available_bandwidth_mbps{};
};

struct FusionDemand {
    double pose_uncertainty{};
    bool loop_closure_candidate{};
    bool mission_critical{};
};

struct AdaptiveQosConfig {
    double healthy_loss_max{0.05};
    double healthy_latency_max_ms{50.0};
    double healthy_queue_max{0.50};
    double critical_loss_min{0.25};
    double critical_latency_min_ms{250.0};
    double critical_queue_min{0.90};
    std::size_t transition_confirmation_samples{2};
};

struct QosDecision {
    NetworkMode mode{NetworkMode::Healthy};
    TopicPolicy pose;
    TopicPolicy health;
    TopicPolicy keyframe;
    TopicPolicy submap;
    int compression_level{};
    bool defer_submaps{};
};

class AdaptiveQosController {
public:
    explicit AdaptiveQosController(AdaptiveQosConfig config = {});

    QosDecision update(
        const LinkMetrics& metrics,
        const FusionDemand& demand = {});

    [[nodiscard]] NetworkMode mode() const noexcept { return mode_; }
    [[nodiscard]] static std::string_view name(NetworkMode mode) noexcept;
    [[nodiscard]] static std::string_view name(Reliability reliability) noexcept;

private:
    [[nodiscard]] NetworkMode classify(const LinkMetrics& metrics) const;
    [[nodiscard]] QosDecision policy(const FusionDemand& demand) const;

    AdaptiveQosConfig config_;
    NetworkMode mode_{NetworkMode::Healthy};
    NetworkMode pending_mode_{NetworkMode::Healthy};
    std::size_t pending_samples_{};
};

}  // namespace swarm_adapter::link

#endif
