#include "swarm_adapter/link/clock_offset_estimator.h"

#include <algorithm>
#include <cstdlib>
#include <stdexcept>
#include <utility>
#include <vector>

namespace swarm_adapter::link {
namespace {

std::int64_t median(std::vector<std::int64_t> values) {
    if (values.empty()) {
        return 0;
    }
    const auto middle = values.begin() + static_cast<std::ptrdiff_t>(
        (values.size() - 1) / 2);
    std::nth_element(values.begin(), middle, values.end());
    return *middle;
}

}  // namespace

ClockOffsetEstimator::ClockOffsetEstimator(
    std::size_t capacity,
    std::int64_t maximum_deviation_ns)
    : capacity_(capacity), maximum_deviation_ns_(maximum_deviation_ns) {
    if (capacity_ == 0 || maximum_deviation_ns_ < 0) {
        throw std::invalid_argument("invalid clock estimator config");
    }
}

void ClockOffsetEstimator::observe(
    std::int64_t source_time_ns,
    std::int64_t receive_time_ns,
    std::int64_t round_trip_time_ns) {
    if (round_trip_time_ns < 0) {
        throw std::invalid_argument("round-trip time must be non-negative");
    }
    const std::int64_t offset =
        receive_time_ns - source_time_ns - round_trip_time_ns / 2;
    if (offsets_.size() == capacity_) {
        offsets_.pop_front();
    }
    offsets_.push_back(offset);
}

ClockEstimate ClockOffsetEstimator::estimate() const {
    if (offsets_.empty()) {
        return {};
    }
    const std::vector<std::int64_t> values(offsets_.begin(), offsets_.end());
    const std::int64_t center = median(values);

    std::vector<std::int64_t> deviations;
    deviations.reserve(values.size());
    for (std::int64_t value : values) {
        deviations.push_back(std::llabs(value - center));
    }
    const std::int64_t deviation = median(std::move(deviations));
    return {
        values.size(),
        center,
        deviation,
        values.size() >= 3 && deviation <= maximum_deviation_ns_,
    };
}

}  // namespace swarm_adapter::link
