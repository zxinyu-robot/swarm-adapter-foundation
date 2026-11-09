#!/usr/bin/env bash
# Gazebo Harmonic 公共环境（GZ_IP / 资源路径 / GUI）
# shellcheck disable=SC2034
set -euo pipefail

_gz_env_root() {
  if [[ -n "${RGB_WS_ROOT:-}" ]]; then
    echo "${RGB_WS_ROOT}"
    return
  fi
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")/../.." && pwd)"
  echo "${here}"
}

setup_gz_env() {
  local root
  root="$(_gz_env_root)"
  export RGB_WS_ROOT="${root}"
  export GZ_DIR="${root}/gazebo"
  export GZ_SIM_RESOURCE_PATH="${GZ_DIR}/models:${GZ_DIR}/worlds:${GZ_SIM_RESOURCE_PATH:-}"
  export GZ_IP="${GZ_IP:-127.0.0.1}"
  # 本机桌面（常见 :0 / :1）
  if [[ -z "${DISPLAY:-}" ]]; then
    for d in :1 :0; do
      if [[ -e "/tmp/.X11-unix/X${d#:}" ]]; then
        export DISPLAY="${d}"
        break
      fi
    done
  fi
}

# 是否已有 corridor 仿真正在跑
is_gazebo_running() {
  setup_gz_env
  gz topic -l 2>/dev/null | grep -q '/world/corridor/' && return 0
  return 1
}

# 启动 Gazebo；已有实例则复用
# 用法: start_gazebo corridor.sdf [--gui|--headless]
start_gazebo() {
  local world_file="${1:?world sdf path}"
  local mode="${2:---gui}"
  setup_gz_env

  if is_gazebo_running; then
    echo "==> [gazebo] 已有 corridor 仿真实例，复用（不重复启动）"
    return 0
  fi

  local world_path="${world_file}"
  if [[ ! -f "${world_path}" ]]; then
    world_path="${GZ_DIR}/worlds/${world_file}"
  fi

  local gz_args=(-r "${world_path}")
  if [[ "${mode}" == "--headless" ]]; then
    gz_args=(-s -r "${world_path}")
    echo "==> [gazebo] headless: gz sim -s -r ${world_path}"
  else
    echo "==> [gazebo] GUI: DISPLAY=${DISPLAY:-unset} gz sim -r ${world_path}"
  fi

  nohup gz sim "${gz_args[@]}" > /tmp/rgb_gazebo_sim.log 2>&1 &
  GZ_PID=$!
  export GZ_PID

  local i
  for i in $(seq 1 30); do
    if is_gazebo_running; then
      echo "==> [gazebo] 就绪 (pid=${GZ_PID})"
      return 0
    fi
    sleep 0.5
  done

  echo "WARN: Gazebo 启动超时，见 /tmp/rgb_gazebo_sim.log" >&2
  tail -20 /tmp/rgb_gazebo_sim.log >&2 || true
  return 1
}

stop_gazebo_if_owned() {
  [[ -n "${GZ_PID:-}" ]] && kill "${GZ_PID}" 2>/dev/null || true
}
