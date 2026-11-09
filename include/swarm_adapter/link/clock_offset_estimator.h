#ifndef SWARM_ADAPTER_LINK_CLOCK_OFFSET_ESTIMATOR_H
#define SWARM_ADAPTER_LINK_CLOCK_OFFSET_ESTIMATOR_H

#include <cstddef>
#include <cstdint>
#include <deque>

namespace swarm_adapter::link {

struct ClockEstimate {
    std::size_t samples{};
    std::int64_t offset_ns{};
    std::int64_t median_absolute_deviation_ns{};
    bool synchronized{};
};

class ClockOffsetEstimator {
public:
    explicit ClockOffsetEstimator(
        std::size_t capacity = 31,
        std::int64_t maximum_deviation_ns = 2'000'000);

    void observe(
        std::int64_t source_time_ns,
        std::int64_t receive_time_ns,
        std::int64_t round_trip_time_ns);

    [[nodiscard]] ClockEstimate estimate() const;

private:
    std::size_t capacity_;
    std::int64_t maximum_deviation_ns_;
    std::deque<std::int64_t> offsets_;
};

}  // namespace swarm_adapter::link

#endif
