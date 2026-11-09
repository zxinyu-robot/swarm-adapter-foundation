"""平面运动：线速度 + 角速度 → set_pose（保持直立，不经 VelocityControl）."""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from typing import Optional

from gazebo.bridge.pose_reader import read_pose

STAND_Z_M = 0.21
WORLD = "corridor"


@dataclass
class PlanarVelocity:
    linear_m_s: float
    angular_rad_s: float


def _yaw_to_quat(yaw_rad: float) -> tuple[float, float, float, float]:
    return 0.0, 0.0, math.sin(yaw_rad / 2.0), math.cos(yaw_rad / 2.0)


def set_model_pose(
    x: float,
    y: float,
    z: float,
    yaw_deg: float,
    *,
    model_name: str = "go2",
    world: str = WORLD,
    timeout_s: float = 2.0,
) -> bool:
    yaw = math.radians(yaw_deg)
    qx, qy, qz, qw = _yaw_to_quat(yaw)
    req = (
        f'name: "{model_name}", '
        f"position: {{x: {x:.6f}, y: {y:.6f}, z: {z:.6f}}}, "
        f"orientation: {{x: {qx:.6f}, y: {qy:.6f}, z: {qz:.6f}, w: {qw:.6f}}}"
    )
    try:
        proc = subprocess.run(
            [
                "gz",
                "service",
                "-s",
                f"/world/{world}/set_pose",
                "--reqtype",
                "gz.msgs.Pose",
                "--reptype",
                "gz.msgs.Boolean",
                "--timeout",
                str(int(timeout_s * 1000)),
                "--req",
                req,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s + 1.0,
        )
        return proc.returncode == 0 and "data: true" in proc.stdout.lower()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def apply_velocity_step(
    linear_m_s: float,
    angular_rad_s: float,
    dt_s: float,
    *,
    model_name: str = "go2",
    stand_z: float = STAND_Z_M,
) -> bool:
    pose = read_pose(model_name)
    if pose is None:
        return False
    yaw = math.radians(pose.yaw_deg)
    nx = pose.x + linear_m_s * math.cos(yaw) * dt_s
    ny = pose.y + linear_m_s * math.sin(yaw) * dt_s
    nyaw = pose.yaw_deg + math.degrees(angular_rad_s * dt_s)
    return set_model_pose(nx, ny, stand_z, nyaw, model_name=model_name)


def publish_velocity(
    linear_m_s: float,
    angular_rad_s: float,
    *,
    model_name: str = "go2",
    dt_s: float = 0.1,
) -> bool:
    """单步运动学积分（保持 z 与 roll/pitch 直立）."""
    return apply_velocity_step(linear_m_s, angular_rad_s, dt_s, model_name=model_name)


def stop(model_name: str = "go2") -> bool:
    pose = read_pose(model_name)
    if pose is None:
        return True
    return set_model_pose(pose.x, pose.y, STAND_Z_M, pose.yaw_deg, model_name=model_name)


def reset_upright(model_name: str = "go2", *, x: float = 0.0, y: float = 0.0) -> bool:
    """重置到站立位姿."""
    return set_model_pose(x, y, STAND_Z_M, 0.0, model_name=model_name)
