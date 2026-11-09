"""frontier_id → 世界坐标（corridor 场景）."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO = ROOT / "sim" / "scenarios" / "corridor_3frontiers.json"


def load_frontier_positions(scenario_path: Path = DEFAULT_SCENARIO) -> dict[str, dict[str, float]]:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, float]] = {}
    for step in scenario.get("steps", []):
        for fr in step.get("frontiers", []):
            fid = str(fr["frontier_id"])
            pos = fr.get("position", {})
            out[fid] = {"x": float(pos["x"]), "y": float(pos["y"]), "z": float(pos.get("z", 0))}
    return out


def compute_planar_velocity(
    pose_x: float,
    pose_y: float,
    yaw_deg: float,
    target_x: float,
    target_y: float,
    *,
    max_linear: float = 0.35,
    max_angular: float = 0.8,
    arrive_m: float = 0.25,
) -> tuple[float, float, float]:
    """返回 (linear_m_s, angular_rad_s, dist_m)."""
    dx = target_x - pose_x
    dy = target_y - pose_y
    dist = math.hypot(dx, dy)
    if dist < arrive_m:
        return 0.0, 0.0, dist

    target_yaw = math.atan2(dy, dx)
    yaw = math.radians(yaw_deg)
    err = (target_yaw - yaw + math.pi) % (2 * math.pi) - math.pi

    angular = max(-max_angular, min(max_angular, 2.0 * err))
    linear = 0.0 if abs(err) > 0.45 else min(max_linear, 0.15 + 0.25 * dist)
    return linear, angular, dist
