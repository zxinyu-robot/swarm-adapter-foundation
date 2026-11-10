# Swarm Adapter Foundation

[![CI](https://github.com/zxinyu-robot/swarm-adapter-foundation/actions/workflows/ci.yml/badge.svg)](https://github.com/zxinyu-robot/swarm-adapter-foundation/actions/workflows/ci.yml)
[![C++17](https://img.shields.io/badge/C%2B%2B-17-00599C.svg)](https://isocpp.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

面向异构多机（无人机、机器狗等）的 Adapter 基础设施。项目把多机状态、通信策略、地图后端和下行指令统一到稳定的接口上，并将 Flower 输出的**通信建议**安全地落到端侧 `TopicPolicy`。

> **核心边界：联邦学习只负责通信建议，不参与 SLAM、建图、定位或滤波。**

本仓库由以下公开工作聚合演进而来，来源与贡献边界见[引用与相关工作](docs/references.md)：

- [swarm-spatial-link](https://github.com/zxinyu-robot/swarm-spatial-link)：弱网 QoS 与通道调度
- [multi-robot-map-fusion](https://github.com/zxinyu-robot/multi-robot-map-fusion)：共享内存与子图融合
- [edge-semantic-gateway](https://github.com/zxinyu-robot/edge-semantic-gateway)：边侧语义调度

## 当前状态

| 能力 | 状态 |
| --- | --- |
| C++17 Adapter 核心 | Linux/macOS，无 ROS 依赖；单元测试与合成数据 Demo |
| Flower 联邦适配 | Python 3.10+；ClientApp/ServerApp、FedAvg、本地记录训练 |
| GrAco 通信验证 | 已完成 ground sample 的结果验证；实验脚本与派生数据暂存于验证工作区 |
| 真实通信 MVP | 已完成 2 客户端 × 3 轮 FedAvg 的 ground sample 闭环 |
| 真实异构 ground/aerial 联邦 | 尚未完成，需要 aerial ROS bag |
| 真实 DDS/netem 联邦链路 | 不属于当前 MVP |

## 设计原则

1. **策略只改通信配置。** Flower 输出只能影响 `TopicPolicy`：可靠性、历史深度、频率、deadline、优先级和压缩等级。
2. **端侧最终否决。** `SafetyEnvelope` 限制动作范围，`PolicyGate` 旁路比较、准入并在效果变差时回滚。
3. **数据留在端侧。** `RingStrategyStore` 记录链路观测、配置决策、效果回执和策略版本；服务端只接收模型权重与汇总指标。
4. **训练样本可追溯。** 样本按 `map_version` / `decision_id` 配对；新鲜度和时钟偏差在接收端计算。

## 架构

```text
                 Flower ServerApp / FedAvg
                    ▲ 权重与汇总指标
                    │
┌───────────────────┴────────────── 机器人本机 ───────────────────┐
│ Flower ClientApp ── 本地 records ── 本地 utility 训练            │
│        │                                                        │
│        └── FilePolicyClient → PolicyGate → SafetyEnvelope       │
│                                      │                          │
│ AdaptiveQosController ── TopicPolicy ──► Transport              │
│ RingStrategyStore ◄── 链路观测 / 决策 / 回执                     │
│ SharedFrameSlot / SubmapRegistry ──► MapBackend                 │
│ DirectiveGate ──► RobotBackend                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 三条接口通道

| 通道 | 主要契约 | 作用 |
| --- | --- | --- |
| 状态通道 | `MessageEnvelope` + `TopicPolicy` | 依据本地基准和安全边界发送状态数据 |
| 学习通道 | `PolicyUpdate` / `RoundSummary` | 从端侧记录生成样本，Flower 聚合通信 utility |
| 指令通道 | `TaskDirective` / `ExecutionReport` | 下行任务准入、执行和回执 |

## 快速开始

### C++ 核心

```bash
cmake --preset test
cmake --build --preset test
ctest --preset test
./build/test/adapter_demo
```

### Python 与 Flower

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[simulation,dev]"
pytest -q tests/python
```

部署 Flower 节点时，通过 `node_config` 的 `records-dir` 和 `policy-path` 指向本机记录目录与策略文件。C++ 核心不依赖 Flower。

### 可选 CycloneDDS

```bash
cmake -S . -B build/dds -DSWARM_ADAPTER_BUILD_DDS=ON
cmake --build build/dds
ctest --test-dir build/dds
```

## 真实 GrAco 通信 MVP

**实验与结果整理：zxinyu**

使用真实 GrAco ground ROS bag 完成以下闭环：

```text
normalized events
    → communication features
    → Flower ClientApp
    → FedAvg global weights
    → TopicPolicy
    → 端侧策略安装与通信 utility 评估
```

本次验证将同一个 ground sample 按时间窗口划分为 `node_0` 和 `node_1` 两个客户端，仅用于验证联邦通信建议机制；它们不代表真实 ground/aerial 异构客户端。RTK ground truth 仅用于数据解码和一致性检查，不进入策略训练。

### FedAvg 结果

| 指标 | 结果 |
| --- | ---: |
| 客户端 / 联邦轮数 | 2 / 3 |
| 每轮训练返回 | 2/2 |
| 每轮评估返回 | 2/2 |
| 第 1 轮 `mse-before` | 0.82736 |
| 第 1 轮 `mse-after` | 0.27134 |
| 第 1 轮 `eval-mse` | 0.27135 |
| 第 2/3 轮 `mse-after` | 约 0.27134 |
| 第 2/3 轮 `eval-mse` | 约 0.27135 |

### 通信 baseline

| 策略 | Delivered | On-time | 带宽比例 | 发送字节 |
| --- | ---: | ---: | ---: | ---: |
| BestEffort，无压缩 | 89.82% | 89.82% | 0.768 | 3.22 GB |
| Reliable + 压缩等级 4 | 97.52% | 97.52% | 0.522 | 2.19 GB |
| rate scale 0.5 | 44.03% | 44.03% | 0.320 | 1.34 GB |

验证工作区中生成了全局策略、客户端策略、normalized events 和高精度 RTK ground-truth
文件；这些派生数据没有随本次 README 提交进入 Git 仓库。Replay 只模拟通信行为，不修改
估计器或建图参数；ground-truth stream 作为评估参考保留，但不会进入通信 replay。

## 项目结构

```text
include/swarm_adapter/       C++ 公开头文件
src/                         C++17 实现
apps/adapter_demo/           合成数据端到端演示
apps/directive_receiver/     下行指令参考接收器
adapters/dds/                可选 CycloneDDS 适配器与弱网脚本
proto/swarm_adapter/v1/      protobuf 契约 IDL
python/swarm_adapter/        特征、记录、本地训练和 Flower 应用
gateway/                     边侧语义调度参考消费方
tests/                       C++、Python 与 fixture 测试
docs/                        接口、契约、证据和引用说明
```

## 范围与限制

- 不包含状态估计、卡尔曼滤波实现，或把联邦输出写回滤波器的通道。
- 不包含 ROS 2 / DDS 厂商通用适配、真实 Mesh 配置或真机性能结论。
- GrAco 实验脚本和派生数据当前属于验证工作区，不是本 Git 提交中的运行时组件。
- 当前真实联邦结果只覆盖 ground sample 的通信建议 MVP，不代表 ground/aerial 异构实验。
- ATE/RPE 仅可作为未来外部系统评估，不属于当前 Flower 通信策略闭环。

## 文档与引用

- [Adapter API](docs/adapter-api.md)
- [协议契约](docs/contracts.md)
- [实验依据](docs/evidence.md)
- [引用与相关工作](docs/references.md)
- [第三方依赖](THIRD_PARTY.md)

## 许可证

[MIT](LICENSE)
