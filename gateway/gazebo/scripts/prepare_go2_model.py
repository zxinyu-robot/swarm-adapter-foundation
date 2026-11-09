#!/usr/bin/env python3
"""从 assets/GO2_URDF 生成 Gazebo 可用 go2_description 模型."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "assets" / "GO2_URDF"
ZIP = ROOT / "Go2_URDF.zip"
DST = ROOT / "gazebo" / "models" / "go2_description"
URDF_IN = "urdf/go2_description.urdf"
URDF_OUT = DST / URDF_IN


def _ensure_src() -> None:
    if not SRC.exists():
        if not ZIP.exists():
            print(f"缺少 {ZIP}", file=sys.stderr)
            sys.exit(1)
        import zipfile

        print(f"[prepare] 解压 {ZIP.name}")
        with zipfile.ZipFile(ZIP, "r") as zf:
            zf.extractall(ROOT / "assets")


def _fix_urdf(text: str) -> str:
    # package://go2_description/dae/foo.dae → model://go2_description/dae/foo.dae
    text = text.replace(
        "package://go2_description/dae/",
        "model://go2_description/dae/",
    )
    return text


def _write_model_config() -> None:
    (DST / "model.config").write_text(
        """<?xml version="1.0"?>
<model>
  <name>go2_description</name>
  <version>1.0</version>
  <sdf version="1.9">model.sdf</sdf>
  <author>
    <name>Unitree / RGB_ws</name>
  </author>
  <description>Go2 quadruped from Go2_URDF.zip</description>
</model>
""",
        encoding="utf-8",
    )


def _try_gz_sdf(urdf_path: Path, sdf_path: Path) -> bool:
    try:
        proc = subprocess.run(
            ["gz", "sdf", "-p", str(urdf_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        sdf_path.write_text(proc.stdout, encoding="utf-8")
        print(f"[prepare] model.sdf <- gz sdf -p ({sdf_path.stat().st_size} bytes)")
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"[prepare] WARN: gz sdf 不可用 ({exc})，将使用 fallback model.sdf")
        return False


def _write_fallback_sdf() -> None:
    """无 gz 命令时的最小可 spawn 模型（box 机身 + 四条腿占位）."""
    sdf = """<?xml version="1.0" ?>
<sdf version="1.9">
  <model name="go2_description">
    <pose>0 0 0.35 0 0 0</pose>
    <link name="base">
      <inertial><mass>6.921</mass></inertial>
      <collision name="body"><geometry><box><size>0.3762 0.0935 0.114</size></box></geometry></collision>
      <visual name="body"><geometry><box><size>0.3762 0.0935 0.114</size></box></geometry>
        <material><ambient>0.35 0.35 0.38 1</ambient></material></visual>
    </link>
  </model>
</sdf>
"""
    (DST / "model.sdf").write_text(sdf, encoding="utf-8")
    print("[prepare] fallback model.sdf（简化 box；安装 gz 后请重跑以生成完整 SDF）")


def main() -> int:
    _ensure_src()
    if DST.exists():
        shutil.rmtree(DST, ignore_errors=True)
    shutil.copytree(SRC, DST, dirs_exist_ok=True)

    raw = URDF_OUT.read_text(encoding="utf-8")
    URDF_OUT.write_text(_fix_urdf(raw), encoding="utf-8")
    _write_model_config()

    if not _try_gz_sdf(URDF_OUT, DST / "model.sdf"):
        _write_fallback_sdf()

    # GG5：注入相机 + LiDAR
    inject_script = ROOT / "gazebo" / "scripts" / "inject_sensors.py"
    if inject_script.exists():
        subprocess.run([sys.executable, str(inject_script)], check=False)

    nav_script = ROOT / "gazebo" / "scripts" / "inject_nav_plugin.py"
    if nav_script.exists():
        subprocess.run([sys.executable, str(nav_script)], check=False)

    stand_script = ROOT / "gazebo" / "scripts" / "inject_sim_physics.py"
    if stand_script.exists():
        subprocess.run([sys.executable, str(stand_script)], check=False)

    gen_stand = ROOT / "gazebo" / "scripts" / "gen_go2_stand.py"
    if gen_stand.exists():
        subprocess.run([sys.executable, str(gen_stand)], check=False)

    print(f"[prepare] OK -> {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
