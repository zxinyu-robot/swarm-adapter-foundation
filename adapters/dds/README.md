# CycloneDDS 传输适配器（可选）

`Transport` 的 CycloneDDS 实现和一个跨机链路探测程序。核心库 `swarm_adapter` 不依赖本目录；
用 `-DSWARM_ADAPTER_BUILD_DDS=ON` 打开。需要 CycloneDDS ≥ 0.10（含 `idlc`），只用它的 C 接口，不需要 ROS。

```bash
# Ubuntu 24.04：sudo apt install cyclonedds-dev cyclonedds-tools
cmake -S . -B build/dds -DSWARM_ADAPTER_BUILD_DDS=ON   # 源码安装时加 -DCMAKE_PREFIX_PATH=<安装前缀>
cmake --build build/dds
ctest --test-dir build/dds
```

## TopicPolicy → DDS QoS

| TopicPolicy / 信封 | DDS QoS | 说明 |
| --- | --- | --- |
| `reliability` | RELIABILITY（RELIABLE / BEST_EFFORT） | |
| `history_depth` | HISTORY KEEP_LAST(depth) | 最小 1 |
| `deadline_ms` | DEADLINE | 0 表示不设 |
| `priority` | TRANSPORT_PRIORITY | |
| 信封 `ttl_ms` | LIFESPAN | 0 表示不过期 |
| `target_rate_hz` | — | 发送端节流，不是 DDS QoS |
| `compression_level` | — | 编码层负责；本仓未实现真实压缩 |

DDS 的可靠性等 QoS 在 writer 创建后不能改，`DdsTransport` 按（消息类，QoS）缓存 writer，
切换策略时换用另一个已匹配的 writer，不重建。`DdsReceiver` 同时开 Reliable 和 BestEffort
两个 reader（BestEffort reader 能匹配两种 writer，Reliable reader 负责重传），按（robot_id, sequence）去重。

## 链路探测 `swarm_link_probe`

- `rx` 端发起往返对时（`ClockOffsetEstimator`），在接收端算新鲜度（`FreshnessEvaluator`），
  按 `decision_id` 周期回传送达数、准时数、平均新鲜度、时钟不确定度。
- `tx` 端每个窗口在 `SafetyEnvelope` 的候选动作里随机选一个（只探索 `rate_scale` 和 `reliable`，压缩固定 0），
  把链路观测 / 配置决策 / 效果回执写进 `RingStrategyStore`，结束时输出 JSONL 分段，
  Python 端 `swarm_adapter.records.load_samples` 直接读取。
- 决策时的链路特征取自上一个已结算窗口；`queue_fill_ratio` 未测量，记为 0。
- 时钟不确定度超过 `--clock-max-dev-ms` 的窗口标记为不可训练。

```bash
# 接收端
CYCLONEDDS_URI=file://$PWD/cyclonedds.xml ./build/dds/adapters/dds/swarm_link_probe rx
# 发送端
CYCLONEDDS_URI=file://$PWD/cyclonedds.xml ./build/dds/adapters/dds/swarm_link_probe tx \
  --windows 20 --window-s 2 --records records/
```

网络接口、单播 peers 等由 `CYCLONEDDS_URI` 配置，例如只走某块网卡：

```xml
<CycloneDDS><Domain><General><Interfaces>
  <NetworkInterface name="wg0"/>
</Interfaces></General></Domain></CycloneDDS>
```

## 单机弱网实验

`scripts/netns_netem_probe.sh` 在一台机器上建两个网络命名空间，用 veth 相连，
两端加 `tc netem`（时延 / 抖动 / 丢包 / 限速），依次跑 healthy / constrained / critical 三档（需要 root）：

```bash
sudo adapters/dds/scripts/netns_netem_probe.sh build/dds/adapters/dds/swarm_link_probe out/ 20 2
```

这是真实 DDS 协议栈和内核网络，但链路劣化是注入的，不代表真实无线或广域网。结果见 `docs/evidence.md`。

## 跨机实验

`scripts/wg_netem_probe.sh` 在本机跑 tx、经 SSH 在远端跑 rx，DDS 走两机之间的隧道网卡（例如 WireGuard `wg0`）。
WireGuard 不转发组播，CycloneDDS 需关组播并写明单播 peer：

```xml
<CycloneDDS><Domain id="any">
  <General><Interfaces><NetworkInterface name="wg0"/></Interfaces><AllowMulticast>false</AllowMulticast></General>
  <Discovery><ParticipantIndex>auto</ParticipantIndex><Peers><Peer address="10.88.0.1"/></Peers></Discovery>
</Domain></CycloneDDS>
```

先跑 baseline（只有真实链路），再在两端 `wg0` 出口叠加与单机实验相同的三档 netem。
