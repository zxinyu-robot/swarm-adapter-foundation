"""端侧本地训练：用岭回归拟合 utility ≈ w · phi(link, action)。"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .features import FEATURE_DIM, make_features, outcome_utility
from .records import TrainingSample


def design_matrix(samples: Sequence[TrainingSample]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([make_features(s.link, s.action) for s in samples], dtype=np.float64)
    y = np.array([outcome_utility(s.outcome) for s in samples], dtype=np.float64)
    return x.reshape(len(samples), FEATURE_DIM), y


def fit_ridge(
    samples: Sequence[TrainingSample],
    initial: np.ndarray | None = None,
    l2: float = 1e-2,
) -> np.ndarray:
    """以 initial（全局模型）为先验的岭回归：min |Xw - y|² + l2 |w - initial|²。

    样本为空时原样返回 initial，保证本轮不会产生无意义的更新。
    """
    prior = np.zeros(FEATURE_DIM) if initial is None else np.asarray(initial, np.float64)
    if prior.shape != (FEATURE_DIM,):
        raise ValueError(f"initial weights must have shape ({FEATURE_DIM},)")
    if not samples:
        return prior.copy()
    x, y = design_matrix(samples)
    a = x.T @ x + l2 * np.eye(FEATURE_DIM)
    b = x.T @ y + l2 * prior
    return np.linalg.solve(a, b)


def mean_squared_error(samples: Sequence[TrainingSample], weights: np.ndarray) -> float:
    if not samples:
        return 0.0
    x, y = design_matrix(samples)
    return float(np.mean((x @ weights - y) ** 2))
