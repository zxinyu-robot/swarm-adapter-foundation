#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
RGB_ROOT="$(cd "${DIR}/../.." && pwd)"
# shellcheck disable=SC1091
source "${RGB_ROOT}/config/edge.env"
cd "${DIR}"
exec python3 edge_mvpi1_planner.py \
  --host "${LISTEN_HOST}" \
  --go2-host "${GO2_HOST}" \
  --session-id "${SESSION_ID}" \
  "$@"
