"""StreamVLN 官方 HTTP 客户端（对齐 realworld/go2_vln_client.py + http_realworld_server.py）."""
from __future__ import annotations

import io
import json
from typing import Any, Optional

import numpy as np
import requests
from PIL import Image

# 官方动作编码：0 STOP, 1 FORWARD, 2 TURN LEFT, 3 TURN RIGHT
ACTION_STOP = 0
ACTION_FORWARD = 1
ACTION_TURN_LEFT = 2
ACTION_TURN_RIGHT = 3


class StreamVLNClient:
    """POST multipart: image/jpeg + json{reset, instruction}."""

    def __init__(self, url: str, *, timeout_s: float = 30.0) -> None:
        self.url = url.rstrip("/")
        if not self.url.endswith("/eval_vln"):
            self.url = f"{self.url}/eval_vln"
        self.timeout_s = timeout_s
        self._needs_reset: set[str] = set()

    def reset_session(self, session_id: str) -> None:
        self._needs_reset.add(session_id)

    def eval_vln(
        self,
        *,
        session_id: str,
        instruction: str,
        rgb_tag: str = "",
        image_rgb: Optional[np.ndarray] = None,
    ) -> dict[str, Any]:
        policy_init = session_id in self._needs_reset
        if policy_init:
            self._needs_reset.discard(session_id)

        jpeg_buf = _encode_jpeg(image_rgb, rgb_tag=rgb_tag)
        payload = {"reset": policy_init, "instruction": instruction}
        resp = requests.post(
            self.url,
            files={"image": ("rgb.jpg", jpeg_buf, "image/jpeg")},
            data={"json": json.dumps(payload)},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        actions = [int(x) for x in data.get("action", [0])]
        return {
            "action": actions,
            "llm_output": str(data.get("llm_output", "")),
            "done": bool(data.get("done", 0 in actions)),
        }


def _encode_jpeg(image_rgb: Optional[np.ndarray], *, rgb_tag: str) -> io.BytesIO:
    if image_rgb is not None and image_rgb.size > 0:
        img = Image.fromarray(image_rgb.astype(np.uint8), mode="RGB")
    else:
        # 仿真 MSRGB 载荷无真实像素时，生成占位 JPEG（stub 读 instruction/tag 规则）
        color = _tag_color(rgb_tag)
        img = Image.new("RGB", (640, 480), color)
    buf = io.BytesIO()
    img.save(buf, format="jpeg", quality=85)
    buf.seek(0)
    return buf


def _tag_color(rgb_tag: str) -> tuple[int, int, int]:
    tag = (rgb_tag or "sim").lower()
    if "kitchen" in tag:
        return (180, 120, 80)
    if "hall" in tag:
        return (120, 120, 180)
    return (90, 90, 90)
