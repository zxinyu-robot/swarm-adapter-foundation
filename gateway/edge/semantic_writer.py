"""语义标注回写：把老师（VLM）的语义判断写成 overlay 文件.

闭环位置
--------
::

    VLM 看懂 RGB（room_found / found_room_type）
      → 本模块写成 overlay（JSONL，带 map_version）
      → semantic_label_merge（C++）合并进语义瓦片，版本 +1
      → 端侧策略查询合并后的语义地图

为什么不在 Python 里直接改瓦片
------------------------------
标注给的是 WGS84 经纬度，落瓦片要经 GCJ-02 换算。这个换算必须只有
一份实现（C++ 的 ``wgs84_to_amap_tile``）——在 Python 里重写一遍，
必然重演「GCJ-02 当 WGS84 用」那类 500m 偏移 bug。
所以 Python 只负责**产出 overlay**，落瓦片交给 C++ 工具。

为什么要独立 overlay 文件而不是就地改
-------------------------------------
回滚 = 丢掉合并产物，base 文件始终原样。这是 Fork「可回滚」原则的落实。

为什么必须带 map_version
------------------------
标注是在某个版本的地图上产生的。若地图已更新（版本变了）而标注仍被
应用，就会把「旧图上的厨房」贴到「新图上的走廊」。故合并端逐条校验版本，
不匹配即丢弃 —— 宁可少标，不可错标。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

OVERLAY_SCHEMA = "semantictile.overlay.v1"

# 与 C++ SemanticCategory 的 semantic_name() 对齐
VALID_CATEGORIES = frozenset({
    "corridor", "door", "kitchen", "bedroom", "living_room",
    "bathroom", "staircase", "elevator", "obstacle", "free_space",
    "goal_object",
})

# 老师标注的默认置信度：可信但低于 SLAM 实测高置信标签，
# 合并时不会压掉传感器实测结果。
DEFAULT_TEACHER_CONFIDENCE = 70


@dataclass(frozen=True)
class SemanticLabel:
    """一条老师标注."""

    category: str
    confidence: int
    lat: float
    lon: float
    map_version: int
    source: str = "qwen_vl"
    stamp_ns: int = field(default_factory=time.time_ns)
    session_id: str = ""
    explanation: str = ""

    def validate(self) -> tuple[bool, str]:
        if self.category not in VALID_CATEGORIES:
            return False, f"unknown category: {self.category}"
        if self.map_version <= 0:
            return False, "map_version must be > 0"
        if not (-90.0 <= self.lat <= 90.0):
            return False, f"lat out of range: {self.lat}"
        if not (-180.0 <= self.lon <= 180.0):
            return False, f"lon out of range: {self.lon}"
        if not (0 <= self.confidence <= 100):
            return False, f"confidence out of range: {self.confidence}"
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema": OVERLAY_SCHEMA,
            "map_version": int(self.map_version),
            "lat": round(float(self.lat), 9),
            "lon": round(float(self.lon), 9),
            "category": self.category,
            "confidence": int(self.confidence),
            "source": self.source,
            "stamp_ns": int(self.stamp_ns),
        }
        if self.session_id:
            d["session_id"] = self.session_id
        if self.explanation:
            d["explanation"] = self.explanation
        return d


def normalize_category(raw: str) -> str:
    """把 VLM 输出的房间类型归一到瓦片类别.

    模型可能说 "Kitchen"、"厨房"、"a kitchen with counters"。这里做保守归一：
    命中关键词即采用，否则返回空串（表示不标注，而不是标成 unknown）。
    """
    if not raw:
        return ""
    s = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if s in VALID_CATEGORIES:
        return s

    # 中文 / 带修饰的英文 → 标准类别
    aliases = (
        (("厨房", "kitchen", "cook"), "kitchen"),
        (("卧室", "bedroom"), "bedroom"),
        (("客厅", "living", "lounge"), "living_room"),
        (("卫生间", "浴室", "bathroom", "toilet", "restroom"), "bathroom"),
        (("楼梯", "stair"), "staircase"),
        (("电梯", "elevator", "lift"), "elevator"),
        (("走廊", "过道", "corridor", "hallway"), "corridor"),
        (("门", "door", "doorway"), "door"),
        (("障碍", "obstacle"), "obstacle"),
        (("空地", "开阔", "free_space"), "free_space"),
    )
    for keys, cat in aliases:
        for k in keys:
            if k in s:
                return cat
    return ""


class OverlayWriter:
    """追加写 overlay JSONL. ``enabled=False`` 时全部静默丢弃."""

    def __init__(self, path: Optional[Path | str], *, enabled: bool = True) -> None:
        self.path = Path(path) if path is not None else None
        self.enabled = bool(enabled) and self.path is not None
        self._written = 0
        self._rejected = 0
        self._last_error = ""
        if self.enabled and self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def written(self) -> int:
        return self._written

    @property
    def rejected(self) -> int:
        return self._rejected

    @property
    def last_error(self) -> str:
        return self._last_error

    def write(self, label: SemanticLabel) -> bool:
        if not self.enabled or self.path is None:
            return False

        ok, reason = label.validate()
        if not ok:
            self._rejected += 1
            self._last_error = reason
            return False

        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(label.to_dict(), ensure_ascii=False))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            self._rejected += 1
            self._last_error = f"write failed: {exc}"
            return False

        self._written += 1
        return True

    def summary(self) -> dict[str, Any]:
        return {
            "path": str(self.path) if self.path is not None else "",
            "written": self._written,
            "rejected": self._rejected,
            "last_error": self._last_error,
        }


def labels_from_vlm_result(
    *,
    room_found: bool,
    found_room_type: str,
    confidence: float,
    lat: float,
    lon: float,
    map_version: int,
    session_id: str = "",
    source: str = "qwen_vl",
    explanation: str = "",
) -> list[SemanticLabel]:
    """把 VLM 推理结果转成待回写标注.

    ``room_found`` 为 false 或房间类型无法归一 → 返回空列表。
    宁可不标，也不把 "unknown" 写到地图上 —— 地图上的空白是有意义的
    （表示未探索），写错标签会让下游把错误当事实。
    """
    if not room_found:
        return []
    category = normalize_category(found_room_type)
    if not category:
        return []

    conf = int(round(float(confidence) * 100.0)) if confidence <= 1.0 else int(round(confidence))
    if conf <= 0:
        conf = DEFAULT_TEACHER_CONFIDENCE
    if conf > 100:
        conf = 100

    return [
        SemanticLabel(
            category=category,
            confidence=conf,
            lat=lat,
            lon=lon,
            map_version=map_version,
            source=source,
            session_id=session_id,
            explanation=explanation,
        )
    ]


def load_overlay(path: Path | str) -> list[dict[str, Any]]:
    """读 overlay JSONL；跳过坏行."""
    out: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def summarize_overlay(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """按 (map_version, category, source) 汇总，用于判断标注质量."""
    by_version: dict[int, int] = {}
    by_category: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for e in entries:
        if e.get("schema") != OVERLAY_SCHEMA:
            continue
        v = int(e.get("map_version", 0))
        by_version[v] = by_version.get(v, 0) + 1
        c = str(e.get("category", ""))
        by_category[c] = by_category.get(c, 0) + 1
        s = str(e.get("source", ""))
        by_source[s] = by_source.get(s, 0) + 1
    return {
        "total": sum(by_version.values()),
        "by_version": by_version,
        "by_category": by_category,
        "by_source": by_source,
    }
