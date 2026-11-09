# Gazebo Harmonic — Go2 corridor 仿真

基于你提供的 `Go2_URDF.zip`，在 **Gazebo Harmonic** 中加载 corridor 场景（对齐 `sim/scenarios/corridor_3frontiers.json`）。

## 快速开始

```bash
cd RGB_ws

# 1. 安装 Gazebo Harmonic（Ubuntu 24.04，仅需一次）
./gazebo/scripts/install_gazebo_harmonic.sh

# 2. 准备 Go2 模型（从 assets 复制 + 修正 mesh 路径 + 可选生成 SDF）
./gazebo/scripts/prepare_go2_model.sh

# 3. 生成 corridor 世界并启动
./gazebo/scripts/run_corridor.sh
```

## 目录

```text
gazebo/
├── bridge/                   # pose_reader + uplink_bridge → edge
├── models/go2_description/
├── worlds/corridor.sdf
├── reports/                  # GG 评测报告
└── scripts/
    ├── run_gazebo_bench.sh   # GG5–GG8 一键
    └── ...
```

## 图例（与 Open3D 可视化一致）

| 颜色 | frontier |
|------|----------|
| 绿 | fr_kitchen |
| 红 | fr_hall |
| 紫 | fr_bedroom |

## GG5–GG8 闭环（本机 → edge）

```bash
./gazebo/scripts/run_gazebo_bench.sh              # 自动：gz + edge + 评测
./gazebo/scripts/run_gazebo_bench.sh --mode scenario  # 无 Gazebo 时协议回环
```

手动：

```bash
# 终端 1
./gazebo/scripts/run_corridor.sh
# 终端 2
source config/sim.env && ./scripts/run_edge_server.sh
# 终端 3
python3 gazebo/bridge/uplink_bridge.py --scenario sim/scenarios/corridor_3frontiers.json
```

报告：`gazebo/reports/<timestamp>/summary.md`

corridor 场景用 **`go2_stand`**：机身 + **四条腿站立视觉**（FK 固定 mesh，无关节物理，避免塌倒）。完整 URDF 关节动力学见 `go2_description/`（P1 ROS 腿控）。

```bash
./gazebo/scripts/stop_gazebo.sh
./gazebo/scripts/prepare_go2_model.sh
python3 gazebo/scripts/gen_corridor_world.py
DISPLAY=:1 ./gazebo/scripts/run_corridor.sh
# 或已运行时：
./gazebo/scripts/reset_go2_pose.sh
```

边侧 directive 指定 frontier 后，仿真端下发 **线速度 `linear_m_s` + 角速度 `angular_rad_s`**：

```bash
./gazebo/scripts/run_nav_loop.sh
# 或
python3 gazebo/bridge/nav_loop.py --scenario sim/scenarios/corridor_3frontiers.json
```

底层经运动学 **`set_pose`**（保持直立）；**不经 ROS `/cmd_vel`**。

## LiDAR frontier（Super-LIO 替身）

```bash
./gazebo/scripts/run_gazebo_bench.sh --frontier-source scan   # 或 hybrid
```

## 双机 Swarm（motion M2）

世界文件：`gazebo/worlds/corridor_dual.sdf`（`go2_a` / `go2_b`）  
入口：[`motion_ws/gazebo/README.md`](../../motion_ws/gazebo/README.md)

## 环境变量

`run_corridor.sh` 自动设置：

```bash
export GZ_SIM_RESOURCE_PATH="$RGB_ws/gazebo/models:$RGB_ws/gazebo/worlds"
```

## 文档

选型与路线图：[`docs/v1-Gazebo与Isaac仿真选型.md`](../docs/v1-Gazebo与Isaac仿真选型.md)
