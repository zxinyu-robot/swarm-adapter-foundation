#!/usr/bin/env bash
# Go2 URDF 3D 可视化（corridor 场景回放）
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${ROOT}/assets/GO2_URDF/urdf/go2_description.urdf" ]]; then
  echo "==> 解压 Go2_URDF.zip"
  unzip -qo "${ROOT}/Go2_URDF.zip" -d "${ROOT}/assets/"
fi

SCENARIO="${ROOT}/sim/scenarios/corridor_3frontiers.json"
GUI=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario) SCENARIO="${ROOT}/sim/scenarios/${2}.json"; shift 2 ;;
    --png-only) GUI=0; shift ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

ARGS=(--scenario "${SCENARIO}")
[[ "${GUI}" -eq 0 ]] && ARGS+=(--no-gui)

export PYTHONPATH="${ROOT}"
python3 "${ROOT}/sim/visual_sim.py" "${ARGS[@]}"
