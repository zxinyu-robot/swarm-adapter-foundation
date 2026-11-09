"""生成 MSRGB 用 JPEG 载荷（按 rgb_tag 着色，与 edge streamvln stub 一致）."""
from __future__ import annotations

import io
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


def encode_tagged_jpeg(rgb_tag: str, *, width: int = 640, height: int = 480) -> bytes:
    tag = rgb_tag.lower()
    if "kitchen" in tag:
        color = (40, 180, 80)
    elif "hall" in tag:
        color = (200, 60, 50)
    elif "bedroom" in tag:
        color = (120, 80, 200)
    else:
        color = (90, 90, 100)

    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 28)
    except OSError:
        font = ImageFont.load_default()
    draw.text((24, 24), f"gazebo:{rgb_tag}", fill=(255, 255, 255), font=font)

    buf = io.BytesIO()
    img.save(buf, format="jpeg", quality=85)
    return buf.getvalue()
