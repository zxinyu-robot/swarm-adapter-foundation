"""由 LiDAR 扫描推导 corridor frontiers（Super-LIO 替身，v1 扇区法）."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

from gazebo.bridge.lidar_reader import LidarScan, read_lidar, sector_mean_range

ROOT = Path(__file__).resolve().parents[2]

# corridor 三岔：相对机器人朝向的扇区中心（rad）
SECTORS = {
    "fr_kitchen": math.pi / 2,   # +Y
    "fr_hall": 0.0,              # +X
    "fr_bedroom": math.pi,       # -X
}


def frontiers_from_scan(
    scan: LidarScan,
    robot_pose: dict[str, float],
    *,
    scenario_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """开放距离越大 geom_score 越高."""
    positions = _load_positions(scenario_path)
    scored: list[tuple[str, float]] = []
    for fid, center in SECTORS.items():
        mean_r = sector_mean_range(scan, center)
        scored.append((fid, mean_r))

    max_r = max(r for _, r in scored) or 1.0
    frontiers: list[dict[str, Any]] = []
    for fid, mean_r in scored:
        pos = positions.get(fid, {"x": 0, "y": 0, "z": 0})
        score = round(0.55 + 0.4 * (mean_r / max_r), 3)
        frontiers.append(
            {
                "frontier_id": fid,
                "position": pos,
                "geom_score": score,
                "scan_open_m": round(mean_r, 3),
            }
        )
    return frontiers


def _load_positions(scenario_path: Optional[Path]) -> dict[str, dict[str, float]]:
    path = scenario_path or (ROOT / "sim/scenarios/corridor_3frontiers.json")
    scenario = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, float]] = {}
    for step in scenario.get("steps", []):
        for fr in step.get("frontiers", []):
            fid = str(fr["frontier_id"])
            p = fr.get("position", {})
            out[fid] = {"x": float(p["x"]), "y": float(p["y"]), "z": float(p.get("z", 0))}
    return out


def try_scan_frontiers(
    robot_pose: dict[str, float],
    *,
    topic: str = "/lidar",
    scenario_path: Optional[Path] = None,
) -> Optional[list[dict[str, Any]]]:
    scan = read_lidar(topic)
    if scan is None:
        return None
    return frontiers_from_scan(scan, robot_pose, scenario_path=scenario_path)
