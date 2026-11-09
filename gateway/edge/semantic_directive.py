"""SemanticDirective 构建与校验."""
from __future__ import annotations

import time
from typing import Any, Optional

from edge.multimodal_layers import AlignedBundle
from edge.qwen_vl.client import QwenVLInferenceResult
from edge.schedulers import pick_frontier

SCHEMA = "motionslam.semantic_directive.v1"


def build_mock_directive(
    *,
    session_id: str,
    map_version: int,
    subgraph: dict[str, Any],
    instruction: str = "mock_edge_directive",
) -> dict[str, Any]:
    return build_directive(
        session_id=session_id,
        map_version=map_version,
        subgraph=subgraph,
        instruction=instruction,
        scheduler="mock",
        bundle=None,
    )


def build_directive(
    *,
    session_id: str,
    map_version: int,
    subgraph: dict[str, Any],
    instruction: str,
    scheduler: str,
    bundle: Optional[AlignedBundle],
    action_bias: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    frontiers = subgraph.get("frontiers") or []
    nodes = subgraph.get("nodes") or []

    all_ids = [str(f["frontier_id"]) for f in frontiers if f.get("frontier_id")]
    if not all_ids:
        all_ids = ["bt_next_subgoal"]

    top_pick = pick_frontier(scheduler, subgraph, bundle)
    candidate_ids = [top_pick] + [x for x in all_ids if x != top_pick]

    target_node = ""
    if nodes:
        target_node = str(nodes[0].get("node_id", ""))

    layers_meta: dict[str, Any] = {
        "scheduler": scheduler,
        "layers_aligned": [],
        "layers_present": [],
    }
    if bundle is not None:
        layers_meta["layers_aligned"] = [x.value for x in bundle.layers_aligned]
        layers_meta["layers_present"] = [x.value for x in bundle.layers_present]

    out: dict[str, Any] = {
        "schema": SCHEMA,
        "session_id": session_id,
        "map_version": map_version,
        "issued_at_ns": time.time_ns(),
        "ttl_ms": 30000,
        "target_subgraph_node_id": target_node,
        "candidate_frontier_ids": candidate_ids,
        "exploration_bias": "BIAS_TOWARD_SUBGRAPH_NODE",
        "subgraph_confidence": 0.85,
        "confidence": 0.85,
        "instruction": instruction,
        "room_found": False,
        "found_room_type": "",
        "natural_language_explanation": (
            f"{scheduler} pick={top_pick} v={map_version}, {len(nodes)} nodes"
        ),
        "multimodal_layers": layers_meta,
    }
    if action_bias is not None:
        out["action_bias"] = action_bias
    return out


def build_directive_from_qwen_vl(
    *,
    session_id: str,
    map_version: int,
    subgraph: dict[str, Any],
    instruction: str,
    result: QwenVLInferenceResult,
    bundle: Optional[AlignedBundle],
) -> dict[str, Any]:
    """Qwen-VL 推理结果 → SemanticDirective v1."""
    layers_meta: dict[str, Any] = {
        "scheduler": "qwen_vl",
        "inference_source": result.source,
        "layers_aligned": [],
        "layers_present": [],
    }
    if bundle is not None:
        layers_meta["layers_aligned"] = [x.value for x in bundle.layers_aligned]
        layers_meta["layers_present"] = [x.value for x in bundle.layers_present]

    return {
        "schema": SCHEMA,
        "session_id": session_id,
        "map_version": map_version,
        "issued_at_ns": time.time_ns(),
        "ttl_ms": 30000,
        "target_subgraph_node_id": result.target_subgraph_node_id,
        "candidate_frontier_ids": list(result.candidate_frontier_ids),
        "exploration_bias": result.exploration_bias,
        "subgraph_confidence": result.confidence,
        "confidence": result.confidence,
        "instruction": instruction,
        "room_found": result.room_found,
        "found_room_type": result.found_room_type,
        "natural_language_explanation": result.natural_language_explanation,
        "multimodal_layers": layers_meta,
    }


def send_directive(host: str, port: int, payload: dict[str, Any], timeout_s: float = 3.0) -> None:
    import json
    import socket

    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with socket.create_connection((host, port), timeout=timeout_s) as conn:
        conn.sendall(line.encode("utf-8"))
