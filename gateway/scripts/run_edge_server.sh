#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/config/edge.env"

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

ARGS=(
  --host "${LISTEN_HOST}"
  --subgraph-port "${SUBGRAPH_PORT}"
  --rgb-port "${RGB_PORT}"
  --go2-host "${GO2_HOST}"
  --go2-directive-port "${GO2_DIRECTIVE_PORT}"
  --session-id "${SESSION_ID}"
  --instruction "${INSTRUCTION}"
  --status-interval-s "${STATUS_INTERVAL_S}"
  --scheduler "${SCHEDULER:-mock}"
  --align-wait-s "${ALIGN_WAIT_S:-0.25}"
)

if [[ "${AUTO_DIRECTIVE}" == "true" ]]; then
  ARGS+=(--auto-directive)
else
  ARGS+=(--no-auto-directive)
fi

if [[ "${SCHEDULER:-mock}" == "streamvln" ]]; then
  ARGS+=(--streamvln-url "${STREAMVLN_URL:-http://127.0.0.1:5801/eval_vln}")
fi

if [[ "${SCHEDULER:-mock}" == "qwen_vl" ]]; then
  ARGS+=(
    --qwen-vl-model "${QWEN_VL_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
    --qwen-vl-device "${QWEN_VL_DEVICE:-cuda:0}"
    --qwen-vl-max-tokens "${QWEN_VL_MAX_TOKENS:-512}"
    --qwen-vl-min-interval-s "${QWEN_VL_MIN_INTERVAL_S:-0.5}"
  )
  if [[ "${QWEN_VL_4BIT:-true}" == "true" ]]; then
    ARGS+=(--qwen-vl-4bit)
  else
    ARGS+=(--no-qwen-vl-4bit)
  fi
  if [[ "${QWEN_VL_STUB:-false}" == "true" ]]; then
    ARGS+=(--qwen-vl-stub)
  else
    ARGS+=(--no-qwen-vl-stub)
  fi
fi

echo "==> edge server | scheduler=${SCHEDULER:-mock} | uplink :${SUBGRAPH_PORT}/:${RGB_PORT} | directive -> ${GO2_HOST}:${GO2_DIRECTIVE_PORT}"
exec python3 "${ROOT}/edge/server.py" "${ARGS[@]}"
