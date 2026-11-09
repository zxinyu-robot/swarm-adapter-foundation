"""Flower ServerApp（Message API，flwr 1.43）：FedAvg 聚合通信策略权重。

服务端只看到权重和汇总指标，看不到端侧原始记录。
run_config 键：num-server-rounds、fraction-train、min-nodes、l2、output-policy
（output-policy 未设置时读 $SWARM_ADAPTER_OUTPUT_POLICY）。
"""

from __future__ import annotations

import os

import numpy as np
from flwr.app import ArrayRecord, ConfigRecord, Context
from flwr.serverapp import Grid, ServerApp
from flwr.serverapp.strategy import FedAvg

from .. import policy_file
from ..features import FEATURE_DIM

app = ServerApp()


@app.main()
def main(grid: Grid, context: Context) -> None:
    num_rounds = int(context.run_config.get("num-server-rounds", 3))
    min_nodes = int(context.run_config.get("min-nodes", 2))
    strategy = FedAvg(
        fraction_train=float(context.run_config.get("fraction-train", 1.0)),
        fraction_evaluate=1.0,
        min_train_nodes=min_nodes,
        min_evaluate_nodes=min_nodes,
        min_available_nodes=min_nodes,
    )
    result = strategy.start(
        grid=grid,
        initial_arrays=ArrayRecord([np.zeros(FEATURE_DIM)]),
        num_rounds=num_rounds,
        train_config=ConfigRecord({"l2": float(context.run_config.get("l2", 1e-2))}),
    )
    output = context.run_config.get(
        "output-policy", os.environ.get("SWARM_ADAPTER_OUTPUT_POLICY")
    )
    if output:
        weights = result.arrays.to_numpy_ndarrays()[0]
        policy_file.save(
            str(output),
            policy_file.PolicyWeights(num_rounds, num_rounds, tuple(float(w) for w in weights)),
        )
