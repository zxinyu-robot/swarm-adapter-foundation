# Swarm Adapter Foundation

[![CI](https://github.com/zxinyu-robot/swarm-adapter-foundation/actions/workflows/ci.yml/badge.svg)](https://github.com/zxinyu-robot/swarm-adapter-foundation/actions/workflows/ci.yml)
[![C++17](https://img.shields.io/badge/C%2B%2B-17-00599C.svg)](https://isocpp.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

面向异构多机（无人机 + 机器狗）的底层 Adapter 基础设施：统一多机状态流、地图融合和下行指令的契约，并把中心化联邦学习框架（Flower）输出的**通信策略**安全地落到端侧通信配置上。

本仓库由三个公开仓库聚合演进而来，原仓库保留不动：
[swarm-spatial-link](https://github.com/zxinyu-robot/swarm-spatial-link)（弱网 QoS 调度）、
[multi-robot-map-fusion](https://github.com/zxinyu-robot/multi-robot-map-fusion)（共享内存与子图融合）、
[edge-semantic-gateway](https://github.com/zxinyu-robot/edge-semantic-gateway)（边侧语义调度）。

## 平台与验证程度

| 部分 | 平台 | 验证程度 |
| --- | --- | --- |
| C++17 核心（`include/`、`src/`） | Linux / macOS，无 ROS 依赖 | 单元测试 + 合成数据 Demo |
| Python 联邦适配（`python/swarm_adapter`） | Python 3.10+，Flower 1.43 | 单元测试 + Flower 本机仿真（2 节点 × 3 轮，合成数据） |
| 边侧参考消费方（`gateway/`） | Python，Qwen-VL / Gazebo 为可选 | 原仓 28 项单测 + TaskDirective 下行 5 项；仿真链路见 `gateway/README.md` |
| 下行指令接收器（`apps/directive_receiver`） | Linux / macOS | 与网关进程间端到端测试（DirectiveGate 准入 + ExecutionReport） |
| CycloneDDS 传输适配器（`adapters/dds`，可选） | Linux，CycloneDDS 0.10.4 | 单元测试；单机网络命名空间 + netem；两台主机经 WireGuard 跨机 + netem |

没有真机数据。链路数字来自真实 DDS 协议栈在单机网络模拟和一条跨境公网链路上的单次运行，不代表机器人之间的无线链路；其余数字都是合成数据下的接口验证。逐条证据见 [docs/evidence.md](docs/evidence.md)。

## 核心原则

1. **联邦策略只能改通信配置。** 策略的输出类型只有 `TopicPolicy`（可靠性、历史深度、频率、deadline、优先级、压缩等级），代码里没有任何写入状态估计（卡尔曼滤波等）内部量的接口。滤波器的不确定度只能作为只读输入特征。
2. **端侧有最终否决权。** 联邦端、调度端只有建议权。`SafetyEnvelope` 限定每类消息允许的动作范围（例如健康度、任务指令必须 Reliable，位姿频率有下限）；`PolicyGate` 先旁路比对再生效，效果变差自动回滚；`DirectiveGate` 校验租约、地图版本和本机安全保持。
3. **按版本配对，不按时间配对。** 多条数据之间用 `map_version` / `decision_id` 配对；`map_version = 0` 一律拒收。
4. **新鲜度在接收端算。** `age = receive_time - source_time - clock_offset`，时钟不同步的样本不进训练集。
5. **原始记录不出机器人。** 端侧 `StrategyStore` 记录链路观测、配置决策、效果回执、策略版本四张表；上传给联邦服务端的只有模型权重和汇总指标。

## 架构

```text
              Flower ServerApp（FedAvg，聚合通信策略权重）
                       ▲ 权重 + 汇总指标      │ 全局权重
                       │                      ▼
 ┌──────────── 机器人本机 ─────────────────────────────────────────┐
 │ Flower ClientApp（python/swarm_adapter/fl）                     │
 │   本地训练 ◄── JSONL 分段文件        策略文件 ──┐               │
 │ ────────────────────────────────────────────── │ ───────────── │
 │ C++17 核心                                     ▼               │
 │   RingStrategyStore ◄── 记录 ──┐   FilePolicyClient → PolicyGate│
 │                                │       （旁路比对 / 生效 / 回滚）│
 │   AdaptiveQosController ──► select_action ◄── SafetyEnvelope   │
 │   （本地规则基准）              │                               │
 │                                ▼                               │
 │   FreshnessEvaluator   TopicPolicy ──► Transport（DDS/共享内存…）│
 │   ClockOffsetEstimator                                         │
 │   SharedFrameSlot / SubmapRegistry ──► MapBackend               │
 │   DirectiveGate ──► RobotBackend                                │
 └────────────────────────────────────────────────────────────────┘
```

## 三条通道

| 通道 | 方向 | 契约 | 实现 |
| --- | --- | --- | --- |
| 状态通道 | 上行 | `MessageEnvelope` + `TopicPolicy` | `AdaptiveQosController` 定基准，`SafetyEnvelope` 限幅，`Transport` 发送；`DdsTransport` 把 `TopicPolicy` 映射成 DDS QoS |
| 学习通道 | 双向 | `PolicyUpdate` / `RoundSummary`（proto） | 端侧 `RingStrategyStore` 出样本，Flower ClientApp 本地训练，`PolicyGate` 旁路比对后生效 |
| 指令通道 | 下行 + 回执 | `TaskDirective` / `ExecutionReport`（JSONL，字段与 proto 一致） | `gateway/` 把语义调度结果转成 `TaskDirective`，机器人端 `DirectiveGate` 准入后回 `ExecutionReport` |

## 链路实测要点

`adapters/dds/scripts/` 里的两个脚本分别在单机网络命名空间和两台主机之间（WireGuard 隧道）跑真实 DDS，
叠加 `tc netem` 劣化，结果直接写进端侧策略库，可被 Flower 客户端读成训练样本。完整数字和条件见 [docs/evidence.md](docs/evidence.md)。

- 跨机链路 RTT 约 160 ms 时，Reliable 重传后送达率接近 1，但准时率（deadline 200 ms）低于 BestEffort。
  这类“配置 → 效果”的关系只能在端侧记录里学到，规则表写不出来。
- 拥塞档位下往返对时误差升到 100 ms 以上，这些窗口按规则不进训练集；对时方法还需要改进。

## Adapter 接口

| 接口 | 头文件 | 作用 | 首版实现 |
| --- | --- | --- | --- |
| `Transport` | `adapter/transport.h` | 怎么传 | `DdsTransport`（可选包 `adapters/dds`，CycloneDDS）；共享内存等由使用方实现 |
| `FederatedClient` | `adapter/federated_client.h` | 和联邦框架对接 | `FilePolicyClient`（读 Flower 客户端写的策略文件） |
| `RobotBackend` | `adapter/robot_backend.h` | 和具体机器人对接 | 由使用方实现（Go2、无人机）；下行准入参考实现见 `apps/directive_receiver` |
| `MapBackend` | `adapter/map_backend.h` | 建图后端 | `LocalMapBackend`（基于 `SubmapRegistry`） |
| `StrategyStore` | `adapter/strategy_store.h` | 端侧策略记录 | `RingStrategyStore`（环形缓冲 + 只追加 JSONL） |

接口细节见 [docs/adapter-api.md](docs/adapter-api.md)，契约字段见 [docs/contracts.md](docs/contracts.md) 与 [proto/swarm_adapter/v1](proto/swarm_adapter/v1)。

## 快速开始

```bash
# C++17 核心
cmake --preset test
cmake --build --preset test
ctest --preset test
./build/test/adapter_demo

# 可选：CycloneDDS 传输适配器与链路探测（见 adapters/dds/README.md）
cmake -S . -B build/dds -DSWARM_ADAPTER_BUILD_DDS=ON
cmake --build build/dds && ctest --test-dir build/dds

# 机器人端下行指令参考接收器：TaskDirective → DirectiveGate → ExecutionReport
./build/test/swarm_directive_receiver --port 9879 --robot-id 1 --session-id 7 --map-version 1 --lease-epoch 1

# Python 侧（含 Flower 仿真）
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[simulation,dev]"
pytest -q tests/python
```

`pyproject.toml` 的 `[tool.flwr.app.components]` 已登记 ServerApp / ClientApp；部署时每个节点通过 node_config 的 `records-dir`、`policy-path` 指向本机记录目录和策略文件。

作为库使用：

```cmake
find_package(swarm_adapter REQUIRED)
target_link_libraries(your_target PRIVATE swarm_adapter::swarm_adapter)
```

## 目录

```text
include/swarm_adapter/  公开头文件：contract/ link/ fusion/ strategy/ directive/ adapter/
src/                    C++17 实现
apps/adapter_demo/      端到端演示（合成数据）
apps/directive_receiver/ 机器人端下行指令参考接收器（DirectiveGate 准入）
adapters/dds/           可选 CycloneDDS 传输适配器、链路探测、弱网实验脚本
proto/swarm_adapter/v1/ 跨语言契约 IDL（protobuf）
python/swarm_adapter/   特征、记录读取、本地训练、Flower ClientApp/ServerApp
gateway/                边侧语义调度参考消费方（原 edge-semantic-gateway）
config/                 链路策略配置
tests/                  cpp/ python/ fixtures/
docs/                   契约、接口、证据
```

## 自研与开源

- 本仓库代码为自研的脱敏公开重构。
- 联邦学习框架使用 [Flower](https://github.com/adap/flower)（Apache-2.0），作为可选依赖，C++ 核心不依赖它。
- 协同建图后端（如 Swarm-SLAM）与原工程中的联邦调度模块不在本仓库中，只通过 `MapBackend` / `FederatedClient` 接口对接。
- 第三方依赖见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 不包含

- 状态估计 / 卡尔曼滤波实现，以及任何把联邦输出写回滤波器的通道。
- ROS 2 适配器、真实 Mesh 网络配置、真机数据。DDS 只提供 CycloneDDS 一种实现。
- protobuf 生成代码（IDL 已定义，生成与 gRPC 传输后续接入）。

## 许可证

[MIT](LICENSE)

## 引用与相关工作

本项目聚合并扩展了已有的 Adapter、边侧调度和联邦学习工作。上游仓库、Flower、GrAco 数据集及其在本项目中的具体用途、继承边界和署名说明见 [docs/references.md](docs/references.md)。

## Flower communication MVP: real GrAco ground sample

**实验与结果整理：zxinyu**

已使用真实 GrAco ground ROS bag 完成通信建议链路闭环验证：

```text
normalized events -> communication features -> Flower ClientApp
                 -> FedAvg global weights -> TopicPolicy
                 ->端侧策略安装与通信 utility 评估
```

本次 MVP 将同一 ground sample 按时间窗口划分为两个客户端 `node_0` 和 `node_1`，仅用于验证 Flower 联邦通信建议链路；这两个客户端不代表 ground/aerial 异构机器人。RTK ground truth 仅作为数据参考，不进入通信策略训练特征，也不参与 SLAM、建图、定位或滤波流程。

### FedAvg 验证结果

| 项目 | 结果 |
| --- | --- |
| 客户端 | 2 个真实 ground 时间窗口客户端 |
| 联邦轮数 | 3 轮 FedAvg |
| 每轮返回 | 2/2 客户端训练成功，2/2 客户端评估成功 |
| 第 1 轮 `mse-before` | 0.82736 |
| 第 1 轮 `mse-after` | 0.27134 |
| 第 1 轮 `eval-mse` | 0.27135 |
| 第 2/3 轮 `mse-after` | 约 0.27134 |
| 第 2/3 轮 `eval-mse` | 约 0.27135 |

最终全局策略已写入两个客户端的策略文件，策略输出仍只允许影响 `TopicPolicy`；`SafetyEnvelope` 和 `PolicyGate` 保持端侧最终约束。

### 与通信 baseline 对照

| 策略 | Delivered | On-time | 带宽比例 | 发送字节 |
| --- | ---: | ---: | ---: | ---: |
| BestEffort，无压缩 | 89.82% | 89.82% | 0.768 | 3.22 GB |
| Reliable + 压缩等级 4 | 97.52% | 97.52% | 0.522 | 2.19 GB |
| rate scale 0.5 | 44.03% | 44.03% | 0.320 | 1.34 GB |

### MVP 产物

- 全局策略：`data/graco/mvp-global-policy.txt`
- 客户端策略：`data/graco/mvp_clients/node_0/policy.txt`、`data/graco/mvp_clients/node_1/policy.txt`
- 真实 normalized events：`data/graco/sample-ground/events.jsonl`
- 高精度 RTK ground truth：`data/graco/sample-ground/ground_truth.jsonl`

该结果验证的是“联邦学习向通信层提供策略建议”的闭环，不宣称完成 SLAM 精度验证。后续若要进行真实 ground/aerial 异构联邦实验，还需要接入 aerial ROS bag；DDS/netem 也不包含在本次 MVP 中。
