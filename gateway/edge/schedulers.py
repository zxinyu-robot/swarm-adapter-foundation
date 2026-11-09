"""边侧 / 仿真共用调度器（CPU，无 GPU）."""
from __future__ import annotations

from typing import Any, Optional

from edge.multimodal_layers import AlignedBundle, LayerId, SCHEDULER_REQUIRED_LAYERS


def pick_geom_baseline(subgraph: dict[str, Any]) -> str:
    frontiers = subgraph.get("frontiers") or []
    if not frontiers:
        return "bt_next_subgoal"
    best = max(frontiers, key=lambda f: float(f.get("geom_score", 0.0)))
    return str(best.get("frontier_id", "bt_next_subgoal"))


def pick_mock_style(subgraph: dict[str, Any]) -> str:
    frontiers = subgraph.get("frontiers") or []
    ids = [str(f["frontier_id"]) for f in frontiers if f.get("frontier_id")]
    if not ids:
        return "bt_next_subgoal"
    return ids[0]


def pick_layer_fusion_stub(bundle: AlignedBundle) -> str:
    """L0+L1+L2 分层融合 stub：vision rgb_tag + task goal 匹配 frontier_id."""
    if not bundle.ready_for("layer_fusion_stub"):
        return pick_geom_baseline(bundle.structure)

    goal = (bundle.task.goal_room_type if bundle.task else "") or ""
    rgb_tag = str((bundle.vision_meta or {}).get("rgb_tag", ""))

    for fr in bundle.structure.get("frontiers") or []:
        fid = str(fr.get("frontier_id", "")).lower()
        if goal and goal in fid:
            return str(fr["frontier_id"])

    if "kitchen" in rgb_tag.lower():
        for fr in bundle.structure.get("frontiers") or []:
            if "kitchen" in str(fr.get("frontier_id", "")).lower():
                return str(fr["frontier_id"])

    return pick_geom_baseline(bundle.structure)


def pick_frontier(
    scheduler: str,
    subgraph: dict[str, Any],
    bundle: Optional[AlignedBundle],
) -> str:
    if scheduler == "geom_baseline":
        return pick_geom_baseline(subgraph)
    if scheduler == "layer_fusion_stub":
        if bundle is not None:
            return pick_layer_fusion_stub(bundle)
        return pick_geom_baseline(subgraph)
    return pick_mock_style(subgraph)


def scheduler_required_layers(scheduler: str) -> tuple[LayerId, ...]:
    return SCHEDULER_REQUIRED_LAYERS.get(scheduler, (LayerId.STRUCTURE,))


def layers_aligned(bundle: Optional[AlignedBundle], required: tuple[LayerId, ...]) -> bool:
    if bundle is None:
        return False
    return all(layer in bundle.layers_aligned for layer in required)
