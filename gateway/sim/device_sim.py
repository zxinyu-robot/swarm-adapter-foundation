#!/usr/bin/env python3
"""仿真端侧：多模态分层 tick → 双路 TCP 上行（L0 子图 + L1 RGB，L2 task 挂载子图）."""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge.multimodal_layers import LayerId, LayeredTick, TaskLayer, attach_layers_to_subgraph  # noqa: E402
from edge.rgb_forward import META_SCHEMA, pack_rgb_forward_frame  # noqa: E402

SCHEMA_SUBG = "motionslam.sparse_subgraph.v1"


def _send_line(host: str, port: int, obj: dict[str, Any], timeout: float) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(line.encode("utf-8"))


def _send_rgb(host: str, port: int, meta: dict[str, Any], payload: bytes, timeout: float) -> None:
    frame = pack_rgb_forward_frame(meta, payload)
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(frame)


def _rgb_payload(tag: str, version: int) -> bytes:
    header = tag.encode("utf-8")[:32].ljust(32, b"\x00")
    return header + bytes([version & 0xFF]) + b"\x00" * 32


def _task_from_step(step: dict[str, Any], scenario: dict[str, Any]) -> TaskLayer:
    layers = step.get("layers") or {}
    task_cfg = layers.get("task") or scenario.get("task") or {}
    return TaskLayer(
        instruction=str(task_cfg.get("instruction", scenario.get("instruction", "mock sim"))),
        goal_room_type=str(task_cfg.get("goal_room_type", step.get("goal_room_type", ""))),
        language=str(task_cfg.get("language", "zh")),
    )


def build_layered_tick(step: dict[str, Any], scenario: dict[str, Any]) -> LayeredTick:
    ver = int(step["version"])
    ts = time.time_ns()
    sid = str(scenario.get("session_id", "sim"))
    tag = str((step.get("layers") or {}).get("vision", {}).get("rgb_tag", step.get("rgb_tag", "sim")))

    structure = {
        "schema": SCHEMA_SUBG,
        "version": ver,
        "session_id": sid,
        "map_id": f"{sid}_map",
        "timestamp_ns": ts,
        "trigger_reason": "sim_tick",
        "robot_pose": step.get("robot_pose", {"x": 0, "y": 0, "z": 0, "yaw_deg": 0}),
        "nodes": step.get("nodes", []),
        "edges": step.get("edges", []),
        "frontiers": step.get("frontiers", []),
        "keyframes_meta": [
            {
                "keyframe_id": f"kf_{ver}",
                "subgraph_version": ver,
                "rgb_tag": tag,
            }
        ],
    }

    task = _task_from_step(step, scenario)
    vision_meta = {
        "schema": META_SCHEMA,
        "session_id": sid,
        "stream_field": str((step.get("layers") or {}).get("vision", {}).get("stream_field", "video360p")),
        "time_frame": 1000 + ver,
        "seq": ver,
        "timestamp_ns": ts,
        "subgraph_version": ver,
        "rgb_tag": tag,
        "pose": step.get("robot_pose", {}),
    }
    payload = _rgb_payload(tag, ver)
    vision_meta["payload_len"] = len(payload)

    tick = LayeredTick(
        session_id=sid,
        version=ver,
        timestamp_ns=ts,
        structure=structure,
        vision_meta=vision_meta,
        vision_payload=payload,
        task=task,
        present_layers=[LayerId.STRUCTURE, LayerId.VISION, LayerId.TASK],
    )
    tick.structure = attach_layers_to_subgraph(structure, tick)
    return tick


def run_scenario(
    scenario_path: Path,
    *,
    edge_host: str,
    subgraph_port: int,
    rgb_port: int,
    connect_timeout: float,
    version_offset: int = 0,
) -> list[dict[str, Any]]:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    tick_hz = float(scenario.get("tick_hz", 1.0))
    period = 1.0 / max(0.1, tick_hz)
    tick_log: list[dict[str, Any]] = []

    for step in scenario.get("steps", []):
        t0 = time.monotonic()
        ver = int(step["version"]) + version_offset
        step_copy = {**step, "version": ver}
        layered = build_layered_tick(step_copy, scenario)

        _send_line(edge_host, subgraph_port, layered.structure, connect_timeout)
        _send_rgb(edge_host, rgb_port, layered.vision_meta, layered.vision_payload, connect_timeout)

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        tick_log.append(
            {
                "version": ver,
                "expected_frontier_id": step.get("expected_frontier_id", "bt_next_subgoal"),
                "expected_vln_actions": step.get("expected_vln_actions"),
                "subgraph": layered.structure,
                "layer_manifest": layered.manifest(),
                "task_instruction": layered.task.instruction,
                "rgb_tag": layered.vision_meta.get("rgb_tag", ""),
                "send_ms": round(elapsed_ms, 2),
                "sent_mono": time.monotonic(),
            }
        )
        time.sleep(period)

    return tick_log


def main() -> int:
    p = argparse.ArgumentParser(description="Sim device layered multimodal uplink")
    p.add_argument("--scenario", type=Path, required=True)
    p.add_argument("--edge-host", default="127.0.0.1")
    p.add_argument("--subgraph-port", type=int, default=9877)
    p.add_argument("--rgb-port", type=int, default=9878)
    p.add_argument("--timeout", type=float, default=3.0)
    args = p.parse_args()
    log = run_scenario(
        args.scenario,
        edge_host=args.edge_host,
        subgraph_port=args.subgraph_port,
        rgb_port=args.rgb_port,
        connect_timeout=args.timeout,
    )
    print(json.dumps({"scenario": args.scenario.name, "ticks_sent": len(log)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
