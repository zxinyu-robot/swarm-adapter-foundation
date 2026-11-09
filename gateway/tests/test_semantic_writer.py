#!/usr/bin/env python3
"""语义标注回写（overlay 生成）测试.

运行：python3 tests/test_semantic_writer.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge.semantic_writer import (  # noqa: E402
    DEFAULT_TEACHER_CONFIDENCE,
    OVERLAY_SCHEMA,
    OverlayWriter,
    SemanticLabel,
    labels_from_vlm_result,
    load_overlay,
    normalize_category,
    summarize_overlay,
)

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        FAILURES.append(label)
        print(f"  [FAIL] {label}")


def test_normalize_category() -> None:
    check(normalize_category("kitchen") == "kitchen", "exact match")
    check(normalize_category("Kitchen") == "kitchen", "case insensitive")
    check(normalize_category("  kitchen  ") == "kitchen", "whitespace stripped")
    check(normalize_category("a kitchen with counters") == "kitchen", "substring match")
    check(normalize_category("厨房") == "kitchen", "chinese kitchen")
    check(normalize_category("卧室") == "bedroom", "chinese bedroom")
    check(normalize_category("卫生间") == "bathroom", "chinese bathroom")
    check(normalize_category("楼梯间") == "staircase", "chinese staircase")
    check(normalize_category("电梯") == "elevator", "chinese elevator")
    check(normalize_category("living-room") == "living_room", "hyphen normalized")
    check(normalize_category("") == "", "empty yields empty")
    check(normalize_category("nonsense") == "", "unknown yields empty, not 'unknown'")
    print("  [ok] normalize category")


def test_room_found_false_yields_nothing() -> None:
    """未找到房间时不标注 —— 地图上的空白是有意义的."""
    got = labels_from_vlm_result(
        room_found=False, found_room_type="kitchen", confidence=0.9,
        lat=30.0, lon=120.0, map_version=7,
    )
    check(got == [], "room_found=False -> no labels")
    print("  [ok] room_found=False yields nothing")


def test_unmappable_type_yields_nothing() -> None:
    got = labels_from_vlm_result(
        room_found=True, found_room_type="some weird place", confidence=0.9,
        lat=30.0, lon=120.0, map_version=7,
    )
    check(got == [], "unmappable type -> no labels (not 'unknown' on map)")
    print("  [ok] unmappable type yields nothing")


def test_confidence_normalization() -> None:
    # 0..1 浮点 → 百分比
    labs = labels_from_vlm_result(
        room_found=True, found_room_type="kitchen", confidence=0.88,
        lat=30.0, lon=120.0, map_version=7,
    )
    check(len(labs) == 1 and labs[0].confidence == 88, "0.88 -> 88")

    # 已经是百分比
    labs = labels_from_vlm_result(
        room_found=True, found_room_type="kitchen", confidence=75.0,
        lat=30.0, lon=120.0, map_version=7,
    )
    check(labs[0].confidence == 75, "75.0 -> 75")

    # 0 → 用默认值（避免 0 置信度浪费一次标注）
    labs = labels_from_vlm_result(
        room_found=True, found_room_type="kitchen", confidence=0.0,
        lat=30.0, lon=120.0, map_version=7,
    )
    check(labs[0].confidence == DEFAULT_TEACHER_CONFIDENCE, "0 -> default")

    # 约定：<=1.0 视为比例，>1.0 视为百分比。
    # 2.0 是 2%，不是 200% —— 边界必须明确，否则 1.0/1.01 会造成跳变。
    labs = labels_from_vlm_result(
        room_found=True, found_room_type="kitchen", confidence=2.0,
        lat=30.0, lon=120.0, map_version=7,
    )
    check(labs[0].confidence == 2, "2.0 -> 2% (percentage convention)")

    labs = labels_from_vlm_result(
        room_found=True, found_room_type="kitchen", confidence=1.0,
        lat=30.0, lon=120.0, map_version=7,
    )
    check(labs[0].confidence == 100, "1.0 -> 100% (fraction boundary)")

    # 超过 100 才截断
    labs = labels_from_vlm_result(
        room_found=True, found_room_type="kitchen", confidence=500.0,
        lat=30.0, lon=120.0, map_version=7,
    )
    check(labs[0].confidence == 100, "500 -> 100 clamped")
    print("  [ok] confidence normalization")


def test_label_validation() -> None:
    ok = SemanticLabel("kitchen", 80, 30.0, 120.0, 7)
    check(ok.validate()[0] is True, "valid label passes")

    cases = [
        (SemanticLabel("nonsense", 80, 30.0, 120.0, 7), "unknown category"),
        (SemanticLabel("kitchen", 80, 30.0, 120.0, 0), "map_version 0"),
        (SemanticLabel("kitchen", 80, 99.0, 120.0, 7), "lat out of range"),
        (SemanticLabel("kitchen", 80, 30.0, 999.0, 7), "lon out of range"),
        (SemanticLabel("kitchen", 200, 30.0, 120.0, 7), "confidence out of range"),
    ]
    for label, why in cases:
        good, _ = label.validate()
        check(good is False, f"rejects {why}")
    print("  [ok] label validation")


def test_writer_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "labels.jsonl"
        w = OverlayWriter(path)
        lab = SemanticLabel("kitchen", 85, 30.2741, 120.1551, 7,
                            session_id="s1", explanation="sees stove")
        check(w.write(lab) is True, "write ok")

        entries = load_overlay(path)
        check(len(entries) == 1, "one entry")
        e = entries[0]
        check(e["schema"] == OVERLAY_SCHEMA, "schema tag")
        check(e["map_version"] == 7, "version persisted")
        check(e["category"] == "kitchen", "category persisted")
        check(e["confidence"] == 85, "confidence persisted")
        check(abs(e["lat"] - 30.2741) < 1e-9, "lat persisted")
        check(e["session_id"] == "s1", "session id persisted")
        check(e["explanation"] == "sees stove", "explanation persisted")
    print("  [ok] writer roundtrip")


def test_writer_rejects_invalid() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "labels.jsonl"
        w = OverlayWriter(path)
        check(w.write(SemanticLabel("nonsense", 80, 30.0, 120.0, 7)) is False,
              "invalid category rejected")
        check(w.written == 0, "nothing written")
        check(w.rejected == 1, "rejected counted")
        check(not path.exists(), "file not created")
    print("  [ok] writer rejects invalid")


def test_writer_disabled() -> None:
    w = OverlayWriter(None)
    check(w.enabled is False, "disabled without path")
    check(w.write(SemanticLabel("kitchen", 80, 30.0, 120.0, 7)) is False, "noop")
    print("  [ok] writer disabled noop")


def test_corrupt_line_tolerated() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "labels.jsonl"
        w = OverlayWriter(path)
        w.write(SemanticLabel("kitchen", 80, 30.0, 120.0, 7))
        with path.open("a", encoding="utf-8") as f:
            f.write('{"broken": \n')
        w.write(SemanticLabel("door", 70, 30.0, 120.0, 7))
        entries = load_overlay(path)
        check(len(entries) == 2, "corrupt line skipped")
    print("  [ok] corrupt line tolerated")


def test_summarize_overlay() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "labels.jsonl"
        w = OverlayWriter(path)
        w.write(SemanticLabel("kitchen", 80, 30.0, 120.0, 7, source="qwen_vl"))
        w.write(SemanticLabel("kitchen", 80, 30.1, 120.1, 7, source="qwen_vl"))
        w.write(SemanticLabel("door", 70, 30.2, 120.2, 8, source="layer_fusion_stub"))
        stats = summarize_overlay(load_overlay(path))
        check(stats["total"] == 3, "total")
        check(stats["by_version"] == {7: 2, 8: 1}, "by version")
        check(stats["by_category"] == {"kitchen": 2, "door": 1}, "by category")
        check(stats["by_source"]["qwen_vl"] == 2, "by source")
    print("  [ok] summarize overlay")


def test_json_is_valid() -> None:
    """overlay 必须能被严格 JSON 解析（C++ 端按行读）."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "labels.jsonl"
        w = OverlayWriter(path)
        w.write(SemanticLabel("kitchen", 85, 30.2741, 120.1551, 7,
                              explanation="含中文说明 与 \"引号\""))
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = json.loads(line)     # 不抛异常即可
            check(isinstance(parsed, dict), "line is object")
    print("  [ok] json valid (incl. unicode & quotes)")


def main() -> int:
    print("== semantic writer tests ==")
    test_normalize_category()
    test_room_found_false_yields_nothing()
    test_unmappable_type_yields_nothing()
    test_confidence_normalization()
    test_label_validation()
    test_writer_roundtrip()
    test_writer_rejects_invalid()
    test_writer_disabled()
    test_corrupt_line_tolerated()
    test_summarize_overlay()
    test_json_is_valid()

    if FAILURES:
        print(f"== {len(FAILURES)} failure(s) ==")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("== all passed ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
