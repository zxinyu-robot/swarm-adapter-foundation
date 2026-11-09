#!/usr/bin/env python3
"""SemanticDirective → TaskDirective 映射，以及与 C++ 参考接收器（DirectiveGate）的端到端测试.

运行：python3 tests/test_task_directive.py
端到端部分需要环境变量 SWARM_DIRECTIVE_RECEIVER 指向 swarm_directive_receiver，未设置则跳过。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge.task_directive import (  # noqa: E402
    SCHEMA,
    send_task_directive,
    session_id_to_u32,
    to_task_directive,
)


def _semantic(**overrides):
    base = {
        "schema": "motionslam.semantic_directive.v1",
        "session_id": "demo_live",
        "map_version": 5,
        "issued_at_ns": time.time_ns(),
        "ttl_ms": 30000,
        "target_subgraph_node_id": "node_3",
        "candidate_frontier_ids": ["f_2", "f_1"],
        "confidence": 0.85,
        "natural_language_explanation": "去厨房 {\"quoted\": [1, 2]}",
        "multimodal_layers": {"scheduler": "mock", "layers_aligned": []},
    }
    base.update(overrides)
    return base


def test_session_id_mapping():
    assert session_id_to_u32("7") == 7
    assert session_id_to_u32(7) == 7
    assert session_id_to_u32("demo_live") == zlib.crc32(b"demo_live") & 0xFFFFFFFF
    assert session_id_to_u32(str(2**32)) == zlib.crc32(str(2**32).encode()) & 0xFFFFFFFF


def test_mapping_fields():
    sem = _semantic()
    task = to_task_directive(sem, directive_id=11, robot_id=3, lease_epoch=2)
    assert task["schema"] == SCHEMA
    assert task["directive_id"] == 11 and task["robot_id"] == 3 and task["lease_epoch"] == 2
    assert task["session_id"] == session_id_to_u32("demo_live")
    assert task["map_version"] == 5 and task["ttl_ms"] == 30000
    assert task["issued_at_ns"] == sem["issued_at_ns"]
    assert task["target_node_id"] == "node_3" and task["confidence"] == 0.85
    assert task["semantic"] is sem


def test_target_falls_back_to_first_candidate():
    task = to_task_directive(
        _semantic(target_subgraph_node_id=""), directive_id=1, robot_id=1, lease_epoch=1
    )
    assert task["target_node_id"] == "f_2"


def test_rejects_bad_ids():
    for kwargs in (
        {"directive_id": 0, "robot_id": 1, "lease_epoch": 1},
        {"directive_id": 1, "robot_id": -1, "lease_epoch": 1},
        {"directive_id": 1, "robot_id": 2**32, "lease_epoch": 1},
    ):
        try:
            to_task_directive(_semantic(), **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"accepted {kwargs}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_end_to_end_with_directive_gate():
    binary = os.environ.get("SWARM_DIRECTIVE_RECEIVER")
    if not binary:
        print("skip end-to-end: SWARM_DIRECTIVE_RECEIVER not set")
        return
    port = _free_port()
    proc = subprocess.Popen(
        [binary, "--port", str(port), "--robot-id", "3",
         "--session-id", str(session_id_to_u32("demo_live")),
         "--map-version", "5", "--lease-epoch", "2", "--max-connections", "5"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout is not None
        assert "directive receiver" in proc.stdout.readline()

        def send(directive_id, **overrides):
            task = to_task_directive(
                _semantic(**overrides), directive_id=directive_id, robot_id=3, lease_epoch=2
            )
            return send_task_directive("127.0.0.1", port, task, timeout_s=5.0)

        ok = send(100)
        assert ok["reason"] == "ok" and ok["directive_id"] == 100, ok
        assert ok["executed"] is False and ok["robot_id"] == 3
        assert send(100)["reason"] == "duplicate"
        assert send(101, map_version=4)["reason"] == "map_version_mismatch"
        stale = send(102, issued_at_ns=time.time_ns() - 60 * 10**9)
        assert stale["reason"] == "expired", stale
        task = to_task_directive(_semantic(), directive_id=103, robot_id=3, lease_epoch=9)
        assert send_task_directive("127.0.0.1", port, task)["reason"] == "lease_mismatch"
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
