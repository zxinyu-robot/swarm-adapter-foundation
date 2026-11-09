"""师生决策 trace 采集（蒸馏数据入口）.

蒸馏不是训练问题，是数据问题。没有 trace 就无法回答：
「老师在同样的端侧可见信息下，会选哪个 frontier？」——这是学生要学的唯一东西。

三条记录原则
------------
1. **以 map_version 为连接键，不以时间为键**。
   时间戳在弱网/时钟漂移下不可靠；map_version 是图、语义瓦片、样本三者
   共同的对齐依据。map_version=0（未知）直接拒收，否则静默污染训练集。

2. **context 只记端侧可见信息**。
   端侧学生看不到 RGB，只看到 subgraph（frontier + geom_score + 任务目标）。
   若在训练时喂了 RGB 派生特征，上线必然崩。故 trace 的 context 必须与
   端侧 Adapter 实际入参同源。

3. **outcome.source 必填，仿真代理绝不可冒充真机回执**。
   - ``sim_expected``：用场景标定的 expected_frontier 做代理判据
   - ``robot_execution``：真机执行回执（到达 / 失败码 / 耗时）
   两者混在一份数据集里训练，等于用假标签蒸馏。

4. **``outcome`` 属于被执行的动作（学生选的），不属于老师**。
   老师的选择只在仿真里被"虚拟执行"；真机上真正跑的是端侧策略的输出。
   故老师的判据单列 ``teacher_outcome``，真机场景下老师恒为 unknown ——
   否则会产出"老师成功了"这种没有任何执行依据的假样本。

追加写 JSONL：崩溃安全，不需要重写历史，可直接 cat 采样。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

TRACE_SCHEMA = "motionslam.teacher_student_trace.v1"

# 与端侧 Adapter / SemanticDirective 的失败码对齐。
OUTCOME_SUCCESS = "success"
OUTCOME_FAILED = "failed"
OUTCOME_UNKNOWN = "unknown"

SOURCE_SIM_EXPECTED = "sim_expected"
SOURCE_ROBOT_EXECUTION = "robot_execution"

FAIL_NONE = ""


@dataclass(frozen=True)
class TeacherDecision:
    """老师（边侧 VLM / 任意高能力调度器）的决策.

    ``inputs`` 记录老师**实际消费了哪些模态** —— 这是判断样本可否蒸馏的关键:

    - 只消费 ``structure`` / ``task`` → 学生也看得到，这是**抄规则**，蒸馏无意义
    - 消费了 ``vision``（RGB）→ 学生看不到，才是**可蒸馏的知识**
      此时老师的能力必须经「语义瓦片」落地，学生才能间接继承

    故 ``distillable`` 由 inputs 是否含 vision 推导，不允许人工填写。
    """

    scheduler: str
    picked: str
    ranked: tuple[str, ...] = ()
    confidence: float = 0.0
    semantic_labels: tuple[dict[str, Any], ...] = ()
    inputs: tuple[str, ...] = ()

    @property
    def distillable(self) -> bool:
        """老师是否消费了端侧学生看不到的模态（当前仅 RGB/vision）."""
        return "vision" in self.inputs

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "scheduler": self.scheduler,
            "picked": self.picked,
            "ranked": list(self.ranked),
            "confidence": round(float(self.confidence), 4),
            "inputs": list(self.inputs),
            "distillable": self.distillable,
        }
        if self.semantic_labels:
            d["semantic_labels"] = [dict(x) for x in self.semantic_labels]
        return d


@dataclass(frozen=True)
class StudentDecision:
    """端侧学生（当前规则baseline 或已部署策略）的决策."""

    kind: str
    picked: str
    ranked: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "picked": self.picked,
            "ranked": list(self.ranked),
        }


@dataclass(frozen=True)
class Outcome:
    """执行结果。source 决定这条样本能不能用于训练."""

    status: str = OUTCOME_UNKNOWN
    fail_code: str = FAIL_NONE
    source: str = SOURCE_SIM_EXPECTED
    elapsed_ms: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "fail_code": self.fail_code,
            "source": self.source,
        }
        if self.elapsed_ms is not None:
            d["elapsed_ms"] = round(float(self.elapsed_ms), 3)
        return d


@dataclass
class TraceRecord:
    """一条师生对照样本."""

    map_version: int
    session_id: str
    teacher: TeacherDecision
    student: StudentDecision
    outcome: Outcome
    scenario: str = ""
    tick_index: int = -1
    stamp_ns: int = field(default_factory=time.time_ns)
    # 端侧可见上下文：必须与端侧 Adapter 入参同源。
    context: dict[str, Any] = field(default_factory=dict)
    # 老师选择的代理判据。真机场景下无执行依据，应为 None 或 unknown。
    teacher_outcome: Optional[Outcome] = None

    def validate(self) -> tuple[bool, str]:
        if self.map_version <= 0:
            return False, "map_version must be > 0 (unknown version poisons training data)"
        if not self.session_id:
            return False, "session_id required"
        if not self.teacher.picked:
            return False, "teacher.picked required"
        if not self.student.picked:
            return False, "student.picked required"
        if self.outcome.source not in (SOURCE_SIM_EXPECTED, SOURCE_ROBOT_EXECUTION):
            return False, f"outcome.source invalid: {self.outcome.source}"
        if self.outcome.status not in (OUTCOME_SUCCESS, OUTCOME_FAILED, OUTCOME_UNKNOWN):
            return False, f"outcome.status invalid: {self.outcome.status}"
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TRACE_SCHEMA,
            "session_id": self.session_id,
            "scenario": self.scenario,
            "map_version": int(self.map_version),
            "tick_index": int(self.tick_index),
            "stamp_ns": int(self.stamp_ns),
            "teacher": self.teacher.to_dict(),
            "student": self.student.to_dict(),
            "outcome": self.outcome.to_dict(),
            "teacher_outcome": (
                self.teacher_outcome.to_dict() if self.teacher_outcome is not None else None
            ),
            "context": dict(self.context),
        }


class TraceRecorder:
    """追加写 JSONL 的 trace 采集器.

    ``enabled=False`` 时全部写入静默丢弃，方便在热路径上无分支调用。
    """

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

    def record(self, rec: TraceRecord) -> bool:
        """写一条样本。校验失败或 IO 失败返回 False，不抛异常（热路径安全）."""
        if not self.enabled or self.path is None:
            return False

        ok, reason = rec.validate()
        if not ok:
            self._rejected += 1
            self._last_error = reason
            return False

        line = json.dumps(rec.to_dict(), ensure_ascii=False)
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            self._last_error = f"write failed: {exc}"
            self._rejected += 1
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


def build_context(
    subgraph: dict[str, Any],
    *,
    layers_aligned: Optional[list[str]] = None,
    task_goal: str = "",
) -> dict[str, Any]:
    """构造端侧可见上下文 —— 与端侧 Adapter 入参同源.

    刻意不含 RGB / 图像特征：端侧拿不到，喂了就是分布外。
    """
    frontiers: list[dict[str, Any]] = []
    for fr in subgraph.get("frontiers") or []:
        frontiers.append(
            {
                "frontier_id": str(fr.get("frontier_id", "")),
                "geom_score": round(float(fr.get("geom_score", 0.0)), 6),
            }
        )
    nodes = [
        {"node_id": str(n.get("node_id", ""))}
        for n in (subgraph.get("nodes") or [])
    ]
    return {
        "frontiers": frontiers,
        "nodes": nodes,
        "task_goal": task_goal,
        "layers_aligned": list(layers_aligned or []),
        # 端侧可用输入不含 RGB：此字段恒为 false，显式记录下来避免误用。
        "rgb_visible_to_student": False,
    }


def judge_by_expected(picked: Optional[str], expected: str) -> Outcome:
    """仿真代理判据：与场景标定的 expected_frontier 比对.

    这是**代理标签**，不是真机回执；source 明确标为 sim_expected。
    """
    if not picked or not expected:
        return Outcome(status=OUTCOME_UNKNOWN, fail_code=FAIL_NONE,
                       source=SOURCE_SIM_EXPECTED)
    if picked == expected:
        return Outcome(status=OUTCOME_SUCCESS, fail_code=FAIL_NONE,
                       source=SOURCE_SIM_EXPECTED)
    return Outcome(status=OUTCOME_FAILED, fail_code="MismatchExpectedFrontier",
                   source=SOURCE_SIM_EXPECTED)


def robot_outcome(
    status: str,
    *,
    fail_code: str = FAIL_NONE,
    elapsed_ms: Optional[float] = None,
) -> Outcome:
    """真机执行回执 —— 训练集的稀缺监督信号."""
    return Outcome(
        status=status,
        fail_code=fail_code,
        source=SOURCE_ROBOT_EXECUTION,
        elapsed_ms=elapsed_ms,
    )


def load_traces(path: Path | str) -> list[dict[str, Any]]:
    """读取 JSONL trace；跳过损坏行（断网写入可能留半行）."""
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


def agreement_rate(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """老师 / 学生 top-1 一致率 —— 蒸馏的第一项健康指标.

    蒸馏前必须先看这个数：
    - 一致率过高（≈100%）→ 学生已经会了，蒸馏无收益
    - 一致率过低（<50%）→ 输入分布或任务定义有问题，先查数据
    同时统计老师标注的代理成功率，用于判断"这个老师值不值得学"。
    """
    total = 0
    agree = 0
    teacher_ok = 0
    teacher_known = 0
    distillable = 0
    vers: set[int] = set()
    sources: dict[str, int] = {}

    for t in traces:
        if t.get("schema") != TRACE_SCHEMA:
            continue
        teacher = (t.get("teacher") or {}).get("picked")
        student = (t.get("student") or {}).get("picked")
        if not teacher or not student:
            continue

        total += 1
        vers.add(int(t.get("map_version", 0)))
        if teacher == student:
            agree += 1

        src = (t.get("outcome") or {}).get("source", "")
        sources[src] = sources.get(src, 0) + 1

        if (t.get("teacher") or {}).get("distillable"):
            distillable += 1

        to = t.get("teacher_outcome") or {}
        if to.get("status") in (OUTCOME_SUCCESS, OUTCOME_FAILED):
            teacher_known += 1
            if to.get("status") == OUTCOME_SUCCESS:
                teacher_ok += 1

    return {
        "samples": total,
        "agree": agree,
        "rate": round(agree / total, 4) if total else 0.0,
        "teacher_known": teacher_known,
        "teacher_success_rate": (
            round(teacher_ok / teacher_known, 4) if teacher_known else 0.0
        ),
        "distinct_versions": len(vers),
        "outcome_sources": sources,
        "distillable_samples": distillable,
        "distillable_rate": round(distillable / total, 4) if total else 0.0,
    }
