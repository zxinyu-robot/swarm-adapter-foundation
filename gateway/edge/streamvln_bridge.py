"""StreamVLN 动作序列 → SemanticDirective（v1 不直控 /cmd_vel，仅 action_bias + frontier 软偏置）."""
from __future__ import annotations

from typing import Any, Optional

from edge.multimodal_layers import AlignedBundle
from edge.schedulers import pick_frontier, pick_layer_fusion_stub
from edge.streamvln_client import ACTION_TURN_LEFT


def actions_to_frontier_hint(
    actions: list[int],
    subgraph: dict[str, Any],
    bundle: Optional[AlignedBundle],
) -> str:
    """结合官方离散动作 + L0 子图，给出 frontier 首选（仿真/联调用）."""
    if bundle is not None and bundle.ready_for("layer_fusion_stub"):
        return pick_layer_fusion_stub(bundle)

    goal = ""
    if bundle and bundle.task:
        goal = (bundle.task.goal_room_type or bundle.task.instruction or "").lower()

    if goal and "kitchen" in goal and ACTION_TURN_LEFT in actions:
        for fr in subgraph.get("frontiers") or []:
            fid = str(fr.get("frontier_id", "")).lower()
            if "kitchen" in fid:
                return str(fr["frontier_id"])

    if subgraph.get("frontiers"):
        return pick_frontier("geom_baseline", subgraph, bundle)
    return "bt_next_subgoal"


def build_action_bias(actions: list[int], llm_output: str) -> dict[str, Any]:
    return {
        "source": "streamvln",
        "schema": "motionslam.streamvln_action.v1",
        "actions": actions,
        "action_names": [_action_name(a) for a in actions],
        "llm_output": llm_output,
        "note": "v1: BT 消费 bias，不直连 sport API（对齐官方 go2 支路与 v1 双路方案）",
    }


def _action_name(code: int) -> str:
    return {0: "STOP", 1: "FORWARD", 2: "TURN_LEFT", 3: "TURN_RIGHT"}.get(code, "UNKNOWN")
