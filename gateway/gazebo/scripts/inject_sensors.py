#!/usr/bin/env python3
"""向 go2 model.sdf 的 base link 注入 Gazebo Harmonic 相机 + 2D LiDAR."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_SDF = ROOT / "gazebo" / "models" / "go2_description" / "model.sdf"

SENSOR_BLOCK = """
    <sensor name='front_camera' type='camera'>
      <pose>0.29 0 -0.05 0 0 0</pose>
      <camera>
        <horizontal_fov>1.047</horizontal_fov>
        <image>
          <width>640</width>
          <height>480</height>
          <format>R8G8B8</format>
        </image>
        <clip>
          <near>0.08</near>
          <far>30</far>
        </clip>
      </camera>
      <always_on>1</always_on>
      <update_rate>15</update_rate>
      <visualize>true</visualize>
      <topic>front_camera</topic>
    </sensor>
    <sensor name='lidar' type='gpu_lidar'>
      <pose>0 0 0.08 0 0 0</pose>
      <lidar>
        <scan>
          <horizontal>
            <samples>360</samples>
            <resolution>1</resolution>
            <min_angle>-3.14159</min_angle>
            <max_angle>3.14159</max_angle>
          </horizontal>
        </scan>
        <range>
          <min>0.12</min>
          <max>12</max>
          <resolution>0.01</resolution>
        </range>
      </lidar>
      <always_on>1</always_on>
      <update_rate>10</update_rate>
      <visualize>true</visualize>
      <topic>lidar</topic>
    </sensor>
"""


def inject(sdf_path: Path = MODEL_SDF) -> bool:
    if not sdf_path.exists():
        print(f"[inject_sensors] 缺少 {sdf_path}", file=sys.stderr)
        return False

    text = sdf_path.read_text(encoding="utf-8")
    if "name='front_camera'" in text or 'name="front_camera"' in text:
        print(f"[inject_sensors] 已含传感器，跳过 {sdf_path}")
        return True

    # 在第一个 base link 的 </link> 前插入（go2 URDF 转换后 link 名为 base）
    pat = re.compile(
        r"(<link\s+name=['\"]base['\"][\s\S]*?)(</link>)",
        re.MULTILINE,
    )
    m = pat.search(text)
    if not m:
        print("[inject_sensors] WARN: 未找到 base link，追加到 model 末尾", file=sys.stderr)
        text = text.replace("</model>", f"  <link name='sensors_anchor'>{SENSOR_BLOCK}\n    </link>\n  </model>")
    else:
        text = pat.sub(rf"\1{SENSOR_BLOCK}\n    \2", text, count=1)

    sdf_path.write_text(text, encoding="utf-8")
    print(f"[inject_sensors] OK -> {sdf_path}")
    return True


def main() -> int:
    ok = inject()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
