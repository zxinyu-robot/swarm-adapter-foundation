"""Flower ClientApp（Message API，flwr 1.43）。

每轮：收全局权重 → 写策略文件交给端侧 C++ 策略门 → 用本机记录做本地训练 → 回传权重和汇总指标。
原始记录不离开本机。

node_config 键：
- records-dir：C++ RingStrategyStore 分段文件目录；
  未设置时用 $SWARM_ADAPTER_RECORDS_ROOT/node_<partition-id>（仿真用）；
- policy-path：策略文件路径（C++ FilePolicyClient 读取），默认 <records-dir>/policy.txt。
"""

from __future__ import annotations

import os
from pathlib import Path

from flwr.app import ArrayRecord, Context, Message, MetricRecord, RecordDict
from flwr.clientapp import ClientApp

from .local_round import install_global_policy, run_local_round

app = ClientApp()


def _paths(context: Context) -> tuple[str, str]:
    records_dir = context.node_config.get("records-dir")
    if records_dir is None:
        root = os.environ.get("SWARM_ADAPTER_RECORDS_ROOT", "records")
        records_dir = Path(root) / f"node_{context.node_config.get('partition-id', 0)}"
    policy_path = context.node_config.get("policy-path", Path(records_dir) / "policy.txt")
    return str(records_dir), str(policy_path)


@app.train()
def train(msg: Message, context: Context) -> Message:
    records_dir, policy_path = _paths(context)
    global_weights = msg.content["arrays"].to_numpy_ndarrays()[0]
    server_round = int(msg.content["config"]["server-round"])
    install_global_policy(policy_path, global_weights, server_round)

    l2 = float(msg.content["config"].get("l2", 1e-2))
    result = run_local_round(records_dir, global_weights, l2=l2)
    metrics = MetricRecord(
        {
            "num-examples": result.num_samples,
            "mse-before": result.mse_before,
            "mse-after": result.mse_after,
        }
    )
    content = RecordDict({"arrays": ArrayRecord([result.weights]), "metrics": metrics})
    return Message(content=content, reply_to=msg)


@app.evaluate()
def evaluate(msg: Message, context: Context) -> Message:
    records_dir, _ = _paths(context)
    global_weights = msg.content["arrays"].to_numpy_ndarrays()[0]
    result = run_local_round(records_dir, global_weights, l2=0.0)
    metrics = MetricRecord(
        {"num-examples": result.num_samples, "eval-mse": result.mse_before}
    )
    return Message(content=RecordDict({"metrics": metrics}), reply_to=msg)
