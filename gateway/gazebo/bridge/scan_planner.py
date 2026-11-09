"""BT-scan-planner 仿真替身：LiDAR frontier 几何分 + SemanticDirective 语义偏置 → 执行."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from gazebo.bridge.frontier_targets import compute_planar_velocity, load_frontier_positions
from gazebo.bridge.pose_reader import read_pose
from gazebo.bridge.scan_frontiers import try_scan_frontiers
from gazebo.bridge.velocity_driver import publish_velocity, stop
from edge.streamvln_client import ACTION_FORWARD, ACTION_STOP, ACTION_TURN_LEFT, ACTION_TURN_RIGHT

# 对齐 v1-双路上行语义调度方案 §6 默认权重
W_GEOM = 0.6
W_GRAPH = 0.3
W_CONF = 0.1


@dataclass
class FrontierPlan:
    frontier_id: str
    score: float
    geom_score: float
    graph_bias: float
    position: dict[str, float]
    source: str  # lidar_scan | scenario_fallback


def graph_bias(frontier_id: str, directive: dict[str, Any]) -> float:
    """语义软偏置：candidate 内 0.5，target 节点 1.0，否则 0."""
    fid = str(frontier_id)
    target_node = str(directive.get("target_subgraph_node_id") or "")
    attached = str(directive.get("attached_node_id") or "")
    if target_node and attached and attached == target_node:
        return 1.0
    cands = [str(x) for x in (directive.get("candidate_frontier_ids") or [])]
    if fid in cands:
        return 0.5 if cands[0] != fid else 0.65
    return 0.0


def frontier_score(
    frontier: dict[str, Any],
    directive: dict[str, Any],
    *,
    w_geom: float = W_GEOM,
    w_graph: float = W_GRAPH,
    w_conf: float = W_CONF,
) -> float:
    fid = str(frontier.get("frontier_id", ""))
    geom = float(frontier.get("geom_score", 0.0))
    gb = graph_bias(fid, directive)
    conf = float(directive.get("subgraph_confidence") or 1.0)
    return w_geom * geom + w_graph * gb + w_conf * conf


def resolve_frontier_plan(
    directive: dict[str, Any],
    live_frontiers: list[dict[str, Any]],
    *,
    fr_source: str,
) -> Optional[FrontierPlan]:
    """VLN 决策 top-1 frontier；scan 提供 LiDAR 几何表与目标坐标."""
    cands = [str(x) for x in (directive.get("candidate_frontier_ids") or [])]
    by_id = {str(f.get("frontier_id", "")): f for f in live_frontiers}

    if cands:
        top = cands[0]
        if top in by_id:
            fr = by_id[top]
            pos = fr.get("position") or {}
            return FrontierPlan(
                frontier_id=top,
                score=frontier_score(fr, directive),
                geom_score=float(fr.get("geom_score", 0.0)),
                graph_bias=graph_bias(top, directive),
                position={
                    "x": float(pos.get("x", 0)),
                    "y": float(pos.get("y", 0)),
                    "z": float(pos.get("z", 0)),
                },
                source=f"vln_decision+{fr_source}",
            )

    plan = pick_frontier(directive, live_frontiers)
    if plan is not None:
        plan.source = f"scan_fallback+{fr_source}"
    return plan


def pick_frontier(
    directive: dict[str, Any],
    live_frontiers: list[dict[str, Any]],
) -> Optional[FrontierPlan]:
    """无 VLN top-1 时的 fallback：几何 + 语义加权."""
    if not live_frontiers:
        return None

    best: Optional[FrontierPlan] = None
    for fr in live_frontiers:
        fid = str(fr.get("frontier_id", ""))
        if not fid:
            continue
        score = frontier_score(fr, directive)
        pos = fr.get("position") or {}
        plan = FrontierPlan(
            frontier_id=fid,
            score=round(score, 4),
            geom_score=float(fr.get("geom_score", 0.0)),
            graph_bias=graph_bias(fid, directive),
            position={
                "x": float(pos.get("x", 0)),
                "y": float(pos.get("y", 0)),
                "z": float(pos.get("z", 0)),
            },
            source="lidar_scan",
        )
        if best is None or plan.score > best.score:
            best = plan
    return best


def refresh_scan_frontiers(
    robot_pose: dict[str, float],
    *,
    scenario_path: Path,
) -> tuple[list[dict[str, Any]], str]:
    """刷新 LiDAR frontier 表；失败时回退 scenario 模板."""
    live = try_scan_frontiers(robot_pose, scenario_path=scenario_path)
    if live is not None:
        return live, "lidar_scan"
    positions = load_frontier_positions(scenario_path)
    fallback: list[dict[str, Any]] = []
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    for step in scenario.get("steps", []):
        for fr in step.get("frontiers", []):
            fid = str(fr["frontier_id"])
            fallback.append(
                {
                    "frontier_id": fid,
                    "position": positions.get(fid, fr.get("position", {})),
                    "geom_score": float(fr.get("geom_score", 0.5)),
                }
            )
        break
    return fallback, "scenario_fallback"


def execute_vln_action(
    action: int,
    *,
    model_name: str = "go2",
    rate_hz: float = 10.0,
) -> None:
    """执行 StreamVLN 离散动作一步（仿真运动学，非 sport API）."""
    period = 1.0 / max(1.0, rate_hz)
    if action == ACTION_FORWARD:
        for _ in range(8):
            publish_velocity(0.25, 0.0, model_name=model_name, dt_s=period)
            time.sleep(period)
    elif action == ACTION_TURN_LEFT:
        for _ in range(6):
            publish_velocity(0.0, 0.6, model_name=model_name, dt_s=period)
            time.sleep(period)
    elif action == ACTION_TURN_RIGHT:
        for _ in range(6):
            publish_velocity(0.0, -0.6, model_name=model_name, dt_s=period)
            time.sleep(period)
    elif action == ACTION_STOP:
        stop(model_name)


def execute_action_bias(
    directive: dict[str, Any],
    *,
    model_name: str = "go2",
    rate_hz: float = 10.0,
) -> list[int]:
    """VLN action_bias 微动作序列（边侧决策，端侧执行第一步粗对齐）."""
    bias = directive.get("action_bias") or {}
    actions = [int(x) for x in (bias.get("actions") or [])]
    if not actions:
        return []
    # 仅执行第一个非 STOP 动作为朝向粗调；完整 batch 留给真机 PID
    for act in actions:
        if act == ACTION_STOP:
            stop(model_name)
            break
        execute_vln_action(act, model_name=model_name, rate_hz=rate_hz)
        break
    return actions


def navigate_to_frontier(
    plan: FrontierPlan,
    *,
    model_name: str = "go2",
    duration_s: float = 12.0,
    rate_hz: float = 10.0,
) -> dict[str, Any]:
    """scan-planner 局部执行：线速度 + 角速度 → frontier 目标."""
    period = 1.0 / max(1.0, rate_hz)
    t_end = time.monotonic() + duration_s
    tgt = plan.position
    min_dist = 999.0
    last_pose = None

    while time.monotonic() < t_end:
        pose = read_pose(model_name)
        if pose is None:
            time.sleep(period)
            continue
        last_pose = pose.as_dict()
        lin, ang, dist = compute_planar_velocity(
            pose.x, pose.y, pose.yaw_deg, tgt["x"], tgt["y"],
            max_linear=0.45,
        )
        min_dist = min(min_dist, dist)
        publish_velocity(lin, ang, model_name=model_name, dt_s=period)
        if dist < 0.8:
            break
        time.sleep(period)

    stop(model_name)
    return {
        "ok": min_dist < 1.2,
        "frontier_id": plan.frontier_id,
        "planner_score": plan.score,
        "geom_score": plan.geom_score,
        "graph_bias": plan.graph_bias,
        "target": tgt,
        "min_dist_m": round(min_dist, 3),
        "final_pose": last_pose,
        "frontier_source": plan.source,
    }


def run_scan_planner(
    directive: dict[str, Any],
    *,
    scenario_path: Path,
    model_name: str = "go2",
    nav_duration_s: float = 12.0,
    use_vln_premove: bool = True,
) -> dict[str, Any]:
    """VLN 决策（directive）+ scan-planner 执行（LiDAR frontier + 局部导航）."""
    pose = read_pose(model_name)
    robot_pose = pose.as_dict() if pose else {"x": 0.0, "y": 0.0, "yaw_deg": 0.0}

    vln_actions: list[int] = []
    if use_vln_premove and directive.get("action_bias"):
        vln_actions = execute_action_bias(directive, model_name=model_name)
        pose = read_pose(model_name)
        if pose:
            robot_pose = pose.as_dict()

    live_fr, fr_source = refresh_scan_frontiers(robot_pose, scenario_path=scenario_path)
    plan = resolve_frontier_plan(directive, live_fr, fr_source=fr_source)
    if plan is None:
        return {"ok": False, "reason": "no_frontier", "frontier_source": fr_source}

    nav = navigate_to_frontier(
        plan,
        model_name=model_name,
        duration_s=nav_duration_s,
    )
    return {
        "ok": nav.get("ok", False),
        "vln_actions": vln_actions,
        "directive_candidates": directive.get("candidate_frontier_ids"),
        "selected_frontier": plan.frontier_id,
        "planner_mode": plan.source,
        "nav": nav,
    }
