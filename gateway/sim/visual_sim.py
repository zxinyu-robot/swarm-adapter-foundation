#!/usr/bin/env python3
"""Go2 URDF 3D 可视化 + corridor 场景回放（Open3D）."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.go2_visual import Go2UrdfModel, frontier_color, make_ground, make_marker  # noqa: E402

try:
    import open3d as o3d
except ImportError:
    raise SystemExit("缺少 open3d，请安装: pip install open3d")

URDF_DEFAULT = ROOT / "assets" / "GO2_URDF" / "urdf" / "go2_description.urdf"
SCENARIO_DEFAULT = ROOT / "sim" / "scenarios" / "corridor_3frontiers.json"
REPORT_DIR = ROOT / "sim" / "reports" / "visual"


def _load_scenario(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_scene(model: Go2UrdfModel, step: dict) -> list:
    geoms = [make_ground()]
    pose = step.get("robot_pose", {})
    bx = float(pose.get("x", 0.0))
    by = float(pose.get("y", 0.0))
    bz = float(pose.get("z", 0.35))
    yaw = float(pose.get("yaw_deg", 0.0))
    geoms.extend(model.to_open3d_meshes(base_xyz=(bx, by, bz), base_yaw_deg=yaw))

    for fr in step.get("frontiers", []):
        fid = str(fr.get("frontier_id", ""))
        pos = fr.get("position", {})
        fx = float(pos.get("x", 0.0))
        fy = float(pos.get("y", 0.0))
        geoms.append(make_marker(fx, fy, frontier_color(fid)))
    return geoms


def _save_png_matplotlib(geoms: list, out_path: Path) -> None:
    """无 DISPLAY / 无 OSMesa 时用 matplotlib 离屏渲染."""
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import art3d

    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("#f2f4f8")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    ax.set_zlabel("Z (m)")

    for mesh in geoms:
        verts = np.asarray(mesh.vertices)
        tris = np.asarray(mesh.triangles)
        if len(verts) == 0:
            continue
        color = np.asarray(mesh.vertex_colors[0][:3]) if mesh.vertex_colors else [0.5, 0.5, 0.5]
        poly = art3d.Poly3DCollection(verts[tris], alpha=0.85, linewidths=0.05, edgecolor="k")
        poly.set_facecolor(color)
        ax.add_collection3d(poly)

    ax.set_xlim(-3, 3)
    ax.set_ylim(-1, 4)
    ax.set_zlim(-0.1, 1.2)
    ax.view_init(elev=22, azim=-58)
    ax.set_title("Go2 URDF · corridor frontiers")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def _save_png(geoms: list, out_path: Path, width: int = 1280, height: int = 720) -> None:
    try:
        vis = o3d.visualization.Visualizer()
        ok = vis.create_window(visible=False, width=width, height=height)
        if not ok:
            raise RuntimeError("create_window failed")
        for g in geoms:
            vis.add_geometry(g)
        opt = vis.get_render_option()
        if opt is None:
            raise RuntimeError("no render option")
        opt.background_color = [0.95, 0.96, 0.98]
        opt.mesh_show_back_face = True
        vis.poll_events()
        vis.update_renderer()
        ctr = vis.get_view_control()
        ctr.set_zoom(0.55)
        ctr.set_front([0.5, -0.85, -0.25])
        ctr.set_lookat([0.0, 1.0, 0.2])
        ctr.set_up([0, 0, 1])
        vis.poll_events()
        vis.update_renderer()
        vis.capture_screen_image(str(out_path), do_render=True)
        vis.destroy_window()
    except Exception as exc:
        print(f"[visual] Open3D 离屏失败 ({exc})，改用 matplotlib", flush=True)
        _save_png_matplotlib(geoms, out_path)


def _run_gui(model: Go2UrdfModel, steps: list[dict], hold_s: float) -> None:
    geoms = _build_scene(model, steps[0])
    vis = o3d.visualization.Visualizer()
    title = "RGB_ws Go2 URDF Visual Sim (corridor)"
    vis.create_window(window_name=title, width=1280, height=720)
    for g in geoms:
        vis.add_geometry(g)
    opt = vis.get_render_option()
    opt.background_color = [0.92, 0.94, 0.97]
    ctr = vis.get_view_control()
    ctr.set_zoom(0.55)
    ctr.set_front([0.55, -0.8, -0.22])
    ctr.set_lookat([0.0, 1.0, 0.2])
    ctr.set_up([0, 0, 1])

    idx = 0
    t_next = time.time() + hold_s
    while vis.poll_events():
        vis.update_renderer()
        if time.time() >= t_next:
            idx = (idx + 1) % len(steps)
            vis.clear_geometries()
            for g in _build_scene(model, steps[idx]):
                vis.add_geometry(g)
            t_next = time.time() + hold_s
        time.sleep(0.02)
    vis.destroy_window()


def main() -> int:
    p = argparse.ArgumentParser(description="Go2 URDF visual simulation")
    p.add_argument("--urdf", type=Path, default=URDF_DEFAULT)
    p.add_argument("--scenario", type=Path, default=SCENARIO_DEFAULT)
    p.add_argument("--gui", action="store_true", help="打开 Open3D 交互窗口")
    p.add_argument("--hold-s", type=float, default=2.5, help="GUI 每步停留秒数")
    p.add_argument("--no-gui", action="store_true", help="仅导出 PNG")
    args = p.parse_args()

    if not args.urdf.exists():
        print(f"URDF 不存在: {args.urdf}", file=sys.stderr)
        print("请确认 Go2_URDF.zip 已解压到 assets/GO2_URDF/", file=sys.stderr)
        return 1

    scenario = _load_scenario(args.scenario)
    steps = scenario.get("steps") or [{}]
    model = Go2UrdfModel(args.urdf)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORT_DIR / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, step in enumerate(steps):
        geoms = _build_scene(model, step)
        png = out_dir / f"step_{i+1:02d}.png"
        _save_png(geoms, png)
        print(f"[visual] saved {png}", flush=True)

    meta = {
        "scenario": scenario.get("name", args.scenario.stem),
        "urdf": str(args.urdf),
        "steps": len(steps),
        "output_dir": str(out_dir),
        "legend": {
            "green": "fr_kitchen",
            "red": "fr_hall",
            "purple": "fr_bedroom",
        },
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[visual] report -> {out_dir}", flush=True)

    use_gui = args.gui or (not args.no_gui and os.environ.get("DISPLAY"))
    if use_gui:
        print("[visual] 启动 Open3D GUI（关闭窗口结束）...", flush=True)
        _run_gui(model, steps, args.hold_s)
    else:
        print("[visual] 无 DISPLAY，已仅导出 PNG", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
