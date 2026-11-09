#!/usr/bin/env bash
# 跨机 DDS 链路探测：本机跑 tx，远端（经 SSH）跑 rx，DDS 走两机之间的隧道网卡（如 WireGuard wg0）。
# 每档在两端隧道网卡出口加同样的 tc netem；baseline 档不加，只有真实链路。
# 证据等级：跨机真实网络 + 注入劣化；不是无线、不是真机。本机需要 sudo，远端需要 root。
# 用法：
#   REMOTE=root@host REMOTE_PROBE=/path/swarm_link_probe \
#   LOCAL_URI=file://$HOME/cdds_wg.xml REMOTE_URI=file:///root/cdds_wg.xml \
#   adapters/dds/scripts/wg_netem_probe.sh <本机 swarm_link_probe> <输出目录> [网卡] [窗口数] [窗口秒数]
set -euo pipefail

PROBE=${1:?probe binary}
OUT=${2:?output dir}
IFACE=${3:-wg0}
WINDOWS=${4:-20}
WINDOW_S=${5:-2}
: "${REMOTE:?}" "${REMOTE_PROBE:?}" "${LOCAL_URI:?}" "${REMOTE_URI:?}"
CLOCK_MAX_DEV_MS=${CLOCK_MAX_DEV_MS:-5}

PROFILES=(
  "baseline - - - -"
  "healthy 10ms 2ms 0.5% 20mbit"
  "constrained 40ms 10ms 5% 2mbit"
  "critical 120ms 30ms 15% 600kbit"
)

clear_netem() {
  sudo tc qdisc del dev "$IFACE" root 2>/dev/null || true
  ssh -o BatchMode=yes "$REMOTE" "tc qdisc del dev $IFACE root 2>/dev/null || true"
}
trap clear_netem EXIT

for entry in "${PROFILES[@]}"; do
  read -r name delay jitter loss rate <<<"$entry"
  clear_netem
  if [[ "$delay" != "-" ]]; then
    args="delay $delay $jitter loss $loss rate $rate"
    sudo tc qdisc replace dev "$IFACE" root netem $args
    ssh -o BatchMode=yes "$REMOTE" "tc qdisc replace dev $IFACE root netem $args"
  fi
  mkdir -p "$OUT/$name"
  echo "== profile $name: delay=$delay jitter=$jitter loss=$loss rate=$rate"
  ping -c 20 -i 0.2 -q "$(ssh -o BatchMode=yes "$REMOTE" "ip -4 -o addr show $IFACE | awk '{print \$4}' | cut -d/ -f1")" \
    > "$OUT/$name/ping.log" 2>&1 || true
  tail -2 "$OUT/$name/ping.log"
  ssh -o BatchMode=yes "$REMOTE" "CYCLONEDDS_URI=$REMOTE_URI $REMOTE_PROBE rx --idle-exit-s 8 \
    --clock-max-dev-ms $CLOCK_MAX_DEV_MS" > "$OUT/$name/rx.log" 2>&1 &
  rx_pid=$!
  sleep 2
  CYCLONEDDS_URI="$LOCAL_URI" "$PROBE" tx --windows "$WINDOWS" --window-s "$WINDOW_S" \
    --records "$OUT/$name" --clock-max-dev-ms "$CLOCK_MAX_DEV_MS" --match-timeout-s 30 | tee "$OUT/$name/tx.log"
  wait "$rx_pid" || true
  tail -2 "$OUT/$name/rx.log"
done
