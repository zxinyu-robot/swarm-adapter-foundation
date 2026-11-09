"""SemanticDirective v1 → swarm_adapter TaskDirective 线格式（JSONL）。

边侧只给建议：机器人端用 C++ DirectiveGate 准入（身份、重复、过期、租约、地图版本、
本机安全保持），并回一行 ExecutionReport。本模块只用标准库。
"""
from __future__ import annotations

import json
import socket
import zlib
from typing import Any

SCHEMA = "swarm_adapter.task_directive.v1"
REPORT_SCHEMA = "swarm_adapter.execution_report.v1"
_U32 = 2**32


def session_id_to_u32(session_id: str | int) -> int:
    """十进制且小于 2^32 时原样使用，否则取 UTF-8 的 CRC32。机器人端按同一规则配置。"""
    text = str(session_id)
    if text.isdigit() and int(text) < _U32:
        return int(text)
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


def to_task_directive(
    semantic: dict[str, Any],
    *,
    directive_id: int,
    robot_id: int,
    lease_epoch: int,
) -> dict[str, Any]:
    if directive_id <= 0 or not 0 <= robot_id < _U32 or lease_epoch < 0:
        raise ValueError("directive_id > 0, robot_id in u32, lease_epoch >= 0")
    target = semantic.get("target_subgraph_node_id") or ""
    if not target:
        candidates = semantic.get("candidate_frontier_ids") or []
        target = str(candidates[0]) if candidates else ""
    return {
        "schema": SCHEMA,
        "directive_id": int(directive_id),
        "robot_id": int(robot_id),
        "session_id": session_id_to_u32(semantic["session_id"]),
        "map_version": int(semantic["map_version"]),
        "lease_epoch": int(lease_epoch),
        "issued_at_ns": int(semantic["issued_at_ns"]),
        "ttl_ms": int(semantic["ttl_ms"]),
        "target_node_id": str(target),
        "confidence": float(semantic["confidence"]),
        "semantic": semantic,
    }


def send_task_directive(
    host: str, port: int, directive: dict[str, Any], timeout_s: float = 3.0
) -> dict[str, Any]:
    """发送一行 TaskDirective，返回机器人端的 ExecutionReport。"""
    line = json.dumps(directive, ensure_ascii=False) + "\n"
    with socket.create_connection((host, port), timeout=timeout_s) as conn:
        conn.sendall(line.encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
    report = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError(f"unexpected report schema: {report.get('schema')}")
    return report
