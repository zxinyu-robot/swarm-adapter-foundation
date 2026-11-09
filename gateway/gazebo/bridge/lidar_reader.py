"""从 Gazebo /lidar 话题解析 2D 扫描（protobuf 文本）."""
from __future__ import annotations

import math
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

_ANGLE_MIN = re.compile(r"angle_min:\s*([-\d.eE+]+)")
_ANGLE_MAX = re.compile(r"angle_max:\s*([-\d.eE+]+)")
_ANGLE_STEP = re.compile(r"angle_step:\s*([-\d.eE+]+)")
_RANGES_LINE = re.compile(r"^\s*ranges:\s*([-\d.eE+]+)", re.MULTILINE)
# 旧格式 fallback
_RANGE_BLOCK = re.compile(r"range\s*\{([^}]*)\}", re.MULTILINE)
_FLOAT = re.compile(r"data:\s*([-\d.eE+]+)")


@dataclass
class LidarScan:
    ranges: list[float]
    angle_min: float
    angle_max: float
    angle_step: float


def _parse_ranges(text: str) -> list[float]:
    lines = _RANGES_LINE.findall(text)
    if lines:
        return [float(x) for x in lines]
    m = _RANGE_BLOCK.search(text)
    if m:
        return [float(x) for x in _FLOAT.findall(m.group(1))]
    return []


def _parse_scan(text: str) -> Optional[LidarScan]:
    ranges = _parse_ranges(text)
    if not ranges:
        return None

    def _f(pat: re.Pattern[str], default: float) -> float:
        m = pat.search(text)
        return float(m.group(1)) if m else default

    angle_min = _f(_ANGLE_MIN, -math.pi)
    angle_max = _f(_ANGLE_MAX, math.pi)
    angle_step = _f(_ANGLE_STEP, (angle_max - angle_min) / max(1, len(ranges) - 1))
    return LidarScan(
        ranges=ranges,
        angle_min=angle_min,
        angle_max=angle_max,
        angle_step=angle_step,
    )


def read_lidar(
    topic: str = "/lidar",
    *,
    timeout_s: float = 8.0,
    retries: int = 5,
    retry_sleep_s: float = 0.8,
) -> Optional[LidarScan]:
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while time.monotonic() < deadline and attempt < retries:
        attempt += 1
        try:
            proc = subprocess.run(
                ["gz", "topic", "-e", "-t", topic, "-n", "1"],
                capture_output=True,
                text=True,
                timeout=max(2.0, timeout_s / retries),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            time.sleep(retry_sleep_s)
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            scan = _parse_scan(proc.stdout)
            if scan is not None:
                return scan
        time.sleep(retry_sleep_s)
    return None


def sector_mean_range(scan: LidarScan, center_rad: float, half_width_rad: float = 0.35) -> float:
    vals: list[float] = []
    for i, r in enumerate(scan.ranges):
        if not (0.05 < r < 11.0):
            continue
        ang = scan.angle_min + i * scan.angle_step
        diff = (ang - center_rad + math.pi) % (2 * math.pi) - math.pi
        if abs(diff) <= half_width_rad:
            vals.append(r)
    return sum(vals) / len(vals) if vals else 0.0
