"""边侧状态：最新子图 + RGB 环缓冲."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

LinkObserver = Callable[[str, dict[str, Any]], None]


@dataclass
class RgbFrame:
    meta: dict[str, Any]
    payload: bytes
    recv_mono: float = field(default_factory=time.monotonic)


class EdgeStore:
    def __init__(self, rgb_ring_size: int = 60) -> None:
        self._lock = threading.Lock()
        self.latest_subgraph: Optional[dict[str, Any]] = None
        self.subgraph_count = 0
        self.rgb_count = 0
        self.directive_sent = 0
        self._rgb_ring: deque[RgbFrame] = deque(maxlen=max(1, rgb_ring_size))
        self._observers: list[LinkObserver] = []
        self._last_subgraph_mono = 0.0
        self._last_rgb_mono = 0.0
        self._last_directive_mono = 0.0
        self._subgraph_times: deque[float] = deque(maxlen=120)
        self._rgb_times: deque[float] = deque(maxlen=600)

    def add_observer(self, cb: LinkObserver) -> None:
        with self._lock:
            self._observers.append(cb)

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        for cb in list(self._observers):
            try:
                cb(event, payload)
            except Exception as exc:  # noqa: BLE001 — 监控不得拖垮网关
                print(f"[store] observer error ({event}): {exc}", flush=True)

    def put_subgraph(self, obj: dict[str, Any]) -> None:
        with self._lock:
            self.latest_subgraph = obj
            self.subgraph_count += 1
            now = time.monotonic()
            self._last_subgraph_mono = now
            self._subgraph_times.append(now)
        self._emit("subgraph", obj)

    def put_rgb(self, meta: dict[str, Any], payload: bytes) -> None:
        with self._lock:
            self._rgb_ring.append(RgbFrame(meta=meta, payload=payload))
            self.rgb_count += 1
            now = time.monotonic()
            self._last_rgb_mono = now
            self._rgb_times.append(now)
        self._emit("rgb", {"meta": meta, "payload": payload})

    def aligned_rgb(self, subgraph_version: int) -> Optional[RgbFrame]:
        with self._lock:
            for frame in reversed(self._rgb_ring):
                if int(frame.meta.get("subgraph_version", -1)) == subgraph_version:
                    return frame
            if self._rgb_ring:
                return self._rgb_ring[-1]
            return None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            sg = self.latest_subgraph or {}
            return {
                "subgraph_count": self.subgraph_count,
                "rgb_count": self.rgb_count,
                "directive_sent": self.directive_sent,
                "latest_version": sg.get("version"),
                "latest_nodes": len(sg.get("nodes") or []),
                "latest_frontiers": len(sg.get("frontiers") or []),
                "rgb_ring_len": len(self._rgb_ring),
            }

    def inc_directive_sent(self) -> None:
        with self._lock:
            self.directive_sent += 1
            self._last_directive_mono = time.monotonic()

    def notify_directive(self, directive: dict[str, Any], extra: Optional[dict[str, Any]] = None) -> None:
        payload = {"directive": directive}
        if extra:
            payload.update(extra)
        self._emit("directive", payload)

    @staticmethod
    def _rate_hz(times: deque[float], window_s: float = 10.0) -> float:
        if len(times) < 2:
            return 0.0
        now = time.monotonic()
        recent = [t for t in times if now - t <= window_s]
        if len(recent) < 2:
            return 0.0
        return (len(recent) - 1) / max(recent[-1] - recent[0], 1e-6)

    def link_metrics(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            sg = self.latest_subgraph or {}
            return {
                "subgraph_count": self.subgraph_count,
                "rgb_count": self.rgb_count,
                "directive_sent": self.directive_sent,
                "latest_version": sg.get("version"),
                "subgraph_hz_10s": round(self._rate_hz(self._subgraph_times), 2),
                "rgb_hz_10s": round(self._rate_hz(self._rgb_times), 2),
                "last_subgraph_age_s": round(now - self._last_subgraph_mono, 2)
                if self._last_subgraph_mono
                else None,
                "last_rgb_age_s": round(now - self._last_rgb_mono, 2) if self._last_rgb_mono else None,
                "last_directive_age_s": round(now - self._last_directive_mono, 2)
                if self._last_directive_mono
                else None,
                "rgb_ring_len": len(self._rgb_ring),
                "ports": {"subgraph": 9877, "rgb": 9878, "directive": 9879},
            }
