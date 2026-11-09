#!/usr/bin/env bash
# 从 HuggingFace 下载 StreamVLN 真机部署 checkpoint (~16GB)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/config/server.env"
export RGB_WS_ROOT="${ROOT}"

mkdir -p "$(dirname "${MODEL_PATH}")"

if [[ -f "${MODEL_PATH}/config.json" ]]; then
  echo "==> Model already exists at ${MODEL_PATH}"
  exit 0
fi

echo "==> Downloading ${MODEL_HF_ID} ..."
echo "    Target: ${MODEL_PATH}"

if command -v huggingface-cli &>/dev/null; then
  huggingface-cli download "${MODEL_HF_ID}" --local-dir "${MODEL_PATH}"
elif python3 -c "import huggingface_hub" 2>/dev/null; then
  python3 - <<PY
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="${MODEL_HF_ID}",
    local_dir="${MODEL_PATH}",
)
PY
else
  pip install -q huggingface_hub
  huggingface-cli download "${MODEL_HF_ID}" --local-dir "${MODEL_PATH}"
fi

echo "==> Download complete."
