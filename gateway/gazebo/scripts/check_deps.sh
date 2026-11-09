#!/usr/bin/env bash
# 检查 Gazebo Harmonic 依赖
set -euo pipefail
ok=0
if command -v gz >/dev/null 2>&1; then
  echo "[deps] gz: $(gz sim --version 2>&1 | head -1)"
  ok=1
else
  echo "[deps] MISSING: gz (Gazebo Harmonic)"
  echo "       运行: ./gazebo/scripts/install_gazebo_harmonic.sh"
fi
if [[ -f "$(dirname "$0")/../models/go2_description/model.sdf" ]]; then
  echo "[deps] go2 model: OK"
else
  echo "[deps] MISSING: go2 model — 运行 prepare_go2_model.sh"
  ok=0
fi
if [[ -f "$(dirname "$0")/../worlds/corridor.sdf" ]]; then
  echo "[deps] corridor world: OK"
else
  echo "[deps] MISSING: corridor.sdf — run_corridor.sh 会自动生成"
fi
exit $(( ok == 1 ? 0 : 1 ))
