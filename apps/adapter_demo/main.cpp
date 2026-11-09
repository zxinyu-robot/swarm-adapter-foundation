// 端到端演示：链路劣化 → 本地规则 QoS → 记录 → 联邦策略旁路比对 → 生效 → 越界保护。
// 数据为合成数据，仅用于演示接口，不代表真机性能。
#include "swarm_adapter/link/adaptive_qos.h"
#include "swarm_adapter/strategy/comm_selector.h"
#include "swarm_adapter/strategy/ring_strategy_store.h"

#include <cstdio>

using namespace swarm_adapter;
using namespace swarm_adapter::strategy;

int main() {
    link::AdaptiveQosController qos;
    SafetyEnvelope envelope;
    PolicyGateConfig gate_config;
    gate_config.shadow_min_samples = 20;
    PolicyGate gate(gate_config);
    RingStrategyStore store(1024);

    PolicyWeights federated;
    federated.policy_version = 1;
    federated.round_id = 1;
    federated.weights = {0.9, -1.0, -0.5, -0.2, -0.1, 0.05, -0.05, 0.1, -0.5, 0.3, -0.4, -0.3};

    std::uint64_t decision_id = 0;
    for (int step = 0; step < 60; ++step) {
        const double loss = step < 20 ? 0.02 : 0.18;
        const link::LinkMetrics metrics{loss, step < 20 ? 30.0 : 120.0, 2.0,
                                        step < 20 ? 0.3 : 0.7, 20.0};
        const link::QosDecision rule = qos.update(metrics);
        const LinkFeatures features{loss, metrics.one_way_latency_ms / 1000.0,
                                    metrics.queue_fill_ratio, step < 20 ? 0.4 : 1.1};
        if (step == 10) {
            gate.propose(federated);
        }
        const CommAction local{rule.keyframe.target_rate_hz / 10.0, rule.compression_level,
                               rule.keyframe.reliability == Reliability::Reliable};
        const Selection chosen =
            select_action(MessageClass::Keyframe, features, local, gate, envelope);
        const TopicPolicy applied = envelope.apply(MessageClass::Keyframe, rule.keyframe,
                                                   chosen.action);

        ++decision_id;
        store.append(ConfigDecisionRecord{decision_id, step, 1, MessageClass::Keyframe,
                                          features, chosen.action, chosen.source,
                                          chosen.policy_version});
        const Outcome outcome{1.0 - loss, 1.0 - loss * 2.0, chosen.action.rate_scale * 0.5};
        store.append(OutcomeRecord{decision_id, step, outcome, 100'000, true});
        if (auto event = gate.observe(features, chosen.action, outcome_utility(outcome))) {
            store.append(PolicyVersionRecord{step, *event});
            std::printf("step %2d policy v%llu -> %s (%s) candidate_mse=%.4f\n", step,
                        static_cast<unsigned long long>(event->policy_version),
                        gate_state_name(event->state), reason_name(event->reason),
                        event->candidate_mse);
        }
        if (step % 10 == 0 || step == 59) {
            std::printf("step %2d mode=%s source=%s keyframe_rate=%.2fHz compression=%d\n",
                        step, link::AdaptiveQosController::name(qos.mode()).data(),
                        decision_source_name(chosen.source), applied.target_rate_hz,
                        applied.compression_level);
        }
    }
    std::printf("trainable samples: %zu\n", store.samples(0, 1).size());
    return 0;
}
