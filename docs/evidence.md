# 证据

证据等级：**单测**＝单元测试；**仿真**＝本机或云端仿真；**网络模拟**＝真实 DDS 协议栈与内核网络，链路劣化由 `tc netem` 注入；**跨机**＝两台主机经真实网络；**真机**＝实机运行。本仓库目前没有真机证据。

| 结论 | 等级 | 平台 | 出处 |
| --- | --- | --- | --- |
| C++ 核心按 C++17 编译，无 ROS 依赖 | 单测 | Linux（GCC）；CI 另跑 macOS | `CMakeLists.txt`、CI |
| 链路三档切换、QoS 矩阵、时钟偏差估计、关键帧调度 | 单测 | 同上 | `tests/cpp/link_tests.cpp`（迁自 swarm-spatial-link） |
| 共享内存帧槽、子图注册幂等与版本递增 | 单测 | 同上 | `tests/cpp/fusion_tests.cpp`（迁自 multi-robot-map-fusion） |
| 安全边界拒绝越界动作；健康度 / 任务 / 指令强制 Reliable | 单测 | 同上 | `tests/cpp/strategy_tests.cpp` |
| 新鲜度、未知地图版本拒收、时钟未同步样本不进训练集 | 单测 | 同上 | `tests/cpp/strategy_tests.cpp` |
| 策略门：旁路比对生效 / 拒绝、旧版本拒收、效果变差回滚 | 单测 | 同上 | `tests/cpp/strategy_tests.cpp` |
| 策略库：去重、缺失引用、容量淘汰、TTL 淘汰、JSONL 分段 | 单测 | 同上 | `tests/cpp/strategy_tests.cpp` |
| 指令准入七项校验 | 单测 | 同上 | `tests/cpp/directive_tests.cpp` |
| C++ 与 Python 特征、效用逐位一致；proto 与 C++ 枚举一致 | 单测 | Python 3.12 | `tests/python/test_features.py`、`test_contract_parity.py` |
| Flower FedAvg 2 节点 × 3 轮，在合成线性数据上收敛到真值（容差 1e-2），各节点装上最后一轮策略文件 | 仿真（本机，合成数据） | Flower 1.43 + Ray | `tests/python/test_flower_simulation.py` |
| `TopicPolicy` → DDS QoS 映射；Reliable / BestEffort 双 reader 去重后每条恰好一次 | 单测 | Linux，CycloneDDS 0.10.4 | `adapters/dds/tests/dds_tests.cpp` |
| 探测程序进程内回环：对时、接收端新鲜度、按 decision_id 回传、写出 JSONL 并被 Python 读入 | 单测 | 同上 | `adapters/dds/tests/dds_tests.cpp` |
| 弱网三档下真实 DDS 的送达率 / 准时率（见下表） | 网络模拟 | 阿里云 ECS，Ubuntu 24.04，2 vCPU，CycloneDDS 0.10.4（apt） | `adapters/dds/scripts/netns_netem_probe.sh`，2026-11-09 运行 |
| TaskDirective JSONL 编解码；嵌套语义字段跳过；越界 / 负数 / 缺字段拒收 | 单测 | Linux（GCC） | `tests/cpp/directive_codec_tests.cpp` |
| 网关 SemanticDirective → TaskDirective，经 C++ `DirectiveGate` 准入并回 ExecutionReport（通过、重复、地图版本不符、过期、租约不符） | 单测（本机进程间） | Linux | `gateway/tests/test_task_directive.py`（CTest `gateway_directive_e2e`） |
| 边侧网关原有测试 | 单测 | Python | `gateway/tests`（28 项） |

`adapter_demo` 输出的数值（如策略生效步数、关键帧频率）来自合成链路数据，只说明接口串联可用，不代表真机性能。`SafetyEnvelope`、`PolicyGate` 的阈值均为配置默认值，不是实测标定。

## 弱网三档 DDS 实测（网络模拟）

单机两个网络命名空间经 veth 相连，两端各加同样的 netem；每档 20 个窗口 × 2 s，基准 20 Hz、负载 2000 B、deadline 200 ms，
动作在 `SafetyEnvelope` 候选里随机（rate_scale ∈ {0.25, 0.5, 0.75, 1.0}，reliable ∈ {否, 是}，压缩固定 0）。
数值是 20 个窗口的平均，单次运行，未做重复统计。

| 档位（单向时延 / 抖动 / 丢包 / 限速） | 送达率 | 准时率 | 可训练窗口 |
| --- | --- | --- | --- |
| healthy（10 ms / 2 ms / 0.5% / 20 Mbit） | 1.000 | 1.000 | 20/20 |
| constrained（40 ms / 10 ms / 5% / 2 Mbit） | 0.946 | 0.887 | 20/20 |
| critical（120 ms / 30 ms / 15% / 600 kbit） | 0.750 | 0.476 | 0/20 |

critical 档对时的中位绝对偏差为 10.4 ms，超过 5 ms 门限，所有窗口被标为不可训练：
往返对时在拥塞、抖动大的链路上误差明显变大。两个命名空间共用同一个系统时钟，真实时钟偏差为 0，
接收端估计出 2.6 ms 的偏差，全部来自对时方法本身。

## 跨机 DDS 实测（跨机 + 注入劣化）

两台主机：开发 VM（公网出口 140.232.64.x）与阿里云 ECS（Ubuntu 24.04，2 vCPU），经 WireGuard（UDP 5000）互联，
CycloneDDS 0.10.4 只走 `wg0`，关组播、单播 peer。两端系统时钟都由 NTP 同步。
脚本 `adapters/dds/scripts/wg_netem_probe.sh`，2026-11-09 单次运行；参数与上节相同（20 窗口 × 2 s、20 Hz、2000 B、deadline 200 ms）。
baseline 只有真实公网链路；其余三档在两端 `wg0` 出口再叠加同样的 netem，所以总时延 = 真实链路 + 注入值。
数值为单次运行的窗口平均（新鲜度为窗口中位数），未做重复统计；这是一条跨境公网链路，不代表机器人之间的无线链路。

| 档位 | ping RTT（均值） | BestEffort 送达 / 准时 / 新鲜度 | Reliable 送达 / 准时 / 新鲜度 | 对时 MAD | 可训练窗口 |
| --- | --- | --- | --- | --- | --- |
| baseline（无注入） | 161 ms，丢包 5% | 0.816 / 0.816 / 81 ms | 0.994 / 0.392 / 334 ms | 0.13 ms | 20/20 |
| healthy | 181 ms | 0.756 / 0.756 / 92 ms | 0.949 / 0.491 / 281 ms | 0.53 ms | 20/20 |
| constrained | 240 ms | 0.714 / 0.714 / 128 ms | 0.901 / 0.350 / 497 ms | 99.9 ms | 8/20 |
| critical | 380 ms，丢包 50% | 0.604 / 0.169 / 226 ms | 0.581 / 0.000 / 789 ms | 202 ms | 0/20 |

（每档 BestEffort 12 个窗口、Reliable 8 个窗口，动作随机抽取。）

观察：

- 在约 160 ms RTT、本身有丢包的链路上，Reliable 用重传换来接近 1 的送达率，但重传超过 200 ms deadline，准时率反而低于 BestEffort。
  这正是端侧策略库要学的“链路状况 → 通信配置 → 效果”关系；单机网络模拟（无真实 RTT）里看不到这个反转。
- baseline 下接收端估计的时钟偏差为 1.58 ms、MAD 0.13 ms。两机都经 NTP 同步，这个值包含了路径不对称，不能当作真实时钟差。
- constrained 和 critical 档对时 MAD 升到 100～200 ms，样本被门限（5 ms）拒掉：对时报文和数据共用同一条限速、排队的隧道，往返时间被排队拉长且不对称。
  当前对时方法在拥塞链路上不可用，需要改进（例如只用最小 RTT 的样本），而不是放宽门限。
