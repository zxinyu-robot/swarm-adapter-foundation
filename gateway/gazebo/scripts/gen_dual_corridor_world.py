#!/usr/bin/env python3
"""双 Go2 corridor 世界（motion M2 命名空间：go2_a / go2_b）."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "sim" / "scenarios" / "corridor_3frontiers.json"
OUT = ROOT / "gazebo" / "worlds" / "corridor_dual.sdf"

_gen_path = ROOT / "gazebo" / "scripts" / "gen_corridor_world.py"
_spec = importlib.util.spec_from_file_location("gen_corridor_world", _gen_path)
_gen = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_gen)


def main() -> int:
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    step = scenario["steps"][0]
    frontiers = step.get("frontiers", [])

    markers = ""
    for fr in frontiers:
        fid = str(fr.get("frontier_id", "fr"))
        pos = fr.get("position", {})
        fx, fy = float(pos.get("x", 0)), float(pos.get("y", 0))
        markers += _gen._sphere(f"marker_{fid}", fx, fy, _gen._color_for(fid))

    sdf = f"""<?xml version="1.0" ?>
<sdf version="1.9">
  <world name="corridor_dual">
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
      <direction>-0.5 0.2 -1</direction>
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

{markers}

    <include>
      <uri>model://go2_stand</uri>
      <name>go2_a</name>
      <pose>-0.8 0.0 0.21 0 0 0</pose>
    </include>
    <include>
      <uri>model://go2_stand</uri>
      <name>go2_b</name>
      <pose>0.8 0.0 0.21 0 0 3.14159</pose>
    </include>
  </world>
</sdf>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(sdf, encoding="utf-8")
    print(f"[gen_dual] {OUT} (go2_a @ -0.8,0 | go2_b @ 0.8,0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
