#!/usr/bin/env python3
"""VLN 决策 + scan-planner 执行闭环（Gazebo 仿真，不经 ROS /cmd_vel）."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gazebo.bridge.scan_planner import run_scan_planner  # noqa: E402
from gazebo.bridge.uplink_bridge import run_gazebo_scenario  # noqa: E402
from sim.directive_sink import DirectiveSink  # noqa: E402


def _latest_directive(sink: DirectiveSink) -> Optional[dict[str, Any]]:
    recs = sink.records()
    return recs[-1].payload if recs else None


def main() -> int:
    p = argparse.ArgumentParser(description="Gazebo: VLN directive → scan-planner execute")
    p.add_argument("--scenario", type=Path, default=ROOT / "sim/scenarios/streamvln_kitchen.json")
    p.add_argument("--edge-host", default="127.0.0.1")
    p.add_argument("--subgraph-port", type=int, default=9877)
    p.add_argument("--rgb-port", type=int, default=9878)
    p.add_argument("--directive-port", type=int, default=9879)
    p.add_argument("--model", default="go2")
    p.add_argument("--nav-duration-s", type=float, default=12.0)
    p.add_argument(
        "--frontier-source",
        choices=("scenario", "scan", "hybrid"),
        default="scan",
        help="frontier 表来源（scan=LiDAR 扇区，对齐 BT-scan-planner）",
    )
    p.add_argument("--no-vln-premove", action="store_true", help="跳过 VLN action_bias 粗对齐")
    p.add_argument("--uplink-only", action="store_true")
    p.add_argument("--lidar-wait-s", type=float, default=3.0)
    args = p.parse_args()

    if args.frontier_source in ("scan", "hybrid") and args.lidar_wait_s > 0:
        print(f"[nav] 等待 LiDAR 就绪 ({args.lidar_wait_s}s)", flush=True)
        time.sleep(args.lidar_wait_s)

    sink = DirectiveSink(host=args.edge_host, port=args.directive_port)
    sink.start()

    run_gazebo_scenario(
        args.scenario,
        edge_host=args.edge_host,
        subgraph_port=args.subgraph_port,
        rgb_port=args.rgb_port,
        connect_timeout=5.0,
        mode="live",
        model_name=args.model,
        frontier_source=args.frontier_source,
    )

    if args.uplink_only:
        print(json.dumps({"uplink": "done"}, ensure_ascii=False))
        return 0

    if not sink.wait_count(1, timeout_s=12.0):
        print("[nav] WARN: 未收到 directive", flush=True)
        return 1

    directive = _latest_directive(sink)
    if not directive:
        print("[nav] WARN: directive 为空", flush=True)
        return 1

    print(
        f"[nav] VLN directive frontiers={directive.get('candidate_frontier_ids')} "
        f"action_bias={((directive.get('action_bias') or {}).get('actions'))}",
        flush=True,
    )

    result = run_scan_planner(
        directive,
        scenario_path=args.scenario,
        model_name=args.model,
        nav_duration_s=args.nav_duration_s,
        use_vln_premove=not args.no_vln_premove,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
