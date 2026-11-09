#!/usr/bin/env bash
# Ubuntu 24.04 安装 Gazebo Harmonic（OSRF 官方源）
set -euo pipefail

if command -v gz >/dev/null 2>&1; then
  echo "[install] 已安装: $(gz sim --version 2>&1 | head -1)"
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[install] 需要 sudo 安装系统包，将提示输入密码"
  SUDO=sudo
else
  SUDO=""
fi

echo "==> 添加 OSRF Gazebo 源 (Harmonic / Ubuntu 24.04 Noble)"
$SUDO apt-get update -qq
$SUDO apt-get install -y curl lsb-release gnupg

if [[ ! -f /usr/share/keyrings/gazebo.gpg ]]; then
  curl -sSL https://packages.osrfoundation.org/gazebo.gpg -o /tmp/gazebo.gpg
  $SUDO mv /tmp/gazebo.gpg /usr/share/keyrings/gazebo.gpg
fi

SOURCE_LINE="deb [arch=amd64 signed-by=/usr/share/keyrings/gazebo.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main"
if ! grep -q "packages.osrfoundation.org/gazebo" /etc/apt/sources.list.d/gazebo-stable.list 2>/dev/null; then
  echo "$SOURCE_LINE" | $SUDO tee /etc/apt/sources.list.d/gazebo-stable.list >/dev/null
fi

echo "==> 安装 gz-harmonic"
$SUDO apt-get update -qq
$SUDO apt-get install -y gz-harmonic

echo "==> 验证"
gz sim --version
echo "[install] 完成"
