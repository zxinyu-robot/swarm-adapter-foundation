# v1 motion 体系对齐说明

> **版本**：v1.0-draft  
> **日期**：2026-08-06  
> **目的**：在全面查阅本机 `motion/`、`motion_ws/`、`MotionSLAM_ws`（Go2）后，说明 **RGB_ws v1 语义双路** 与 **motion 统筹架构（ForkSpatialLink / SLAM-Token）** 的位置关系、已实现状态、差距与验证对齐方式。  
> **读者**：统筹 AI、边端开发、Go2 端侧开发。

---

## 1. 本机四仓拓扑

```text
/home/ubuntu/Downloads/
├── motion/           # 统筹文档仓：宪章、P0 排序、Gate、专利、40-验证
├── motion_ws/        # 开发机实现：Swarm Gate、SUBM1 点云上行 :9876、Foxglove 拼接
├── RGB_ws/           # 边侧语义网关 + 协议级仿真 + StreamVLN 支路（9877/9878/9879）
└── （Go2 远端）MotionSLAM_ws/   # 真机栈：Super-LIO + BT-scan-planner + v1 uplink 节点

专网：Go2 wlan0 192.0.2.61  ◄──►  开发机/边侧 192.0.2.93
机身网：eth0 198.51.100.18（Mid-360 198.51.100.20）
```

| 仓 | 登记于 motion 技术栈索引 | 职责 |
|----|-------------------------|------|
| `motion/` | 自身 | 系统工程 OS、ForkSpatialLink P0-A～D、证据等级 |
| `motion_ws/` | ✅ | SUBM1 调试链、Swarm Gate、端边契约设计（proposal） |
| `RGB_ws/` | ✅（2026-08-06 起） | v1 语义双路 + Qwen-VL/StreamVLN 选型 + 专网 VLN 验证 |
| Go2 `MotionSLAM_ws` | ✅ | 控制闭环、SubgraphPublisher、RgbUplink、DirectiveReceiver |

**本机 `/home/ubuntu/MotionSLAM_ws`** 仅为 legacy **SUBM1 接收端**（:9876），**不是** Go2 真机完整栈；真机源码在 `unitree@192.0.2.61:~/MotionSLAM_ws`。

---

## 2. motion 统筹主线 vs RGB_ws v1 路径

### 2.1 motion canonical P0（冻结排序）

来源：[`motion/01-工作计划/ForkSpatialLink-实现方向_含AsyncShield对齐.md`](../../motion/01-工作计划/ForkSpatialLink-实现方向_含AsyncShield对齐.md)

```text
P0-A  OctVox → VoxelTransaction + Recorder
P0-B  TokenSequence v0.1 编解码 → x86 上送
P0-C  x86 VLN Adapter → waypoint/ActionGroup → Nav2 2D → L1 固件
P0-D  WeakNet 单变量首扫
```

- **空间契约**：`VoxelTransaction` → `TokenSequence` → Network Payload → VLN Input  
- **下行**：waypoint / **ActionGroup**（非 SemanticDirective）  
- **端侧执行**：Nav2 2D MPPI（P0 canonical）；BT-scan-planner 为 Go2 **实测主线**但未写入 motion BENCH 首组

### 2.2 RGB_ws v1（当前工程实现）

```text
L0 structure  :9877  motionslam.sparse_subgraph.v1
L1 vision     :9878  MSRGB / H265K1
L2 task       挂载于子图 task_context
        ↓ Aligner（subgraph_version join_key）
边侧 Qwen2.5-VL-7B / mock / StreamVLN bias
        ↓
:9879  motionslam.semantic_directive.v1
        ↓
端侧 BT-scan-planner frontier 加权（设计目标；见 §4 缺口）
```

### 2.3 关系：并行演进，非替代

| 维度 | motion P0 canonical | RGB_ws v1 | 关系 |
|------|---------------------|-----------|------|
| 上行几何 | TokenSequence（体素增量） | sparse_subgraph（拓扑+frontier JSON） | **语义等价层不同**；子图更轻、更适合 VLM frontier 排序 |
| 上行视觉 | 关键帧随 Token | 独立 RGB 路 MSRGB/H.265 | RGB_ws **显式分层 L1** |
| 下行 | ActionGroup / waypoint | SemanticDirective + graph_bias | RGB_ws **不替代 Nav2/BT 规划** |
| 边侧模型 | 可替换 VLN Adapter | Qwen-VL + 可选 StreamVLN | RGB_ws 已选型文档化 |
| 调试点云 | — | SUBM1 :9876（motion_ws） | **并行保留**，不参与 v1 语义闭环 |

**共同铁律**（与 [`motion/00-指导AI/项目宪章`](../../motion/00-指导AI/项目宪章-无人协同系统工程.md) 一致）：

- VLN/VLA/WAM **不直接发 `/cmd_vel`**
- 几何真值与占据在 **端侧**；边侧不做全局栅格重建
- L1 固件 / 本地 planner 为安全兜底

**中长期收敛方向**（推断，非已冻结决策）：

1. `sparse_subgraph.v1` 作为 TokenSequence 的 **L0 语义视图**（frontier 拓扑子集）  
2. SUBM1 点云作为 **调试 / Foxglove / 离线评估** 通道  
3. SemanticDirective 与 ActionGroup 在 BT 黑板 **统一为「语义偏置 + 可选 coarse goal」**

---

## 3. 端口与协议对照（实测登记）

| 端口 | 协议 / schema | 方向 | 实现仓 | 状态 |
|------|--------------|------|--------|------|
| **9876** | SUBM1 / `motionslam.submap_tile.v1` | 狗→边 | motion_ws + Go2 uploader | ✅ 2026-07-29 有 100+ tile 日志 |
| **9877** | JSON Lines / `motionslam.sparse_subgraph.v1` | 狗→边 | RGB_ws edge + Go2 subgraph_publisher | ✅ 联调日志 SUBGRAPH_UPLINK ok |
| **9878** | MSRGB 二进制 | 狗→边 | RGB_ws + Go2 rgb_keyframe_uplink | ✅ video360p 转发 |
| **9879** | JSON / `motionslam.semantic_directive.v1` | 边→狗 | RGB_ws + Go2 directive_receiver | ✅ DIRECTIVE_ACCEPT；BT 未消费 |

**配置文件**：

| 侧 | 路径 |
|----|------|
| 边侧 | `RGB_ws/config/edge.env`（`GO2_HOST=192.0.2.61`） |
| 狗端 | Go2 `src/motionslam_bringup/config/edge_uplink.yaml`（`edge_host=192.0.2.93`） |
| 仿真 | `RGB_ws/config/sim.env`（127.0.0.1，不发真狗） |

**主机登记**：[`motion_ws/hosts.md`](../../motion_ws/hosts.md)

---

## 4. Go2 真机当前状态（2026-08-06 事实）

来源：Go2 `demo_scan_stack.launch.py` 运行态 + [`motion_ws/docs/双边事实-motion与Go2-2026-07-27.md`](../../motion_ws/docs/双边事实-motion与Go2-2026-07-27.md)

### 4.1 已跑通

| 模块 | 节点 / 证据 |
|------|------------|
| Super-LIO + 局部占据 | `super_lio_node` |
| BT-scan-planner | `demo_scan_bt_orchestrator` + `scan_planner_node` + `closed_loop_controller` |
| 子图上行 v1 | `subgraph_publisher_node` → :9877 |
| RGB 上行 v1 | `rgb_keyframe_uplink_node` ← `/frontvideostream` → :9878 |
| 语义下行 | `directive_receiver_node` listen :9879 → 发布 `/semantic/directive` |
| 运动基线 | N4 2m 误差 0.253 m、N6 3m 0.283 m、N5 急停 0.011 m/3s（[`motion/40-验证/BENCH-P0-Go2-MotionSLAM-基线.md`](../../motion/40-验证/BENCH-P0-Go2-MotionSLAM-基线.md)） |

### 4.2 关键缺口（阻塞 G3 任务成功率）

| 缺口 | 影响 | 对应任务 |
|------|------|---------|
| **BT 未订阅 `/semantic/directive`** | directive 到 ROS 话题但 **不影响 frontier 选择** | RGB_ws `T-P0-4` SemanticBias |
| **Qwen-VL 未接入 edge** | 边侧仍为 mock | S2 / M1 |
| **StreamVLN 与 v1 主环未统一** | README 支路仍描述 HTTP→PID；与「action bias only」需对齐 | v1.1 N0 |
| **motion P0 Token 链未实现** | 与 RGB v1 **独立**，不影响当前 VLN 验证 | motion T-003 |

---

## 5. 验证体系对齐（RGB_ws ↔ motion/40-验证）

### 5.1 Gate 映射

| RGB_ws Gate | motion Gate / Benchmark | 说明 |
|-------------|-------------------------|------|
| G0 仿真 | — | motion 无等价；RGB 独有协议回归 |
| G1 专网协议 | 弱网轴 A（无损基线） | N1–N6 对齐 motion 通信健康 |
| G2/G3 VLN 任务 | P0-Benchmark **SR / SSR / SPL** | frontier@1 ↔ 语义层；SR_subgoal ↔ Arrival |
| G4 流畅性 | N5 急停 + **闭环不断** | E1 对齐「Super-LIO 频率下降 <5%」 |
| — | **N4/N6 到达** | motion 已有 measured；RGB VLN **前置依赖** |

### 5.2 指标对照表（填表时用）

| motion `P0-Benchmark-模板` | RGB_ws `v1-技术验证标准` | 备注 |
|------------------------------|--------------------------|------|
| SR (%) | SR_task / SR_subgoal | RGB 分 subgoal 与整任务 |
| SSR (%) | frontier@1 + 到达语义区域 | 严格成功率 |
| SPL | SPL_task（可选） | 需轨迹记录 |
| CR / 固件避障 | F_ctrl + N5 | 共用 N5 证据 |
| Token 编解码成功率 | — | P0 Token 未接入 |
| align / 版本连续 | align_hit_rate / N3 | join_key 不同但意图相同 |
| 端到端 waypoint 延迟 | S1/S2 e2e_latency | Token→waypoint vs tick→directive |
| 断网恢复 | N5 / G1 | 30 s 断网 60 s 恢复 |

### 5.3 建议 measured 回链路径

专网 VLN 验证通过后，在 **motion** 侧新建：

```text
motion/40-验证/BENCH-v1-RGB-语义双路-VLN.md
```

字段对齐 [`P0-Benchmark-模板.md`](../../motion/40-验证/P0-Benchmark-模板.md)，并引用：

- RGB_ws `sim/reports/<ts>/summary.json`（G0）
- 专网试次 YAML（G2/G3，见 `v1-技术验证标准.md` §7）
- Go2 bag / 日志路径
- `RGB_ws` + Go2 `MotionSLAM_ws` commit

---

## 6. 世界模型 / VLN / VLA 在 motion 体系中的位置

| 概念 | motion 文档 | RGB_ws 文档 | 当前阶段 |
|------|------------|-------------|---------|
| SLAM-Token | [`Go2-VLA-SLAM-Token技术方案.md`](../../motion/02-架构设计/Go2-VLA-SLAM-Token技术方案.md) | L0 structure 子图 | motion **proposal**；RGB **v1 实现** |
| 世界模型 WM | A 族专利、Nav2 解耦 §阶段二 | `v1-世界模型-VLN-VLA选型方案` W1/W2 | **P2** |
| WAM | C2 专利叙事 | 明确 v1 不实时闭环 | **P2+ 离线** |
| VLN Adapter | P0-C todo | Qwen-VL + StreamVLN | RGB **M1/N0** |
| AsyncShield | ForkSpatialLink P0.5 | 未实现 | 与 TTL/version 校验互补 |

---

## 7. 推荐工作顺序（对齐 motion P0 与 RGB v1）

```text
① G0 仿真回归（RGB_ws）                    ← 每次改协议
② G1 专网三通道（9877/9878/9879）           ← 单实例 edge
③ T-P0-4 BT 消费 SemanticDirective         ← 阻塞 G3 的关键
④ S2 接 Qwen-VL（边侧 M1）                 ← 替换 mock
⑤ G2/G3 标准任务包 + 填 motion BENCH 实例
⑥ G4 30 min 长稳
⑦（并行）motion P0-B Token 与 subgraph  schema 收敛设计
⑧（P1）StreamVLN action_bias；motion P0-D 弱网
```

---

## 8. 文档索引（motion 侧必读）

| 主题 | 路径 |
|------|------|
| 项目宪章 | `motion/00-指导AI/项目宪章-无人协同系统工程.md` |
| P0 排序 | `motion/01-工作计划/ForkSpatialLink-实现方向_含AsyncShield对齐.md` |
| 技术栈登记 | `motion/01-工作计划/技术栈索引.md` |
| Go2 端侧闭环 | `motion/02-架构设计/Go2端侧-可闭环易解释系统工程.md` |
| SLAM-Token | `motion/02-架构设计/Go2-VLA-SLAM-Token技术方案.md` |
| Nav2 端边解耦 | `motion/02-架构设计/Nav2端边解耦与地图任务契约_两阶段演进.md` |
| P0 Benchmark 模板 | `motion/40-验证/P0-Benchmark-模板.md` |
| Go2 运动基线 | `motion/40-验证/BENCH-P0-Go2-MotionSLAM-基线.md` |
| 双边事实 | `motion_ws/docs/双边事实-motion与Go2-2026-07-27.md` |
| SUBM1 协议 | `motion_ws/scripts/submap_uplink/protocol.py` |

## 9. 文档索引（RGB_ws 侧）

| 主题 | 路径 |
|------|------|
| v1 总方案 | `RGB_ws/docs/v1-双路上行语义调度方案.md` |
| 专网 VLN 验证 | `RGB_ws/docs/v1-技术验证标准.md` |
| 仿真选型 | `RGB_ws/docs/v1-仿真环境技术选型方案.md` |
| WM/VLN/VLA 选型 | `RGB_ws/docs/v1-世界模型-VLN-VLA选型方案.md` |
| 端侧待办 | `RGB_ws/docs/v1-端侧剩余工作清单.md` |

---

## 10. 结论

- **RGB_ws 是 motion 体系下 Go2 垂直 SKU 的 v1 语义调度实现仓**，专网 VLN 验证标准已独立成文，须 **回链 motion/40-验证** 才升为 measured。  
- **motion P0 Token 链与 RGB v1 双路当前并行**，短期以 RGB v1 完成「专网视觉语言导航 + 任务成功率 + 边端流畅性」验证；中长期再收敛 schema。  
- **当前最大工程缺口**：Go2 BT **未消费** `/semantic/directive`；边侧 **未接 Qwen-VL**。二者完成前，G3 任务成功率无法代表真实 VLN 能力。
