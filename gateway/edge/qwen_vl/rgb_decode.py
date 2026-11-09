"""MSRGB 载荷 → PIL Image（真 JPEG 或仿真 tag 占位）."""
from __future__ import annotations

import io
from typing import Any, Optional

from PIL import Image


def payload_to_image(payload: bytes, meta: Optional[dict[str, Any]] = None) -> Image.Image:
    """解码 RGB 帧；仿真 tag 载荷则生成占位图."""
    if payload[:2] == b"\xff\xd8":
        return Image.open(io.BytesIO(payload)).convert("RGB")

    tag = ""
    if meta:
        tag = str(meta.get("rgb_tag", ""))
    if not tag and len(payload) >= 32:
        tag = payload[:32].split(b"\x00")[0].decode("utf-8", errors="replace")
    return Image.new("RGB", (640, 480), _tag_color(tag))


def _tag_color(rgb_tag: str) -> tuple[int, int, int]:
    tag = (rgb_tag or "sim").lower()
    if "kitchen" in tag:
        return (180, 120, 80)
    if "hall" in tag:
        return (120, 120, 180)
    if "bedroom" in tag:
        return (140, 100, 160)
    return (90, 90, 90)
