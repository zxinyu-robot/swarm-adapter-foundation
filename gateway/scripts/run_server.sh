#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export RGB_WS_ROOT="${ROOT}"

# shellcheck disable=SC1091
source "${ROOT}/config/server.env"

CONDA_ENV="${CONDA_ENV:-streamvln}"
# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"

if [[ ! -f "${MODEL_PATH}/config.json" ]]; then
  echo "ERROR: Model not found at ${MODEL_PATH}"
  echo "Run: ./scripts/download_model.sh"
  exit 1
fi

echo "==> Starting StreamVLN server on ${HOST}:${PORT}"
echo "    Model: ${MODEL_PATH}"
echo "    Device: ${DEVICE}"

cd "${ROOT}"
python server/http_realworld_server.py \
  --model_path "${MODEL_PATH}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --device "${DEVICE}" \
  --default_instruction "${DEFAULT_INSTRUCTION}" \
  --num_future_steps "${NUM_FUTURE_STEPS}" \
  --num_frames "${NUM_FRAMES}" \
  --num_history "${NUM_HISTORY}" \
  --model_max_length "${MODEL_MAX_LENGTH}"
