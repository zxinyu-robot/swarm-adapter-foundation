"""读取 C++ RingStrategyStore 写出的 JSONL 分段文件，按 decision_id 配对成训练样本。"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .features import CommAction, LinkFeatures, Outcome


@dataclass(frozen=True)
class TrainingSample:
    decision_id: int
    message_class: str
    policy_version: int
    link: LinkFeatures
    action: CommAction
    outcome: Outcome


def iter_lines(paths: Iterable[str | os.PathLike[str]]) -> Iterable[dict]:
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    # 掉电可能留下半行，跳过而不是让整轮训练失败。
                    continue


def segment_paths(directory: str | os.PathLike[str]) -> list[Path]:
    return sorted(Path(directory).glob("segment_*.jsonl"))


def load_samples(
    paths: Iterable[str | os.PathLike[str]],
    min_version: int = 0,
    max_version: int | None = None,
) -> list[TrainingSample]:
    """只返回有回执且 trainable 的样本；未配对或时钟不可信的样本丢弃。"""
    decisions: dict[int, dict] = {}
    outcomes: dict[int, dict] = {}
    for row in iter_lines(paths):
        table = row.get("table")
        if table == "config_decision":
            decisions.setdefault(int(row["decision_id"]), row)
        elif table == "outcome":
            outcomes.setdefault(int(row["decision_id"]), row)

    samples: list[TrainingSample] = []
    for decision_id, d in decisions.items():
        o = outcomes.get(decision_id)
        if o is None or not o.get("trainable", False):
            continue
        version = int(d["policy_version"])
        if version < min_version or (max_version is not None and version > max_version):
            continue
        samples.append(
            TrainingSample(
                decision_id=decision_id,
                message_class=str(d["message_class"]),
                policy_version=version,
                link=LinkFeatures(
                    float(d["packet_loss_ratio"]),
                    float(d["latency_s"]),
                    float(d["queue_fill_ratio"]),
                    float(d["age_ratio"]),
                ),
                action=CommAction(
                    float(d["rate_scale"]),
                    int(d["compression_level"]),
                    bool(d["reliable"]),
                ),
                outcome=Outcome(
                    float(o["delivered_ratio"]),
                    float(o["on_time_ratio"]),
                    float(o["bandwidth_ratio"]),
                ),
            )
        )
    samples.sort(key=lambda s: s.decision_id)
    return samples
