#include "swarm_adapter/link/freshness.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace swarm_adapter::link {

FreshnessEvaluator::FreshnessEvaluator(std::int64_t max_clock_uncertainty_ns)
    : max_clock_uncertainty_ns_(max_clock_uncertainty_ns) {
    if (max_clock_uncertainty_ns_ < 0) {
        throw std::invalid_argument("clock uncertainty bound must be non-negative");
    }
}

ReasonCode FreshnessEvaluator::evaluate(
    const MessageEnvelope& envelope,
    std::int64_t receive_time_ns,
    const ClockEstimate& clock,
    std::int64_t deadline_ms,
    FreshnessSample& out) const {
    out = {};
    out.message_class = envelope.message_class;
    out.deadline_ns = deadline_ms * 1'000'000;
    out.clock_uncertainty_ns = clock.median_absolute_deviation_ns;

    if (envelope.robot_id == 0 || deadline_ms <= 0 || envelope.ttl_ms < 0 ||
        !std::isfinite(envelope.confidence) || envelope.confidence < 0.0 ||
        envelope.confidence > 1.0) {
        return ReasonCode::InvalidInput;
    }

    out.age_ns = std::max<std::int64_t>(
        0, receive_time_ns - envelope.source_time_ns - clock.offset_ns);
    out.age_ratio = static_cast<double>(out.age_ns) /
                    static_cast<double>(out.deadline_ns);
    out.on_time = out.age_ns <= out.deadline_ns;

    if (envelope.map_version == 0) {
        return ReasonCode::UnknownMapVersion;
    }
    if (!clock.synchronized ||
        clock.median_absolute_deviation_ns > max_clock_uncertainty_ns_) {
        return ReasonCode::ClockUnsynchronized;
    }
    if (envelope.ttl_ms > 0 && out.age_ns > envelope.ttl_ms * 1'000'000) {
        out.trainable = true;
        return ReasonCode::Expired;
    }
    out.trainable = true;
    return ReasonCode::Ok;
}

}  // namespace swarm_adapter::link
