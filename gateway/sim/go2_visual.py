"""Go2 URDF 解析 + 简易 FK + Open3D 可视化（无需 PyBullet/Gazebo）."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    import open3d as o3d
except ImportError as exc:  # pragma: no cover
    raise SystemExit("需要 open3d: pip install open3d") from exc


@dataclass
class Geom:
    kind: str  # box | cylinder
    size: tuple[float, ...]
    origin_xyz: np.ndarray
    origin_rpy: np.ndarray
    color: tuple[float, float, float]


@dataclass
class Link:
    name: str
    geoms: list[Geom] = field(default_factory=list)


@dataclass
class Joint:
    name: str
    parent: str
    child: str
    joint_type: str
    origin_xyz: np.ndarray
    origin_rpy: np.ndarray
    axis: np.ndarray
    lower: float = 0.0
    upper: float = 0.0


def _parse_floats(text: str, n: int) -> tuple[float, ...]:
    vals = [float(x) for x in (text or "").split()]
    if len(vals) < n:
        vals.extend([0.0] * (n - len(vals)))
    return tuple(vals[:n])


def _rpy_matrix(rpy: np.ndarray) -> np.ndarray:
    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ],
        dtype=float,
    )


def _transform(xyz: np.ndarray, rpy: np.ndarray) -> np.ndarray:
    t = np.eye(4)
    t[:3, :3] = _rpy_matrix(rpy)
    t[:3, 3] = xyz
    return t


def _axis_angle_matrix(axis: np.ndarray, theta: float) -> np.ndarray:
    axis = axis / (np.linalg.norm(axis) + 1e-12)
    x, y, z = axis
    c, s = math.cos(theta), math.sin(theta)
    t = 1 - c
    return np.array(
        [
            [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
        ],
        dtype=float,
    )


def _joint_motion_matrix(joint: Joint, angle: float) -> np.ndarray:
    t = np.eye(4)
    t[:3, :3] = _axis_angle_matrix(joint.axis, angle)
    return t


class Go2UrdfModel:
    """基于 URDF collision 几何的轻量可视化模型."""

    DEFAULT_STAND: dict[str, float] = {
        "FL_hip_joint": 0.0,
        "FR_hip_joint": 0.0,
        "RL_hip_joint": 0.0,
        "RR_hip_joint": 0.0,
        "FL_thigh_joint": 0.75,
        "FR_thigh_joint": 0.75,
        "RL_thigh_joint": 0.75,
        "RR_thigh_joint": 0.75,
        "FL_calf_joint": -1.45,
        "FR_calf_joint": -1.45,
        "RL_calf_joint": -1.45,
        "RR_calf_joint": -1.45,
    }

    def __init__(self, urdf_path: Path) -> None:
        self.urdf_path = urdf_path
        self.links: dict[str, Link] = {}
        self.joints: dict[str, Joint] = {}
        self.joint_by_child: dict[str, Joint] = {}
        self._parse(urdf_path)

    def _parse(self, urdf_path: Path) -> None:
        root = ET.parse(urdf_path).getroot()
        palette = {
            "base": (0.35, 0.35, 0.38),
            "hip": (0.2, 0.55, 0.85),
            "thigh": (0.15, 0.45, 0.75),
            "calf": (0.1, 0.35, 0.65),
            "foot": (0.1, 0.1, 0.1),
            "head": (0.5, 0.5, 0.55),
        }

        for link_el in root.findall("link"):
            name = link_el.get("name", "")
            color = (0.5, 0.5, 0.5)
            lname = name.lower()
            for key, col in palette.items():
                if key in lname:
                    color = col
                    break
            geoms: list[Geom] = []
            for col_el in link_el.findall("collision"):
                origin = col_el.find("origin")
                xyz = np.array(_parse_floats(origin.get("xyz", "0 0 0") if origin is not None else "0 0 0", 3))
                rpy = np.array(_parse_floats(origin.get("rpy", "0 0 0") if origin is not None else "0 0 0", 3))
                geom_el = col_el.find("geometry")
                if geom_el is None:
                    continue
                box = geom_el.find("box")
                cyl = geom_el.find("cylinder")
                if box is not None:
                    size = _parse_floats(box.get("size", "0.1 0.1 0.1"), 3)
                    geoms.append(Geom("box", size, xyz, rpy, color))
                elif cyl is not None:
                    radius = float(cyl.get("radius", "0.02"))
                    length = float(cyl.get("length", "0.05"))
                    geoms.append(Geom("cylinder", (radius, length), xyz, rpy, color))
            if geoms:
                self.links[name] = Link(name=name, geoms=geoms)

        for joint_el in root.findall("joint"):
            jname = joint_el.get("name", "")
            jtype = joint_el.get("type", "fixed")
            parent = joint_el.find("parent").get("link", "")
            child = joint_el.find("child").get("link", "")
            origin = joint_el.find("origin")
            xyz = np.array(_parse_floats(origin.get("xyz", "0 0 0") if origin is not None else "0 0 0", 3))
            rpy = np.array(_parse_floats(origin.get("rpy", "0 0 0") if origin is not None else "0 0 0", 3))
            axis_el = joint_el.find("axis")
            axis = np.array(_parse_floats(axis_el.get("xyz", "0 0 1") if axis_el is not None else "0 0 1", 3))
            limit_el = joint_el.find("limit")
            lower = float(limit_el.get("lower", "0")) if limit_el is not None else 0.0
            upper = float(limit_el.get("upper", "0")) if limit_el is not None else 0.0
            joint = Joint(jname, parent, child, jtype, xyz, rpy, axis, lower, upper)
            self.joints[jname] = joint
            self.joint_by_child[child] = joint

    def link_transforms(
        self,
        joint_angles: dict[str, float],
        *,
        base_xyz: tuple[float, float, float] = (0.0, 0.0, 0.35),
        base_yaw_deg: float = 0.0,
    ) -> dict[str, np.ndarray]:
        world: dict[str, np.ndarray] = {}
        yaw = math.radians(base_yaw_deg)
        base_t = _transform(np.array(base_xyz), np.array([0.0, 0.0, yaw]))
        world["base"] = base_t

        def visit(link_name: str, parent_t: np.ndarray) -> None:
            for joint in self.joints.values():
                if joint.parent != link_name or joint.child in world:
                    continue
                j_origin = _transform(joint.origin_xyz, joint.origin_rpy)
                if joint.joint_type == "revolute":
                    angle = joint_angles.get(joint.name, 0.0)
                    j_motion = _joint_motion_matrix(joint, angle)
                else:
                    j_motion = np.eye(4)
                child_t = parent_t @ j_origin @ j_motion
                world[joint.child] = child_t
                visit(joint.child, child_t)

        visit("base", base_t)
        return world

    def to_open3d_meshes(
        self,
        joint_angles: Optional[dict[str, float]] = None,
        *,
        base_xyz: tuple[float, float, float] = (0.0, 0.0, 0.35),
        base_yaw_deg: float = 0.0,
    ) -> list[o3d.geometry.TriangleMesh]:
        angles = dict(self.DEFAULT_STAND)
        if joint_angles:
            angles.update(joint_angles)
        transforms = self.link_transforms(angles, base_xyz=base_xyz, base_yaw_deg=base_yaw_deg)
        meshes: list[o3d.geometry.TriangleMesh] = []
        for link_name, link in self.links.items():
            if link_name not in transforms:
                continue
            lt = transforms[link_name]
            for geom in link.geoms:
                gt = _transform(geom.origin_xyz, geom.origin_rpy)
                full = lt @ gt
                if geom.kind == "box":
                    sx, sy, sz = geom.size
                    m = o3d.geometry.TriangleMesh.create_box(sx, sy, sz)
                    m.translate([-sx / 2, -sy / 2, -sz / 2])
                else:
                    radius, length = geom.size
                    m = o3d.geometry.TriangleMesh.create_cylinder(radius, length)
                    m.translate([0, 0, -length / 2])
                m.paint_uniform_color(list(geom.color))
                m.compute_vertex_normals()
                m.transform(full)
                meshes.append(m)
        return meshes


def make_ground(size: float = 12.0) -> o3d.geometry.TriangleMesh:
    g = o3d.geometry.TriangleMesh.create_box(size, size, 0.02)
    g.paint_uniform_color([0.82, 0.82, 0.80])
    g.translate([-size / 2, -size / 2, -0.02])
    g.compute_vertex_normals()
    return g


def make_marker(x: float, y: float, color: tuple[float, float, float], label_size: float = 0.15) -> o3d.geometry.TriangleMesh:
    s = o3d.geometry.TriangleMesh.create_sphere(label_size)
    s.translate([x, y, label_size])
    s.paint_uniform_color(list(color))
    s.compute_vertex_normals()
    return s


def frontier_color(frontier_id: str) -> tuple[float, float, float]:
    fid = frontier_id.lower()
    if "kitchen" in fid:
        return (0.2, 0.85, 0.35)
    if "hall" in fid:
        return (0.9, 0.25, 0.2)
    if "bedroom" in fid:
        return (0.55, 0.35, 0.9)
    return (0.9, 0.75, 0.1)
