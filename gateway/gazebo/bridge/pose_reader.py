"""从 Gazebo Harmonic 读取 Go2 位姿（gz model -p）."""
from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class RobotPose:
    x: float
    y: float
    z: float
    yaw_deg: float

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "yaw_deg": self.yaw_deg}


_POSE_RE = re.compile(
    r"Pose\s*\[\s*XYZ\s*\(m\)\s*\]\s*\[\s*RPY\s*\(rad\)\s*\]\s*:\s*"
    r"\[\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*\]\s*"
    r"\[\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*\]",
    re.MULTILINE,
)


def _yaw_deg_from_rpy(roll: float, pitch: float, yaw: float) -> float:
    return math.degrees(yaw)


def read_pose(model_name: str = "go2", *, timeout_s: float = 2.0) -> Optional[RobotPose]:
    try:
        proc = subprocess.run(
            ["gz", "model", "-m", model_name, "-p"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if proc.returncode != 0:
        return None

    m = _POSE_RE.search(proc.stdout)
    if not m:
        return None

    x, y, z, roll, pitch, yaw = (float(m.group(i)) for i in range(1, 7))
    return RobotPose(x=x, y=y, z=z, yaw_deg=_yaw_deg_from_rpy(roll, pitch, yaw))


def wait_pose(
    model_name: str = "go2",
    *,
    timeout_s: float = 30.0,
    poll_s: float = 0.5,
) -> Optional[RobotPose]:
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pose = read_pose(model_name)
        if pose is not None:
            return pose
        time.sleep(poll_s)
    return None
