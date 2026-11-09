#!/usr/bin/env python3
"""Gazebo → edge 双路上行桥（复用 sim/device_sim 协议）."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gazebo.bridge.frontier_builder import build_step_from_template  # noqa: E402
from gazebo.bridge.jpeg_util import encode_tagged_jpeg  # noqa: E402
from gazebo.bridge.pose_reader import read_pose, wait_pose  # noqa: E402
from gazebo.bridge.scan_frontiers import try_scan_frontiers  # noqa: E402
from sim.device_sim import build_layered_tick, _send_line, _send_rgb  # noqa: E402


def _scenario_with_session(scenario: dict[str, Any], session_id: str) -> dict[str, Any]:
    out = dict(scenario)
    out["session_id"] = session_id
    return out


def run_gazebo_scenario(
    scenario_path: Path,
    *,
    edge_host: str,
    subgraph_port: int,
    rgb_port: int,
    connect_timeout: float,
    mode: str = "live",
    model_name: str = "go2",
    session_id: str = "gazebo_corridor",
    version_offset: int = 0,
    wait_pose_s: float = 15.0,
    frontier_source: str = "scenario",
) -> list[dict[str, Any]]:
    scenario_raw = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario = _scenario_with_session(scenario_raw, session_id)
    tick_hz = float(scenario.get("tick_hz", 1.0))
    period = 1.0 / max(0.1, tick_hz)
    tick_log: list[dict[str, Any]] = []

    if mode == "live":
        if wait_pose(model_name=model_name, timeout_s=wait_pose_s) is None:
            print(f"[gazebo_uplink] WARN: {wait_pose_s}s 内未读到 {model_name} 位姿，回退 scenario 位姿", flush=True)

    for step_tpl in scenario.get("steps", []):
        t0 = time.monotonic()
        ver = int(step_tpl["version"]) + version_offset

        if mode == "live":
            pose = read_pose(model_name)
            if pose is not None:
                robot_pose = pose.as_dict()
            else:
                robot_pose = dict(step_tpl.get("robot_pose", {}))
        else:
            robot_pose = dict(step_tpl.get("robot_pose", {}))

        step = build_step_from_template(step_tpl, robot_pose, version=ver)
        if frontier_source in ("scan", "hybrid"):
            scan_fr = try_scan_frontiers(robot_pose, scenario_path=scenario_path)
            if scan_fr is not None:
                step["frontiers"] = scan_fr
                step["_frontier_from"] = "lidar_scan"
            elif frontier_source == "scan":
                print("[gazebo_uplink] WARN: LiDAR 不可用，回退 scenario frontiers", flush=True)
                step["_frontier_from"] = "scenario_fallback"
            else:
                step["_frontier_from"] = "scenario_hybrid_fallback"
        else:
            step["_frontier_from"] = "scenario"
        layered = build_layered_tick(step, scenario)

        # Gazebo 线：真实 JPEG（按 rgb_tag）
        tag = str(layered.vision_meta.get("rgb_tag", "gazebo"))
        jpeg = encode_tagged_jpeg(tag)
        layered.vision_payload = jpeg
        layered.vision_meta["payload_len"] = len(jpeg)

        _send_line(edge_host, subgraph_port, layered.structure, connect_timeout)
        _send_rgb(edge_host, rgb_port, layered.vision_meta, layered.vision_payload, connect_timeout)

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        tick_log.append(
            {
                "version": ver,
                "expected_frontier_id": step_tpl.get("expected_frontier_id", "bt_next_subgoal"),
                "expected_vln_actions": step_tpl.get("expected_vln_actions"),
                "subgraph": layered.structure,
                "layer_manifest": layered.manifest(),
                "task_instruction": layered.task.instruction,
                "rgb_tag": layered.vision_meta.get("rgb_tag", ""),
                "robot_pose": robot_pose,
                "send_ms": round(elapsed_ms, 2),
                "sent_mono": time.monotonic(),
                "source": f"gazebo_{mode}_{frontier_source}",
                "frontier_from": step.get("_frontier_from", frontier_source),
            }
        )
        time.sleep(period)

    return tick_log


def main() -> int:
    p = argparse.ArgumentParser(description="Gazebo uplink bridge → edge :9877/:9878")
    p.add_argument("--scenario", type=Path, required=True)
    p.add_argument("--edge-host", default="127.0.0.1")
    p.add_argument("--subgraph-port", type=int, default=9877)
    p.add_argument("--rgb-port", type=int, default=9878)
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--mode", choices=("live", "scenario"), default="live")
    p.add_argument("--model", default="go2")
    p.add_argument("--session-id", default="gazebo_corridor")
    p.add_argument("--wait-pose-s", type=float, default=15.0)
    p.add_argument(
        "--frontier-source",
        choices=("scenario", "scan", "hybrid"),
        default="scenario",
        help="frontier 来源：scenario 模板 / LiDAR scan / hybrid",
    )
    args = p.parse_args()

    log = run_gazebo_scenario(
        args.scenario,
        edge_host=args.edge_host,
        subgraph_port=args.subgraph_port,
        rgb_port=args.rgb_port,
        connect_timeout=args.timeout,
        mode=args.mode,
        model_name=args.model,
        session_id=args.session_id,
        wait_pose_s=args.wait_pose_s,
        frontier_source=args.frontier_source,
    )
    print(
        json.dumps(
            {"scenario": args.scenario.name, "mode": args.mode, "ticks_sent": len(log)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
