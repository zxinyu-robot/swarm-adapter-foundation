#!/usr/bin/env bash
# Gazebo 线闭环评测：gz sim + edge + uplink_bridge + GG5–GG8
# 用法:
#   ./gazebo/scripts/run_gazebo_bench.sh              # live（需 Gazebo 已 spawn go2）
#   ./gazebo/scripts/run_gazebo_bench.sh --mode scenario  # 无 gz 时协议回环
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GZ_DIR="${ROOT}/gazebo"
# shellcheck source=/dev/null
source "${ROOT}/config/sim.env"

MODE="live"
STRICT=1
START_GZ=1
FRONTIER_SOURCE="scenario"
KEEP_GZ=1
HEADLESS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --frontier-source)
      FRONTIER_SOURCE="$2"
      shift 2
      ;;
    --no-gz)
      START_GZ=0
      shift
      ;;
    --headless)
      HEADLESS=1
      shift
      ;;
    --no-keep-gz)
      KEEP_GZ=0
      shift
      ;;
    --no-strict)
      STRICT=0
      shift
      ;;
    --scheduler)
      SCHEDULER="$2"
      shift 2
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 1
      ;;
  esac
done

# shellcheck source=gazebo/scripts/gz_env.sh
source "${ROOT}/gazebo/scripts/gz_env.sh"
setup_gz_env

OWNED_GZ=0
cleanup() {
  [[ -n "${STREAMVLN_PID:-}" ]] && kill "${STREAMVLN_PID}" 2>/dev/null || true
  [[ -n "${EDGE_PID:-}" ]] && kill "${EDGE_PID}" 2>/dev/null || true
  if [[ "${KEEP_GZ}" -eq 0 && "${OWNED_GZ}" -eq 1 ]]; then
    stop_gazebo_if_owned
  fi
}
trap cleanup EXIT

echo "==> [gazebo_bench] prepare Go2 + corridor"
"${GZ_DIR}/scripts/prepare_go2_model.sh"
python3 "${GZ_DIR}/scripts/gen_corridor_world.py"

fuser -k "${SUBGRAPH_PORT}/tcp" "${RGB_PORT}/tcp" "${DIRECTIVE_PORT}/tcp" 2>/dev/null || true
fuser -k "${STREAMVLN_PORT:-5801}/tcp" 2>/dev/null || true
sleep 0.5

STREAMVLN_URL="${STREAMVLN_URL:-http://127.0.0.1:5801/eval_vln}"
if [[ "${SCHEDULER:-layer_fusion_stub}" == "streamvln" ]]; then
  echo "==> [gazebo_bench] StreamVLN stub :${STREAMVLN_PORT:-5801}"
  nohup python3 "${ROOT}/sim/streamvln_stub_server.py" \
    --host "127.0.0.1" --port "${STREAMVLN_PORT:-5801}" \
    > /tmp/rgb_gazebo_streamvln.log 2>&1 &
  STREAMVLN_PID=$!
  sleep 1.0
fi

if [[ "${START_GZ}" -eq 1 && "${MODE}" == "live" ]]; then
  if command -v gz >/dev/null 2>&1; then
    if is_gazebo_running; then
      echo "==> [gazebo_bench] 复用已有 Gazebo"
    else
      if [[ "${HEADLESS}" -eq 1 ]]; then
        start_gazebo "${GZ_DIR}/worlds/corridor.sdf" --headless
      else
        start_gazebo "${GZ_DIR}/worlds/corridor.sdf" --gui
      fi
      OWNED_GZ=1
    fi
  else
    echo "WARN: 无 gz，改用 --mode scenario" >&2
    MODE="scenario"
  fi
fi

if [[ "${FRONTIER_SOURCE}" == "scan" || "${FRONTIER_SOURCE}" == "hybrid" ]]; then
  echo "==> [gazebo_bench] 等待 LiDAR 就绪 (3s)"
  sleep 3
fi

echo "==> [gazebo_bench] 启动 edge scheduler=${SCHEDULER:-layer_fusion_stub} frontier=${FRONTIER_SOURCE}"
export PYTHONPATH="${ROOT}"
EDGE_ARGS=(
  --host "${LISTEN_HOST}"
  --subgraph-port "${SUBGRAPH_PORT}"
  --rgb-port "${RGB_PORT}"
  --go2-host "${GO2_HOST}"
  --go2-directive-port "${GO2_DIRECTIVE_PORT}"
  --session-id "gazebo_corridor"
  --instruction "找厨房"
  --scheduler "${SCHEDULER:-layer_fusion_stub}"
  --align-wait-s "${ALIGN_WAIT_S:-0.25}"
  --status-interval-s 0
  --auto-directive
)
if [[ "${SCHEDULER:-layer_fusion_stub}" == "streamvln" ]]; then
  EDGE_ARGS+=(--streamvln-url "${STREAMVLN_URL}")
fi
nohup python3 "${ROOT}/edge/server.py" "${EDGE_ARGS[@]}" \
  > /tmp/rgb_gazebo_edge.log 2>&1 &
EDGE_PID=$!
sleep 1.5

SCENARIO_FILE="${ROOT}/sim/scenarios/corridor_3frontiers.json"
if [[ "${SCHEDULER:-layer_fusion_stub}" == "streamvln" ]]; then
  SCENARIO_FILE="${ROOT}/sim/scenarios/streamvln_kitchen.json"
fi

EVAL_ARGS=(
  --edge-host "${LISTEN_HOST}"
  --subgraph-port "${SUBGRAPH_PORT}"
  --rgb-port "${RGB_PORT}"
  --directive-port "${DIRECTIVE_PORT}"
  --scheduler "${SCHEDULER:-layer_fusion_stub}"
  --mode "${MODE}"
  --frontier-source "${FRONTIER_SOURCE}"
  --scenario "${SCENARIO_FILE}"
  --skip-edge-check
)
[[ "${STRICT}" -eq 1 ]] && EVAL_ARGS+=(--strict)
[[ "${MODE}" == "scenario" ]] && EVAL_ARGS+=(--skip-gg6)

python3 "${GZ_DIR}/eval_runner.py" "${EVAL_ARGS[@]}"

if [[ "${KEEP_GZ}" -eq 1 ]]; then
  echo "==> [gazebo_bench] 完成（Gazebo 保持运行）"
else
  echo "==> [gazebo_bench] 完成（Gazebo 已停止）"
fi
echo "    开 GUI: ./gazebo/scripts/run_corridor.sh | 停止: ./gazebo/scripts/stop_gazebo.sh"
