#!/usr/bin/env python3
"""v1 边侧网关：9877 子图 + 9878 MSRGB → SemanticDirective → :9879."""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from typing import Any, Callable, Optional

from edge.aligner import align_bundle
from edge.rgb_forward import unpack_rgb_forward_frame
from edge.schedulers import scheduler_required_layers
from edge.semantic_directive import build_directive, build_directive_from_qwen_vl, send_directive
from edge.task_directive import send_task_directive, to_task_directive
from edge.store import EdgeStore
from edge.streamvln_bridge import actions_to_frontier_hint, build_action_bias
from edge.streamvln_client import StreamVLNClient
from edge.qwen_vl.client import QwenVLClient


def _serve_json_lines(
    name: str,
    host: str,
    port: int,
    on_line: Callable[[dict[str, Any]], None],
) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    print(f"[{name}] listening on {host}:{port}", flush=True)
    while True:
        conn, addr = srv.accept()
        print(f"[{name}] client {addr}", flush=True)
        peer_buf = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                peer_buf += chunk
                while b"\n" in peer_buf:
                    line, peer_buf = peer_buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError as exc:
                        print(f"[{name}] JSON error: {exc}", flush=True)
                        continue
                    on_line(obj)
        finally:
            conn.close()


def _serve_rgb_binary(host: str, port: int, on_frame: Callable[[dict[str, Any], bytes], None]) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    print(f"[rgb] listening on {host}:{port} (MSRGB)", flush=True)
    count = 0
    while True:
        conn, addr = srv.accept()
        print(f"[rgb] client {addr}", flush=True)
        buf = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    try:
                        meta, payload, consumed = unpack_rgb_forward_frame(buf)
                    except ValueError:
                        break
                    buf = buf[consumed:]
                    count += 1
                    on_frame(meta, payload)
                    if count == 1 or count % 30 == 0:
                        print(
                            f"[rgb][{count}] v={meta.get('subgraph_version')} "
                            f"seq={meta.get('seq')} field={meta.get('stream_field')} "
                            f"bytes={len(payload)}",
                            flush=True,
                        )
        finally:
            conn.close()


class EdgeServer:
    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args
        self._store = EdgeStore(rgb_ring_size=args.rgb_ring_size)
        self._directive_lock = threading.Lock()
        self._last_directive_version = -1
        self._directive_seq = time.time_ns()
        self._required_layers = scheduler_required_layers(args.scheduler)
        self._streamvln: Optional[StreamVLNClient] = None
        self._streamvln_session = ""
        self._qwen_vl: Optional[QwenVLClient] = None
        self._foxglove: Optional[Any] = None
        if args.foxglove_port > 0:
            from monitor.foxglove_bridge import FoxgloveBridge

            self._foxglove = FoxgloveBridge(
                host=args.foxglove_host,
                port=args.foxglove_port,
                frame_id=args.foxglove_frame_id,
                pcd_dir=args.foxglove_pcd_dir or None,
                link_hz=args.foxglove_link_hz,
                metrics_fn=self._store.link_metrics,
            )
            self._store.add_observer(self._on_store_event)
        if args.scheduler == "streamvln":
            self._streamvln = StreamVLNClient(args.streamvln_url, timeout_s=args.streamvln_timeout_s)
        if args.scheduler == "qwen_vl":
            self._qwen_vl = QwenVLClient(
                model_id=args.qwen_vl_model,
                device=args.qwen_vl_device,
                load_in_4bit=args.qwen_vl_4bit,
                max_new_tokens=args.qwen_vl_max_tokens,
                min_interval_s=args.qwen_vl_min_interval_s,
                stub=args.qwen_vl_stub,
            )
            mode = "stub" if args.qwen_vl_stub else f"gpu model={args.qwen_vl_model}"
            print(f"[qwen_vl] scheduler enabled ({mode})", flush=True)

    def _on_store_event(self, event: str, payload: dict[str, Any]) -> None:
        if self._foxglove is None:
            return
        if event == "subgraph":
            self._foxglove.on_subgraph(payload)
        elif event == "rgb":
            self._foxglove.on_rgb(payload["meta"], payload["payload"])
        elif event == "directive":
            self._foxglove.on_directive(
                payload["directive"],
                bundle=payload.get("bundle"),
                scheduler=payload.get("scheduler", self._args.scheduler),
            )

    def on_subgraph(self, obj: dict[str, Any]) -> None:
        self._store.put_subgraph(obj)
        ver = obj.get("version", "?")
        nodes = len(obj.get("nodes") or [])
        frs = len(obj.get("frontiers") or [])
        print(
            f"[subgraph] {obj.get('schema')} v={ver} nodes={nodes} "
            f"frontiers={frs} trigger={obj.get('trigger_reason')}",
            flush=True,
        )
        if not self._args.auto_directive:
            return
        try:
            map_version = int(obj.get("version", 0))
        except (TypeError, ValueError):
            return
        if map_version <= self._last_directive_version:
            return
        self._schedule_directive(map_version)

    def on_rgb(self, meta: dict[str, Any], payload: bytes) -> None:
        self._store.put_rgb(meta, payload)
        try:
            map_version = int(meta.get("subgraph_version", 0))
        except (TypeError, ValueError):
            return
        if map_version > self._last_directive_version:
            self._schedule_directive(map_version)

    def _schedule_directive(self, map_version: int) -> None:
        threading.Thread(
            target=self._send_directive_when_ready,
            args=(map_version,),
            daemon=True,
        ).start()

    def _send_directive_when_ready(self, map_version: int) -> None:
        deadline = time.monotonic() + self._args.align_wait_s
        bundle = None
        while time.monotonic() < deadline:
            bundle = align_bundle(self._store, map_version)
            if bundle and all(layer in bundle.layers_aligned for layer in self._required_layers):
                break
            time.sleep(0.01)

        sg = self._store.latest_subgraph
        if sg is None or int(sg.get("version", -1)) != map_version:
            return

        if bundle:
            aligned = ",".join(x.value for x in bundle.layers_aligned)
            print(
                f"[align] v={map_version} layers=[{aligned}] "
                f"task={bundle.task.instruction[:24] if bundle.task else '-'} "
                f"rgb_tag={(bundle.vision_meta or {}).get('rgb_tag', '-')}",
                flush=True,
            )

        self._maybe_send_directive(sg, map_version, bundle)

    def _maybe_send_directive(
        self,
        subgraph: dict[str, Any],
        map_version: int,
        bundle: Optional[Any],
    ) -> None:
        with self._directive_lock:
            if map_version <= self._last_directive_version:
                return
            session_id = str(subgraph.get("session_id", self._args.session_id))
            instruction = self._args.instruction
            if bundle and bundle.task and bundle.task.instruction:
                instruction = bundle.task.instruction

            action_bias = None
            if self._args.scheduler == "qwen_vl" and self._qwen_vl is not None:
                if bundle is None or not bundle.ready_for("qwen_vl"):
                    print(f"[qwen_vl] v={map_version} layers not ready, skip", flush=True)
                    return
                qwen_result = self._qwen_vl.infer(subgraph, bundle, instruction)
                directive = build_directive_from_qwen_vl(
                    session_id=session_id,
                    map_version=map_version,
                    subgraph=subgraph,
                    instruction=instruction,
                    result=qwen_result,
                    bundle=bundle,
                )
            elif self._args.scheduler == "streamvln" and self._streamvln is not None:
                if session_id != self._streamvln_session:
                    self._streamvln.reset_session(session_id)
                    self._streamvln_session = session_id
                rgb_tag = str((bundle.vision_meta or {}).get("rgb_tag", "")) if bundle else ""
                vln_result = self._streamvln.eval_vln(
                    session_id=session_id,
                    instruction=instruction,
                    rgb_tag=rgb_tag,
                )
                actions = vln_result["action"]
                action_bias = build_action_bias(actions, vln_result.get("llm_output", ""))
                top_pick = actions_to_frontier_hint(actions, subgraph, bundle)
                all_ids = [str(f["frontier_id"]) for f in (subgraph.get("frontiers") or []) if f.get("frontier_id")]
                if not all_ids:
                    all_ids = ["bt_next_subgoal"]
                candidate_ids = [top_pick] + [x for x in all_ids if x != top_pick]
                directive = build_directive(
                    session_id=session_id,
                    map_version=map_version,
                    subgraph=subgraph,
                    instruction=instruction,
                    scheduler=self._args.scheduler,
                    bundle=bundle,
                    action_bias=action_bias,
                )
                directive["candidate_frontier_ids"] = candidate_ids
            else:
                directive = build_directive(
                    session_id=session_id,
                    map_version=map_version,
                    subgraph=subgraph,
                    instruction=instruction,
                    scheduler=self._args.scheduler,
                    bundle=bundle,
                    action_bias=action_bias,
                )
            report = None
            try:
                if self._args.directive_protocol == "task":
                    self._directive_seq += 1
                    task = to_task_directive(
                        directive,
                        directive_id=self._directive_seq,
                        robot_id=self._args.robot_id,
                        lease_epoch=self._args.lease_epoch,
                    )
                    report = send_task_directive(
                        self._args.go2_host,
                        self._args.go2_directive_port,
                        task,
                        timeout_s=self._args.directive_timeout_s,
                    )
                else:
                    send_directive(
                        self._args.go2_host,
                        self._args.go2_directive_port,
                        directive,
                        timeout_s=self._args.directive_timeout_s,
                    )
            except (OSError, ValueError) as exc:
                print(f"[directive] send failed: {exc}", flush=True)
                return
            if report is not None and report.get("reason") != "ok":
                print(f"[directive] robot rejected v={map_version}: {report.get('reason')}", flush=True)
            self._last_directive_version = map_version
            self._store.inc_directive_sent()
            self._store.notify_directive(
                directive,
                extra={"bundle": bundle, "scheduler": self._args.scheduler},
            )
            print(
                f"[directive] -> {self._args.go2_host}:{self._args.go2_directive_port} "
                f"scheduler={self._args.scheduler} v={map_version} "
                f"frontiers={directive.get('candidate_frontier_ids')}",
                flush=True,
            )

    def send_directive_once(self) -> None:
        sg = self._store.latest_subgraph
        if sg is None:
            print("[directive] no subgraph yet", flush=True)
            return
        try:
            map_version = int(sg.get("version", 1))
        except (TypeError, ValueError):
            map_version = 1
        bundle = align_bundle(self._store, map_version)
        self._maybe_send_directive(sg, map_version, bundle)

    def status_loop(self) -> None:
        while True:
            time.sleep(self._args.status_interval_s)
            snap = self._store.snapshot()
            print(f"[status] {json.dumps(snap, ensure_ascii=False)}", flush=True)

    def run(self) -> None:
        t_sub = threading.Thread(
            target=_serve_json_lines,
            args=("subgraph", self._args.host, self._args.subgraph_port, self.on_subgraph),
            daemon=True,
        )
        t_rgb = threading.Thread(
            target=_serve_rgb_binary,
            args=(self._args.host, self._args.rgb_port, self.on_rgb),
            daemon=True,
        )
        t_status = threading.Thread(target=self.status_loop, daemon=True)
        t_sub.start()
        t_rgb.start()
        if self._args.status_interval_s > 0:
            t_status.start()

        print(
            f"[edge] ready | uplink {self._args.host}:"
            f"{self._args.subgraph_port}/{self._args.rgb_port} | "
            f"directive -> {self._args.go2_host}:{self._args.go2_directive_port} | "
            f"scheduler={self._args.scheduler} auto_directive={self._args.auto_directive}"
            + (
                f" | foxglove ws://{self._args.foxglove_host}:{self._args.foxglove_port}"
                if self._args.foxglove_port > 0
                else ""
            ),
            flush=True,
        )
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\n[edge] stopped", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="RGB_ws v1 edge gateway")
    parser.add_argument("--host", default="0.0.0.0", help="listen for uplink")
    parser.add_argument("--subgraph-port", type=int, default=9877)
    parser.add_argument("--rgb-port", type=int, default=9878)
    parser.add_argument("--go2-host", default="192.0.2.61", help="directive sink host")
    parser.add_argument("--go2-directive-port", type=int, default=9879)
    parser.add_argument("--session-id", default="demo_live")
    parser.add_argument("--instruction", default="mock_edge_directive")
    parser.add_argument(
        "--scheduler",
        default="mock",
        choices=("mock", "geom_baseline", "layer_fusion_stub", "streamvln", "qwen_vl"),
        help="frontier / StreamVLN / Qwen-VL 策略",
    )
    parser.add_argument(
        "--streamvln-url",
        default="http://127.0.0.1:5801/eval_vln",
        help="StreamVLN 官方 HTTP 端点（scheduler=streamvln）",
    )
    parser.add_argument("--streamvln-timeout-s", type=float, default=30.0)
    parser.add_argument(
        "--qwen-vl-model",
        default="Qwen/Qwen2.5-VL-3B-Instruct",
        help="HuggingFace 模型 ID（scheduler=qwen_vl）",
    )
    parser.add_argument("--qwen-vl-device", default="cuda:0", help="cuda:0 | auto")
    parser.add_argument(
        "--qwen-vl-4bit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="bitsandbytes INT4 加载（5070 约 6–8GB）",
    )
    parser.add_argument("--qwen-vl-max-tokens", type=int, default=512)
    parser.add_argument("--qwen-vl-min-interval-s", type=float, default=0.5)
    parser.add_argument(
        "--qwen-vl-stub",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="CPU 规则 stub，不加载 GPU 模型（仿真/联调）",
    )
    parser.add_argument("--align-wait-s", type=float, default=0.25, help="等待 L0/L1/L2 对齐窗口")
    parser.add_argument("--auto-directive", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--directive-timeout-s", type=float, default=3.0)
    parser.add_argument(
        "--directive-protocol",
        choices=["task", "semantic"],
        default="task",
        help="task: TaskDirective + ExecutionReport（机器人端 DirectiveGate 准入）; semantic: 旧 SemanticDirective JSONL",
    )
    parser.add_argument("--robot-id", type=int, default=1, help="TaskDirective.robot_id")
    parser.add_argument("--lease-epoch", type=int, default=1, help="TaskDirective.lease_epoch")
    parser.add_argument("--rgb-ring-size", type=int, default=60)
    parser.add_argument("--status-interval-s", type=float, default=30.0)
    parser.add_argument("--foxglove-host", default="127.0.0.1", help="Foxglove WebSocket 监听地址")
    parser.add_argument(
        "--foxglove-port",
        type=int,
        default=0,
        help="Foxglove WebSocket 端口；0=关闭，8765=开启监控",
    )
    parser.add_argument("--foxglove-frame-id", default="map", help="子图 SceneUpdate frame_id")
    parser.add_argument(
        "--foxglove-pcd-dir",
        default="",
        help="可选 SUBM1 拼接 PCD 目录（如 motion_ws/logs/submaps_recv）",
    )
    parser.add_argument("--foxglove-link-hz", type=float, default=1.0, help="链路状态推送频率")
    args = parser.parse_args()
    EdgeServer(args).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
