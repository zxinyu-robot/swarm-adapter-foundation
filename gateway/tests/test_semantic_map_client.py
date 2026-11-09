#!/usr/bin/env python3
"""语义地图客户端测试.

运行：python3 tests/test_semantic_map_client.py

服务端依赖：需要一个运行中的 semantic_tile_service。本测试**自带
一个假服务端**（用 socket 起在随机端口），因此无需编译 C++ 也能跑，
也不会占用 9881 影响真实服务。
"""
from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge.semantic_map_client import (  # noqa: E402
    QueryResult,
    SemanticMapClient,
    SemanticMapError,
    SemanticMapVersionMismatch,
    SemanticTag,
    SemanticTile,
    describe_for_prompt,
)

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        FAILURES.append(label)
        print(f"  [FAIL] {label}")


class FakeService:
    """最小假服务端：按 handler 返回一行 JSON."""

    def __init__(self, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.handler = handler
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(4)
        self.port = self._srv.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self._srv.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                buf = b""
                while not self._stop.is_set():
                    try:
                        chunk = conn.recv(4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            req = json.loads(line.decode())
                        except json.JSONDecodeError:
                            resp = {"ok": False, "error": "bad json"}
                        else:
                            resp = self.handler(req)
                        conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode())

    def close(self) -> None:
        self._stop.set()
        try:
            self._srv.close()
        except OSError:
            pass


def _tiles_resp(version: int = 7, count: int = 2) -> dict[str, Any]:
    return {
        "ok": True,
        "map_version": version,
        "count": count,
        "truncated": False,
        "tiles": [
            {"z": 18, "x": 100, "y": 200, "dist_m": 12.5,
             "tags": [{"cat": "kitchen", "conf": 90}, {"cat": "goal_object", "conf": 80}]},
            {"z": 18, "x": 101, "y": 200, "dist_m": 44.0,
             "tags": [{"cat": "door", "conf": 70}]},
        ],
    }


def test_info() -> None:
    svc = FakeService(lambda req: {
        "ok": True, "map_version": 7, "zoom": 18, "tile_count": 4,
        "anchor": {"lat": 30.2741, "lon": 120.1551},
    })
    try:
        with SemanticMapClient(port=svc.port) as c:
            info = c.info()
            check(info.map_version == 7, "info version")
            check(info.zoom == 18, "info zoom")
            check(info.tile_count == 4, "info tile count")
            check(abs(info.anchor_lat - 30.2741) < 1e-9, "info anchor lat")
    finally:
        svc.close()
    print("  [ok] info")


def test_query_parses_tiles() -> None:
    seen: dict[str, Any] = {}

    def handler(req: dict[str, Any]) -> dict[str, Any]:
        seen.update(req)
        return _tiles_resp()

    svc = FakeService(handler)
    try:
        with SemanticMapClient(port=svc.port) as c:
            r = c.query(30.27, 120.15, 500, categories=["kitchen"], min_confidence=60)
            check(len(r) == 2, "two tiles")
            check(r.map_version == 7, "result version")
            check(r.tiles[0].dist_m == 12.5, "dist parsed")
            check(r.tiles[0].best_confidence("kitchen") == 90, "best confidence")
            check(r.tiles[1].best_confidence("kitchen") == 0, "absent category is 0")
            check("door" in r.categories_present(), "categories_present")
            nearest = r.nearest_with("door")
            check(nearest is not None and nearest.x == 101, "nearest_with door")
            check(r.nearest_with("bedroom") is None, "nearest_with missing is None")
        # 请求参数正确透传
        check(seen["cmd"] == "query", "cmd query")
        check(abs(seen["lat"] - 30.27) < 1e-9, "lat passed")
        check(abs(seen["radius_m"] - 500.0) < 1e-9, "radius passed")
        check(seen["categories"] == ["kitchen"], "categories passed")
        check(seen["min_confidence"] == 60, "min_confidence passed")
    finally:
        svc.close()
    print("  [ok] query parses tiles")


def test_version_mismatch_raises() -> None:
    """版本不一致必须显式抛错 —— 静默接受会污染蒸馏样本."""
    svc = FakeService(lambda req: _tiles_resp(version=45))
    try:
        with SemanticMapClient(port=svc.port, expected_version=42) as c:
            try:
                c.query(30.27, 120.15)
                check(False, "mismatch should raise")
            except SemanticMapVersionMismatch as exc:
                check(exc.expected == 42 and exc.actual == 45, "mismatch details")
    finally:
        svc.close()
    print("  [ok] version mismatch raises")


def test_version_ok_when_unset() -> None:
    svc = FakeService(lambda req: _tiles_resp(version=45))
    try:
        with SemanticMapClient(port=svc.port) as c:
            r = c.query(30.27, 120.15)
            check(r.map_version == 45, "no expected_version means no check")
    finally:
        svc.close()
    print("  [ok] no expected version = no check")


def test_service_error_raises() -> None:
    svc = FakeService(lambda req: {"ok": False, "error": "unknown cmd"})
    try:
        with SemanticMapClient(port=svc.port) as c:
            try:
                c.info()
                check(False, "service error should raise")
            except SemanticMapError as exc:
                check("unknown cmd" in str(exc), "error message surfaced")
    finally:
        svc.close()
    print("  [ok] service error raises")


def test_not_connected_raises() -> None:
    c = SemanticMapClient(port=1)
    check(c.connected is False, "not connected")
    try:
        c.info()
        check(False, "should raise when not connected")
    except SemanticMapError:
        pass
    print("  [ok] not connected raises")


def test_truncated_flag() -> None:
    resp = _tiles_resp()
    resp["truncated"] = True
    svc = FakeService(lambda req: resp)
    try:
        with SemanticMapClient(port=svc.port) as c:
            r = c.query(30.27, 120.15)
            check(r.truncated is True, "truncated flag propagated")
    finally:
        svc.close()
    print("  [ok] truncated flag")


def test_describe_for_prompt() -> None:
    empty = describe_for_prompt(QueryResult(map_version=7, tiles=[]))
    check("未标注" in empty, "empty description")

    tiles = [
        SemanticTile(18, 1, 2, (SemanticTag("kitchen", 90),), 12.0),
        SemanticTile(18, 1, 3, (SemanticTag("door", 70),), 40.0),
    ]
    text = describe_for_prompt(QueryResult(map_version=7, tiles=tiles))
    check("kitchen(90)" in text, "category with confidence")
    check("12m" in text, "distance rendered")
    check("v7" in text, "version mentioned")

    # limit 生效并标注截断
    many = [SemanticTile(18, i, 0, (), float(i)) for i in range(12)]
    truncated_text = describe_for_prompt(QueryResult(map_version=7, tiles=many), limit=3)
    check("已截断" in truncated_text, "truncation noted")
    print("  [ok] describe for prompt")


def main() -> int:
    print("== semantic map client tests ==")
    test_info()
    test_query_parses_tiles()
    test_version_mismatch_raises()
    test_version_ok_when_unset()
    test_service_error_raises()
    test_not_connected_raises()
    test_truncated_flag()
    test_describe_for_prompt()

    if FAILURES:
        print(f"== {len(FAILURES)} failure(s) ==")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("== all passed ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
