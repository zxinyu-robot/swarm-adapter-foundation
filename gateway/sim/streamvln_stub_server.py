#!/usr/bin/env python3
"""StreamVLN 官方 /eval_vln 协议的 CPU stub（仿真 S3，无需 GPU）。

对齐：
  - third_party/StreamVLN/realworld/go2_vln_client.py  上行格式
  - server/http_realworld_server.py                   响应 JSON
  - 动作 0 STOP / 1 FORWARD / 2 TURN LEFT / 3 TURN RIGHT，每 tick 返回 4 步 batch
"""
from __future__ import annotations

import argparse
import json
import time

from flask import Flask, jsonify, request

app = Flask(__name__)

# session_id -> {step_id, terminate}
_sessions: dict[str, dict] = {}


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model_loaded": False, "mode": "cpu_stub"})


@app.route("/eval_vln", methods=["POST"])
def eval_vln():
    image_file = request.files.get("image")
    raw_json = request.form.get("json", "{}")
    data = json.loads(raw_json)

    instruction = str(data.get("instruction", ""))
    policy_init = bool(data.get("reset", False))
    session_id = str(data.get("session_id", "default"))

    if image_file:
        image_file.stream.read()  # 消费上传，与官方一致

    if policy_init or session_id not in _sessions:
        _sessions[session_id] = {"step_id": 0, "terminate": False}
        print(f"[stub] reset session={session_id} instruction={instruction!r}", flush=True)

    state = _sessions[session_id]
    state["step_id"] += 1

    if state["terminate"]:
        return jsonify({"action": [0], "done": True, "llm_output": "STOP"})

    actions, llm = _rule_actions(instruction, state["step_id"])
    if 0 in actions:
        state["terminate"] = True

    print(f"[stub] session={session_id} step={state['step_id']} actions={actions}", flush=True)
    return jsonify({
        "action": actions,
        "llm_output": llm,
        "done": bool(state["terminate"]),
    })


def _rule_actions(instruction: str, step_id: int) -> tuple[list[int], str]:
    """规则 stub：厨房任务 → 左转+前进（对齐 corridor GT）；普通前进 → 官方默认 forward batch."""
    inst = instruction.lower()
    if "厨房" in instruction or "kitchen" in inst:
        # 相对 geom 选 hall(直走)，VLN stub 应左转探厨房
        actions = [2, 1, 1, 0]
        return actions, "←↑↑STOP (kitchen stub)"

    if "走廊" in instruction or "hall" in inst:
        actions = [1, 1, 1, 0]
        return actions, "↑↑↑STOP (hall stub)"

    if "forward" in inst or "前进" in instruction or "walk" in inst:
        actions = [1, 1, 1, 0]
        return actions, "↑↑↑STOP (forward stub)"

    # 官方默认：前几步前进
    actions = [1, 1, 2, 3] if step_id <= 2 else [1, 0, 0, 0]
    return actions, "default stub batch"


def main() -> int:
    p = argparse.ArgumentParser(description="StreamVLN CPU stub for sim")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5801)
    args = p.parse_args()
    print(f"[stub] StreamVLN eval_vln ready http://{args.host}:{args.port}/eval_vln", flush=True)
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
