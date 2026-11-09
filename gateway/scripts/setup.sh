#!/usr/bin/env bash
# 安装 StreamVLN 7B 推理环境（x86 GPU 服务端）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STREAMVLN_DIR="${ROOT}/third_party/StreamVLN"
CONDA_ENV="${CONDA_ENV:-streamvln}"

echo "==> RGB_ws root: ${ROOT}"

# 1. 克隆 StreamVLN
if [[ ! -d "${STREAMVLN_DIR}/.git" ]]; then
  echo "==> Cloning StreamVLN..."
  mkdir -p "${ROOT}/third_party"
  git clone --depth 1 https://github.com/InternRobotics/StreamVLN.git "${STREAMVLN_DIR}"
else
  echo "==> StreamVLN already cloned, pulling latest..."
  git -C "${STREAMVLN_DIR}" pull --ff-only || true
fi

# 2. conda 环境
if ! command -v conda &>/dev/null; then
  echo "ERROR: conda not found. Install Miniconda first."
  exit 1
fi

if ! conda env list | grep -q "^${CONDA_ENV} "; then
  echo "==> Creating conda env: ${CONDA_ENV} (python 3.9)"
  conda create -y -n "${CONDA_ENV}" python=3.9
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"

echo "==> Installing PyTorch 2.1.2 + CUDA 12.1..."
pip install torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cu121

echo "==> Installing inference dependencies..."
pip install \
  "transformers==4.45.1" \
  "accelerate==0.28.0" \
  "flask" \
  "pillow" \
  "numpy" \
  "omegaconf" \
  "einops" \
  "sentencepiece" \
  "protobuf" \
  "requests" \
  "opencv-python" \
  "quaternion" \
  "depth-camera-filtering @ git+https://github.com/naokiyokoyama/depth_camera_filtering@39d6e2f391c8b2198a67ad96f94bf6da0acd48a0"

# flash-attn 可选，失败则回退 sdpa
pip install flash-attn --no-build-isolation 2>/dev/null || echo "WARN: flash-attn install skipped, server will use default attention"

echo "==> Setup done."
echo ""
echo "Next steps:"
echo "  1. source config/server.env"
echo "  2. ./scripts/download_model.sh"
echo "  3. ./scripts/run_server.sh"
