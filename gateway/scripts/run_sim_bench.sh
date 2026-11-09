#!/usr/bin/env bash
# 本机仿真评测：edge + directive sink + 场景双路上行 + G0 Gate 报告
# 用法:
#   ./scripts/run_sim_bench.sh
#   ./scripts/run_sim_bench.sh --scenario corridor_3frontiers
#   ./scripts/run_sim_bench.sh --scheduler streamvln --scenario streamvln_kitchen
#   ./scripts/run_sim_bench.sh --scheduler mock --no-strict
#   ./scripts/run_sim_bench.sh --trace            # 额外采集师生 trace（蒸馏数据集）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "${ROOT}/config/sim.env"

SCENARIO_ARGS=()
SCHEDULER="${SCHEDULER:-layer_fusion_stub}"
STRICT=1
TRACE_OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario)
      SCENARIO_ARGS+=(--scenario "${ROOT}/sim/scenarios/${2}.json")
      shift 2
      ;;
    --scheduler)
      SCHEDULER="$2"
      shift 2
      ;;
    --no-strict)
      STRICT=0
      shift
      ;;
    --trace)
      TRACE_DIR="${ROOT}/sim/traces"
      mkdir -p "${TRACE_DIR}"
      TRACE_OUT="${TRACE_DIR}/trace_$(date +%Y%m%d_%H%M%S).jsonl"
      shift
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 1
      ;;
  esac
done

cleanup() {
  [[ -n "${STREAMVLN_PID:-}" ]] && kill "${STREAMVLN_PID}" 2>/dev/null || true
  [[ -n "${EDGE_PID:-}" ]] && kill "${EDGE_PID}" 2>/dev/null || true
}
trap cleanup EXIT

echo "==> [sim] 释放端口 ${SUBGRAPH_PORT}/${RGB_PORT}/${DIRECTIVE_PORT}/${STREAMVLN_PORT:-5801}"
fuser -k "${SUBGRAPH_PORT}/tcp" "${RGB_PORT}/tcp" "${DIRECTIVE_PORT}/tcp" 2>/dev/null || true
fuser -k "${STREAMVLN_PORT:-5801}/tcp" 2>/dev/null || true
sleep 0.5

STREAMVLN_URL="${STREAMVLN_URL:-http://127.0.0.1:5801/eval_vln}"
if [[ "${SCHEDULER}" == "streamvln" ]]; then
  echo "==> [sim] 启动 StreamVLN CPU stub（官方 /eval_vln 协议）"
  nohup python3 "${ROOT}/sim/streamvln_stub_server.py" \
    --host "127.0.0.1" \
    --port "${STREAMVLN_PORT:-5801}" \
    > /tmp/rgb_sim_streamvln_stub.log 2>&1 &
  STREAMVLN_PID=$!
  sleep 1.0
  if ! curl -sf "http://127.0.0.1:${STREAMVLN_PORT:-5801}/health" >/dev/null; then
    echo "StreamVLN stub 启动失败，见 /tmp/rgb_sim_streamvln_stub.log" >&2
    tail -20 /tmp/rgb_sim_streamvln_stub.log >&2 || true
    exit 1
  fi
fi

echo "==> [sim] 启动边侧 scheduler=${SCHEDULER} (本机回环)"
export PYTHONPATH="${ROOT}"
EDGE_ARGS=(
  --host "${LISTEN_HOST}"
  --subgraph-port "${SUBGRAPH_PORT}"
  --rgb-port "${RGB_PORT}"
  --go2-host "${GO2_HOST}"
  --go2-directive-port "${GO2_DIRECTIVE_PORT}"
  --session-id "${SESSION_ID}"
  --instruction "${INSTRUCTION}"
  --scheduler "${SCHEDULER}"
  --align-wait-s "${ALIGN_WAIT_S:-0.25}"
  --status-interval-s "${STATUS_INTERVAL_S}"
  --auto-directive
)
if [[ "${SCHEDULER}" == "streamvln" ]]; then
  EDGE_ARGS+=(--streamvln-url "${STREAMVLN_URL}")
fi
if [[ "${SCHEDULER}" == "qwen_vl" ]]; then
  EDGE_ARGS+=(
    --qwen-vl-model "${QWEN_VL_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
    --qwen-vl-device "${QWEN_VL_DEVICE:-cuda:0}"
    --qwen-vl-max-tokens "${QWEN_VL_MAX_TOKENS:-512}"
    --qwen-vl-min-interval-s "${QWEN_VL_MIN_INTERVAL_S:-0.5}"
  )
  if [[ "${QWEN_VL_4BIT:-true}" == "true" ]]; then
    EDGE_ARGS+=(--qwen-vl-4bit)
  else
    EDGE_ARGS+=(--no-qwen-vl-4bit)
  fi
  if [[ "${QWEN_VL_STUB:-true}" == "true" ]]; then
    EDGE_ARGS+=(--qwen-vl-stub)
  else
    EDGE_ARGS+=(--no-qwen-vl-stub)
  fi
fi

nohup python3 "${ROOT}/edge/server.py" "${EDGE_ARGS[@]}" \
  > /tmp/rgb_sim_edge.log 2>&1 &
EDGE_PID=$!
sleep 1.5

if ! python3 -c "import socket; s=socket.create_connection(('${LISTEN_HOST}',${SUBGRAPH_PORT}),2); s.close()"; then
  echo "边侧启动失败，见 /tmp/rgb_sim_edge.log" >&2
  tail -30 /tmp/rgb_sim_edge.log >&2 || true
  exit 1
fi

echo "==> [sim] 运行评测 (G0 strict=${STRICT})"
EVAL_ARGS=(
  --edge-host "${LISTEN_HOST}"
  --subgraph-port "${SUBGRAPH_PORT}"
  --rgb-port "${RGB_PORT}"
  --directive-port "${DIRECTIVE_PORT}"
  --scheduler "${SCHEDULER}"
  --skip-edge-check
)
[[ "${STRICT}" -eq 1 ]] && EVAL_ARGS+=(--strict)
[[ -n "${TRACE_OUT}" ]] && EVAL_ARGS+=(--trace-out "${TRACE_OUT}")

if [[ ${#SCENARIO_ARGS[@]} -eq 0 ]]; then
  if [[ "${SCHEDULER}" == "streamvln" ]]; then
    SCENARIO_ARGS=(--scenario "${ROOT}/sim/scenarios/streamvln_kitchen.json")
  else
    SCENARIO_ARGS=(--scenario "${ROOT}/sim/scenarios/corridor_3frontiers.json")
  fi
fi

python3 "${ROOT}/sim/eval_runner.py" "${EVAL_ARGS[@]}" "${SCENARIO_ARGS[@]}"

echo "==> [sim] G0 通过。边侧: /tmp/rgb_sim_edge.log"
[[ -n "${TRACE_OUT}" ]] && echo "    trace: ${TRACE_OUT}"
[[ "${SCHEDULER}" == "streamvln" ]] && echo "    StreamVLN stub: /tmp/rgb_sim_streamvln_stub.log"
[[ "${SCHEDULER}" == "qwen_vl" ]] && echo "    Qwen-VL stub=${QWEN_VL_STUB:-true}（仿真默认 stub，真 GPU 设 QWEN_VL_STUB=false）"

# macOS bash 3.2 下 set -e + EXIT trap 会把 cleanup 的 kill 退出码带成脚本退出码，
# 此处显式归零，保证 G0 通过时脚本返回 0（供 CI / 自动化判断）。
exit 0
