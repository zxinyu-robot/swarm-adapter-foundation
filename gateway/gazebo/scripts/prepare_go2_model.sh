#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="${ROOT}"
python3 "${ROOT}/gazebo/scripts/prepare_go2_model.py"
