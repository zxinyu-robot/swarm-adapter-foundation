"""与 C++ strategy::make_features / outcome_utility 逐位一致的特征函数。

修改这里必须同步修改 src/strategy/features.cpp，并重新生成 tests/fixtures/feature_golden.txt。
"""

from __future__ import annotations

from dataclasses import dataclass

FEATURE_DIM = 12
MAX_COMPRESSION_LEVEL = 9
MAX_AGE_RATIO = 4.0


@dataclass(frozen=True)
class LinkFeatures:
    packet_loss_ratio: float
    latency_s: float
    queue_fill_ratio: float
    age_ratio: float


@dataclass(frozen=True)
class CommAction:
    rate_scale: float
    compression_level: int
    reliable: bool


@dataclass(frozen=True)
class Outcome:
    delivered_ratio: float
    on_time_ratio: float
    bandwidth_ratio: float


def make_features(link: LinkFeatures, action: CommAction) -> list[float]:
    loss = link.packet_loss_ratio
    latency = link.latency_s
    queue = link.queue_fill_ratio
    age = min(link.age_ratio, MAX_AGE_RATIO)
    rate = action.rate_scale
    compression = action.compression_level / MAX_COMPRESSION_LEVEL
    reliable = 1.0 if action.reliable else 0.0
    return [
        1.0,
        loss,
        latency,
        queue,
        age,
        rate,
        compression,
        reliable,
        loss * rate,
        loss * reliable,
        latency * rate,
        queue * rate,
    ]


def outcome_utility(outcome: Outcome) -> float:
    return (
        outcome.on_time_ratio
        - 0.2 * outcome.bandwidth_ratio
        - 0.5 * (1.0 - outcome.delivered_ratio)
    )
