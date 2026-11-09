#!/usr/bin/env python3
"""生成单 link 直立 Go2 + 四条腿视觉（站立 FK，无关节物理）."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_DAE = ROOT / "gazebo" / "models" / "go2_description" / "dae"
DST = ROOT / "gazebo" / "models" / "go2_stand"
MESH_DIR = DST / "meshes"
sys.path.insert(0, str(ROOT / "gazebo" / "scripts"))
from leg_fk_stand import all_leg_visuals, visuals_to_sdf  # noqa: E402

MESHES = (
    "trunk.dae",
    "base.dae",
    "hip.dae",
    "thigh.dae",
    "thigh_mirror.dae",
    "calf.dae",
    "calf_mirror.dae",
    "foot.dae",
)


def main() -> int:
    if not SRC_DAE.exists():
        print(f"[go2_stand] 请先运行 prepare_go2_model.sh（缺少 {SRC_DAE}）", file=sys.stderr)
        return 1

    if DST.exists():
        shutil.rmtree(DST, ignore_errors=True)
    MESH_DIR.mkdir(parents=True)

    for name in MESHES:
        src = SRC_DAE / name
        if src.exists():
            shutil.copy2(src, MESH_DIR / name)

    if not (MESH_DIR / "trunk.dae").exists() and (MESH_DIR / "base.dae").exists():
        shutil.copy2(MESH_DIR / "base.dae", MESH_DIR / "trunk.dae")

    leg_sdf = visuals_to_sdf(all_leg_visuals())

    (DST / "model.config").write_text(
        """<?xml version="1.0"?>
<model>
  <name>go2_stand</name>
  <version>1.1</version>
  <sdf version="1.9">model.sdf</sdf>
  <description>Go2 upright body + standing leg visuals (kinematic sim)</description>
</model>
""",
        encoding="utf-8",
    )

    sdf = f"""<?xml version="1.0" ?>
<sdf version="1.9">
  <model name="go2_stand">
    <link name="base">
      <enable_gravity>false</enable_gravity>
      <inertial>
        <mass>6.923</mass>
        <inertia>
          <ixx>0.1</ixx><iyy>0.1</iyy><izz>0.1</izz>
        </inertia>
      </inertial>
      <visual name="trunk">
        <pose>0 0 0 0 0 0</pose>
        <geometry>
          <mesh><uri>model://go2_stand/meshes/trunk.dae</uri></mesh>
        </geometry>
      </visual>
{leg_sdf}
      <collision name="body">
        <geometry>
          <box><size>0.3762 0.0935 0.114</size></box>
        </geometry>
      </collision>
      <sensor name="front_camera" type="camera">
        <pose>0.29 0 -0.05 0 0 0</pose>
        <camera>
          <horizontal_fov>1.047</horizontal_fov>
          <image><width>640</width><height>480</height><format>R8G8B8</format></image>
          <clip><near>0.08</near><far>30</far></clip>
        </camera>
        <always_on>1</always_on>
        <update_rate>15</update_rate>
        <topic>front_camera</topic>
      </sensor>
      <sensor name="lidar" type="gpu_lidar">
        <pose>0 0 0.08 0 0 0</pose>
        <lidar>
          <scan>
            <horizontal>
              <samples>360</samples>
              <min_angle>-3.14159</min_angle>
              <max_angle>3.14159</max_angle>
            </horizontal>
          </scan>
          <range><min>0.12</min><max>12</max></range>
        </lidar>
        <always_on>1</always_on>
        <update_rate>10</update_rate>
        <topic>lidar</topic>
      </sensor>
    </link>
  </model>
</sdf>
"""
    (DST / "model.sdf").write_text(sdf, encoding="utf-8")
    print(f"[go2_stand] OK -> {DST} (trunk + 16 leg visuals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
