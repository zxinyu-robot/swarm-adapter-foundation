#!/usr/bin/env python3
"""师生 trace 采集测试.

运行：python3 tests/test_trace.py
无第三方依赖（仓库未引入 pytest），失败即非零退出。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge.trace import (  # noqa: E402
    OUTCOME_FAILED,
    OUTCOME_SUCCESS,
    SOURCE_ROBOT_EXECUTION,
    SOURCE_SIM_EXPECTED,
    Outcome,
    StudentDecision,
    TeacherDecision,
    TraceRecord,
    TraceRecorder,
    agreement_rate,
    build_context,
    judge_by_expected,
    load_traces,
    robot_outcome,
)

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    if not cond:
        FAILURES.append(label)
        print(f"  [FAIL] {label}")


def _rec(map_version: int = 7, teacher_pick: str = "fr_kitchen",
         student_pick: str = "fr_hall") -> TraceRecord:
    return TraceRecord(
        map_version=map_version,
        session_id="s1",
        teacher=TeacherDecision("qwen_vl", teacher_pick, (teacher_pick,), 0.9,
                                inputs=("structure", "task", "vision")),
        student=StudentDecision("geom_baseline", student_pick),
        outcome=judge_by_expected(student_pick, "fr_kitchen"),
        teacher_outcome=judge_by_expected(teacher_pick, "fr_kitchen"),
        context={"frontiers": [], "rgb_visible_to_student": False},
    )


def test_reject_unknown_version() -> None:
    """map_version=0 必须拒收 —— 未知版本会静默污染训练集."""
    with tempfile.TemporaryDirectory() as td:
        r = TraceRecorder(Path(td) / "t.jsonl")
        ok = r.record(_rec(map_version=0))
        check(ok is False, "map_version=0 rejected")
        check(r.written == 0, "no write on rejected record")
        check(r.rejected == 1, "rejected counter incremented")
        check("map_version" in r.last_error, "reason mentions map_version")
        check(not (Path(td) / "t.jsonl").exists(), "file not created")
    print("  [ok] reject unknown version")


def test_reject_invalid_source() -> None:
    """outcome.source 只允许两个可信来源."""
    rec = _rec()
    bad = TraceRecord(
        map_version=7, session_id="s1",
        teacher=rec.teacher, student=rec.student,
        outcome=Outcome(status=OUTCOME_SUCCESS, source="made_up"),
    )
    ok, reason = bad.validate()
    check(ok is False, "invalid source rejected")
    check("source" in reason, "reason mentions source")
    print("  [ok] reject invalid outcome source")


def test_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.jsonl"
        r = TraceRecorder(path)
        check(r.record(_rec()) is True, "record written")
        traces = load_traces(path)
        check(len(traces) == 1, "one trace loaded")
        t = traces[0]
        check(t["schema"] == "motionslam.teacher_student_trace.v1", "schema tag")
        check(t["map_version"] == 7, "map_version persisted")
        check(t["teacher"]["picked"] == "fr_kitchen", "teacher pick persisted")
        check(t["student"]["picked"] == "fr_hall", "student pick persisted")
        check(t["teacher"]["distillable"] is True, "distillable from vision input")
        check(t["outcome"]["status"] == OUTCOME_FAILED, "student outcome failed")
        check(t["teacher_outcome"]["status"] == OUTCOME_SUCCESS, "teacher outcome ok")
    print("  [ok] roundtrip")


def test_teacher_rule_only_not_distillable() -> None:
    """老师只用 structure/task → 学生也看得到，不可蒸馏."""
    td_teacher = TeacherDecision("geom_baseline", "fr_hall", inputs=("structure",))
    check(td_teacher.distillable is False, "rule-only teacher not distillable")
    rec = _rec()
    rule_rec = TraceRecord(
        map_version=7, session_id="s1",
        teacher=td_teacher, student=rec.student,
        outcome=rec.outcome,
    )
    ok, _ = rule_rec.validate()
    check(ok is True, "rule-only record still valid")
    d = rule_rec.teacher.to_dict()
    check(d["distillable"] is False, "serialized distillable false")
    print("  [ok] rule-only teacher flagged not distillable")


def test_append_only_survives_corrupt_line() -> None:
    """断网可能留半行；读取应跳过坏行而非整体失败."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.jsonl"
        r = TraceRecorder(path)
        r.record(_rec(map_version=1))
        with path.open("a", encoding="utf-8") as f:
            f.write('{"broken": \n')
        r.record(_rec(map_version=2))
        traces = load_traces(path)
        check(len(traces) == 2, "corrupt line skipped, good lines kept")
        check([t["map_version"] for t in traces] == [1, 2], "order preserved")
    print("  [ok] corrupt line tolerated")


def test_agreement_rate() -> None:
    """老师成功率 100% + 学生一致率 0% = 最大蒸馏空间."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.jsonl"
        r = TraceRecorder(path)
        r.record(_rec(map_version=1, teacher_pick="fr_kitchen", student_pick="fr_hall"))
        r.record(_rec(map_version=2, teacher_pick="fr_kitchen", student_pick="fr_kitchen"))
        stats = agreement_rate(load_traces(path))
        check(stats["samples"] == 2, "two samples")
        check(stats["agree"] == 1, "one agreement")
        check(stats["rate"] == 0.5, "rate 50%")
        check(stats["teacher_known"] == 2, "teacher outcomes known")
        check(stats["teacher_success_rate"] == 1.0, "teacher success 100%")
        check(stats["distinct_versions"] == 2, "two versions")
        check(stats["outcome_sources"].get(SOURCE_SIM_EXPECTED) == 2, "source counted")
        check(stats["distillable_samples"] == 2, "distillable counted")
    print("  [ok] agreement rate")


def test_robot_outcome_source() -> None:
    """真机回执必须标为 robot_execution，不可与仿真代理混淆."""
    o = robot_outcome(OUTCOME_FAILED, fail_code="TargetUnreachable", elapsed_ms=1234.5)
    check(o.source == SOURCE_ROBOT_EXECUTION, "robot source set")
    check(o.fail_code == "TargetUnreachable", "fail code kept")
    check(o.to_dict()["elapsed_ms"] == 1234.5, "elapsed persisted")
    print("  [ok] robot outcome source")


def test_context_excludes_rgb() -> None:
    """端侧看不到 RGB：context 显式标注，防止误用."""
    ctx = build_context(
        {"frontiers": [{"frontier_id": "f1", "geom_score": 0.9}],
         "nodes": [{"node_id": "n1"}]},
        layers_aligned=["structure"], task_goal="kitchen",
    )
    check(ctx["rgb_visible_to_student"] is False, "rgb flagged invisible")
    check(ctx["frontiers"][0]["frontier_id"] == "f1", "frontier kept")
    check(ctx["task_goal"] == "kitchen", "task goal kept")
    check("rgb_tag" not in json.dumps(ctx), "no rgb-derived field leaked")
    print("  [ok] context excludes rgb")


def test_disabled_recorder_is_noop() -> None:
    """未开启时热路径调用零副作用、不建文件."""
    r = TraceRecorder(None)
    check(r.enabled is False, "disabled without path")
    check(r.record(_rec()) is False, "record returns False")
    check(r.written == 0, "nothing written")
    print("  [ok] disabled recorder noop")


def main() -> int:
    print("== trace tests ==")
    test_reject_unknown_version()
    test_reject_invalid_source()
    test_roundtrip()
    test_teacher_rule_only_not_distillable()
    test_append_only_survives_corrupt_line()
    test_agreement_rate()
    test_robot_outcome_source()
    test_context_excludes_rgb()
    test_disabled_recorder_is_noop()

    if FAILURES:
        print(f"== {len(FAILURES)} failure(s) ==")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("== all passed ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
