# Edge Semantic Gateway — 边侧语义调度网关

> 本目录来自 [edge-semantic-gateway](https://github.com/zxinyu-robot/edge-semantic-gateway)（`89d4280`），在 swarm-adapter-foundation 中作为边侧参考消费方；C++ 核心与 Python 联邦适配不依赖本目录。

边侧语义调度网关：收端侧 RGB 流 + 子图流双路上行，语义调度后回 `SemanticDirective` 下行。只产出 frontier 级任务建议，不碰运动控制。

> 仓库名 `edge-semantic-gateway`；本目录沿用 `RGB_ws`。

## 系统角色

| 项目 | 角色 | 与本网关的关系 |
| --- | --- | --- |
| [quadruped-crossfloor-nav-ws](https://github.com/zxinyu-robot/quadruped-crossfloor-nav-ws) | Go2 端侧导航执行栈 | 端边协同主链路（`EDGE_HOST` ↔ `GO2_HOST`） |
| [legged-navigation-runtime](https://github.com/zxinyu-robot/legged-navigation-runtime) | 定位失效恢复 | 安全兜底，优先于一切任务指令 |

详细耦合设计见 [docs/v1-与跨楼层导航栈及恢复插件的耦合.md](docs/v1-与跨楼层导航栈及恢复插件的耦合.md)。

## 数据流

```text
Go2 端侧                            边侧（本网关）
┌──────────────────┐                ┌─────────────────────┐
│ Super-LIO/PCT/SCAN│  子图 :9877   │  subgraph 接收        │
│ edge_uplink      │ ─────────────► │  (frontiers/nodes)    │
│ rgb_forward      │  RGB  :9878    │  RGB 缓存             │
│                  │ ─────────────► │  语义调度（scheduler） │
│ directive_receiver│ ◄───────────── │  SemanticDirective 下行│
│                  │  :9879          │  (frontier 级建议)    │
└──────────────────┘                └─────────────────────┘
```

## 调度器

| 调度器 | 说明 | 需要 GPU |
| --- | --- | --- |
| `qwen_vl`（默认） | Qwen2.5-VL-3B，视觉+子图对齐选 frontier | 真推理需，无 GPU 用 stub |
| `layer_fusion_stub` | L0结构+L1视觉+L2任务分层融合（CPU 规则） | 否 |
| `geom_baseline` | 纯几何基线（frontier 分数最高者） | 否 |
| `streamvln` | StreamVLN 7B 官方 HTTP 协议 | 是 |
| `mock` | 仅测连通（取第一个 frontier） | 否 |

## 师生 trace（蒸馏数据入口）

边侧老师（VLM）与端侧学生在同一 tick 上的决策对照，落 JSONL，用于后续端侧策略蒸馏。

```bash
./scripts/run_sim_bench.sh --trace
# [trace] written=2 rejected=0 -> sim/traces/trace_YYYYmmdd_HHMMSS.jsonl
# [trace] teacher/student agreement=0% (0/2) teacher_success=100% versions=2
# [trace] distillable=100% (2/2) — 老师未消费 RGB 时该值为 0，说明只是在抄规则，蒸馏无收益
```

**三条记录原则**（`edge/trace.py`）：

1. **以 `map_version` 为连接键，不以时间为键**。弱网下时钟不可靠；`map_version=0`（未知）直接拒收，否则静默污染训练集。
2. **`context` 只记端侧可见信息**。端侧看不到 RGB，只看到 `frontier + geom_score + task_goal`；喂了 RGB 派生特征，上线必然崩。
3. **`outcome.source` 必填**。`sim_expected`（场景标定代理）与 `robot_execution`（真机回执）不可混训，否则等于用假标签蒸馏。

此外 `teacher.inputs` 记录老师实际消费的模态，`distillable` 由是否含 `vision` 推导：

- 老师只用 `structure`/`task` → 学生也看得到，**是抄规则，蒸馏无收益**
- 老师用了 `vision` → 才是可蒸馏知识，且必须经**语义瓦片**落地，学生才能间接继承

`outcome` 属于被执行的动作（学生选的），老师的判据单列 `teacher_outcome`——真机上真正跑的是端侧策略，老师的选择没有执行依据。

## 语义地图消费（老师能力落地通道）

老师（VLM）的 RGB 理解无法直接教给学生（端侧看不到 RGB），必须经**语义瓦片**中转：

```text
边侧 VLM 看懂 RGB  →  写成地图上的语义标签  →  端侧策略消费同一张语义地图
```

`edge/semantic_map_client.py` 消费 [spatial-map-foundation](https://github.com/zxinyu-robot/spatial-map-foundation) 的语义瓦片查询服务：

```python
from edge.semantic_map_client import SemanticMapClient, describe_for_prompt

with SemanticMapClient("127.0.0.1", 9881, expected_version=7) as c:
    r = c.query(lat, lon, radius_m=300, categories=["kitchen"], min_confidence=60)
    prompt_hint = describe_for_prompt(r)   # 塞进 VLM prompt 的语义上下文
```

**版本校验**：每次响应带 `map_version`，客户端主动比对；不一致抛 `SemanticMapVersionMismatch`。拿 v45 的坐标配 v42 的语义，会产出看起来合理但完全错误的样本。

**坐标系**：查询点给 WGS84（机器人位姿空间），服务端负责换算到瓦片的 GCJ-02 空间。

### 标注回写（VLM 结论 → 地图）

VLM 已经输出 `room_found` / `found_room_type`，`edge/semantic_writer.py` 把它转成待回写标注：

```python
from edge.semantic_writer import OverlayWriter, labels_from_vlm_result

labels = labels_from_vlm_result(
    room_found=result.room_found,
    found_room_type=result.found_room_type,
    confidence=result.confidence,
    lat=pose.lat, lon=pose.lon,       # WGS84
    map_version=current_map_version,
    session_id=session_id,
)
for label in labels:
    overlay.write(label)              # 追加 JSONL，带 map_version
```

再由 C++ 工具合并进瓦片（`spatial-map-foundation` 的 `semantic_label_merge`）。

**为什么 Python 不直接改瓦片**：落瓦片要过 GCJ-02 换算，这个换算只能有一份实现（C++ 的 `wgs84_to_amap_tile`）。在 Python 里重写必然重演 500m 偏移那类 bug。

**两个「宁可不标」**：
- `room_found=False` → 不标注。地图上的空白是有意义的（未探索），写错标签会让下游把错误当事实。
- 房间类型无法归一 → 不标注，**绝不写 `unknown`**。

**置信度约定**：`<=1.0` 视为比例（0.88 → 88），`>1.0` 视为百分比（75.0 → 75）。边界明确，避免 1.0/1.01 跳变。

## 快速开始（G0 协议级闭环，无 GPU）

```bash
cd RGB_ws
chmod +x scripts/*.sh

# 一键 G0 仿真评测（回环 127.0.0.1，不会发到真狗）
./scripts/run_sim_bench.sh                              # layer_fusion_stub，G0 全过
./scripts/run_sim_bench.sh --scheduler qwen_vl          # 千问 stub 路径
./scripts/run_sim_bench.sh --scheduler mock --no-strict # 仅测连通
```

报告：`sim/reports/<timestamp>/summary.md`（含 G0 Gate 明细）。

真 GPU 边侧：

```bash
# config/edge.env 中 QWEN_VL_STUB=false，默认模型 Qwen2.5-VL-3B
./scripts/setup_qwen_vl.sh
./scripts/run_edge_server.sh

# 另一终端：本机模拟上行（无需狗）
python3 scripts/mock_uplink_client.py
```

与 Go2 真机联调：狗端 `edge_uplink.yaml` 里 `edge_host` 改为本机 IP；本机 `config/edge.env` 里 `GO2_HOST` 改为狗 IP。

## 可选支路

### StreamVLN（真机 VLN 替代调度）

Go2 端侧推 RGB 流 → x86 跑 StreamVLN 7B → 返回导航动作序列。详见 `docs/v1-世界模型-VLN-VLA选型方案.md`；服务端安装见 `scripts/setup.sh` + `scripts/download_model.sh` + `scripts/run_server.sh`。

### Gazebo 物理仿真

```bash
./gazebo/scripts/install_gazebo_harmonic.sh   # 首次：Ubuntu 24.04
./gazebo/scripts/run_corridor.sh              # corridor 三岔 + Go2 spawn
./gazebo/scripts/run_gazebo_bench.sh          # GG5–GG8 闭环
```

### Go2 URDF 可视化

```bash
./scripts/run_visual_sim.sh --png-only        # 导出 corridor 场景 PNG
```

## 目录结构

```text
edge/         边侧网关（对齐器/调度器/语义指令/千问客户端/师生 trace）
server/       StreamVLN x86 服务端
go2/          Go2 狗端客户端（拷到狗上）
sim/          协议级仿真（G0 评测）
gazebo/       Gazebo 物理仿真
monitor/      Foxglove 网页监控
config/       edge/sim/server/monitor 四组 env
docs/         方案与选型文档
tests/        无框架测试（trace / semantic_map_client / semantic_writer）
```

## 设计文档

| 文档 | 说明 |
| --- | --- |
| [v1-双路上行语义调度方案.md](docs/v1-双路上行语义调度方案.md) | v1 总方案 |
| [v1-与跨楼层导航栈及恢复插件的耦合.md](docs/v1-与跨楼层导航栈及恢复插件的耦合.md) | 与端侧两项目的耦合 |
| [v1-技术验证标准.md](docs/v1-技术验证标准.md) | G0–G4 验证标准 |
| [v1-世界模型-VLN-VLA选型方案.md](docs/v1-世界模型-VLN-VLA选型方案.md) | 模型选型矩阵 |
| [v1-Gazebo与Isaac仿真选型.md](docs/v1-Gazebo与Isaac仿真选型.md) | 仿真选型 |

## 参考

- StreamVLN 论文 [arXiv:2507.05240](https://arxiv.org/abs/2507.05240)
- 真机权重 [mengwei0427/StreamVLN_Video_qwen_1_5_r2r_rxr_envdrop_scalevln_real_world](https://huggingface.co/mengwei0427/StreamVLN_Video_qwen_1_5_r2r_rxr_envdrop_scalevln_real_world)
