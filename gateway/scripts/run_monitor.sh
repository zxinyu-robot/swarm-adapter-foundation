#!/usr/bin/env bash
# 边侧网关 + Foxglove 网页监控（本机联调 / 真狗联调）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/config/edge.env"
# shellcheck disable=SC1091
source "${ROOT}/config/monitor.env"

export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

if ! python3 -c "import foxglove" 2>/dev/null; then
  echo "==> 安装 foxglove-sdk ..."
  pip3 install --user --break-system-packages 'foxglove-sdk>=0.25' \
    || pip3 install --break-system-packages 'foxglove-sdk>=0.25'
fi

ARGS=(
  --host "${LISTEN_HOST}"
  --subgraph-port "${SUBGRAPH_PORT}"
  --rgb-port "${RGB_PORT}"
  --go2-host "${GO2_HOST}"
  --go2-directive-port "${GO2_DIRECTIVE_PORT}"
  --session-id "${SESSION_ID}"
  --instruction "${INSTRUCTION}"
  --status-interval-s "${STATUS_INTERVAL_S}"
  --foxglove-host "${FOXGLOVE_HOST}"
  --foxglove-port "${FOXGLOVE_PORT}"
  --foxglove-frame-id "${FOXGLOVE_FRAME_ID}"
  --foxglove-link-hz "${FOXGLOVE_LINK_HZ}"
)

if [[ "${AUTO_DIRECTIVE}" == "true" ]]; then
  ARGS+=(--auto-directive)
else
  ARGS+=(--no-auto-directive)
fi

if [[ -n "${FOXGLOVE_PCD_DIR:-}" ]]; then
  ARGS+=(--foxglove-pcd-dir "${FOXGLOVE_PCD_DIR}")
fi

echo "==> edge + foxglove | uplink :${SUBGRAPH_PORT}/:${RGB_PORT}"
echo "==> Foxglove Studio → ws://${FOXGLOVE_HOST}:${FOXGLOVE_PORT}"
echo "==> Layout 导入: ${ROOT}/monitor/layouts/rgb_ws_monitor.json"
exec python3 "${ROOT}/edge/server.py" "${ARGS[@]}"
