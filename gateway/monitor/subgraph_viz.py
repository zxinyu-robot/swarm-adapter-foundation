"""sparse_subgraph.v1 → Foxglove SceneUpdate."""
from __future__ import annotations

import math
from typing import Any, Optional

from foxglove.messages import (
    ArrowPrimitive,
    Color,
    CubePrimitive,
    LinePrimitive,
    LinePrimitiveLineType,
    Point3,
    Pose,
    Quaternion,
    SceneEntity,
    SceneUpdate,
    TextPrimitive,
    Vector3,
)


def _yaw_quat(yaw_rad: float) -> Quaternion:
    return Quaternion(x=0.0, y=0.0, z=math.sin(yaw_rad * 0.5), w=math.cos(yaw_rad * 0.5))


def _pos(obj: dict[str, Any], default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if not obj:
        return default
    return (
        float(obj.get("x", default[0])),
        float(obj.get("y", default[1])),
        float(obj.get("z", default[2])),
    )


def _vec3(t: tuple[float, float, float]) -> Vector3:
    return Vector3(x=t[0], y=t[1], z=t[2])


def _geom_color(score: float) -> Color:
    t = max(0.0, min(1.0, float(score)))
    return Color(r=1.0 - t, g=0.3 + 0.7 * t, b=0.2, a=0.9)


def subgraph_to_scene(
    subgraph: dict[str, Any],
    *,
    frame_id: str = "map",
    highlight_frontiers: Optional[list[str]] = None,
) -> SceneUpdate:
    """将 L0 子图快照转为 3D 标注（节点方块、边线、frontier 箭头）."""
    highlight = set(highlight_frontiers or [])
    node_pos: dict[str, tuple[float, float, float]] = {}
    entities: list[SceneEntity] = []

    for node in subgraph.get("nodes") or []:
        nid = str(node.get("node_id", ""))
        if not nid:
            continue
        c = _pos(node.get("centroid") or {})
        node_pos[nid] = c
        visited = bool(node.get("visited"))
        entities.append(
            SceneEntity(
                frame_id=frame_id,
                id=f"node_{nid}",
                cubes=[
                    CubePrimitive(
                        pose=Pose(position=_vec3(c), orientation=Quaternion(x=0, y=0, z=0, w=1)),
                        size=Vector3(x=0.45, y=0.45, z=0.08),
                        color=Color(r=0.4, g=0.4, b=0.85, a=0.85)
                        if visited
                        else Color(r=0.25, g=0.55, b=0.95, a=0.75),
                    )
                ],
                texts=[
                    TextPrimitive(
                        pose=Pose(
                            position=Vector3(x=c[0], y=c[1], z=c[2] + 0.25),
                            orientation=Quaternion(x=0, y=0, z=0, w=1),
                        ),
                        text=nid,
                        font_size=0.18,
                        color=Color(r=1, g=1, b=1, a=0.9),
                    )
                ],
            )
        )

    edge_lines: list[Point3] = []
    for edge in subgraph.get("edges") or []:
        src = str(edge.get("src", ""))
        dst = str(edge.get("dst", ""))
        if src not in node_pos or dst not in node_pos:
            continue
        a, b = node_pos[src], node_pos[dst]
        edge_lines.extend(
            [
                Point3(x=a[0], y=a[1], z=a[2] + 0.05),
                Point3(x=b[0], y=b[1], z=b[2] + 0.05),
            ]
        )

    if edge_lines:
        entities.append(
            SceneEntity(
                frame_id=frame_id,
                id="edges",
                lines=[
                    LinePrimitive(
                        type=LinePrimitiveLineType.LineList,
                        pose=Pose(
                            position=Vector3(x=0, y=0, z=0),
                            orientation=Quaternion(x=0, y=0, z=0, w=1),
                        ),
                        thickness=0.04,
                        scale_invariant=False,
                        points=edge_lines,
                        color=Color(r=0.6, g=0.6, b=0.6, a=0.8),
                    )
                ],
            )
        )

    for fr in subgraph.get("frontiers") or []:
        fid = str(fr.get("frontier_id", ""))
        if not fid:
            continue
        p = _pos(fr.get("position") or {})
        yaw = float(fr.get("normal_yaw_rad", 0.0))
        score = float(fr.get("geom_score", 0.5))
        is_pick = fid in highlight
        entities.append(
            SceneEntity(
                frame_id=frame_id,
                id=f"frontier_{fid}",
                arrows=[
                    ArrowPrimitive(
                        pose=Pose(position=_vec3(p), orientation=_yaw_quat(yaw)),
                        shaft_length=0.35,
                        shaft_diameter=0.06,
                        head_length=0.12,
                        head_diameter=0.14,
                        color=Color(r=1.0, g=0.85, b=0.1, a=1.0)
                        if is_pick
                        else _geom_color(score),
                    )
                ],
                texts=[
                    TextPrimitive(
                        pose=Pose(
                            position=Vector3(x=p[0], y=p[1], z=p[2] + 0.3),
                            orientation=Quaternion(x=0, y=0, z=0, w=1),
                        ),
                        text=f"{fid} ({score:.2f})",
                        font_size=0.16,
                        color=Color(r=1, g=1, b=0.3, a=1) if is_pick else Color(r=0.9, g=0.9, b=0.9, a=0.9),
                    )
                ],
            )
        )

    return SceneUpdate(entities=entities)


def robot_scene(subgraph: dict[str, Any], *, frame_id: str = "map") -> SceneUpdate:
    pose = subgraph.get("robot_pose") or {}
    p = _pos(pose)
    yaw = float(pose.get("yaw_rad", pose.get("yaw_deg", 0.0)))
    if "yaw_deg" in pose and "yaw_rad" not in pose:
        yaw = math.radians(yaw)
    return SceneUpdate(
        entities=[
            SceneEntity(
                frame_id=frame_id,
                id="robot",
                arrows=[
                    ArrowPrimitive(
                        pose=Pose(position=_vec3(p), orientation=_yaw_quat(yaw)),
                        shaft_length=0.5,
                        shaft_diameter=0.1,
                        head_length=0.15,
                        head_diameter=0.18,
                        color=Color(r=0.1, g=0.9, b=0.3, a=1.0),
                    )
                ],
            )
        ]
    )
