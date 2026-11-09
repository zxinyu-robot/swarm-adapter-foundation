"""可选：motion_ws SUBM1 拼接 PCD → Foxglove PointCloud（与 motion_ws 脚本对齐）."""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Callable, Optional

import numpy as np


def _import_foxglove_pcd():
    try:
        import foxglove
        from foxglove.channels import PointCloudChannel
        from foxglove.messages import (
            PackedElementField,
            PackedElementFieldNumericType,
            PointCloud,
            Pose,
            Quaternion,
            Vector3,
        )
    except ImportError as exc:
        raise SystemExit(
            "缺少 foxglove-sdk。请先: pip3 install --user foxglove-sdk\n"
            f"原始错误: {exc}"
        ) from exc
    return (
        foxglove,
        PointCloudChannel,
        PackedElementField,
        PackedElementFieldNumericType,
        PointCloud,
        Pose,
        Quaternion,
        Vector3,
    )


def _read_pcd_xyzi(path: str) -> np.ndarray:
    """Minimal PCD reader (xyz + intensity). 优先复用 motion_ws pcd_io."""
    motion_pcd = "/home/ubuntu/Downloads/motion_ws/scripts/submap_uplink/pcd_io.py"
    if os.path.isfile(motion_pcd):
        if os.path.dirname(motion_pcd) not in sys.path:
            sys.path.insert(0, os.path.dirname(motion_pcd))
        from pcd_io import read_pcd_xyzi  # type: ignore

        return read_pcd_xyzi(path)

    # fallback: ascii/binary PCD with FIELDS x y z intensity
    with open(path, "rb") as f:
        header = b""
        while True:
            line = f.readline()
            if not line:
                raise ValueError("invalid PCD header")
            header += line
            if line.strip().upper() == b"DATA ascii":
                data_fmt = "ascii"
                break
            if line.strip().upper() == b"DATA binary":
                data_fmt = "binary"
                break
        n_points = 0
        for ln in header.decode("utf-8", errors="replace").splitlines():
            if ln.startswith("POINTS"):
                n_points = int(ln.split()[1])
        if data_fmt == "ascii":
            rows = []
            for _ in range(n_points):
                parts = f.readline().split()
                rows.append([float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])])
            return np.asarray(rows, dtype=np.float32)
        raw = f.read(n_points * 16)
        pts = np.frombuffer(raw, dtype=np.float32).reshape(-1, 4)
        return pts.copy()


def _points_to_msg(points: np.ndarray, frame_id: str, helpers: tuple) -> Any:
    (
        PointCloud,
        PackedElementField,
        PackedElementFieldNumericType,
        Pose,
        Quaternion,
        Vector3,
    ) = helpers[2:]
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 4)
    f32 = PackedElementFieldNumericType.Float32
    fields = [
        PackedElementField(name="x", offset=0, type=f32),
        PackedElementField(name="y", offset=4, type=f32),
        PackedElementField(name="z", offset=8, type=f32),
        PackedElementField(name="intensity", offset=12, type=f32),
    ]
    return PointCloud(
        frame_id=frame_id,
        pose=Pose(
            position=Vector3(x=0.0, y=0.0, z=0.0),
            orientation=Quaternion(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
        point_stride=16,
        fields=fields,
        data=pts.tobytes(order="C"),
    )


class PcdWatcher:
    """后台轮询 stitched.pcd 并推到 /submap/stitched."""

    def __init__(
        self,
        *,
        directory: str,
        channel: Any,
        frame_id: str = "world",
        hz: float = 2.0,
        republish_sec: float = 2.0,
        stitched_name: str = "stitched.pcd",
    ) -> None:
        self._dir = directory
        self._channel = channel
        self._frame_id = frame_id
        self._period = 1.0 / max(hz, 0.1)
        self._republish_sec = republish_sec
        self._stitched_path = os.path.join(directory, stitched_name)
        self._cache_sig: Optional[tuple[float, int]] = None
        self._last_force = 0.0
        self._helpers = _import_foxglove_pcd()[2:]
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="pcd-watcher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _mtime_size(self, path: str) -> Optional[tuple[float, int]]:
        try:
            st = os.stat(path)
            return (st.st_mtime, st.st_size)
        except OSError:
            return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            force = self._republish_sec > 0 and (now - self._last_force) >= self._republish_sec
            if force:
                self._last_force = now
            sig = self._mtime_size(self._stitched_path)
            if sig is None:
                time.sleep(self._period)
                continue
            if not force and sig == self._cache_sig:
                time.sleep(self._period)
                continue
            try:
                pts = _read_pcd_xyzi(self._stitched_path)
                msg = _points_to_msg(pts, self._frame_id, (None,) + self._helpers)
                self._channel.log(msg)
                self._cache_sig = sig
            except Exception as exc:  # noqa: BLE001 — 文件可能写入中
                print(f"[pcd] skip {self._stitched_path}: {exc}", flush=True)
            time.sleep(self._period)


def make_pcd_channel(topic: str = "/submap/stitched") -> Any:
    _, PointCloudChannel, *_ = _import_foxglove_pcd()
    return PointCloudChannel(topic)
