#include "swarm_adapter/link/adaptive_qos.h"
#include "swarm_adapter/link/clock_offset_estimator.h"
#include "swarm_adapter/link/keyframe_scheduler.h"

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void expect(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << "FAILED: " << message << '\n';
        std::exit(1);
    }
}

void test_adaptive_qos_hysteresis() {
    using namespace swarm_adapter;
    using namespace swarm_adapter::link;

    AdaptiveQosController controller;
    const LinkMetrics constrained{0.12, 100.0, 15.0, 0.65, 20.0};
    expect(
        controller.update(constrained).mode == NetworkMode::Healthy,
        "first degraded sample should not flap policy");
    const QosDecision degraded = controller.update(constrained);
    expect(
        degraded.mode == NetworkMode::Constrained,
        "confirmed degradation should enter constrained mode");
    expect(
        degraded.keyframe.reliability == Reliability::Reliable &&
            degraded.keyframe.target_rate_hz == 5.0,
        "constrained mode should retain reliable selected keyframes");

    const LinkMetrics critical{0.30, 300.0, 70.0, 0.95, 3.0};
    controller.update(critical);
    const QosDecision critical_policy = controller.update(critical);
    expect(
        critical_policy.mode == NetworkMode::Critical &&
            critical_policy.defer_submaps,
        "critical link should defer submaps");
    expect(
        critical_policy.keyframe.reliability == Reliability::BestEffort,
        "critical link should avoid reliable keyframe backlog by default");

    const QosDecision loop_candidate =
        controller.update(critical, FusionDemand{0.0, true, false});
    expect(
        loop_candidate.keyframe.reliability == Reliability::Reliable,
        "loop candidate should override keyframe reliability");
}

void test_clock_estimator() {
    using namespace swarm_adapter;
    using namespace swarm_adapter::link;

    ClockOffsetEstimator estimator(7, 200'000);
    estimator.observe(0, 5'500'000, 1'000'000);
    estimator.observe(0, 5'600'000, 1'000'000);
    estimator.observe(0, 5'400'000, 1'000'000);
    estimator.observe(0, 100'000'000, 1'000'000);

    const ClockEstimate estimate = estimator.estimate();
    expect(estimate.offset_ns == 5'000'000, "median should reject clock outlier");
    expect(
        estimate.median_absolute_deviation_ns == 100'000,
        "clock jitter should use median absolute deviation");
    expect(estimate.synchronized, "stable clock samples should be synchronized");
}

void test_keyframe_scheduler() {
    using namespace swarm_adapter;
    using namespace swarm_adapter::link;

    KeyframeScheduler scheduler;
    expect(
        scheduler.should_publish(0, 0.2, false, 5.0),
        "first scheduled keyframe should publish");
    expect(
        !scheduler.should_publish(100'000'000, 0.2, false, 5.0),
        "rate gate should suppress early keyframe");
    expect(
        scheduler.should_publish(200'000'000, 0.2, false, 5.0),
        "rate gate should publish at period");
    expect(
        scheduler.should_publish(250'000'000, 0.9, false, 5.0),
        "high uncertainty should force keyframe");
    expect(
        scheduler.should_publish(260'000'000, 0.2, true, 5.0),
        "loop candidate should force keyframe");

    bool threw = false;
    try {
        scheduler.should_publish(200'000'000, 0.2, false, 5.0);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    expect(threw, "out-of-order keyframe timestamp should be rejected");
}

}  // namespace

int main() {
    test_adaptive_qos_hysteresis();
    test_clock_estimator();
    test_keyframe_scheduler();
    return 0;
}
