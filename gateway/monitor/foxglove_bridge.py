"""Foxglove WebSocket 桥：子图 / RGB / 模型 I/O / 链路状态."""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Optional

from monitor.subgraph_viz import robot_scene, subgraph_to_scene


def _import_foxglove():
    try:
        import foxglove
        from foxglove.channels import CompressedImageChannel, LogChannel, SceneUpdateChannel
        from foxglove.messages import CompressedImage, Log, LogLevel
    except ImportError as exc:
        raise SystemExit(
            "缺少 foxglove-sdk。请先: pip3 install --user foxglove-sdk\n"
            f"原始错误: {exc}"
        ) from exc
    return foxglove, CompressedImageChannel, LogChannel, SceneUpdateChannel, CompressedImage, Log, LogLevel


class FoxgloveBridge:
    """边侧网关 → Foxglove Studio（WebSocket）."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        frame_id: str = "map",
        pcd_dir: Optional[str] = None,
        link_hz: float = 1.0,
        metrics_fn: Optional[Callable[[], dict[str, Any]]] = None,
    ) -> None:
        (
            foxglove,
            CompressedImageChannel,
            LogChannel,
            SceneUpdateChannel,
            CompressedImage,
            Log,
            LogLevel,
        ) = _import_foxglove()

        self._CompressedImage = CompressedImage
        self._Log = Log
        self._LogLevel = LogLevel
        self._frame_id = frame_id
        self._metrics_fn = metrics_fn
        self._link_period = 1.0 / max(link_hz, 0.1)

        foxglove.set_log_level("INFO")
        self._server = foxglove.start_server(name="rgb_ws_monitor", host=host, port=port)

        self._scene_ch = SceneUpdateChannel("/map/subgraph")
        self._robot_ch = SceneUpdateChannel("/map/robot")
        self._rgb_ch = CompressedImageChannel("/vision/rgb")
        self._directive_ch = LogChannel("/model/directive_out")
        self._input_ch = LogChannel("/model/scheduler_input")
        self._link_ch = LogChannel("/network/link_status")

        self._pcd_watcher = None
        if pcd_dir:
            from monitor.pcd_watcher import PcdWatcher, make_pcd_channel

            pcd_ch = make_pcd_channel("/submap/stitched")
            self._pcd_watcher = PcdWatcher(directory=pcd_dir, channel=pcd_ch, frame_id="world")
            self._pcd_watcher.start()

        self._stop = threading.Event()
        self._link_thread = threading.Thread(target=self._link_loop, daemon=True, name="foxglove-link")
        self._link_thread.start()

        print(f"[foxglove] WebSocket ws://{host}:{port}", flush=True)
        print("[foxglove] Studio → Foxglove WebSocket → 上述 URL", flush=True)
        print("[foxglove] 3D: /map/subgraph + /map/robot [+ /submap/stitched]", flush=True)
        print("[foxglove] Image: /vision/rgb | Logs: /model/* /network/link_status", flush=True)

    def stop(self) -> None:
        self._stop.set()
        if self._pcd_watcher is not None:
            self._pcd_watcher.stop()
        try:
            self._server.stop()
        except Exception:  # noqa: BLE001
            pass

    def on_subgraph(self, subgraph: dict[str, Any]) -> None:
        self._scene_ch.log(subgraph_to_scene(subgraph, frame_id=self._frame_id))
        self._robot_ch.log(robot_scene(subgraph, frame_id=self._frame_id))

    def on_rgb(self, meta: dict[str, Any], payload: bytes) -> None:
        fmt = str(meta.get("codec", "jpeg")).lower()
        if fmt in ("h265", "hevc"):
            return  # Studio 不直接解 H265；等边侧 NVDEC 后再推 JPEG
        image_fmt = "jpeg" if fmt in ("jpeg", "jpg", "") else fmt
        self._rgb_ch.log(
            self._CompressedImage(
                frame_id="camera",
                format=image_fmt,
                data=payload,
            )
        )

    def on_directive(
        self,
        directive: dict[str, Any],
        *,
        bundle: Optional[Any] = None,
        scheduler: str = "",
    ) -> None:
        pick = (directive.get("candidate_frontier_ids") or [""])[0]
        subgraph = bundle.structure if bundle is not None and hasattr(bundle, "structure") else None
        if subgraph:
            self._scene_ch.log(
                subgraph_to_scene(
                    subgraph,
                    frame_id=self._frame_id,
                    highlight_frontiers=list(directive.get("candidate_frontier_ids") or []),
                )
            )

        self._directive_ch.log(
            self._Log(
                level=self._LogLevel.Info,
                name="directive_out",
                message=json.dumps(directive, ensure_ascii=False, separators=(",", ":")),
            )
        )

        inp: dict[str, Any] = {
            "scheduler": scheduler or (directive.get("multimodal_layers") or {}).get("scheduler"),
            "map_version": directive.get("map_version"),
            "instruction": directive.get("instruction"),
            "pick": pick,
        }
        if bundle is not None:
            inp["layers_aligned"] = [x.value for x in getattr(bundle, "layers_aligned", [])]
            inp["layers_present"] = [x.value for x in getattr(bundle, "layers_present", [])]
            if getattr(bundle, "task", None):
                inp["task"] = bundle.task.instruction
            if getattr(bundle, "vision_meta", None):
                inp["rgb_tag"] = bundle.vision_meta.get("rgb_tag")
        self._input_ch.log(
            self._Log(
                level=self._LogLevel.Info,
                name="scheduler_input",
                message=json.dumps(inp, ensure_ascii=False, separators=(",", ":")),
            )
        )

    def _link_loop(self) -> None:
        while not self._stop.is_set():
            if self._metrics_fn is not None:
                m = self._metrics_fn()
                self._link_ch.log(
                    self._Log(
                        level=self._LogLevel.Info,
                        name="link_status",
                        message=json.dumps(m, ensure_ascii=False, separators=(",", ":")),
                    )
                )
            time.sleep(self._link_period)
