#!/usr/bin/env bash
# 单机双网络命名空间 + veth + tc netem 跑真实 DDS 链路探测（需要 root）。
# 证据等级：真实 DDS 协议栈与内核网络，链路劣化为 netem 注入，不是真实无线/广域网。
# 用法：sudo adapters/dds/scripts/netns_netem_probe.sh <swarm_link_probe 路径> <输出目录> [窗口数] [窗口秒数]
set -euo pipefail

PROBE=${1:?probe binary}
OUT=${2:?output dir}
WINDOWS=${3:-20}
WINDOW_S=${4:-2}
NS_TX=swarm_tx
NS_RX=swarm_rx

cleanup() {
  ip netns del "$NS_TX" 2>/dev/null || true
  ip netns del "$NS_RX" 2>/dev/null || true
}
trap cleanup EXIT
cleanup

ip netns add "$NS_TX"
ip netns add "$NS_RX"
ip link add veth_tx netns "$NS_TX" type veth peer name veth_rx netns "$NS_RX"
ip -n "$NS_TX" addr add 10.77.0.1/24 dev veth_tx
ip -n "$NS_RX" addr add 10.77.0.2/24 dev veth_rx
for ns in "$NS_TX" "$NS_RX"; do
  ip -n "$ns" link set lo up
done
ip -n "$NS_TX" link set veth_tx up multicast on
ip -n "$NS_RX" link set veth_rx up multicast on

# 名称 / 单向时延 / 抖动 / 丢包 / 限速
PROFILES=(
  "healthy 10ms 2ms 0.5% 20mbit"
  "constrained 40ms 10ms 5% 2mbit"
  "critical 120ms 30ms 15% 600kbit"
)

mkdir -p "$OUT"
for entry in "${PROFILES[@]}"; do
  read -r name delay jitter loss rate <<<"$entry"
  for pair in "$NS_TX veth_tx" "$NS_RX veth_rx"; do
    read -r ns dev <<<"$pair"
    tc -n "$ns" qdisc replace dev "$dev" root netem delay "$delay" "$jitter" loss "$loss" rate "$rate"
  done
  mkdir -p "$OUT/$name"
  tx_uri="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"veth_tx\"/></Interfaces></General></Domain></CycloneDDS>"
  rx_uri="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"veth_rx\"/></Interfaces></General></Domain></CycloneDDS>"
  echo "== profile $name: delay=$delay jitter=$jitter loss=$loss rate=$rate"
  ip netns exec "$NS_RX" env CYCLONEDDS_URI="$rx_uri" "$PROBE" rx --idle-exit-s 6 \
    --clock-max-dev-ms 5 > "$OUT/$name/rx.log" 2>&1 &
  rx_pid=$!
  sleep 1
  ip netns exec "$NS_TX" env CYCLONEDDS_URI="$tx_uri" "$PROBE" tx --windows "$WINDOWS" \
    --window-s "$WINDOW_S" --records "$OUT/$name" --clock-max-dev-ms 5 | tee "$OUT/$name/tx.log"
  wait "$rx_pid" || true
  tail -2 "$OUT/$name/rx.log"
done
