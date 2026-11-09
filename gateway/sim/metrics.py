"""仿真评测指标."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TickMetrics:
    version: int
    expected_frontier: str
    mock_pick: str
    geom_pick: str
    fusion_pick: str
    directive_pick: Optional[str]
    align_ok: bool
    layers_aligned: list[str]
    multimodal_ready: bool
    latency_ms: Optional[float]
    directive_valid: bool
    vln_actions: Optional[list[int]] = None
    expected_vln_actions: Optional[list[int]] = None
    vln_action_match: bool = False


@dataclass
class ScenarioReport:
    name: str
    scheduler: str
    ticks: list[TickMetrics] = field(default_factory=list)

    @property
    def vln_action_acc(self) -> float:
        tracked = [t for t in self.ticks if t.expected_vln_actions is not None]
        if not tracked:
            return 0.0
        return sum(1 for t in tracked if t.vln_action_match) / len(tracked)

    @property
    def action_bias_present_rate(self) -> float:
        if not self.ticks:
            return 0.0
        return sum(1 for t in self.ticks if t.vln_actions) / len(self.ticks)

    @property
    def frontier_top1_acc(self) -> float:
        if not self.ticks:
            return 0.0
        hits = sum(
            1 for t in self.ticks if t.directive_pick and t.directive_pick == t.expected_frontier
        )
        return hits / len(self.ticks)

    @property
    def geom_baseline_acc(self) -> float:
        if not self.ticks:
            return 0.0
        hits = sum(1 for t in self.ticks if t.geom_pick == t.expected_frontier)
        return hits / len(self.ticks)

    @property
    def layer_fusion_acc(self) -> float:
        if not self.ticks:
            return 0.0
        hits = sum(1 for t in self.ticks if t.fusion_pick == t.expected_frontier)
        return hits / len(self.ticks)

    @property
    def multimodal_ready_rate(self) -> float:
        if not self.ticks:
            return 0.0
        return sum(1 for t in self.ticks if t.multimodal_ready) / len(self.ticks)

    @property
    def align_hit_rate(self) -> float:
        if not self.ticks:
            return 0.0
        return sum(1 for t in self.ticks if t.align_ok) / len(self.ticks)

    @property
    def directive_valid_rate(self) -> float:
        if not self.ticks:
            return 0.0
        return sum(1 for t in self.ticks if t.directive_valid) / len(self.ticks)

    @property
    def e2e_latency_ms_p50(self) -> Optional[float]:
        vals = sorted(v for t in self.ticks if (v := t.latency_ms) is not None)
        if not vals:
            return None
        return vals[len(vals) // 2]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scheduler": self.scheduler,
            "tick_count": len(self.ticks),
            "frontier_top1_acc": round(self.frontier_top1_acc, 4),
            "geom_baseline_acc": round(self.geom_baseline_acc, 4),
            "layer_fusion_acc": round(self.layer_fusion_acc, 4),
            "multimodal_ready_rate": round(self.multimodal_ready_rate, 4),
            "align_hit_rate": round(self.align_hit_rate, 4),
            "directive_valid_rate": round(self.directive_valid_rate, 4),
            "vln_action_acc": round(self.vln_action_acc, 4),
            "action_bias_present_rate": round(self.action_bias_present_rate, 4),
            "e2e_latency_ms_p50": self.e2e_latency_ms_p50,
            "ticks": [
                {
                    "version": t.version,
                    "expected": t.expected_frontier,
                    "directive_pick": t.directive_pick,
                    "geom_pick": t.geom_pick,
                    "fusion_pick": t.fusion_pick,
                    "layers_aligned": t.layers_aligned,
                    "multimodal_ready": t.multimodal_ready,
                    "latency_ms": t.latency_ms,
                    "vln_actions": t.vln_actions,
                    "vln_action_match": t.vln_action_match,
                }
                for t in self.ticks
            ],
        }


def validate_directive(d: dict[str, Any]) -> bool:
    required = ("schema", "map_version", "candidate_frontier_ids", "ttl_ms")
    return all(k in d for k in required) and d.get("schema") == "motionslam.semantic_directive.v1"
