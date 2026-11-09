"""Gazebo 物理仿真 Gate（GG5–GG8）."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sim.gates import GateResult, SimGateReport
from sim.metrics import ScenarioReport


@dataclass
class GazeboGateReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.results.append(GateResult(name=name, passed=ok, detail=detail))


def check_gg5_sensors(model_sdf: Path) -> GateResult:
    if not model_sdf.exists():
        return GateResult("GG5_sensors", False, f"缺少 {model_sdf}")
    text = model_sdf.read_text(encoding="utf-8")
    has_cam = "front_camera" in text and ("type='camera'" in text or 'type="camera"' in text)
    has_lidar = "gpu_lidar" in text or "type='gpu_lidar'" in text or 'type="gpu_lidar"' in text
    ok = has_cam and has_lidar
    return GateResult(
        "GG5_sensors",
        ok,
        f"camera={has_cam} lidar={has_lidar}",
    )


def check_gg6_pose(model_name: str = "go2") -> GateResult:
    from gazebo.bridge.pose_reader import read_pose

    pose = read_pose(model_name)
    ok = pose is not None
    detail = f"pose={pose.as_dict()}" if pose else "gz model -p 无输出（Gazebo 未运行？）"
    return GateResult("GG6_pose", ok, detail)


def check_gg9_scan_frontier(tick_frontier_from: list[str]) -> GateResult:
    used = [x for x in tick_frontier_from if x == "lidar_scan"]
    ok = len(used) == len(tick_frontier_from) and len(tick_frontier_from) > 0
    detail = f"lidar_scan={len(used)}/{len(tick_frontier_from)} from={tick_frontier_from}"
    return GateResult("GG9_scan_frontier", ok, detail)


def evaluate_gg8(reports: list[ScenarioReport], *, scheduler: str) -> GazeboGateReport:
    """GG7/8：与 G0 同指标，source=gazebo."""
    from sim.gates import evaluate_g0

    g0 = evaluate_g0(reports, scheduler=scheduler)
    out = GazeboGateReport()
    for r in g0.results:
        name = r.name.replace("corridor_", "gg8_")
        out.add(name, r.passed, r.detail)

    if reports:
        r0 = reports[0]
        out.add(
            "GG7_edge_align",
            r0.align_hit_rate >= 1.0 and r0.multimodal_ready_rate >= 1.0,
            f"align={r0.align_hit_rate:.0%} ready={r0.multimodal_ready_rate:.0%}",
        )
        if scheduler == "layer_fusion_stub" and r0.name == "corridor_3frontiers":
            out.add(
                "GG8_fusion_top1",
                r0.frontier_top1_acc >= 1.0,
                f"frontier@1={r0.frontier_top1_acc:.0%}",
            )
    else:
        out.add("GG7_edge_align", False, "无场景报告")
        out.add("GG8_fusion_top1", False, "无场景报告")

    return out
