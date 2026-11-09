import json
import random

import numpy as np
from swarm_adapter import policy_file
from swarm_adapter.features import CommAction, LinkFeatures, make_features
from swarm_adapter.fl.local_round import install_global_policy, run_local_round
from swarm_adapter.records import load_samples, segment_paths
from swarm_adapter.training import fit_ridge, mean_squared_error

TRUE_W = np.array([0.9, -1.0, -0.5, -0.2, -0.1, 0.05, -0.05, 0.1, -0.5, 0.3, -0.4, -0.3])


def write_segment(path, n, seed, version=0, trainable=True):
    rng = random.Random(seed)
    lines = []
    for i in range(1, n + 1):
        link = LinkFeatures(
            rng.uniform(0, 0.3), rng.uniform(0, 0.3), rng.uniform(0, 1), rng.uniform(0, 3)
        )
        action = CommAction(rng.choice([0.25, 0.5, 1.0]), rng.choice([0, 3, 6]), rng.random() < 0.5)
        utility = float(TRUE_W @ np.array(make_features(link, action)))
        lines.append(
            {
                "table": "config_decision",
                "decision_id": seed * 10_000 + i,
                "time_ns": i,
                "robot_id": 1,
                "message_class": "keyframe",
                "packet_loss_ratio": link.packet_loss_ratio,
                "latency_s": link.latency_s,
                "queue_fill_ratio": link.queue_fill_ratio,
                "age_ratio": link.age_ratio,
                "rate_scale": action.rate_scale,
                "compression_level": action.compression_level,
                "reliable": action.reliable,
                "source": "local_rule",
                "policy_version": version,
            }
        )
        # outcome_utility == utility：on_time = utility, delivered = 1, bandwidth = 0
        lines.append(
            {
                "table": "outcome",
                "decision_id": seed * 10_000 + i,
                "time_ns": i,
                "delivered_ratio": 1.0,
                "on_time_ratio": utility,
                "bandwidth_ratio": 0.0,
                "clock_uncertainty_ns": 1000,
                "trainable": trainable,
            }
        )
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n{\"table\": \"outc")


def test_load_samples_pairs_and_filters(tmp_path):
    write_segment(tmp_path / "segment_000001.jsonl", 5, seed=1, version=2)
    write_segment(tmp_path / "segment_000002.jsonl", 5, seed=2, version=3, trainable=False)
    paths = segment_paths(tmp_path)
    assert len(paths) == 2
    samples = load_samples(paths)
    assert len(samples) == 5, "untrainable and truncated rows dropped"
    assert load_samples(paths, min_version=3) == []


def test_ridge_recovers_linear_utility(tmp_path):
    write_segment(tmp_path / "segment_000001.jsonl", 400, seed=3)
    samples = load_samples(segment_paths(tmp_path))
    w = fit_ridge(samples, l2=1e-8)
    assert mean_squared_error(samples, w) < 1e-10
    assert fit_ridge([], initial=TRUE_W).tolist() == TRUE_W.tolist()


def test_local_round_and_install(tmp_path):
    write_segment(tmp_path / "segment_000001.jsonl", 200, seed=4)
    result = run_local_round(tmp_path, np.zeros(12), l2=1e-6)
    assert result.num_samples == 200
    assert result.mse_after < result.mse_before
    install_global_policy(tmp_path / "policy.txt", result.weights, server_round=3)
    loaded = policy_file.load(tmp_path / "policy.txt")
    assert loaded.policy_version == 3
    assert np.allclose(loaded.weights, result.weights, atol=0, rtol=0)
