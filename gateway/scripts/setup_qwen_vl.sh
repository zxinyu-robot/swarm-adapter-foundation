#!/usr/bin/env bash
# 安装 Qwen2.5-VL 边侧推理依赖（5070 + CUDA）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> 安装 Qwen-VL 依赖"
pip install -r "${ROOT}/requirements-qwen-vl.txt"

echo ""
echo "==> 完成。启动边侧（真 GPU）："
echo "  cd ${ROOT}"
echo "  # config/edge.env: SCHEDULER=qwen_vl, QWEN_VL_STUB=false"
echo "  ./scripts/run_edge_server.sh"
echo ""
echo "首次运行会从 HuggingFace 下载 Qwen2.5-VL-7B-Instruct（约 15GB，INT4 加载约 6–8GB 显存）"
