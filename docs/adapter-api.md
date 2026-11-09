# Adapter 接口

所有接口都在 `include/swarm_adapter/adapter/`，命名空间 `swarm_adapter`。除特别说明，实现不要求线程安全，由调用方串行调用。

## Transport

```cpp
ReasonCode publish(const MessageEnvelope&, const TopicPolicy&, fusion::ByteView payload);
```

- `payload` 为借用，只在调用期间有效。
- 不得阻塞超过 `policy.deadline_ms`；超时返回 `Expired`。
- `policy` 是经过 `SafetyEnvelope::apply` 后的最终配置，实现方只需把字段映射到具体中间件（如 DDS QoS）。

## FederatedClient

```cpp
std::optional<strategy::PolicyWeights> poll_global_policy();  // 不阻塞
ReasonCode submit_round_summary(const RoundSummary&);
```

- 返回的权重必须交给 `PolicyGate::propose`，不能直接使用。
- `FilePolicyClient`：轮询读取策略文件，只返回比上次更大的版本；读取失败原因见 `last_error()`。Python 端 Flower ClientApp 每轮把全局权重写入该文件。

## RobotBackend

```cpp
RobotStatus status() const;
ReasonCode execute(const TaskDirective&);
```

- `execute` 只会收到通过 `DirectiveGate::admit` 的指令；执行后由调用方生成 `ExecutionReport` 回传。

## MapBackend

```cpp
fusion::RegistryResult submit_submap(const fusion::SubmapDescriptor&);
fusion::RegistryResult submit_constraint(const fusion::RelativeConstraint&);
std::uint64_t map_version() const;
```

- `LocalMapBackend` 基于 `SubmapRegistry`，`map_version()` 即 `graph_version`。接外部建图后端时实现本接口。

## StrategyStore

```cpp
ReasonCode append(const LinkObservationRecord&);
ReasonCode append(const ConfigDecisionRecord&);   // Duplicate
ReasonCode append(const OutcomeRecord&);          // MissingReference / Duplicate
ReasonCode append(const PolicyVersionRecord&);
std::vector<TrainingSample> samples(min_version, max_version) const;
std::size_t evict_older_than(cutoff_ns);
```

`RingStrategyStore` 额外提供 `flush_segment(directory, written_path)`，把新记录追加写成 JSONL 分段文件。

## 一次通信决策的调用顺序

```cpp
link::QosDecision rule = qos.update(metrics);                 // 本地规则基准
Selection s = strategy::select_action(cls, features, local, gate, envelope);
TopicPolicy policy = envelope.apply(cls, rule.keyframe, s.action);
transport.publish(envelope_msg, policy, payload);
store.append(ConfigDecisionRecord{id, now, robot, cls, features, s.action, s.source, s.policy_version});
// …收到接收端回执后
store.append(OutcomeRecord{id, now, outcome, clock_mad, trainable});
if (auto event = gate.observe(features, s.action, outcome_utility(outcome))) {
    store.append(PolicyVersionRecord{now, *event});
}
```

完整示例见 `apps/adapter_demo/main.cpp`。
