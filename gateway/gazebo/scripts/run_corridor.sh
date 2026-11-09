#!/usr/bin/env bash
# 启动 corridor + Go2（带 GUI，前台运行，关窗口即退出）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=gazebo/scripts/gz_env.sh
source "${ROOT}/gazebo/scripts/gz_env.sh"

setup_gz_env
"${ROOT}/gazebo/scripts/prepare_go2_model.sh"
python3 "${ROOT}/gazebo/scripts/gen_corridor_world.py"

if ! command -v gz >/dev/null 2>&1; then
  echo "未检测到 gz。请运行: ./gazebo/scripts/install_gazebo_harmonic.sh" >&2
  exit 1
fi

if is_gazebo_running; then
  echo "==> [gazebo] corridor 已在运行。若要重启: ./gazebo/scripts/stop_gazebo.sh"
  exit 0
fi

WORLD="${GZ_DIR}/worlds/corridor.sdf"
echo "==> [gazebo] GZ_SIM_RESOURCE_PATH=${GZ_SIM_RESOURCE_PATH}"
echo "==> [gazebo] GZ_IP=${GZ_IP} DISPLAY=${DISPLAY:-unset}"
echo "    图例: 绿=kitchen 红=hall 紫=bedroom | Go2 在原点"
exec gz sim -r "${WORLD}"
