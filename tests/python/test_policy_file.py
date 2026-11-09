import pytest
from swarm_adapter import policy_file
from swarm_adapter.features import FEATURE_DIM


def test_roundtrip_is_exact(tmp_path):
    weights = tuple(i / 3.0 for i in range(FEATURE_DIM))
    policy = policy_file.PolicyWeights(5, 2, weights)
    path = tmp_path / "policy.txt"
    policy_file.save(path, policy)
    assert policy_file.load(path) == policy
    text = path.read_text().splitlines()
    assert text[0] == "swarm_adapter.policy v1"
    assert text[3] == f"feature_dim {FEATURE_DIM}"
    assert not (tmp_path / "policy.txt.tmp").exists()


def test_reads_cpp_written_layout(tmp_path):
    path = tmp_path / "policy.txt"
    path.write_text(
        "swarm_adapter.policy v1\n# comment\npolicy_version 4\nround_id 4\n"
        "feature_dim 12\nweights " + " ".join(["0.5"] + ["0"] * 11) + "\n"
    )
    loaded = policy_file.load(path)
    assert loaded.policy_version == 4 and loaded.weights[0] == 0.5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"policy_version": 0, "round_id": 0, "weights": (0.0,) * FEATURE_DIM},
        {"policy_version": 1, "round_id": 0, "weights": (0.0,) * 3},
        {"policy_version": 1, "round_id": 0, "weights": (float("nan"),) * FEATURE_DIM},
    ],
)
def test_invalid_policy_rejected(kwargs):
    with pytest.raises(ValueError):
        policy_file.PolicyWeights(**kwargs)
