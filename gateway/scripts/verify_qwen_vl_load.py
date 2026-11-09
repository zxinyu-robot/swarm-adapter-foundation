#!/usr/bin/env python3
"""5070 首次加载验证：Qwen2.5-VL-7B INT4 + 单次 corridor 仿真推理."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge.multimodal_layers import AlignedBundle, LayerId, TaskLayer  # noqa: E402
from edge.qwen_vl.client import QwenVLClient  # noqa: E402


def _corridor_fixture() -> tuple[dict, AlignedBundle]:
    subgraph = {
        "schema": "motionslam.sparse_subgraph.v1",
        "version": 1,
        "session_id": "verify_load",
        "nodes": [{"node_id": "cell_0_0", "visited": True, "frontier_count": 3}],
        "frontiers": [
            {"frontier_id": "fr_hall", "geom_score": 0.95, "position": {"x": 2, "y": 0, "z": 0}},
            {"frontier_id": "fr_kitchen", "geom_score": 0.72, "position": {"x": 0, "y": 2, "z": 0}},
            {"frontier_id": "fr_bedroom", "geom_score": 0.80, "position": {"x": -2, "y": 0, "z": 0}},
        ],
        "task_context": {
            "instruction": "找厨房",
            "goal_room_type": "kitchen",
            "language": "zh",
        },
    }
    from PIL import Image
    import io

    img = Image.new("RGB", (640, 480), (180, 120, 80))
    buf = io.BytesIO()
    img.save(buf, format="jpeg", quality=85)
    payload = buf.getvalue()

    bundle = AlignedBundle(
        session_id="verify_load",
        version=1,
        timestamp_ns=time.time_ns(),
        structure=subgraph,
        vision_meta={"rgb_tag": "kitchen_door", "subgraph_version": 1},
        vision_payload=payload,
        task=TaskLayer(instruction="找厨房", goal_room_type="kitchen"),
        layers_present=[LayerId.STRUCTURE, LayerId.VISION, LayerId.TASK],
        layers_aligned=[LayerId.STRUCTURE, LayerId.VISION, LayerId.TASK],
    )
    return subgraph, bundle


def main() -> int:
    p = argparse.ArgumentParser(description="Qwen-VL 5070 首次加载验证")
    p.add_argument("--model", default="Qwen/Qwen2.5-VL-7B-Instruct")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--no-4bit", action="store_true")
    args = p.parse_args()

    import torch

    if not torch.cuda.is_available():
        print("FAIL: CUDA 不可用", file=sys.stderr)
        return 1
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    print(f"VRAM total: {mem:.1f} GB")

    client = QwenVLClient(
        model_id=args.model,
        device=args.device,
        load_in_4bit=not args.no_4bit,
        min_interval_s=0.0,
        stub=False,
    )

    subgraph, bundle = _corridor_fixture()
    t0 = time.monotonic()
    print("==> 加载模型 + 首次推理...")
    result = client.infer(subgraph, bundle, "找厨房")
    elapsed = time.monotonic() - t0

    torch.cuda.synchronize()
    alloc = torch.cuda.max_memory_allocated(0) / (1024**3)
    reserved = torch.cuda.max_memory_reserved(0) / (1024**3)

    print(f"==> source={result.source}")
    print(f"    pick={result.candidate_frontier_ids[0]}")
    print(f"    confidence={result.confidence:.2f}")
    print(f"    explanation={result.natural_language_explanation[:120]}")
    print(f"    wall_time={elapsed:.1f}s")
    print(f"    max_memory_allocated={alloc:.2f} GB")
    print(f"    max_memory_reserved={reserved:.2f} GB")

    if result.source not in ("qwen_vl",):
        print(f"WARN: 未走 GPU 推理路径 (source={result.source})", file=sys.stderr)
        return 2
    print("PASS: Qwen2.5-VL 首次加载与推理成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
