#!/usr/bin/env python3
"""边侧 MVPI1 mock planner v0（P2-6～8 子集）。

监听 GO2 上行 9877 subgraph / 9880 feedback；按 query 下发 SEARCH；
持续刷新 SemanticDirective 驱动 frontier 探索；仅在 mock 检测到目标时下发 NAV。

仅输出 SemanticDirective / ActionGroup → GO2 :9879，不下发 motion。
"""
from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
try:
    from mvpi1_payloads import (  # noqa: E402
        build_action_group,
        build_semantic_directive,
        new_command_id,
        send_json_line,
    )
except ImportError:
    ROOT = str(_SCRIPT_DIR.parents[2])
    sys.path.insert(0, ROOT)
    from scripts.offline.mvpi1_payloads import (  # noqa: E402
        build_action_group,
        build_semantic_directive,
        new_command_id,
        send_json_line,
    )


@dataclass
class PlannerState:
    phase: str = "idle"  # idle | search | found
    query: str = ""
    search_command_id: str = ""
    uplink_count: int = 0
    frontier_reached_count: int = 0
    turn_done: bool = False
    last_directive_uplink: int = 0
    last_subgraph: dict[str, Any] = field(default_factory=dict)
    last_robot_xy: tuple[float, float] = (0.0, 0.0)
    last_robot_yaw: float = 0.0
    last_frontier_ids: list[str] = field(default_factory=list)


def _normalize_angle(rad: float) -> float:
    while rad > math.pi:
        rad -= 2 * math.pi
    while rad < -math.pi:
        rad += 2 * math.pi
    return rad


def _frontier_xy(f: dict[str, Any]) -> Optional[tuple[float, float]]:
    if not isinstance(f, dict):
        return None
    try:
        return float(f["x"]), float(f["y"])
    except (KeyError, TypeError, ValueError):
        return None


def pick_frontier_ids(
    frontiers: list[dict[str, Any]],
    *,
    robot_xy: tuple[float, float],
    robot_yaw: float,
    mode: str = "all",
    limit: int = 3,
) -> list[str]:
    """mode=all 取 geom 分最高；mode=rear 优先身后 frontier（≈先调头探索）。"""
    scored: list[tuple[float, str]] = []
    rx, ry = robot_xy
    for item in frontiers:
        if not isinstance(item, dict):
            continue
        fid = item.get("frontier_id")
        xy = _frontier_xy(item)
        if not fid or xy is None:
            continue
        fx, fy = xy
        if mode == "rear":
            angle_to = math.atan2(fy - ry, fx - rx)
            diff = abs(_normalize_angle(angle_to - robot_yaw))
            rank = -abs(diff - math.pi)  # diff≈π → 身后
        else:
            try:
                rank = float(item.get("geom_score", 0.0))
            except (TypeError, ValueError):
                rank = 0.0
        scored.append((rank, str(fid)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [fid for _, fid in scored[:limit]]


class EdgeMvpi1Planner:
    def __init__(
        self,
        *,
        go2_host: str,
        go2_port: int,
        session_id: str,
        directive_refresh_uplinks: int,
        mock_found_after_reached: int,
        nav_offset_m: float,
        turn_first: bool,
        lock: threading.Lock,
    ) -> None:
        self._go2_host = go2_host
        self._go2_port = go2_port
        self._session_id = session_id
        self._directive_refresh = max(1, directive_refresh_uplinks)
        self._mock_found_after = mock_found_after_reached
        self._nav_offset_m = nav_offset_m
        self._turn_first = turn_first
        self._lock = lock
        self.state = PlannerState()

    def start_search(self, query: str) -> None:
        with self._lock:
            self.state = PlannerState(phase="search", query=query)
            self.state.search_command_id = new_command_id("search")
            self._dispatch_search_locked(rearm=True)

    def _robot_from_subgraph(self, obj: dict[str, Any]) -> tuple[float, float, float]:
        robot = obj.get("robot") or obj.get("robot_pose") or {}
        if isinstance(robot, dict):
            x = float(robot.get("x", 0.0))
            y = float(robot.get("y", 0.0))
            yaw_deg = float(robot.get("yaw_deg", 0.0))
            return x, y, math.radians(yaw_deg)
        nodes = obj.get("nodes") or []
        for node in nodes:
            if isinstance(node, dict) and node.get("node_id") == "robot":
                return float(node.get("x", 0.0)), float(node.get("y", 0.0)), 0.0
        return self.state.last_robot_xy[0], self.state.last_robot_xy[1], self.state.last_robot_yaw

    def _frontier_bias_mode(self) -> str:
        if self._turn_first and not self.state.turn_done:
            return "rear"
        return "all"

    def _pick_frontiers(self, raw: list[Any]) -> list[str]:
        items = [x for x in raw if isinstance(x, dict)]
        return pick_frontier_ids(
            items,
            robot_xy=self.state.last_robot_xy,
            robot_yaw=self.state.last_robot_yaw,
            mode=self._frontier_bias_mode(),
            limit=3,
        )

    def _send_directive(self, frontier_ids: list[str], *, search_mode: str = "explore") -> None:
        directive = build_semantic_directive(
            query=self.state.query,
            session_id=self._session_id,
            map_version=int(self.state.last_subgraph.get("version") or 0),
            context_generation=0,
            search_mode=search_mode,
            candidate_frontier_ids=frontier_ids,
            confidence=0.55 if search_mode == "explore" else 0.91,
            command_id=self.state.search_command_id,
        )
        send_json_line(self._go2_host, self._go2_port, directive)

    def _send_search_pair(self, frontier_ids: list[str]) -> None:
        """成对下发 action_group + directive（refresh 也带 SEARCH stage）。"""
        map_version = int(self.state.last_subgraph.get("version") or 0)
        action_group = build_action_group(
            query=self.state.query,
            session_id=self._session_id,
            map_version=map_version,
            context_generation=0,
            include_search=True,
            include_nav=False,
            command_id=self.state.search_command_id,
        )
        send_json_line(self._go2_host, self._go2_port, action_group)
        self._send_directive(frontier_ids, search_mode="explore")

    def _dispatch_search_locked(self, *, rearm: bool = False) -> None:
        raw = self.state.last_subgraph.get("frontiers") or []
        frontier_ids = self._pick_frontiers(raw)
        mode = self._frontier_bias_mode()

        self._send_search_pair(frontier_ids)
        self.state.last_directive_uplink = self.state.uplink_count
        tag = "SEARCH pair" if rearm else "SEARCH pair (refresh)"
        print(
            f"[planner] {tag} command_id={self.state.search_command_id} "
            f"bias={mode} frontiers={frontier_ids}",
            flush=True,
        )

    def _maybe_refresh_directive_locked(self, reason: str) -> None:
        if self.state.phase != "search":
            return
        since = self.state.uplink_count - self.state.last_directive_uplink
        if since < self._directive_refresh and reason != "turn_handoff":
            return
        if self._turn_first and not self.state.turn_done and reason != "initial":
            self.state.turn_done = True
            print("[planner] turn-first done → switch to all-frontier bias", flush=True)
        self._dispatch_search_locked(rearm=False)

    def on_subgraph(self, obj: dict[str, Any]) -> None:
        with self._lock:
            self.state.last_subgraph = obj
            rx, ry, yaw = self._robot_from_subgraph(obj)
            self.state.last_robot_xy = (rx, ry)
            self.state.last_robot_yaw = yaw
            raw = obj.get("frontiers") or []
            self.state.last_frontier_ids = [
                str(item.get("frontier_id"))
                for item in raw
                if isinstance(item, dict) and item.get("frontier_id")
            ]
            if self.state.phase != "search":
                return
            self.state.uplink_count += 1
            print(
                f"[planner] subgraph v={obj.get('version')} "
                f"frontiers={len(raw)} uplink#{self.state.uplink_count} "
                f"bias={self._frontier_bias_mode()}",
                flush=True,
            )
            self._maybe_refresh_directive_locked("subgraph")

    def on_feedback(self, obj: dict[str, Any]) -> None:
        event = str(obj.get("event", ""))
        with self._lock:
            if event == "object_found":
                self.state.phase = "found"
                print(f"[planner] TARGET FOUND event={event}", flush=True)
                return

            if event == "search_exhausted":
                print(f"[planner] search_exhausted → re-arm SEARCH", flush=True)
                self.state.search_command_id = new_command_id("search")
                self.state.frontier_reached_count = 0
                self.state.turn_done = False
                self.state.phase = "search"
                self._dispatch_search_locked(rearm=True)
                return

            if event == "lifecycle_inactive":
                print("[planner] lifecycle_inactive — 等待狗端 re-activate", flush=True)
                return

            if self.state.phase != "search":
                return

            if event == "search_frontier_reached":
                self.state.frontier_reached_count += 1
                print(
                    f"[planner] feedback {event} count={self.state.frontier_reached_count}",
                    flush=True,
                )
                if self._turn_first and not self.state.turn_done:
                    self.state.turn_done = True
                    self._maybe_refresh_directive_locked("turn_handoff")
                else:
                    self._maybe_refresh_directive_locked("frontier_reached")

                if (
                    self._mock_found_after > 0
                    and self.state.frontier_reached_count >= self._mock_found_after
                ):
                    self._dispatch_found_nav_locked(reason="mock_detect")

            elif event == "search_handoff":
                # 旧 planner 曾发 NAV-only 导致 handoff；立即重新 arm SEARCH
                print("[planner] search_handoff detected → re-arm SEARCH", flush=True)
                self.state.search_command_id = new_command_id("search")
                self.state.phase = "search"
                self._dispatch_search_locked(rearm=True)

    def _dispatch_found_nav_locked(self, reason: str) -> None:
        """Mock 检测到目标：下发 NAV 到当前朝向前方（仅 found 时调用）。"""
        if self.state.phase == "found":
            return
        rx, ry = self.state.last_robot_xy
        yaw = self.state.last_robot_yaw
        gx = rx + self._nav_offset_m * math.cos(yaw)
        gy = ry + self._nav_offset_m * math.sin(yaw)
        nav_id = new_command_id("nav")
        self.state.phase = "found"

        nav_directive = build_semantic_directive(
            query=self.state.query,
            session_id=self._session_id,
            map_version=int(self.state.last_subgraph.get("version") or 0),
            context_generation=0,
            search_mode="navigate",
            confidence=0.91,
            command_id=nav_id,
        )
        nav_group = build_action_group(
            query=self.state.query,
            session_id=self._session_id,
            map_version=int(self.state.last_subgraph.get("version") or 0),
            context_generation=0,
            include_search=False,
            include_nav=True,
            nav_x=gx,
            nav_y=gy,
            command_id=nav_id,
        )
        send_json_line(self._go2_host, self._go2_port, nav_directive)
        send_json_line(self._go2_host, self._go2_port, nav_group)
        print(
            f"[planner] FOUND→NAV ({reason}) command_id={nav_id} goal=({gx:.2f},{gy:.2f})",
            flush=True,
        )


def _serve_json_lines(
    name: str,
    host: str,
    port: int,
    on_line: Callable[[dict[str, Any]], None],
) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(4)
    print(f"[{name}] listening {host}:{port}", flush=True)
    while True:
        conn, addr = srv.accept()
        print(f"[{name}] client {addr}", flush=True)
        buf = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    on_line(obj)
        finally:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Edge MVPI1 mock planner v0")
    parser.add_argument("--host", default="0.0.0.0", help="listen host for uplink")
    parser.add_argument("--subgraph-port", type=int, default=9877)
    parser.add_argument("--feedback-port", type=int, default=9880)
    parser.add_argument("--go2-host", default="127.0.0.1", help="GO2 directive_receiver")
    parser.add_argument("--go2-port", type=int, default=9879)
    parser.add_argument("--session-id", default="demo_live")
    parser.add_argument("--query", default="找红色灭火器")
    parser.add_argument(
        "--directive-refresh-uplinks",
        type=int,
        default=2,
        help="每 N 次子图 uplink 刷新 directive（持续探索）",
    )
    parser.add_argument(
        "--mock-found-after-reached",
        type=int,
        default=0,
        help="mock 检测：到达 N 个 frontier 后下发 NAV；0=关闭，持续探索",
    )
    parser.add_argument("--nav-offset-m", type=float, default=2.0)
    parser.add_argument(
        "--turn-first",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="首轮 directive 偏置身后 frontier（≈先调头）",
    )
    parser.add_argument(
        "--start-search",
        action="store_true",
        help="启动后立即向 GO2 下发 SEARCH（需 GO2 栈已 active）",
    )
    # 兼容旧参数名
    parser.add_argument("--redeploy-uplinks", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--redeploy-reached", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    refresh = args.directive_refresh_uplinks
    if args.redeploy_uplinks is not None:
        refresh = args.redeploy_uplinks
    mock_found = args.mock_found_after_reached
    if args.redeploy_reached is not None and mock_found == 0:
        mock_found = 0  # 旧 redeploy-reached 不再触发中途 NAV

    lock = threading.Lock()
    planner = EdgeMvpi1Planner(
        go2_host=args.go2_host,
        go2_port=args.go2_port,
        session_id=args.session_id,
        directive_refresh_uplinks=refresh,
        mock_found_after_reached=mock_found,
        nav_offset_m=args.nav_offset_m,
        turn_first=args.turn_first,
        lock=lock,
    )

    t_sub = threading.Thread(
        target=_serve_json_lines,
        args=("subgraph", args.host, args.subgraph_port, planner.on_subgraph),
        daemon=True,
    )
    t_fb = threading.Thread(
        target=_serve_json_lines,
        args=("feedback", args.host, args.feedback_port, planner.on_feedback),
        daemon=True,
    )
    t_sub.start()
    t_fb.start()

    if args.start_search:
        time.sleep(0.5)
        planner.start_search(args.query)

    print(
        "[planner] ready | continuous search | turn_first="
        f"{args.turn_first} refresh_uplinks={refresh} mock_found={mock_found}",
        flush=True,
    )
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[planner] stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
