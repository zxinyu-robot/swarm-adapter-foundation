"""CPU stub：无 GPU 时用规则模拟 Qwen-VL 输出（对齐 layer_fusion_stub 语义）."""
from __future__ import annotations

from typing import Any

from edge.multimodal_layers import AlignedBundle
from edge.schedulers import pick_geom_baseline, pick_layer_fusion_stub


def stub_infer(
    subgraph: dict[str, Any],
    bundle: AlignedBundle,
    instruction: str,
) -> dict[str, Any]:
    top = pick_layer_fusion_stub(bundle) if bundle.ready_for("layer_fusion_stub") else pick_geom_baseline(subgraph)
    known = [str(f["frontier_id"]) for f in (subgraph.get("frontiers") or []) if f.get("frontier_id")]
    cands = [top] + [x for x in known if x != top]
    if not cands:
        cands = ["bt_next_subgoal"]

    goal = (bundle.task.goal_room_type if bundle.task else "") or ""
    rgb_tag = str((bundle.vision_meta or {}).get("rgb_tag", ""))
    room_found = bool(goal and any(goal.lower() in c.lower() for c in cands[:1]))

    nodes = subgraph.get("nodes") or []
    target_node = str(nodes[0].get("node_id", "")) if nodes else ""

    return {
        "candidate_frontier_ids": cands,
        "target_subgraph_node_id": target_node,
        "exploration_bias": "BIAS_TOWARD_SUBGRAPH_NODE",
        "confidence": 0.75,
        "room_found": room_found,
        "found_room_type": goal if room_found else "",
        "natural_language_explanation": (
            f"[stub] instruction={instruction!r} rgb_tag={rgb_tag!r} pick={top}"
        ),
    }
