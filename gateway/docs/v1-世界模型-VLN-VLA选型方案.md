# v1 世界模型 · 世界动作模型 · VLN/VLA 选型方案（2026）

> **版本**：v1.0-draft  
> **日期**：2026-08-06  
> **定位**：在 **Go2 + Orin NX / RTX 5070 12GB** 约束下，对 2026 主流 **世界模型（WM）**、**世界动作模型（WAM）**、**VLN**、**VLA** 做可落地选型；与 `[v1-双路上行语义调度方案.md](./v1-双路上行语义调度方案.md)`、`[v1-仿真环境技术选型方案.md](./v1-仿真环境技术选型方案.md)` 配套。  
> **核心原则**：端侧 **BT-scan-planner + Super-LIO** 保持控制闭环一等公民；边侧模型 **不直接发 `/cmd_vel`**，优先输出 **SemanticDirective / action bias**。

---

## 1. 概念分层（2026 业界共识）

```
                    ┌─────────────────────────────────────┐
                    │  任务语义 L2（指令 / goal_room_type）   │
                    └──────────────────┬──────────────────┘
                                       │
     ┌─────────────────────────────────┼─────────────────────────────────┐
     │                                 │                                 │
     ▼                                 ▼                                 ▼
┌─────────────┐              ┌──────────────────┐              ┌──────────────────┐
│ 世界模型 WM  │              │  VLM / VLN       │              │  VLA / WAM       │
│ 预测未来状态  │              │  理解+规划/离散动作 │              │  视觉+语言→连续/  │
│ 无直接动作    │              │  （导航专用）      │              │  离散动作         │
└──────┬──────┘              └────────┬─────────┘              └────────┬─────────┘
       │                              │                                 │
       │         ┌────────────────────┴────────────────────┐           │
       │         │  世界动作模型 WAM = WM 骨干 + 动作解码头   │◄──────────┘
       └────────►│  （Cosmos-Policy / LingBot-VA / DreamZero）│
                 └─────────────────────────────────────────────┘
```

| 类型 | 典型输入 | 典型输出 | 2026 代表 | 与本项目关系 |
|------|---------|---------|-----------|-------------|
| **WM** | 当前帧/状态 + 语言/动作条件 | 未来视频 / latent 状态 | Cosmos Predict、Genie 2、JEPA-WM | 边侧 **想象 roll-out**、frontier 可行性预判（P2） |
| **WAM** | RGB 历史 + 语言 | 未来帧 **+** 机器人动作 | LingBot-VA、Cosmos-Policy、DreamZero、mimic-video | 鲁棒性高、**显存/延迟大**；v1 仅研究支路（P2） |
| **VLN** | RGB 流 + 导航指令 | 离散导航动作（前进/转/停） | StreamVLN、Uni-NaVid、NaVid、JOP-VLN | **已有 StreamVLN 支路**；作 action bias，非主控（P1） |
| **VLA** | RGB + 语言 + 本体状态 | 连续/离散动作 token | π0/π0.5、OpenVLA、GR00T N1、Uni-NaVid | 操作/通用手臂强；四足 **需大量真机数据**（P2+） |
| **VLM（非 VLA）** | 子图 + 少量关键帧 + 指令 | 文本 / 结构化 JSON | Qwen2.5-VL、InternVL3 | **v1 主脑**：SemanticDirective（P0） |

**2026 趋势摘要**（见 [NVIDIA WAM 综述](https://developer.nvidia.com/blog/pretrained-to-imagine-fine-tuned-to-act-the-rise-of-world-action-models/)、[WAM vs VLA 鲁棒性研究](https://arxiv.org/abs/2603.22078)）：

- **WAM** 在视觉扰动（噪声、光照、布局变化）下普遍优于纯 VLA，但 **推理慢、对相机位姿/初始状态敏感**。
- **VLA**（如 π0.5）在充足多样机器人数据下可达可比鲁棒性，**实时性更好**。
- **VLN** 在 VLN-CE 上持续 SOTA 迭代（StreamVLN → JOP-VLN），但 benchmark 为 **离散 Habitat 环境**，与真狗 **占据栅格 + BT** 存在 sim-to-real 鸿沟。
- **混合架构**（VLM 语义 + WM 想象 + BT 几何执行）成为工业界主流，而非端到端替代规划栈。

---

## 2. 与本项目架构的映射

### 2.1 多模态分层输入（L0/L1/L2）

| 层 | 内容 | WM/WAM/VLN/VLA 谁消费 |
|----|------|----------------------|
| **L0 structure** | 子图、frontier、`geom_score` | VLM（frontier 排序）、WM（roll-out 初始状态） |
| **L1 vision** | MSRGB / H.265 关键帧 | VLN/VLA/WAM 主输入；VLM 选 ≤4 帧 |
| **L2 task** | `task_context` 指令 | 全部模型共享 |

**join_key**：`{session_id, subgraph_version}`（`edge/multimodal_layers.py`）。

### 2.2 输出接口（强制）

| 模型族 | 允许输出 | 禁止（v1） |
|--------|---------|-----------|
| Qwen-VL 等 VLM | `SemanticDirective`（frontier 候选 + bias） | 直接 `/cmd_vel` |
| StreamVLN 等 VLN | `action_bias`（短期离散动作建议） | 绕过 BT 调 sport API |
| WAM / 通用 VLA | 同上或 **latent plan** 供 BT 消费 | 独占控制环 |
| WM | `frontier_feasibility_score` / 想象帧缓存 | 无 |

---

## 3. 候选矩阵（2026，按落地优先级）

### 3.1 语义调度层（v1 主路径 · P0）

| ID | 模型 | 类型 | 参数量 | 5070 12GB | 延迟 | 输出 | 推荐度 |
|----|------|------|--------|-----------|------|------|--------|
| **M0** | mock / layer_fusion_stub | 规则 | — | ✅ CPU | <1 ms | Directive | 仿真基线 |
| **M1** | **Qwen2.5-VL-7B INT4** | VLM | 7B | ✅ ~6–8 GB | 1–3 s | SemanticDirective | **v1 首选** |
| M2 | InternVL3-8B INT4 | VLM | 8B | ⚠️ 紧 | 1–4 s | 同上 | 备选 A/B |
| M3 | GPT-4o / Claude（云） | VLM | — | 网络 | 2–5 s | 同上 | 标注/GT，非部署 |

**理由**：与 L0 子图 + L1 关键帧 + L2 指令天然匹配；不改 BT 接口；5070 可单卡常驻。

### 3.2 导航 VLN 支路（v1.1 · P1）

| ID | 模型 | 类型 | 5070 | 真机证据 | 输出 | 接入方式 |
|----|------|------|------|---------|------|---------|
| **N0** | **StreamVLN 7B** | VLN | ✅ ~14 GB 或量化 | ✅ Go2 官方 realworld | 离散 action | `RGB_ws/third_party/StreamVLN`，HTTP → action bias |
| N1 | Uni-NaVid | VLA-VLN | ⚠️ ~A100 5Hz 参考 | ✅ RSS'25 真机 | 离散 action | 替换 StreamVLN 骨干，接口类似 |
| N2 | NaVid | VLN | ✅ | VLN-CE | 离散 action | 性能低于 Uni-NaVid/StreamVLN |
| N3 | JOP-VLN | VLN | ✅ 研究代码 | Habitat SOTA | 离散 action | **仿真/Benchmark 参考**，真机需重训 |

**StreamVLN vs Uni-NaVid（2026 简表）**：

| 维度 | StreamVLN | Uni-NaVid |
|------|-----------|-----------|
| 上下文 | SlowFast 流式 KV + token 剪枝 | 在线 token merge |
| VLN-CE R2R SR | ~56.9%（Val-Unseen） | ~51.8% |
| 真机 Go2 | **仓库已集成** | 需自移植 |
| 与本项目 | **v1.1 默认 N0** | v1.2 若需多任务统一再评估 N1 |

**约束**：StreamVLN 与 Qwen-VL **不同 tick 并行**（5070 显存）；串行或降频至 0.2–0.5 Hz。

### 3.3 通用 VLA（P2 · 非 v1 主线）

| ID | 模型 | 场景 | 5070 | 四足 Go2 适配 |
|----|------|------|------|--------------|
| V1 | OpenVLA-7B | 桌面操作 | ✅ | ❌ 无四足数据 |
| V2 | π0 / π0.5 | 通用手臂+移动 | ⚠️ | 需大量 Go2 示教 |
| V3 | GR00T N1 | 人形/多本体 | ❌ 16GB+ | 研究向 |

**结论**：2026 阶段 **不作为 Go2 导航主选**；若未来做「抓取/开门」等操作子任务，再评估 π0 系或专用 WAM。

### 3.4 世界模型 WM（P2 · 边侧想象）

| ID | 模型 | 范式 | 5070 | 用途（本项目） |
|----|------|------|------|---------------|
| **W1** | Cosmos Predict 2 | 视频扩散 | ⚠️ 7B+ | frontier 后「走这一步会看到什么」想象帧 |
| W2 | JEPA-WM / V-JEPA 2 | latent 预测 | ✅ 中等 | 轻量 feasibility，无像素级开销 |
| W3 | Genie 2 | 交互视频 | ❌ 云端 | 仅仿真数据增广 |

**接入点**：`SemanticScheduler` 在出 Directive 前，对 top-2 frontier 各 roll-out 1–2 步，将 **可行性分** 写入 `directive.rationale` / `graph_bias` 权重。

### 3.5 世界动作模型 WAM（P2+ · 研究/鲁棒性）

| ID | 模型 | 骨干 | 5070 12GB | 鲁棒性 | 实时性 |
|----|------|------|-----------|--------|--------|
| **A1** | LingBot-VA | Wan 2.2-5B MoT | ❌ 需 24GB+ 或蒸馏 | ⭐⭐⭐⭐ | 慢 |
| A2 | Cosmos-Policy | Cosmos 扩散 | ❌ | ⭐⭐⭐⭐ | 慢 |
| A3 | Fast-WAM | Wan 5.5B 表征 | ⚠️ | ⭐⭐⭐ | 中等 |
| A4 | mimic-video | Cosmos 分层 | ❌ | ⭐⭐⭐ | 慢 |

**2026 结论**（[arXiv:2603.22078](https://arxiv.org/abs/2603.22078)）：WAM 在 **视觉扰动** 下优于 VLA，但 **视角/初始位姿变化** 仍弱；5070 12GB **无法实时闭环**。

**本项目策略**：WAM 进入 **离线评测 / 蒸馏目标**，不进入 v1 真狗主环。可选路径：WAM 生成「困难场景」→ 扩充 `sim/scenarios/`。

---

## 4. 推荐技术栈（分阶段）

```
Phase 0（当前）  mock + geom + layer_fusion_stub     ← sim/ 已跑通
Phase 1（v1）    M1 Qwen2.5-VL-7B → SemanticDirective  ← 边侧主脑
Phase 1.1        N0 StreamVLN → action_bias          ← 可选支路
Phase 1.2        M1 + L0 frontier 2D 投影 prompt       ← AgentVLN 思路
Phase 2          W2 JEPA 轻量 WM → feasibility        ← 边侧想象
Phase 2+         A3 Fast-WAM 蒸馏 / 离线鲁棒性评测      ← 研究
```

### 4.1 v1 默认组合（推荐）

| 角色 | 选型 | 说明 |
|------|------|------|
| 语义主脑 | **Qwen2.5-VL-7B INT4** | frontier 排序 + SemanticDirective |
| 几何真值 | 端侧 BT-scan-planner | 不替换 |
| 仿真对照 | S0/S1/S1.5 | CPU 回归 |
| 可选增强 | StreamVLN 7B | 短期 action bias，降频 |

### 4.2 明确不选（v1）

| 方案 | 原因 |
|------|------|
| 端到端 WAM/VLA 直控 Go2 | 5070 算力不足；与 BT 冲突；无四足训练数据 |
| 15 fps 全流进 7B | 带宽与算力浪费；用 FrameSelector 1–4 帧/查询 |
| WM 重建占据栅格 | v1 边界：几何在端侧 Super-LIO |
| 多模型同 tick 并行 | 5070 12GB 显存不够 |

---

## 5. 评测与选型方法

### 5.1 协议级仿真（已具备）

```bash
cd RGB_ws && ./scripts/run_sim_bench.sh
```

| 仿真 ID | 对应真实选型 | 指标 |
|---------|-------------|------|
| S0 mock | 连通性 | directive 到达率 |
| S1 geom | BT 纯几何 | geom@1 |
| S1.5 layer_fusion_stub | M0 分层规则 | 分层融合@1 vs geom@1 |
| S2 qwen_vl（待接） | M1 | frontier@1、置信度校准 |
| S3 streamvln（待接） | N0 | action 与 BT 兼容性 |

### 5.2 真机 / 半真机评测维度

> **专网 VLN 任务成功率与边端流畅性门槛**见 `[v1-技术验证标准.md](./v1-技术验证标准.md)` §4–§5。

| 维度 | WM/WAM | VLN | VLA | VLM |
|------|--------|-----|-----|-----|
| frontier@1 vs GT | — | 间接 | — | **主指标** |
| 对齐率 L0/L1/L2 | 需三层 | L1+L2 | L1+L2 | **L0+L1+L2** |
| 端到端延迟 | >5 s | 2–5 s | 1–3 s | 1–3 s |
| 视觉扰动鲁棒 | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 可解释性 | 低 | 中 | 低 | **高** |
| BT 融合难度 | 高 | 中 | 高 | **低** |

### 5.3 5070 显存分时预算

| 组合 | 显存峰值 | 可行 |
|------|---------|------|
| Qwen2.5-VL-7B INT4 单独 | ~8 GB | ✅ |
| StreamVLN 7B 单独 | ~12–14 GB | ⚠️ INT4/卸载 |
| Qwen-VL + StreamVLN 并行 | >16 GB | ❌ |
| Qwen-VL + JEPA-WM 小模型 | ~10 GB | ✅ Phase 2 |

---

## 6. 与 sim 调度器 ID 对照

| sim ID | 本方案 ID | 模型 |
|--------|-----------|------|
| S0 | M0 | mock |
| S1 | — | geom（端侧 BT，非边侧模型） |
| S1.5 | M0+ | layer_fusion_stub |
| S2 | **M1** | qwen_vl |
| S3 | **N0** | streamvln |
| — | W1/W2 | wm_imagine（待增 S4） |
| — | A1–A4 | wam_offline（待增 S5，仅离线） |

---

## 7. 决策摘要

| 问题 | 2026 推荐 |
|------|-----------|
| v1 边侧主模型？ | **Qwen2.5-VL-7B**（VLM → SemanticDirective） |
| VLN 选谁？ | **StreamVLN**（已集成 Go2）；备选 Uni-NaVid |
| VLA 选谁？ | v1 **不主选**；Uni-NaVid 属 VLA-VLN 交叉，P1.2 再评 |
| 世界模型？ | Phase 2：**JEPA-WM 轻量 feasibility**；Cosmos 作离线想象 |
| 世界动作模型？ | **离线鲁棒性参考**；5070 不做实时 WAM 闭环 |
| 混合架构？ | **VLM 语义 + BT 几何 +（可选）VLN bias**；WAM 不进 v1 主环 |

---

## 8. 后续行动

- [ ] `edge/scheduler/qwen_vl.py` — 接 M1，注册为 sim S2
- [ ] `edge/scheduler/streamvln_bias.py` — 封装 N0 HTTP 客户端，输出 action_bias 字段
- [ ] `sim/scenarios/` — 增加视觉扰动场景（光照/噪声 tag），对比 M1 vs N0
- [ ] Phase 2 spike：`edge/wm/jepa_feasibility.py` 读 L0+L1，写 frontier 可行性分
- [ ] 文档：`v1-端侧剩余工作清单.md` T-P1 StreamVLN bias 与本文 N0 对齐

---

## 9. 参考

- StreamVLN：[arXiv:2507.05240](https://arxiv.org/abs/2507.05240) · [真机 realworld](https://github.com/InternRobotics/StreamVLN/tree/main/realworld)
- Uni-NaVid：[arXiv:2412.06224](https://arxiv.org/abs/2412.06224)
- WAM 综述：[NVIDIA Technical Blog 2026](https://developer.nvidia.com/blog/pretrained-to-imagine-fine-tuned-to-act-the-rise-of-world-action-models/)
- WAM vs VLA 鲁棒性：[arXiv:2603.22078](https://arxiv.org/abs/2603.22078)
- 本项目：`RGB_ws/docs/v1-双路上行语义调度方案.md` · `RGB_ws/docs/v1-仿真环境技术选型方案.md`
