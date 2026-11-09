#!/usr/bin/env python3
"""Gazebo 仿真用物理设置：关闭重力（运动学导航保持直立），清理无效 initial_position."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL_SDF = ROOT / "gazebo" / "models" / "go2_description" / "model.sdf"


def inject(sdf_path: Path = MODEL_SDF) -> bool:
    if not sdf_path.exists():
        print(f"[sim_physics] 缺少 {sdf_path}", file=sys.stderr)
        return False

    text = sdf_path.read_text(encoding="utf-8")

    # 清理无效标签
    text = re.sub(r"\s*<initial_position>[^<]*</initial_position>", "", text)

    if "<enable_gravity>false</enable_gravity>" in text:
        print("[sim_physics] enable_gravity=false 已存在")
        return True

    text = text.replace(
        "<link name='base'>",
        "<link name='base'>\n      <enable_gravity>false</enable_gravity>",
        1,
    )
    text = re.sub(r"\s*<gravity>false</gravity>", "", text)

    sdf_path.write_text(text, encoding="utf-8")
    print(f"[sim_physics] OK -> {sdf_path}")
    return True


def main() -> int:
    return 0 if inject() else 1


if __name__ == "__main__":
    raise SystemExit(main())
