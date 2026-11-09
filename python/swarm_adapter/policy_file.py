"""策略文件读写，格式与 src/strategy/policy_model.cpp 一致（见 docs/contracts.md）。"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from .features import FEATURE_DIM

HEADER = "swarm_adapter.policy v1"


@dataclass(frozen=True)
class PolicyWeights:
    policy_version: int
    round_id: int
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.policy_version <= 0:
            raise ValueError("policy_version must be positive")
        if self.round_id < 0:
            raise ValueError("round_id must be non-negative")
        if len(self.weights) != FEATURE_DIM:
            raise ValueError(f"expected {FEATURE_DIM} weights, got {len(self.weights)}")
        if not all(math.isfinite(w) for w in self.weights):
            raise ValueError("weights must be finite")


def save(path: str | os.PathLike[str], policy: PolicyWeights) -> None:
    """原子写：先写临时文件再 rename，C++ 端不会读到半截文件。"""
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    lines = [
        HEADER,
        f"policy_version {policy.policy_version}",
        f"round_id {policy.round_id}",
        f"feature_dim {FEATURE_DIM}",
        "weights " + " ".join(repr(float(w)) for w in policy.weights),
    ]
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def load(path: str | os.PathLike[str]) -> PolicyWeights:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != HEADER:
        raise ValueError("missing policy header")
    fields: dict[str, list[str]] = {}
    for line in lines[1:]:
        if not line or line.startswith("#"):
            continue
        key, *values = line.split()
        if key not in {"policy_version", "round_id", "feature_dim", "weights"}:
            raise ValueError(f"unknown key {key!r}")
        fields[key] = values
    if "feature_dim" in fields and int(fields["feature_dim"][0]) != FEATURE_DIM:
        raise ValueError("feature_dim mismatch")
    return PolicyWeights(
        policy_version=int(fields["policy_version"][0]),
        round_id=int(fields["round_id"][0]),
        weights=tuple(float(w) for w in fields["weights"]),
    )
