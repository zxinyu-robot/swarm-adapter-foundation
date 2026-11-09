#include "swarm_adapter/strategy/safety_envelope.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace swarm_adapter::strategy {
namespace {

constexpr std::array<double, 4> kRateGrid{0.25, 0.5, 0.75, 1.0};
constexpr std::array<int, 4> kCompressionGrid{0, 3, 6, 9};

std::size_t index_of(MessageClass message_class) {
    const auto index = static_cast<std::size_t>(message_class);
    if (index >= kMessageClassCount) {
        throw std::out_of_range("unknown message class");
    }
    return index;
}

}  // namespace

SafetyEnvelope::SafetyEnvelope() {
    bounds_[index_of(MessageClass::Pose)] = {0.5, 1.0, 0, false, 10.0};
    bounds_[index_of(MessageClass::Health)] = {1.0, 1.0, 0, true, 1.0};
    bounds_[index_of(MessageClass::Keyframe)] = {0.25, 1.0, 6, false, 0.0};
    bounds_[index_of(MessageClass::Submap)] = {0.25, 1.0, 9, false, 0.0};
    bounds_[index_of(MessageClass::Mission)] = {1.0, 1.0, 0, true, 0.0};
    bounds_[index_of(MessageClass::LearningUpdate)] = {0.25, 1.0, 9, false, 0.0};
    bounds_[index_of(MessageClass::Directive)] = {1.0, 1.0, 0, true, 0.0};
}

void SafetyEnvelope::set_bounds(MessageClass message_class, const ClassBounds& bounds) {
    if (!std::isfinite(bounds.min_rate_scale) || !std::isfinite(bounds.max_rate_scale) ||
        bounds.min_rate_scale < 0.0 || bounds.max_rate_scale > 1.0 ||
        bounds.min_rate_scale > bounds.max_rate_scale ||
        bounds.max_compression_level < 0 ||
        bounds.max_compression_level > kMaxCompressionLevel ||
        !std::isfinite(bounds.min_rate_hz) || bounds.min_rate_hz < 0.0) {
        throw std::invalid_argument("invalid safety bounds");
    }
    bounds_[index_of(message_class)] = bounds;
}

const ClassBounds& SafetyEnvelope::bounds(MessageClass message_class) const {
    return bounds_[index_of(message_class)];
}

bool SafetyEnvelope::allows(MessageClass message_class, const CommAction& action) const {
    const ClassBounds& b = bounds(message_class);
    if (!valid(action)) {
        return false;
    }
    if (action.rate_scale < b.min_rate_scale || action.rate_scale > b.max_rate_scale) {
        return false;
    }
    if (action.compression_level > b.max_compression_level) {
        return false;
    }
    return !(b.reliable_required && !action.reliable);
}

std::vector<CommAction> SafetyEnvelope::candidates(MessageClass message_class) const {
    std::vector<CommAction> out;
    for (double rate : kRateGrid) {
        for (int compression : kCompressionGrid) {
            for (bool reliable : {false, true}) {
                const CommAction action{rate, compression, reliable};
                if (allows(message_class, action)) {
                    out.push_back(action);
                }
            }
        }
    }
    return out;
}

TopicPolicy SafetyEnvelope::apply(
    MessageClass message_class,
    const TopicPolicy& base,
    const CommAction& action) const {
    if (!allows(message_class, action)) {
        throw std::invalid_argument("action outside safety envelope");
    }
    const ClassBounds& b = bounds(message_class);
    TopicPolicy out = base;
    out.reliability = action.reliable ? Reliability::Reliable : Reliability::BestEffort;
    out.compression_level = action.compression_level;
    out.target_rate_hz = std::max(base.target_rate_hz * action.rate_scale, b.min_rate_hz);
    if (base.target_rate_hz <= 0.0) {
        out.target_rate_hz = 0.0;
    }
    return out;
}

}  // namespace swarm_adapter::strategy
