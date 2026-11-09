#!/usr/bin/env bash
# 把倒地的 Go2 重置为直立站立（z≈0.21, roll/pitch=0）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONPATH="${ROOT}"
# shellcheck source=gazebo/scripts/gz_env.sh
source "${ROOT}/gazebo/scripts/gz_env.sh"
setup_gz_env

python3 -c "
from gazebo.bridge.velocity_driver import reset_upright
from gazebo.bridge.pose_reader import read_pose
ok = reset_upright('go2', x=0.0, y=0.0)
pose = read_pose('go2')
print(f'[reset] upright={ok} pose={pose.as_dict() if pose else None}')
"
