"""用 Flower 仿真引擎跑两节点、两轮 FedAvg。未安装 flwr[simulation] 时跳过。"""

import numpy as np
import pytest

pytest.importorskip("flwr")
pytest.importorskip("ray")

from flwr.simulation import run_simulation  # noqa: E402
from swarm_adapter import policy_file  # noqa: E402
from swarm_adapter.fl.client_app import app as client_app  # noqa: E402
from swarm_adapter.fl.server_app import app as server_app  # noqa: E402
from test_records_training import TRUE_W, write_segment  # noqa: E402


def test_two_node_fedavg(tmp_path, monkeypatch):
    for node in range(2):
        node_dir = tmp_path / f"node_{node}"
        node_dir.mkdir()
        write_segment(node_dir / "segment_000001.jsonl", 200, seed=10 + node)
    output = tmp_path / "global_policy.txt"
    monkeypatch.setenv("SWARM_ADAPTER_RECORDS_ROOT", str(tmp_path))
    monkeypatch.setenv("SWARM_ADAPTER_OUTPUT_POLICY", str(output))

    run_simulation(
        server_app=server_app,
        client_app=client_app,
        num_supernodes=2,
        backend_config={"client_resources": {"num_cpus": 1, "num_gpus": 0.0}},
    )

    global_policy = policy_file.load(output)
    assert global_policy.policy_version == 3
    assert np.allclose(global_policy.weights, TRUE_W, atol=1e-2)
    for node in range(2):
        installed = policy_file.load(tmp_path / f"node_{node}" / "policy.txt")
        assert installed.policy_version == 3, "last round's global model installed on node"
