# 证据

证据等级：**单测**＝单元测试；**仿真**＝本机或云端仿真；**真机**＝实机运行。本仓库目前没有真机证据。

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
| 边侧网关原有测试 | 单测 | Python | `gateway/tests`（28 项） |

`adapter_demo` 输出的数值（如策略生效步数、关键帧频率）来自合成链路数据，只说明接口串联可用，不代表真机性能。`SafetyEnvelope`、`PolicyGate` 的阈值均为配置默认值，不是实测标定。
