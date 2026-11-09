#!/usr/bin/env python3
"""本地测试：模拟 Go2 上行 RGB 帧，验证服务端推理链路。"""
import argparse
import io
import json
import sys

import numpy as np
import requests
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5801/eval_vln")
    parser.add_argument("--image", default=None, help="JPEG/PNG path; default synthetic")
    parser.add_argument("--instruction", default="Walk forward.")
    parser.add_argument("--reset", action="store_true", help="Reset model memory")
    args = parser.parse_args()

    if args.image:
        img = Image.open(args.image).convert("RGB")
    else:
        arr = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        img = Image.fromarray(arr)

    buf = io.BytesIO()
    img.save(buf, format="jpeg")
    buf.seek(0)

    payload = {"reset": args.reset, "instruction": args.instruction}
    resp = requests.post(
        args.url,
        files={"image": ("test.jpg", buf, "image/jpeg")},
        data={"json": json.dumps(payload)},
        timeout=300,
    )
    print(resp.status_code, resp.text)


if __name__ == "__main__":
    main()
