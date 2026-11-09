"""Qwen-VL prompt 构造与 JSON 响应解析."""
from __future__ import annotations

import json
import re
from typing import Any

VALID_BIASES = frozenset(
    {
        "BIAS_TOWARD_SUBGRAPH_NODE",
        "BIAS_AWAY_FROM_VISITED",
        "BIAS_INTO_OPEN_SPACE",
        "BIAS_STOP_AND_CONFIRM",
        "BIAS_NONE",
    }
)


def build_frontier_context(subgraph: dict[str, Any]) -> str:
    lines = ["## 当前稀疏子图 frontier 候选（只能从中选择）"]
    nodes = subgraph.get("nodes") or []
    if nodes:
        lines.append(f"robot_nodes: {json.dumps(nodes[:8], ensure_ascii=False)}")
    for fr in subgraph.get("frontiers") or []:
        fid = fr.get("frontier_id", "")
        pos = fr.get("position", {})
        geom = fr.get("geom_score", 0)
        node = fr.get("attached_node_id", fr.get("node_id", ""))
        lines.append(
            f"- frontier_id={fid!r} geom_score={geom} position={pos} attached_node={node!r}"
        )
    if len(lines) == 1:
        lines.append("- （无 frontier，使用 bt_next_subgoal）")
    return "\n".join(lines)


def build_user_prompt(*, instruction: str, subgraph: dict[str, Any]) -> str:
    ctx = build_frontier_context(subgraph)
    return f"""你是四足机器人 Go2 的边侧语义调度器。根据 RGB 关键帧、稀疏子图与任务指令，输出探索 frontier 排序。

任务指令：{instruction}

{ctx}

请严格输出一个 JSON 对象（不要 markdown 代码块），字段：
{{
  "candidate_frontier_ids": ["按语义优先级排序的 frontier_id 列表"],
  "target_subgraph_node_id": "与首选 frontier 关联的 node_id，无则空字符串",
  "exploration_bias": "BIAS_TOWARD_SUBGRAPH_NODE|BIAS_AWAY_FROM_VISITED|BIAS_INTO_OPEN_SPACE|BIAS_STOP_AND_CONFIRM|BIAS_NONE",
  "confidence": 0.0到1.0,
  "room_found": true或false,
  "found_room_type": "若 room_found 则为房间类型否则空字符串",
  "natural_language_explanation": "简短中文理由"
}}

规则：
1. candidate_frontier_ids 必须来自上述 frontier 列表；若无 frontier 则 ["bt_next_subgoal"]
2. 不要编造不存在的 frontier_id
3. 仅输出 JSON"""


def parse_model_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)


def sanitize_inference(
    parsed: dict[str, Any],
    subgraph: dict[str, Any],
    *,
    fallback_pick: str,
) -> dict[str, Any]:
    known = {
        str(f["frontier_id"])
        for f in (subgraph.get("frontiers") or [])
        if f.get("frontier_id")
    }
    raw_ids = parsed.get("candidate_frontier_ids") or []
    cands: list[str] = []
    for x in raw_ids:
        fid = str(x)
        if fid in known and fid not in cands:
            cands.append(fid)
    if not cands:
        if fallback_pick in known or fallback_pick == "bt_next_subgoal":
            cands = [fallback_pick]
        elif known:
            cands = [next(iter(known))]
        else:
            cands = ["bt_next_subgoal"]

    bias = str(parsed.get("exploration_bias", "BIAS_TOWARD_SUBGRAPH_NODE"))
    if bias not in VALID_BIASES:
        bias = "BIAS_TOWARD_SUBGRAPH_NODE"

    try:
        conf = float(parsed.get("confidence", 0.85))
    except (TypeError, ValueError):
        conf = 0.85
    conf = max(0.0, min(1.0, conf))

    room_found = bool(parsed.get("room_found", False))
    found_type = str(parsed.get("found_room_type", "")) if room_found else ""

    target_node = str(parsed.get("target_subgraph_node_id", ""))
    nodes = subgraph.get("nodes") or []
    if not target_node and nodes:
        target_node = str(nodes[0].get("node_id", ""))

    explanation = str(parsed.get("natural_language_explanation", "")).strip()
    if not explanation:
        explanation = f"qwen_vl pick={cands[0]}"

    return {
        "candidate_frontier_ids": cands,
        "target_subgraph_node_id": target_node,
        "exploration_bias": bias,
        "confidence": conf,
        "room_found": room_found,
        "found_room_type": found_type,
        "natural_language_explanation": explanation,
    }
