#!/usr/bin/env python3
"""模拟 Go2 上行，测试本机 edge server（无需真狗）."""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge.rgb_forward import META_SCHEMA, pack_rgb_forward_frame  # noqa: E402

MAGIC_SUBG = "motionslam.sparse_subgraph.v1"


def send_json_line(host: str, port: int, obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with socket.create_connection((host, port), timeout=3) as s:
        s.sendall(line.encode("utf-8"))


def pack_rgb_mock(session_id: str, version: int, seq: int) -> bytes:
    payload = b"\x00\x00\x00\x01" + b"\x00" * 64
    meta = {
        "schema": META_SCHEMA,
        "session_id": session_id,
        "stream_field": "video360p",
        "time_frame": 1000 + seq,
        "seq": seq,
        "timestamp_ns": time.time_ns(),
        "subgraph_version": version,
        "payload_len": len(payload),
        "pose": {"x": 0.1, "y": 0.2, "z": 0.0, "yaw_deg": 5.0},
    }
    return pack_rgb_forward_frame(meta, payload)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--subgraph-port", type=int, default=9877)
    p.add_argument("--rgb-port", type=int, default=9878)
    p.add_argument("--version", type=int, default=1)
    args = p.parse_args()

    snap = {
        "schema": MAGIC_SUBG,
        "version": args.version,
        "session_id": "selftest",
        "map_id": "demo_live_map",
        "timestamp_ns": time.time_ns(),
        "trigger_reason": "manual",
        "robot_pose": {"x": 0.5, "y": 0.1, "z": 0.0, "yaw_deg": 0.0},
        "nodes": [{"node_id": "cell_0_0", "visited": False, "frontier_count": 1}],
        "edges": [],
        "frontiers": [
            {
                "frontier_id": "bt_next_subgoal",
                "position": {"x": 1.0, "y": 0.0, "z": 0.0},
                "attached_node_id": "cell_0_0",
                "geom_score": 0.9,
            }
        ],
        "keyframes_meta": [],
    }
    send_json_line(args.host, args.subgraph_port, snap)
    print(f"sent subgraph v={args.version}")

    frame = pack_rgb_mock("selftest", args.version, 1)
    with socket.create_connection((args.host, args.rgb_port), timeout=3) as s:
        s.sendall(frame)
    print("sent MSRGB frame")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
