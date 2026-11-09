"""Go2 站立姿态下各腿 mesh 在 base 系的位姿（仅视觉，无关节物理）."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

THIGH_OFF_Y = 0.0955
SEG_L = 0.213
HIP_X = 0.1934
HIP_Y = 0.0465
THIGH_A = 0.72
CALF_A = -1.45


@dataclass
class VisualPart:
    name: str
    mesh: str
    x: float
    y: float
    z: float
    roll: float
    pitch: float
    yaw: float


def _rot_y_vec(v: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    x, y, z = v
    c, s = math.cos(angle), math.sin(angle)
    return x * c + z * s, y, -x * s + z * c


def _leg_vis(
    prefix: str,
    hip_xy: tuple[float, float],
    *,
    mirror_dae: bool,
    front: bool,
) -> list[VisualPart]:
    hx, hy = hip_xy
    y_sign = 1.0 if hy >= 0 else -1.0

    hip_rpy = (math.pi, 0.0, 0.0)
    if mirror_dae and front:
        hip_rpy = (0.0, 0.0, 0.0)
    elif (not mirror_dae) and (not front):
        hip_rpy = (math.pi, math.pi, 0.0)
    elif mirror_dae and (not front):
        hip_rpy = (0.0, math.pi, 0.0)

    thigh_mesh = "thigh_mirror.dae" if mirror_dae else "thigh.dae"
    calf_mesh = "calf_mirror.dae" if mirror_dae else "calf.dae"

    hip_p = (hx, hy, 0.0)
    thigh_joint = (hx, hy + y_sign * THIGH_OFF_Y, 0.0)
    knee = (
        thigh_joint[0] + _rot_y_vec((0.0, 0.0, -SEG_L), THIGH_A)[0],
        thigh_joint[1],
        thigh_joint[2] + _rot_y_vec((0.0, 0.0, -SEG_L), THIGH_A)[2],
    )
    foot = (
        knee[0] + _rot_y_vec((0.0, 0.0, -SEG_L), THIGH_A + CALF_A)[0],
        knee[1],
        knee[2] + _rot_y_vec((0.0, 0.0, -SEG_L), THIGH_A + CALF_A)[2],
    )

    def part(n: str, mesh: str, p: tuple[float, float, float], rpy: tuple[float, float, float]) -> VisualPart:
        return VisualPart(n, mesh, p[0], p[1], p[2], rpy[0], rpy[1], rpy[2])

    return [
        part(f"{prefix}_hip", "hip.dae", hip_p, hip_rpy),
        part(f"{prefix}_thigh", thigh_mesh, thigh_joint, (0.0, THIGH_A, 0.0)),
        part(f"{prefix}_calf", calf_mesh, knee, (0.0, THIGH_A + CALF_A, 0.0)),
        part(f"{prefix}_foot", "foot.dae", foot, (0.0, THIGH_A + CALF_A, 0.0)),
    ]


def all_leg_visuals() -> Iterable[VisualPart]:
    yield from _leg_vis("FL", (HIP_X, HIP_Y), mirror_dae=False, front=True)
    yield from _leg_vis("FR", (HIP_X, -HIP_Y), mirror_dae=True, front=True)
    yield from _leg_vis("RL", (-HIP_X, HIP_Y), mirror_dae=False, front=False)
    yield from _leg_vis("RR", (-HIP_X, -HIP_Y), mirror_dae=True, front=False)


def visuals_to_sdf(parts: Iterable[VisualPart]) -> str:
    lines: list[str] = []
    for p in parts:
        lines.append(f"""      <visual name="{p.name}">
        <pose>{p.x:.6f} {p.y:.6f} {p.z:.6f} {p.roll:.6f} {p.pitch:.6f} {p.yaw:.6f}</pose>
        <geometry>
          <mesh><uri>model://go2_stand/meshes/{p.mesh}</uri></mesh>
        </geometry>
      </visual>""")
    return "\n".join(lines)
