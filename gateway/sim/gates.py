"""G0 本机仿真 Gate 门槛."""
from __future__ import annotations

from dataclasses import dataclass, field

from sim.metrics import ScenarioReport


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


@dataclass
class SimGateReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.results.append(GateResult(name=name, passed=ok, detail=detail))


def evaluate_g0(reports: list[ScenarioReport], *, scheduler: str) -> SimGateReport:
    """本机协议级仿真 G0：连通、对齐、分层、语义命中（随 scheduler 变化）."""
    out = SimGateReport()
    if not reports:
        out.add("has_scenarios", False, "无场景报告")
        return out

    for r in reports:
        prefix = r.name

        out.add(
            f"{prefix}_directive_received",
            len(r.ticks) > 0 and r.align_hit_rate >= 1.0,
            f"align/directive={r.align_hit_rate:.0%} ticks={len(r.ticks)}",
        )
        out.add(
            f"{prefix}_directive_valid",
            r.directive_valid_rate >= 1.0,
            f"valid={r.directive_valid_rate:.0%}",
        )
        out.add(
            f"{prefix}_multimodal_ready",
            r.multimodal_ready_rate >= 1.0,
            f"ready={r.multimodal_ready_rate:.0%}",
        )

        if scheduler in ("layer_fusion_stub", "qwen_vl"):
            out.add(
                f"{prefix}_frontier_top1",
                r.frontier_top1_acc >= 1.0,
                f"frontier@1={r.frontier_top1_acc:.0%}",
            )

        if scheduler == "streamvln":
            out.add(
                f"{prefix}_action_bias",
                r.action_bias_present_rate >= 1.0,
                f"action_bias={r.action_bias_present_rate:.0%}",
            )
            if any(t.expected_vln_actions for t in r.ticks):
                out.add(
                    f"{prefix}_vln_actions",
                    r.vln_action_acc >= 1.0,
                    f"vln_action={r.vln_action_acc:.0%}",
                )
            out.add(
                f"{prefix}_frontier_top1",
                r.frontier_top1_acc >= 1.0,
                f"frontier@1={r.frontier_top1_acc:.0%}",
            )

        if r.name == "corridor_3frontiers" and scheduler in ("layer_fusion_stub", "qwen_vl"):
            out.add(
                "corridor_fusion_beats_geom",
                r.layer_fusion_acc >= 1.0 and r.geom_baseline_acc < 1.0,
                f"fusion={r.layer_fusion_acc:.0%} geom={r.geom_baseline_acc:.0%}",
            )

    return out
