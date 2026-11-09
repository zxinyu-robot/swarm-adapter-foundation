#!/usr/bin/env python3
"""移除 VelocityControl（全关节模型上易翻倒）；导航改走运动学 set_pose."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_SDF = ROOT / "gazebo" / "models" / "go2_description" / "model.sdf"

PLUGIN_PAT = re.compile(
    r"\s*<plugin filename='gz-sim-velocity-control-system'[\s\S]*?</plugin>\s*",
    re.MULTILINE,
)


def strip_velocity_control(sdf_path: Path = MODEL_SDF) -> bool:
    if not sdf_path.exists():
        return False
    text = sdf_path.read_text(encoding="utf-8")
    if "velocity-control-system" not in text:
        print("[inject_nav] 无 VelocityControl，跳过")
        return True
    text = PLUGIN_PAT.sub("\n", text)
    sdf_path.write_text(text, encoding="utf-8")
    print(f"[inject_nav] 已移除 VelocityControl -> {sdf_path}")
    return True


def main() -> int:
    return 0 if strip_velocity_control() else 1


if __name__ == "__main__":
    raise SystemExit(main())
