"""MSRGB 二进制帧协议（与 Go2 motionslam_bringup 对齐）."""
from __future__ import annotations

import json
import struct
from typing import Any, Tuple

MAGIC = b"MSRGB"
VERSION = 1
HEADER_STRUCT = struct.Struct(">5sBII")
META_SCHEMA = "motionslam.rgb_forward.v1"


def pack_rgb_forward_frame(meta: dict[str, Any], payload: bytes) -> bytes:
    meta_bytes = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return HEADER_STRUCT.pack(MAGIC, VERSION, len(meta_bytes), len(payload)) + meta_bytes + payload


def unpack_rgb_forward_frame(blob: bytes) -> Tuple[dict[str, Any], bytes, int]:
    min_len = HEADER_STRUCT.size
    if len(blob) < min_len:
        raise ValueError("frame too short")
    magic, ver, json_len, payload_len = HEADER_STRUCT.unpack_from(blob, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic: {magic!r}")
    if ver != VERSION:
        raise ValueError(f"unsupported version: {ver}")
    total = min_len + json_len + payload_len
    if len(blob) < total:
        raise ValueError("incomplete frame")
    off = min_len
    meta = json.loads(blob[off : off + json_len].decode("utf-8"))
    off += json_len
    payload = blob[off : off + payload_len]
    return meta, payload, total
