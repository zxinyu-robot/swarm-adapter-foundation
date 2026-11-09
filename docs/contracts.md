# 契约

字段定义以 [proto/swarm_adapter/v1](../proto/swarm_adapter/v1) 为准；C++ 头文件与之一一对应，`tests/python/test_contract_parity.py` 校验枚举值一致，`tests/fixtures/feature_golden.txt` 校验 C++ 与 Python 特征逐位一致。

## 通用规则

| 项 | 规则 |
| --- | --- |
| 时间 | 纳秒整型（`*_ns`），发送端时钟；有效期、deadline 为毫秒（`*_ms`） |
| 时钟 | 接收端用 `ClockOffsetEstimator`（中位数 + MAD）估计偏差；MAD 超过 2 ms 或样本不足视为未同步 |
| 配对 | 按 `map_version`（地图数据、指令）和 `decision_id`（决策与回执）配对，不按时间配对 |
| 未知版本 | `map_version = 0` 拒收（`UnknownMapVersion`） |
| 坐标系 | `frame_id` 必填，由发送端声明；本仓库不做坐标变换 |
| 失败码 | 全仓统一 `ReasonCode`，日志和记录文件用 `reason_name()` 的字符串 |
| 字段演进 | proto 只追加新字段号，不复用、不改语义；删除字段用 `reserved`。C++ 结构体同步追加到末尾 |

## 三条通道

| 通道 | 方向 | 消息 | 执行权 |
| --- | --- | --- | --- |
| 状态通道 | 上行 | `MessageEnvelope` + 位姿 / 健康度 / 关键帧 / 子图 | 本地 `AdaptiveQosController` 给基准 QoS，策略只能在安全边界内调整 |
| 学习通道 | 双向 | 下行 `PolicyUpdate`，上行权重 + `RoundSummary` | 端侧 `PolicyGate` 决定是否生效 |
| 指令通道 | 下行 + 回执 | `TaskDirective` / `ExecutionReport` | 端侧 `DirectiveGate` 与本机安全保持可否决 |

## 联邦策略的锚定点

策略只作用于 `TopicPolicy`：

| 字段 | 单位 | 策略能否改 |
| --- | --- | --- |
| `reliability` | BestEffort / Reliable | 能（健康度、任务、指令强制 Reliable） |
| `target_rate_hz` | Hz | 能，只能按 `rate_scale ∈ [下限, 1]` 降频，且不低于该类消息的 `min_rate_hz` |
| `compression_level` | 0–9 | 能，不超过该类消息上限 |
| `history_depth`、`deadline_ms`、`priority` | — | 首版不开放，沿用本地规则 |

策略**不能**读写：状态估计内部状态（均值、协方差、增益）、运动控制参数、地图内容。`MessageEnvelope.uncertainty` 只作为只读特征。

默认安全边界（`SafetyEnvelope`，配置值，非实测）：

| 消息类别 | rate_scale | 压缩上限 | 强制 Reliable | 最低频率 |
| --- | --- | --- | --- | --- |
| Pose | 0.5–1.0 | 0 | 否 | 10 Hz |
| Health | 1.0 | 0 | 是 | 1 Hz |
| Keyframe | 0.25–1.0 | 6 | 否 | — |
| Submap | 0.25–1.0 | 9 | 否 | — |
| Mission | 1.0 | 0 | 是 | — |
| LearningUpdate | 0.25–1.0 | 9 | 否 | — |
| Directive | 1.0 | 0 | 是 | — |

## 特征与效用

特征 `phi(link, action)`，12 维，顺序固定：

```text
[1, loss, latency_s, queue, min(age_ratio, 4), rate_scale, compression/9, reliable,
 loss*rate_scale, loss*reliable, latency_s*rate_scale, queue*rate_scale]
```

效用（标签）：`utility = on_time_ratio - 0.2 * bandwidth_ratio - 0.5 * (1 - delivered_ratio)`。

策略模型：`utility ≈ weights · phi`。端侧在安全边界的候选动作中取预测效用最高者。

修改特征或效用必须同时改 `src/strategy/features.cpp`、`python/swarm_adapter/features.py`，重新生成 golden fixture，并升级策略文件头的版本号。

## 新鲜度

`age_ns = max(0, receive_time_ns - source_time_ns - clock.offset_ns)`；`age_ratio = age / deadline`。

| 条件 | 结果 | 能否进训练集 |
| --- | --- | --- |
| `map_version = 0` | `UnknownMapVersion` | 否 |
| 时钟未同步 / MAD 超阈值 | `ClockUnsynchronized` | 否 |
| `age > ttl` | `Expired` | 能（过期本身就是通信效果） |
| 其余 | `Ok` | 能 |

## 策略门

```text
LocalRules ──propose──► Shadow ──样本数够、误差不比现行差──► Active
                          │                                  │
                          └──误差更大──► ShadowRejected       └──滚动窗口误差超阈值──► RolledBack（退回上一版）
```

- `policy_version` 必须大于已见过的最大版本，否则 `StalePolicyVersion`。
- 旁路比对：候选策略只计算不执行，用它预测实际执行动作的效用，与真实回执比较 MSE。
- 默认参数（配置值）：旁路样本 50 条；无现行策略时 MSE 上限 0.05；回滚窗口 50 条、MSE 阈值 0.10。

## 端侧策略库

四张表，`RingStrategyStore` 每张表固定容量，满了淘汰最旧；决策被淘汰时一并淘汰它的回执。

| 表 | JSONL `table` | 键 | 内容 |
| --- | --- | --- | --- |
| 链路观测 | `link_observation` | `record_id` | 时间、机器人、消息类别、链路档位、链路特征 |
| 配置决策 | `config_decision` | `decision_id`（唯一） | 特征、动作、来源（`local_rule` / `federated_policy`）、`policy_version` |
| 效果回执 | `outcome` | `decision_id`（必须已存在） | 送达率、准时率、带宽占比、时钟不确定度、`trainable` |
| 策略版本 | `policy_version` | — | 版本、轮次、状态、原因、MSE |

分段文件 `segment_NNNNNN.jsonl` 只追加；读取端跳过无法解析的残行（掉电保护）。

## 策略文件

纯文本，UTF-8，原子替换（写 `.tmp` 后 rename）：

```text
swarm_adapter.policy v1
policy_version <uint64, > 0>
round_id <uint64>
feature_dim 12
weights <12 个 double>
```

`#` 开头为注释。未知键、维度不符、非有限值一律拒收（`InvalidInput`）。

## 指令准入

`DirectiveGate::admit` 按顺序校验，第一项不过即返回：

1. 身份与字段：`directive_id ≠ 0`、机器人 / 会话匹配、`ttl_ms > 0`、`confidence ∈ [0,1]` → `InvalidInput`
2. 重复 `directive_id` → `Duplicate`
3. `map_version = 0` → `UnknownMapVersion`
4. 超过有效期 → `Expired`
5. 租约 epoch 不符 → `LeaseMismatch`
6. 地图版本不符 → `MapVersionMismatch`
7. 本机安全保持 → `SafetyHold`
