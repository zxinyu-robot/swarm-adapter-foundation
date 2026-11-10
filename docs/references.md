# References and Related Work

**整理与署名：zxinyu**

本项目建立在已有的 Adapter、联邦学习和机器人数据集工作之上。下表区分了上游代码、外部框架和实验数据来源；本项目不将这些工作重新声明为自身成果。

## Upstream projects

| Work | Role in this project |
| --- | --- |
| [swarm-spatial-link](https://github.com/zxinyu-robot/swarm-spatial-link) | 提供弱网条件下的 QoS/通道调度基础。相关接口在本项目中抽象为 `TopicPolicy`、`SafetyEnvelope` 和端侧策略门控。 |
| [multi-robot-map-fusion](https://github.com/zxinyu-robot/multi-robot-map-fusion) | 提供共享内存和子图融合方向的基础实现。本项目通过 `MapBackend` / `SubmapRegistry` 保留其地图后端边界，但通信 MVP 不修改 SLAM 或建图流程。 |
| [edge-semantic-gateway](https://github.com/zxinyu-robot/edge-semantic-gateway) | 提供边侧语义调度和下行指令处理基础。本项目通过 Adapter 契约连接通信策略与边侧执行，但 Flower 输出不直接控制任务语义或状态估计。 |

## External frameworks and data

| Work | Role in this project |
| --- | --- |
| [Flower](https://github.com/adap/flower) | Apache-2.0 联邦学习框架。本项目使用 Flower `ClientApp` / `ServerApp` 和 FedAvg 聚合通信 utility 权重；原始端侧记录不上传，服务端只接收模型权重和汇总指标。 |
| [GrAco Dataset](https://sites.google.com/view/graco-dataset) | 提供 ground/aerial 机器人场景和 ROS bag 数据。本项目使用其中的 ground sample 生成 normalized events，并验证通信策略 replay 与 Flower 闭环。 |
| [rosbags](https://ternaris.gitlab.io/rosbags/) | 可选的 ROS1/ROS2 bag 读取库，用于将数据集消息转换为本项目的 normalized event 格式。 |

## Scope and attribution

本项目当前提交的真实数据结果是通信建议 MVP：同一 ground sample 被按时间窗口划分为两个 Flower 客户端，用于验证 `通信特征 -> TopicPolicy -> FedAvg -> 端侧策略安装` 链路。这两个客户端不代表真实 ground/aerial 异构联邦实验。

RTK ground truth 仅用于数据解码和一致性检查，不作为通信策略训练特征；本项目不宣称完成 SLAM、建图、定位或滤波精度验证。后续若加入 aerial bag、真实 DDS/netem 或其他后端，应在对应实验章节中单独说明数据来源、改动范围和引用工作。
