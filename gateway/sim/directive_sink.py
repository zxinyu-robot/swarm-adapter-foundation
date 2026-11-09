#!/usr/bin/env python3
"""仿真用 SemanticDirective 接收器（替代真狗 :9879）."""
from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ReceivedDirective:
    payload: dict[str, Any]
    recv_mono: float
    recv_wall_ns: int


@dataclass
class DirectiveSink:
    host: str = "127.0.0.1"
    port: int = 9879
    _records: list[ReceivedDirective] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _server: Optional[socket.socket] = None
    _thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        for _ in range(50):
            if self._server is not None:
                return
            time.sleep(0.02)

    def stop(self) -> None:
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        self._server = None

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def records(self) -> list[ReceivedDirective]:
        with self._lock:
            return list(self._records)

    def wait_count(self, n: int, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if len(self.records()) >= n:
                return True
            time.sleep(0.05)
        return False

    def _serve(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(8)
        self._server = srv
        buf = b""
        while True:
            try:
                conn, _addr = srv.accept()
            except OSError:
                break
            peer = b""
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    peer += chunk
                    while b"\n" in peer:
                        line, peer = peer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        obj = json.loads(line.decode("utf-8"))
                        rec = ReceivedDirective(
                            payload=obj,
                            recv_mono=time.monotonic(),
                            recv_wall_ns=time.time_ns(),
                        )
                        with self._lock:
                            self._records.append(rec)
            except (json.JSONDecodeError, OSError):
                pass
            finally:
                conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description="SemanticDirective sink for sim")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9879)
    args = p.parse_args()
    sink = DirectiveSink(host=args.host, port=args.port)
    sink.start()
    print(f"[sink] listening on {args.host}:{args.port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sink.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
