"""根据 Gazebo 位姿 + corridor 场景模板生成 frontiers / nodes."""
from __future__ import annotations

import copy
import math
from typing import Any


def _dist(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))


def geom_score_from_pose(fr_pos: dict[str, float], robot: dict[str, float], *, base: float = 0.95) -> float:
    """距离越近分越高；走廊场景 hall 先天几何占优时保留 base 偏移."""
    d = _dist(fr_pos, robot)
    return round(max(0.05, base - 0.06 * d), 3)


def build_step_from_template(
    step_tpl: dict[str, Any],
    robot_pose: dict[str, float],
    *,
    version: int,
) -> dict[str, Any]:
    step = copy.deepcopy(step_tpl)
    step["version"] = version
    step["robot_pose"] = dict(robot_pose)

    base_scores = {str(f["frontier_id"]): float(f.get("geom_score", 0.5)) for f in step_tpl.get("frontiers", [])}
    max_base = max(base_scores.values()) if base_scores else 0.95

    frontiers: list[dict[str, Any]] = []
    for fr in step_tpl.get("frontiers", []):
        pos = dict(fr.get("position", {}))
        fid = str(fr.get("frontier_id", ""))
        base = float(fr.get("geom_score", 0.5))
        # 保留 hall 相对优势：按模板比例缩放距离分
        scale = base / max_base if max_base > 0 else 1.0
        score = geom_score_from_pose(pos, robot_pose, base=0.95 * scale)
        frontiers.append(
            {
                "frontier_id": fid,
                "position": pos,
                "geom_score": score,
            }
        )
    step["frontiers"] = frontiers
    return step
