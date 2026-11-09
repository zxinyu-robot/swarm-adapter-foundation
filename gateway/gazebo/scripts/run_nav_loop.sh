#!/usr/bin/env bash
# Gazebo 导航闭环：VLN 决策（edge directive）→ scan-planner 执行（LiDAR frontier + 线速度/角速度）
# 用法:
#   ./gazebo/scripts/run_nav_loop.sh
#   ./gazebo/scripts/run_nav_loop.sh --scheduler streamvln --frontier-source scan
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GZ_DIR="${ROOT}/gazebo"
# shellcheck source=/dev/null
source "${ROOT}/config/sim.env"
# shellcheck source=gazebo/scripts/gz_env.sh
source "${ROOT}/gazebo/scripts/gz_env.sh"

HEADLESS=0
KEEP_GZ=1
FRONTIER_SOURCE="scan"
SCHEDULER="${SCHEDULER:-streamvln}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --headless) HEADLESS=1; shift ;;
    --no-keep-gz) KEEP_GZ=0; shift ;;
    --scheduler)
      SCHEDULER="$2"
      shift 2
      ;;
    --frontier-source)
      FRONTIER_SOURCE="$2"
      shift 2
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 1
      ;;
  esac
done

setup_gz_env

OWNED_GZ=0
cleanup() {
  [[ -n "${STREAMVLN_PID:-}" ]] && kill "${STREAMVLN_PID}" 2>/dev/null || true
  [[ "${KEEP_GZ}" -eq 1 ]] && return 0
  [[ "${OWNED_GZ}" -eq 1 ]] && stop_gazebo_if_owned
  [[ -n "${EDGE_PID:-}" ]] && kill "${EDGE_PID}" 2>/dev/null || true
}
trap cleanup EXIT

"${GZ_DIR}/scripts/prepare_go2_model.sh"
python3 "${GZ_DIR}/scripts/gen_corridor_world.py"

fuser -k "${SUBGRAPH_PORT}/tcp" "${RGB_PORT}/tcp" "${DIRECTIVE_PORT}/tcp" 2>/dev/null || true
fuser -k "${STREAMVLN_PORT:-5801}/tcp" 2>/dev/null || true
sleep 0.5

STREAMVLN_URL="${STREAMVLN_URL:-http://127.0.0.1:5801/eval_vln}"
if [[ "${SCHEDULER}" == "streamvln" ]]; then
  echo "==> [nav_loop] StreamVLN stub :${STREAMVLN_PORT:-5801}"
  nohup python3 "${ROOT}/sim/streamvln_stub_server.py" \
    --host "127.0.0.1" --port "${STREAMVLN_PORT:-5801}" \
    > /tmp/rgb_gazebo_streamvln.log 2>&1 &
  STREAMVLN_PID=$!
  sleep 1.0
fi

if is_gazebo_running; then
  echo "==> [nav_loop] 复用已有 Gazebo（GUI 保持）"
else
  if [[ "${HEADLESS}" -eq 1 ]]; then
    start_gazebo "${GZ_DIR}/worlds/corridor.sdf" --headless
  else
    start_gazebo "${GZ_DIR}/worlds/corridor.sdf" --gui
  fi
  OWNED_GZ=1
fi

SCENARIO_FILE="${ROOT}/sim/scenarios/corridor_3frontiers.json"
if [[ "${SCHEDULER}" == "streamvln" ]]; then
  SCENARIO_FILE="${ROOT}/sim/scenarios/streamvln_kitchen.json"
fi

echo "==> [nav_loop] 启动 edge scheduler=${SCHEDULER} frontier=${FRONTIER_SOURCE}"
export PYTHONPATH="${ROOT}"
EDGE_ARGS=(
  --host "${LISTEN_HOST}"
  --subgraph-port "${SUBGRAPH_PORT}"
  --rgb-port "${RGB_PORT}"
  --go2-host "${GO2_HOST}"
  --go2-directive-port "${GO2_DIRECTIVE_PORT}"
  --session-id "gazebo_corridor"
  --instruction "找厨房"
  --scheduler "${SCHEDULER}"
  --align-wait-s "${ALIGN_WAIT_S:-0.25}"
  --status-interval-s 0
  --auto-directive
)
if [[ "${SCHEDULER}" == "streamvln" ]]; then
  EDGE_ARGS+=(--streamvln-url "${STREAMVLN_URL}")
fi
nohup python3 "${ROOT}/edge/server.py" "${EDGE_ARGS[@]}" \
  > /tmp/rgb_gazebo_edge.log 2>&1 &
EDGE_PID=$!
sleep 1.5

echo "==> [nav_loop] VLN 决策 → scan-planner 执行 → ${SCENARIO_FILE##*/}"
python3 "${GZ_DIR}/bridge/nav_loop.py" \
  --scenario "${SCENARIO_FILE}" \
  --edge-host "${LISTEN_HOST}" \
  --subgraph-port "${SUBGRAPH_PORT}" \
  --rgb-port "${RGB_PORT}" \
  --directive-port "${DIRECTIVE_PORT}" \
  --frontier-source "${FRONTIER_SOURCE}" \
  --nav-duration-s 20

if [[ "${KEEP_GZ}" -eq 1 ]]; then
  echo "==> [nav_loop] 完成（Gazebo 保持运行）"
else
  echo "==> [nav_loop] 完成（Gazebo 已停止）"
fi
echo "    重新开 GUI: ./gazebo/scripts/run_corridor.sh"
echo "    停止仿真:   ./gazebo/scripts/stop_gazebo.sh"
