"""
StreamVLN x86 推理服务 — 接收 Go2 推上来的 RGB 帧，返回导航动作序列。

基于官方 http_realworld_server.py，增加：
  - 从 JSON 读取 instruction（Go2 端可下发指令）
  - CLI 参数化 host/port/default_instruction
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import torch
import transformers
from flask import Flask, jsonify, request
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STREAMVLN_DIR = os.path.join(ROOT, "third_party", "StreamVLN")
sys.path.insert(0, STREAMVLN_DIR)

from streamvln.streamvln_agent import VLNEvaluator  # noqa: E402
from model.stream_video_vln import StreamVLNForCausalLM  # noqa: E402

app = Flask(__name__)

action_seq = np.zeros(4)
idx = 0
terminate = False
total_generate_time = 0.0
start_time = time.time()
output_dir = ""
default_instruction = ""
evaluator = None


def annotate_image(frame_idx, image, t_start, gen_time, llm_output, out_dir):
    image = Image.fromarray(image)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 20)
    except OSError:
        font = ImageFont.load_default()

    lines = [
        f"Frame Id : {frame_idx}",
        f"Running time: {time.time() - t_start:.2f} s",
        f"Generate time: {gen_time:.2f} s",
        f"Actions : {llm_output}",
    ]
    y = 10
    for line in lines:
        draw.text((10, y), line, fill="white", font=font)
        y += 26
    image.save(f"{out_dir}/rgb_{frame_idx}_annotated.png")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model_loaded": evaluator is not None})


@app.route("/eval_vln", methods=["POST"])
def eval_vln():
    global action_seq, idx, terminate, total_generate_time, output_dir, start_time

    image_file = request.files["image"]
    data = json.loads(request.form["json"])

    image = Image.open(image_file.stream).convert("RGB")
    image = np.asarray(image)[..., ::-1]  # RGB -> BGR for agent

    instruction = data.get("instruction") or default_instruction
    policy_init = data.get("reset", False)

    if policy_init:
        start_time = time.time()
        total_generate_time = 0.0
        terminate = False
        idx = 0
        output_dir = "runs" + datetime.now().strftime("%m-%d-%H%M")
        os.makedirs(output_dir, exist_ok=True)
        print("[reset] memory cleared, instruction:", instruction)
        evaluator.reset_memory()

    idx += 1

    if terminate:
        print("[done] task finished")
        return jsonify({"action": [0], "done": True})

    llm_output = ""
    for _ in range(4):
        t1 = time.time()
        return_action, generate_time, return_llm_output = evaluator.step(
            0,
            image,
            instruction,
            run_model=(evaluator.step_id % 4 == 0),
        )
        llm_output = return_llm_output if return_llm_output is not None else llm_output
        print(f"eval step cost {time.time() - t1:.3f}s")

        if generate_time > 0:
            total_generate_time = generate_time
        action_seq = action_seq if return_action is None else return_action
        if 0 in action_seq:
            terminate = True
        evaluator.step_id += 1

    str_action = "".join(str(i) for i in action_seq)
    str_action = (
        str_action.replace("1", "↑")
        .replace("2", "←")
        .replace("3", "→")
        .replace("0", "STOP")
    )
    if idx > 1 and total_generate_time > 0.5:
        total_generate_time -= 0.3

    if output_dir:
        annotate_image(idx, image, start_time, total_generate_time, str_action, output_dir)

    if len(action_seq) == 0:
        return jsonify({"action": [0], "done": True})

    return jsonify({
        "action": [int(a) for a in action_seq],
        "llm_output": llm_output,
        "done": bool(terminate),
    })


def main():
    global evaluator, default_instruction

    parser = argparse.ArgumentParser()
    parser.add_argument("--model_path", type=str, required=True)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5801)
    parser.add_argument("--default_instruction", type=str, default="Walk forward.")
    parser.add_argument("--num_future_steps", type=int, default=4)
    parser.add_argument("--num_frames", type=int, default=32)
    parser.add_argument("--num_history", type=int, default=8)
    parser.add_argument("--model_max_length", type=int, default=4096)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()

    default_instruction = args.default_instruction

    attn_impl = "flash_attention_2"
    try:
        import flash_attn  # noqa: F401
    except ImportError:
        attn_impl = "sdpa"
        print("WARN: flash-attn not found, using sdpa")

    tokenizer = transformers.AutoTokenizer.from_pretrained(
        args.model_path,
        model_max_length=args.model_max_length,
        padding_side="right",
    )
    config = transformers.AutoConfig.from_pretrained(args.model_path)
    model = StreamVLNForCausalLM.from_pretrained(
        args.model_path,
        attn_implementation=attn_impl,
        torch_dtype=torch.bfloat16,
        config=config,
        low_cpu_mem_usage=False,
    )
    model.model.num_history = args.num_history
    model.reset(1)
    model.requires_grad_(False)
    model.to(args.device)
    model.eval()

    vln_sensor_config = {
        "rgb_height": 1.25,
        "camera_intrinsic": np.array([
            [192.0, 0.0, 191.42857143, 0.0],
            [0.0, 192.0, 191.42857143, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]),
    }

    evaluator = VLNEvaluator(
        vln_sensor_config,
        model=model,
        tokenizer=tokenizer,
        args=args,
    )

    # warmup
    evaluator.step(0, np.zeros((480, 640, 3), dtype=np.uint8), default_instruction, run_model=True)
    print(f"Server ready: http://{args.host}:{args.port}/eval_vln")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
