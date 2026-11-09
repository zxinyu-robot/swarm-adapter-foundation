#include "swarm_adapter/strategy/features.h"

#include <algorithm>
#include <cmath>

namespace swarm_adapter::strategy {
namespace {

bool unit(double value) {
    return std::isfinite(value) && value >= 0.0 && value <= 1.0;
}

}  // namespace

bool valid(const LinkFeatures& link) noexcept {
    return unit(link.packet_loss_ratio) && unit(link.queue_fill_ratio) &&
           std::isfinite(link.latency_s) && link.latency_s >= 0.0 &&
           std::isfinite(link.age_ratio) && link.age_ratio >= 0.0;
}

bool valid(const CommAction& action) noexcept {
    return unit(action.rate_scale) && action.compression_level >= 0 &&
           action.compression_level <= kMaxCompressionLevel;
}

bool valid(const Outcome& outcome) noexcept {
    return unit(outcome.delivered_ratio) && unit(outcome.on_time_ratio) &&
           std::isfinite(outcome.bandwidth_ratio) && outcome.bandwidth_ratio >= 0.0;
}

FeatureVector make_features(const LinkFeatures& link, const CommAction& action) {
    const double loss = link.packet_loss_ratio;
    const double latency = link.latency_s;
    const double queue = link.queue_fill_ratio;
    const double age = std::min(link.age_ratio, kMaxAgeRatio);
    const double rate = action.rate_scale;
    const double compression =
        static_cast<double>(action.compression_level) / kMaxCompressionLevel;
    const double reliable = action.reliable ? 1.0 : 0.0;
    return {
        1.0,
        loss,
        latency,
        queue,
        age,
        rate,
        compression,
        reliable,
        loss * rate,
        loss * reliable,
        latency * rate,
        queue * rate,
    };
}

double outcome_utility(const Outcome& outcome) {
    return outcome.on_time_ratio - 0.2 * outcome.bandwidth_ratio -
           0.5 * (1.0 - outcome.delivered_ratio);
}

}  // namespace swarm_adapter::strategy
