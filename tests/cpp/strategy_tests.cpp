#include "check.h"

#include "swarm_adapter/adapter/federated_client.h"
#include "swarm_adapter/link/freshness.h"
#include "swarm_adapter/strategy/comm_selector.h"
#include "swarm_adapter/strategy/features.h"
#include "swarm_adapter/strategy/policy_gate.h"
#include "swarm_adapter/strategy/policy_model.h"
#include "swarm_adapter/strategy/ring_strategy_store.h"
#include "swarm_adapter/strategy/safety_envelope.h"

#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <unistd.h>

using namespace swarm_adapter;
using namespace swarm_adapter::strategy;

namespace {

bool close(double a, double b) { return std::fabs(a - b) < 1e-12; }

void test_feature_golden() {
    std::ifstream in(std::string(SWARM_ADAPTER_FIXTURE_DIR) + "/feature_golden.txt");
    expect(static_cast<bool>(in), "golden fixture should exist");
    std::string line;
    int phi_cases = 0;
    int utility_cases = 0;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream f(line);
        std::string kind;
        f >> kind;
        if (kind == "phi") {
            LinkFeatures link;
            CommAction action;
            int reliable = 0;
            f >> link.packet_loss_ratio >> link.latency_s >> link.queue_fill_ratio >>
                link.age_ratio >> action.rate_scale >> action.compression_level >> reliable;
            action.reliable = reliable != 0;
            const FeatureVector phi = make_features(link, action);
            for (std::size_t i = 0; i < kFeatureDim; ++i) {
                double expected = 0.0;
                f >> expected;
                expect(close(phi[i], expected), "feature mismatch at index " + std::to_string(i));
            }
            ++phi_cases;
        } else if (kind == "utility") {
            Outcome outcome;
            double expected = 0.0;
            f >> outcome.delivered_ratio >> outcome.on_time_ratio >> outcome.bandwidth_ratio >>
                expected;
            expect(close(outcome_utility(outcome), expected), "utility mismatch");
            ++utility_cases;
        }
    }
    expect(phi_cases > 0 && utility_cases > 0, "golden fixture should have cases");
}

void test_safety_envelope() {
    SafetyEnvelope envelope;
    expect(!envelope.allows(MessageClass::Health, {1.0, 0, false}),
           "health must stay reliable");
    expect(envelope.allows(MessageClass::Health, {1.0, 0, true}), "health reliable allowed");
    expect(!envelope.allows(MessageClass::Pose, {0.25, 0, false}),
           "pose rate below lower bound rejected");
    expect(!envelope.allows(MessageClass::Keyframe, {1.0, 9, true}),
           "keyframe compression above bound rejected");
    for (const CommAction& c : envelope.candidates(MessageClass::Mission)) {
        expect(c.reliable && c.rate_scale == 1.0, "mission candidates fixed and reliable");
    }
    TopicPolicy base;
    base.target_rate_hz = 30.0;
    const TopicPolicy applied = envelope.apply(MessageClass::Pose, base, {0.5, 0, false});
    expect(applied.target_rate_hz == 15.0, "pose rate scaled");
    expect(envelope.candidates(MessageClass::Submap).size() > 1, "submap has choices");
}

void test_freshness() {
    link::FreshnessEvaluator evaluator;
    link::ClockEstimate clock{9, 1'000'000, 100'000, true};
    MessageEnvelope env;
    env.robot_id = 1;
    env.map_version = 3;
    env.source_time_ns = 10'000'000;
    env.ttl_ms = 100;
    link::FreshnessSample sample;
    expect(evaluator.evaluate(env, 31'000'000, clock, 50, sample) == ReasonCode::Ok,
           "fresh sample accepted");
    expect(sample.age_ns == 20'000'000 && sample.on_time && sample.trainable,
           "age = receive - source - offset");
    expect(evaluator.evaluate(env, 300'000'000, clock, 50, sample) == ReasonCode::Expired,
           "ttl expiry detected");
    env.map_version = 0;
    expect(evaluator.evaluate(env, 31'000'000, clock, 50, sample) ==
               ReasonCode::UnknownMapVersion,
           "unknown map version rejected");
    env.map_version = 3;
    clock.synchronized = false;
    expect(evaluator.evaluate(env, 31'000'000, clock, 50, sample) ==
                   ReasonCode::ClockUnsynchronized &&
               !sample.trainable,
           "unsynchronized clock sample not trainable");
}

PolicyWeights linear_policy(std::uint64_t version, double reliable_weight) {
    PolicyWeights p;
    p.policy_version = version;
    p.round_id = version;
    p.weights[0] = 0.5;
    p.weights[7] = reliable_weight;
    return p;
}

void test_policy_file_roundtrip() {
    const std::string path = "/tmp/swarm_adapter_policy_" + std::to_string(::getpid()) + ".txt";
    const PolicyWeights policy = linear_policy(4, 0.1 / 3.0);
    expect(save_policy_file(path, policy) == ReasonCode::Ok, "save policy");
    PolicyWeights loaded;
    expect(load_policy_file(path, loaded) == ReasonCode::Ok, "load policy");
    expect(loaded.policy_version == 4 && loaded.weights == policy.weights, "exact roundtrip");

    FilePolicyClient client(path);
    expect(client.poll_global_policy().has_value(), "first poll returns policy");
    expect(!client.poll_global_policy().has_value(), "same version not returned twice");

    { std::ofstream bad(path); bad << "swarm_adapter.policy v1\npolicy_version 5\nround_id 1\nweights 1 2\n"; }
    expect(load_policy_file(path, loaded) == ReasonCode::InvalidInput, "short weights rejected");
    std::remove(path.c_str());
    expect(load_policy_file(path, loaded) == ReasonCode::IoError, "missing file");
}

void test_policy_gate() {
    PolicyGateConfig config;
    config.shadow_min_samples = 10;
    config.rollback_window = 10;
    PolicyGate gate(config);
    const LinkFeatures link{0.1, 0.05, 0.3, 0.5};
    const CommAction action{1.0, 0, true};

    expect(gate.propose(linear_policy(0, 0.0)) == ReasonCode::InvalidInput, "version 0 invalid");
    expect(gate.propose(linear_policy(1, 0.3)) == ReasonCode::Ok, "candidate accepted");
    expect(gate.state() == GateState::Shadow && gate.active() == nullptr, "shadow only");
    std::optional<GateEvent> event;
    for (int i = 0; i < 10; ++i) event = gate.observe(link, action, 0.8);
    expect(event && event->reason == ReasonCode::Ok && gate.state() == GateState::Active,
           "accurate candidate activated");
    expect(gate.propose(linear_policy(1, 0.3)) == ReasonCode::StalePolicyVersion,
           "same version stale");

    expect(gate.propose(linear_policy(2, -0.4)) == ReasonCode::Ok, "second candidate");
    for (int i = 0; i < 10; ++i) event = gate.observe(link, action, 0.8);
    expect(event && event->reason == ReasonCode::ShadowRejected &&
               gate.active()->policy_version == 1,
           "worse candidate rejected, active kept");

    expect(gate.propose(linear_policy(3, 0.3)) == ReasonCode::Ok, "third candidate");
    for (int i = 0; i < 10; ++i) gate.observe(link, action, 0.8);
    expect(gate.active()->policy_version == 3, "third activated");
    event.reset();
    for (int i = 0; i < 10 && !event; ++i) event = gate.observe(link, action, -0.5);
    expect(event && event->reason == ReasonCode::RolledBack &&
               gate.active()->policy_version == 1,
           "drift triggers rollback to previous policy");
}

void test_selector() {
    SafetyEnvelope envelope;
    PolicyGateConfig config;
    config.shadow_min_samples = 1;
    PolicyGate gate(config);
    const LinkFeatures link{0.2, 0.1, 0.5, 1.0};
    Selection s = select_action(MessageClass::Health, link, {0.2, 5, false}, gate, envelope);
    expect(s.source == DecisionSource::LocalRule && s.action.reliable &&
               s.action.rate_scale == 1.0 && s.action.compression_level == 0,
           "local default clamped into envelope");

    PolicyWeights prefer_low_rate;
    prefer_low_rate.policy_version = 7;
    prefer_low_rate.weights[0] = 0.5;
    prefer_low_rate.weights[5] = -1.0;
    gate.propose(prefer_low_rate);
    gate.observe(link, {1.0, 0, true}, -0.5);
    expect(gate.active() != nullptr, "policy active");
    s = select_action(MessageClass::Keyframe, link, {1.0, 0, true}, gate, envelope);
    expect(s.source == DecisionSource::FederatedPolicy && s.policy_version == 7 &&
               s.action.rate_scale == 0.25,
           "policy picks best in-envelope candidate");
    s = select_action(MessageClass::Health, link, {1.0, 0, true}, gate, envelope);
    expect(s.action.rate_scale == 1.0 && s.action.reliable, "policy cannot leave envelope");
}

void test_store() {
    RingStrategyStore store(2);
    const LinkFeatures link{0.1, 0.05, 0.3, 0.5};
    expect(store.append(ConfigDecisionRecord{1, 100, 1, MessageClass::Keyframe, link,
                                             {1.0, 0, true}, DecisionSource::FederatedPolicy,
                                             3}) == ReasonCode::Ok,
           "decision appended");
    expect(store.append(ConfigDecisionRecord{1, 101, 1, MessageClass::Keyframe, link,
                                             {1.0, 0, true}, DecisionSource::LocalRule, 0}) ==
               ReasonCode::Duplicate,
           "duplicate decision id");
    expect(store.append(OutcomeRecord{9, 110, {1.0, 1.0, 0.1}, 0, true}) ==
               ReasonCode::MissingReference,
           "outcome without decision");
    expect(store.append(OutcomeRecord{1, 110, {1.0, 0.9, 0.1}, 1000, true}) == ReasonCode::Ok,
           "outcome appended");
    expect(store.append(OutcomeRecord{1, 111, {1.0, 0.9, 0.1}, 1000, true}) ==
               ReasonCode::Duplicate,
           "duplicate outcome");
    expect(store.samples(3, 3).size() == 1 && store.samples(4, 9).empty(),
           "samples filtered by policy version");

    store.append(ConfigDecisionRecord{2, 200, 1, MessageClass::Submap, link, {0.5, 3, false},
                                      DecisionSource::LocalRule, 0});
    store.append(OutcomeRecord{2, 210, {0.5, 0.5, 0.2}, 9'000'000, false});
    expect(store.samples(0, 0).empty(), "untrainable outcome excluded");
    store.append(ConfigDecisionRecord{3, 300, 1, MessageClass::Submap, link, {0.5, 3, false},
                                      DecisionSource::LocalRule, 0});
    expect(store.decision_count() == 2 && store.samples(3, 3).empty(),
           "ring evicts oldest decision with its outcome");
    expect(store.evict_older_than(250) == 2 && store.decision_count() == 1, "ttl eviction");

    const std::string dir = "/tmp";
    std::string written;
    expect(store.flush_segment(dir, written) == ReasonCode::Ok && !written.empty(),
           "segment written");
    std::ifstream in(written);
    std::string first;
    std::getline(in, first);
    expect(first.find("\"table\":\"config_decision\"") != std::string::npos, "jsonl content");
    std::remove(written.c_str());
    expect(store.flush_segment(dir, written) == ReasonCode::Ok && written.empty(),
           "empty flush writes nothing");
}

}  // namespace

int main() {
    test_feature_golden();
    test_safety_envelope();
    test_freshness();
    test_policy_file_roundtrip();
    test_policy_gate();
    test_selector();
    test_store();
    return 0;
}
