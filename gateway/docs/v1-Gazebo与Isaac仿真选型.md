# v1 Gazebo 与 Isaac 仿真选型

> **版本**：v1.0-draft  
> **日期**：2026-08-06  
> **定位**：在 **Go2 URDF + 边端 VLN** 主线外，补齐 **全物理仿真** 路线选型；**v1 优先落实 Gazebo 线**，Isaac / Habitat 为 P1/P2。  
> **配套**：`[v1-仿真环境技术选型方案.md](./v1-仿真环境技术选型方案.md)` · `[gazebo/README.md](../gazebo/README.md)` · `[motion/01-工作计划/多机器人协同_详细技术与科研规划.md](../../motion/01-工作计划/多机器人协同_详细技术与科研规划.md)`

---

## 1. 一句话定位

| | **Gazebo Harmonic** | **Isaac Sim** | **Habitat（VLN-CE）** |
|---|---------------------|---------------|------------------------|
| **本质** | 开源物理仿真 + ROS 生态 | NVIDIA GPU 高保真仿真 | VLN 算法 benchmark |
| **本项目角色** | **M2 主选**：Go2 双机、Swarm、与真狗 ROS 栈对齐 | P2：RL / 高保真 RGB / WAM 数据 | StreamVLN 训练评测，非系统集成 |
| **GPU** | 可选 | **必需 RTX** | 可选 |

---

## 2. 核心对比

| 维度 | Gazebo | Isaac Sim |
|------|--------|-----------|
| 许可证 | Apache 2.0 开源 | 免费研究版；商用另议 |
| ROS 2 | **原生**（`ros_gz`） | Bridge，Omniverse 工作流更重 |
| 物理 | ODE / Bullet / DART | PhysX 5 |
| 视觉传感器 | 插件级，画质一般 | RTX 光追，接近真机 |
| Go2 URDF | **已有** `Go2_URDF.zip` + 社区包 | 需 USD 转换 |
| 多机 C-SLAM | motion **M2 Gate** 已规划 | 可做，非主路径 |
| 上手成本 | 中 | 高 |
| 批量 RL | 弱 | **强** |

**2026 项目结论（与 motion 统筹一致）**：

- **近 1 年主选 Gazebo**：ROS2 + Super-LIO/BT 同栈；`Go2_URDF` 现成；Swarm-SLAM 双机 Gate。  
- **Isaac 补强项**：边侧 Qwen-VL / WAM 需大量逼真 RGB、域随机化、并行 RL 时再上。  
- **不替代 G0**：`run_sim_bench.sh` 协议级仿真仍是一改协议必跑的回归。

---

## 3. 三层仿真分工

```text
G0  协议级（RGB_ws/sim/）     TCP 9877/9878/9879 · 无 GPU · 已跑通
G1  Gazebo 物理级（gazebo/）  Go2 URDF · corridor world · 传感器话题
G2  Habitat / Isaac         VLN SR/SPL · 高保真视觉 · P1/P2
```

| 验证目标 | G0 | Gazebo | Isaac |
|---------|-----|--------|-------|
| 专网 VLN 协议 | ✅ | 间接（ROS→TCP 桥） | 间接 |
| frontier/对齐 | ✅ | 可叠加 | 可叠加 |
| Super-LIO + BT | ❌ | 激光+odom 可接 | 可接 |
| 多机 Swarm | ❌ | **M2** | 可选 |
| VLN 论文 SR | ❌ | 弱 | 强 |

---

## 4. Gazebo 线（v1 落实）

### 4.1 资产

| 项 | 路径 |
|----|------|
| 原始 URDF | `Go2_URDF.zip` → `assets/GO2_URDF/` |
| Gazebo 模型 | `gazebo/models/go2_description/`（`prepare_go2_model.py` 生成） |
| 场景 | `gazebo/worlds/corridor.sdf`（由 `corridor_3frontiers.json` 生成） |

### 4.2 一键命令

```bash
cd RGB_ws
./gazebo/scripts/install_gazebo_harmonic.sh   # 首次：装 gz harmonic（Ubuntu 24.04）
./gazebo/scripts/prepare_go2_model.sh           # 准备 URDF/SDF
./gazebo/scripts/run_corridor.sh                # 启动 corridor + Go2
```

### 4.3 与 RGB_ws v1 关系

```text
Gazebo 相机/激光 ROS 话题
    → （P1）device_sim 风格桥接 → edge :9877/:9878
    → SemanticDirective → BT 加权（真狗同 schema）
```

当前 **Gazebo 线 v1** 目标：**可视 + 可 spawn + corridor 场景**，不阻塞 G0/G1 专网联调。

### 4.4 Gate（Gazebo-G1）

| ID | 项 | 通过条件 |
|----|-----|---------|
| GG1 | 依赖 | `gz sim --version` 可用 |
| GG2 | 模型 | `go2_description` SDF 无 mesh 报错 |
| GG3 | 场景 | corridor 世界加载，三色 frontier 标记可见 |
| GG4 | _spawn | Go2 站立 z≈0.35m，无穿透地面 |
| GG5 | 传感器 | `model.sdf` 含 `front_camera` + `gpu_lidar` |
| GG6 | 位姿桥 | `gz model -m go2 -p` 可解析 |
| GG7 | edge 对齐 | uplink → `:9877/:9878`，`[align] layers=L0,L1,L2` |
| GG8 | 闭环评测 | `./gazebo/scripts/run_gazebo_bench.sh` fusion@1 ≥ G0 |

### 4.5 GG5–GG8 命令

```bash
cd RGB_ws
./gazebo/scripts/run_gazebo_bench.sh              # live：自动起 gz + edge + 评测
./gazebo/scripts/run_gazebo_bench.sh --mode scenario  # 无 gz：协议回环（GG6 skip）
# 手动三终端：
#   ./gazebo/scripts/run_corridor.sh
#   ./scripts/run_edge_server.sh  # 或 sim.env 参数
#   python3 gazebo/bridge/uplink_bridge.py --scenario sim/scenarios/corridor_3frontiers.json
```

---

## 5. Isaac 线（P2，暂不实施）

| 场景 | 用途 |
|------|------|
| 高保真 RGB 数据集 | 边侧 VLM / WAM 训练 |
| 并行 RL | 社交导航 ESN-PPO 支线 |
| Sim2Real | 视觉域随机化 |

**前置**：Gazebo GG1–GG4 通过；边侧 Qwen-VL 接入 G2。

---

## 6. 与 motion 里程碑对照

| motion | RGB_ws Gazebo |
|--------|---------------|
| M2 Gazebo 双 Go2 + Swarm | 本仓先 **单机 corridor**；双机命名空间在 motion_ws 扩展 |
| `Go2_URDF.zip` 模型起点 | ✅ 已用 |
| Isaac 非 C-SLAM 关键路径 | 本文 §5 一致 |

---

## 7. 参考

- Gazebo Harmonic：https://gazebosim.org/docs/harmonic  
- OSRF 安装：https://gazebosim.org/docs/harmonic/install_ubuntu/  
- motion M2：`motion_ws/docs/仿真Gate范围选型.md`  
- StreamVLN / Habitat：`third_party/StreamVLN/`  
