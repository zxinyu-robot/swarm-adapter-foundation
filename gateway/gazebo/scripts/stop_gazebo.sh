#!/usr/bin/env bash
# 停止本机 corridor Gazebo（不影响其他 gz 世界）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=gazebo/scripts/gz_env.sh
source "${ROOT}/gazebo/scripts/gz_env.sh"
setup_gz_env

echo "==> [gazebo] 停止 corridor 相关 gz 进程"
pkill -f "gz sim.*corridor" 2>/dev/null || true
pkill -f "gz sim server" 2>/dev/null || true
pkill -f "gz sim gui" 2>/dev/null || true
sleep 1

if is_gazebo_running; then
  echo "WARN: 仍有 /world/corridor/ 话题，可手动 kill gz" >&2
  exit 1
fi
echo "==> [gazebo] 已停止"
