"""一轮本地训练的纯逻辑，不依赖 Flower，便于单测和替换联邦框架。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import policy_file
from ..records import load_samples, segment_paths
from ..training import fit_ridge, mean_squared_error


@dataclass(frozen=True)
class RoundResult:
    weights: np.ndarray
    num_samples: int
    mse_before: float
    mse_after: float


def install_global_policy(
    policy_path: str | os.PathLike[str], weights: np.ndarray, server_round: int
) -> None:
    """把全局模型写成策略文件，交给 C++ FilePolicyClient → PolicyGate 做旁路比对。

    policy_version 取联邦轮次号：轮次单调递增，端侧据此拒收旧版本。
    """
    policy_file.save(
        policy_path,
        policy_file.PolicyWeights(
            policy_version=server_round,
            round_id=server_round,
            weights=tuple(float(w) for w in weights),
        ),
    )


def run_local_round(
    records_dir: str | os.PathLike[str],
    global_weights: np.ndarray,
    l2: float = 1e-2,
) -> RoundResult:
    samples = load_samples(segment_paths(Path(records_dir)))
    weights = fit_ridge(samples, initial=global_weights, l2=l2)
    return RoundResult(
        weights=weights,
        num_samples=len(samples),
        mse_before=mean_squared_error(samples, global_weights),
        mse_after=mean_squared_error(samples, weights),
    )
