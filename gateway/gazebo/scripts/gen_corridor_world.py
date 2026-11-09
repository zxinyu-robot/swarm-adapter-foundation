#!/usr/bin/env python3
"""从 sim/scenarios/corridor_3frontiers.json 生成 Gazebo corridor.sdf."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "sim" / "scenarios" / "corridor_3frontiers.json"
OUT = ROOT / "gazebo" / "worlds" / "corridor.sdf"

COLORS = {
    "kitchen": (0.2, 0.85, 0.35, 1.0),
    "hall": (0.9, 0.25, 0.2, 1.0),
    "bedroom": (0.55, 0.35, 0.9, 1.0),
}


def _color_for(fid: str) -> tuple[float, float, float, float]:
    low = fid.lower()
    for key, rgba in COLORS.items():
        if key in low:
            return rgba
    return (0.9, 0.75, 0.1, 1.0)


def _sphere(name: str, x: float, y: float, rgba: tuple[float, float, float, float]) -> str:
    r, g, b, a = rgba
    return f"""
    <model name="{name}">
      <static>true</static>
      <pose>{x} {y} 0.25 0 0 0</pose>
      <link name="link">
        <visual name="v">
          <geometry><sphere><radius>0.15</radius></sphere></geometry>
          <material><ambient>{r} {g} {b} {a}</ambient><diffuse>{r} {g} {b} {a}</diffuse></material>
        </visual>
      </link>
    </model>"""


def main() -> int:
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    step = scenario["steps"][0]
    frontiers = step.get("frontiers", [])
    pose = step.get("robot_pose", {})
    rx, ry = float(pose.get("x", 0)), float(pose.get("y", 0))

    markers = ""
    for fr in frontiers:
        fid = str(fr.get("frontier_id", "fr"))
        pos = fr.get("position", {})
        fx, fy = float(pos.get("x", 0)), float(pos.get("y", 0))
        markers += _sphere(f"marker_{fid}", fx, fy, _color_for(fid))

    sdf = f"""<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="corridor">
    <physics name="1ms" type="ode">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>

    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>

    <light type="directional" name="sun">
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse>
      <specular>0.3 0.3 0.3 1</specular>
      <direction>-0.5 0.2 -1</direction>
      <cast_shadows>true</cast_shadows>
    </light>

    <model name="ground">
      <static>true</static>
      <link name="link">
        <collision name="c">
          <geometry><plane><normal>0 0 1</normal><size>20 20</size></plane></geometry>
        </collision>
        <visual name="v">
          <geometry><plane><normal>0 0 1</normal><size>20 20</size></plane></geometry>
          <material><ambient>0.85 0.85 0.82 1</ambient></material>
        </visual>
      </link>
    </model>

    <model name="wall_left">
      <static>true</static>
      <pose>-3 2 0.5 0 0 0</pose>
      <link name="link">
        <collision name="c"><geometry><box><size>0.1 8 1</size></box></geometry></collision>
        <visual name="v"><geometry><box><size>0.1 8 1</size></box></geometry>
          <material><ambient>0.7 0.7 0.75 1</ambient></material></visual>
      </link>
    </model>

    <model name="wall_right">
      <static>true</static>
      <pose>3 2 0.5 0 0 0</pose>
      <link name="link">
        <collision name="c"><geometry><box><size>0.1 8 1</size></box></geometry></collision>
        <visual name="v"><geometry><box><size>0.1 8 1</size></box></geometry>
          <material><ambient>0.7 0.7 0.75 1</ambient></material></visual>
      </link>
    </model>

{markers}

    <include>
      <uri>model://go2_stand</uri>
      <name>go2</name>
      <pose>{rx} {ry} 0.21 0 0 0</pose>
    </include>
  </world>
</sdf>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(sdf, encoding="utf-8")
    print(f"[gen] {OUT} ({len(frontiers)} frontiers, go2 @ {rx},{ry})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
