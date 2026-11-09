#!/usr/bin/env python3
"""仿真评测：场景 → 端侧上行 → 边侧 scheduler → directive sink → Gate 报告."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from edge.multimodal_layers import AlignedBundle, LayerId, parse_task_from_subgraph  # noqa: E402
from edge.trace import (  # noqa: E402
    Outcome,
    SOURCE_SIM_EXPECTED,
    StudentDecision,
    TeacherDecision,
    TraceRecord,
    TraceRecorder,
    build_context,
    judge_by_expected,
)
from sim.device_sim import run_scenario  # noqa: E402
from sim.directive_sink import DirectiveSink  # noqa: E402
from sim.gates import evaluate_g0  # noqa: E402
from sim.metrics import ScenarioReport, TickMetrics, validate_directive  # noqa: E402
from sim.schedulers import pick_geom_baseline, pick_layer_fusion_stub, pick_mock_style  # noqa: E402

SCENARIO_DIR = ROOT / "sim" / "scenarios"
REPORT_DIR = ROOT / "sim" / "reports"
LAYER_FUSION_REQUIRED = frozenset({"structure", "vision", "task"})


def _bundle_from_tick(tick: dict[str, Any], subgraph: dict[str, Any], ver: int) -> AlignedBundle:
    present_raw = tick.get("layer_manifest", {}).get("present", [])
    layers_present = [LayerId(x) for x in present_raw if x in LayerId._value2member_map_]
    layers_aligned = list(layers_present)
    return AlignedBundle(
        session_id=str(subgraph.get("session_id", "")),
        version=ver,
        timestamp_ns=int(subgraph.get("timestamp_ns", 0)),
        structure=subgraph,
        vision_meta={
            "rgb_tag": tick.get("rgb_tag", ""),
            "subgraph_version": ver,
        },
        task=parse_task_from_subgraph(subgraph),
        layers_present=layers_present,
        layers_aligned=layers_aligned,
    )


def _align_ok_from_directive(directive: dict[str, Any], scheduler: str) -> bool:
    mm = directive.get("multimodal_layers") or {}
    aligned = set(mm.get("layers_aligned") or [])
    required = (
        frozenset({"vision", "task"})
        if scheduler == "streamvln"
        else LAYER_FUSION_REQUIRED
    )
    return required <= aligned


def _find_directive_for_version(records: list, version: int) -> Optional[dict[str, Any]]:
    for rec in reversed(records):
        d = rec.payload
        if int(d.get("map_version", -1)) == version:
            return d
    return None


def run_one_scenario(
    scenario_path: Path,
    *,
    edge_host: str,
    subgraph_port: int,
    rgb_port: int,
    directive_port: int,
    sink: DirectiveSink,
    scheduler_label: str = "layer_fusion_stub",
    version_offset: int = 0,
    recorder: Optional[TraceRecorder] = None,
) -> ScenarioReport:
    sink.clear()
    tick_log = run_scenario(
        scenario_path,
        edge_host=edge_host,
        subgraph_port=subgraph_port,
        rgb_port=rgb_port,
        connect_timeout=5.0,
        version_offset=version_offset,
    )
    n = len(tick_log)
    if not sink.wait_count(n, timeout_s=max(8.0, n * 3.0 + 2.0)):
        print(f"[eval] WARN: expected {n} directives, got {len(sink.records())}", flush=True)
    time.sleep(0.3)
    records = sink.records()

    report = ScenarioReport(name=scenario_path.stem, scheduler=scheduler_label)
    for tick in tick_log:
        ver = int(tick["version"])
        subgraph = tick["subgraph"]
        expected = str(tick["expected_frontier_id"])
        directive = _find_directive_for_version(records, ver)
        directive_pick = None
        latency_ms = None
        valid = False
        align_ok = False

        expected_vln = tick.get("expected_vln_actions")
        vln_actions = None
        vln_match = False

        if directive:
            valid = validate_directive(directive)
            cands = directive.get("candidate_frontier_ids") or []
            directive_pick = str(cands[0]) if cands else None
            bias = directive.get("action_bias") or {}
            raw_actions = bias.get("actions")
            if raw_actions is not None:
                vln_actions = [int(x) for x in raw_actions]
            for rec in records:
                if int(rec.payload.get("map_version", -1)) == ver:
                    latency_ms = (rec.recv_mono - tick["sent_mono"]) * 1000.0
                    break
            align_ok = _align_ok_from_directive(directive, scheduler_label)
            if expected_vln is not None and vln_actions is not None:
                vln_match = list(vln_actions) == list(expected_vln)

        bundle = _bundle_from_tick(tick, subgraph, ver)
        layers_aligned = [x.value for x in bundle.layers_aligned]
        ready_key = (
            "streamvln"
            if scheduler_label == "streamvln"
            else "qwen_vl"
            if scheduler_label == "qwen_vl"
            else "layer_fusion_stub"
        )
        multimodal_ready = bundle.ready_for(ready_key)

        mock_pick = pick_mock_style(subgraph)
        geom_pick_tick = pick_geom_baseline(subgraph)
        fusion_pick = pick_layer_fusion_stub(bundle)

        report.ticks.append(
            TickMetrics(
                version=ver,
                expected_frontier=expected,
                mock_pick=mock_pick,
                geom_pick=geom_pick_tick,
                fusion_pick=fusion_pick,
                directive_pick=directive_pick,
                align_ok=align_ok,
                layers_aligned=layers_aligned,
                multimodal_ready=multimodal_ready,
                latency_ms=latency_ms,
                directive_valid=valid,
                vln_actions=vln_actions,
                expected_vln_actions=list(expected_vln) if expected_vln else None,
                vln_action_match=vln_match,
            )
        )

        # 师生 trace：一个 tick 一条样本，以 map_version 为连接键。
        # 无 directive 的 tick 没有老师标签，静默跳过（不计入 rejected）。
        if recorder is not None and recorder.enabled and directive_pick:
            ranked = tuple(str(x) for x in (directive.get("candidate_frontier_ids") or [])) \
                if directive else ()
            # 老师实际消费了哪些模态：以 directive 回报的 layers_aligned 为准。
            # 只消费 structure/task 的老师 = 抄规则，学生本就做得到，不可蒸馏。
            mm_layers = (directive or {}).get("multimodal_layers") or {}
            teacher_inputs = tuple(str(x) for x in (mm_layers.get("layers_aligned") or []))
            teacher = TeacherDecision(
                scheduler=scheduler_label,
                picked=directive_pick or "",
                ranked=ranked,
                confidence=float((directive or {}).get("confidence", 0.0) or 0.0),
                inputs=teacher_inputs,
            )
            student = StudentDecision(kind="geom_baseline", picked=geom_pick_tick)
            task_goal = ""
            if bundle.task is not None:
                task_goal = bundle.task.goal_room_type or ""
            recorder.record(
                TraceRecord(
                    map_version=ver,
                    session_id=str(subgraph.get("session_id", "")),
                    scenario=scenario_path.stem,
                    tick_index=len(report.ticks) - 1,
                    teacher=teacher,
                    student=student,
                    # 被执行的是学生输出（端侧真正跑的那一个）
                    outcome=judge_by_expected(student.picked, expected),
                    teacher_outcome=judge_by_expected(teacher.picked, expected),
                    context=build_context(
                        subgraph,
                        layers_aligned=layers_aligned,
                        task_goal=task_goal,
                    ),
                )
            )
    return report


def write_report(
    reports: list[ScenarioReport],
    gate_report: Any,
    out_dir: Path,
    *,
    scheduler: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scheduler": scheduler,
        "g0_passed": gate_report.passed,
        "gates": [{"name": g.name, "passed": g.passed, "detail": g.detail} for g in gate_report.results],
        "scenarios": [r.to_dict() for r in reports],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# RGB_ws 仿真评测报告",
        "",
        f"生成时间：{summary['generated_at']}",
        f"边侧 scheduler：`{scheduler}`",
        f"**G0 通过**：{'✅ 是' if gate_report.passed else '❌ 否'}",
        "",
        "## 场景指标",
        "",
        "| 场景 | directive@1 | geom@1 | 分层融合@1 | 三层就绪 | 边侧对齐 |",
        "|------|-------------|--------|------------|----------|----------|",
    ]
    for r in reports:
        p50 = r.e2e_latency_ms_p50
        p50s = f"{p50:.1f}" if p50 is not None else "-"
        lines.append(
            f"| {r.name} | {r.frontier_top1_acc:.0%} | {r.geom_baseline_acc:.0%} | "
            f"{r.layer_fusion_acc:.0%} | {r.multimodal_ready_rate:.0%} | {r.align_hit_rate:.0%} |"
        )
    lines.extend(
        [
            "",
            f"p50 端到端延迟：{p50s} ms（见 summary.json）",
            "",
            "## G0 Gate",
            "",
        ]
    )
    for g in gate_report.results:
        mark = "✅" if g.passed else "❌"
        lines.append(f"- {mark} **{g.name}**：{g.detail}")
    lines.extend(
        [
            "",
            "## 分层说明",
            "",
            "- **L0 structure** → `:9877` 子图 JSON",
            "- **L1 vision** → `:9878` MSRGB",
            "- **L2 task** → 子图 `task_context`",
            "- 边侧 `--scheduler layer_fusion_stub` 时 directive 首选应等于 GT",
            "",
        ]
    )
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def ensure_edge_running(edge_host: str, subgraph_port: int, rgb_port: int) -> None:
    import socket

    for port in (subgraph_port, rgb_port):
        try:
            with socket.create_connection((edge_host, port), timeout=1.0):
                return
        except OSError:
            continue
    raise SystemExit(
        f"边侧未监听 {edge_host}:{subgraph_port}/{rgb_port}。"
        "请先运行: ./scripts/run_sim_bench.sh"
    )


def main() -> int:
    p = argparse.ArgumentParser(description="RGB_ws sim eval runner")
    p.add_argument("--scenario", action="append", help="场景 json，可重复；默认全部")
    p.add_argument("--edge-host", default="127.0.0.1")
    p.add_argument("--subgraph-port", type=int, default=9877)
    p.add_argument("--rgb-port", type=int, default=9878)
    p.add_argument("--directive-port", type=int, default=9879)
    p.add_argument("--scheduler", default="layer_fusion_stub")
    p.add_argument("--skip-edge-check", action="store_true")
    p.add_argument("--strict", action="store_true", help="G0 未通过时 exit 1")
    p.add_argument(
        "--trace-out",
        default="",
        help="师生 trace JSONL 输出路径（蒸馏数据集）；留空则不采集",
    )
    args = p.parse_args()

    paths = [Path(s) for s in args.scenario] if args.scenario else sorted(SCENARIO_DIR.glob("*.json"))
    if not args.scenario:
        if args.scheduler == "streamvln":
            paths = [p for p in paths if p.stem.startswith("streamvln_")] or paths
        else:
            paths = [p for p in paths if not p.stem.startswith("streamvln_")]
    if not paths:
        print("无场景文件", file=sys.stderr)
        return 1

    if not args.skip_edge_check:
        ensure_edge_running(args.edge_host, args.subgraph_port, args.rgb_port)

    sink = DirectiveSink(host=args.edge_host, port=args.directive_port)
    sink.start()

    recorder: Optional[TraceRecorder] = None
    if args.trace_out:
        recorder = TraceRecorder(args.trace_out)
        print(f"[eval] trace -> {args.trace_out}", flush=True)

    reports: list[ScenarioReport] = []
    for idx, path in enumerate(paths):
        print(f"[eval] scenario={path.name} scheduler={args.scheduler}", flush=True)
        reports.append(
            run_one_scenario(
                path,
                edge_host=args.edge_host,
                subgraph_port=args.subgraph_port,
                rgb_port=args.rgb_port,
                directive_port=args.directive_port,
                sink=sink,
                scheduler_label=args.scheduler,
                version_offset=idx * 1000,
                recorder=recorder,
            )
        )

    gate_report = evaluate_g0(reports, scheduler=args.scheduler)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORT_DIR / ts
    write_report(reports, gate_report, out_dir, scheduler=args.scheduler)
    print(f"[eval] report -> {out_dir}", flush=True)
    for r in reports:
        print(
            f"  {r.name}: directive@1={r.frontier_top1_acc:.0%} "
            f"fusion@1={r.layer_fusion_acc:.0%} "
            f"vln={r.vln_action_acc:.0%} "
            f"align={r.align_hit_rate:.0%} ready={r.multimodal_ready_rate:.0%}",
            flush=True,
        )
    for g in gate_report.results:
        mark = "PASS" if g.passed else "FAIL"
        print(f"  [G0] {mark}: {g.name} ({g.detail})", flush=True)

    if recorder is not None and recorder.enabled:
        from edge.trace import agreement_rate, load_traces

        summary = recorder.summary()
        print(
            f"[trace] written={summary['written']} rejected={summary['rejected']} "
            f"-> {summary['path']}",
            flush=True,
        )
        if summary["last_error"]:
            print(f"[trace] last_error: {summary['last_error']}", flush=True)
        stats = agreement_rate(load_traces(summary["path"]))
        print(
            f"[trace] teacher/student agreement={stats['rate']:.0%} "
            f"({stats['agree']}/{stats['samples']}) "
            f"teacher_success={stats['teacher_success_rate']:.0%} "
            f"versions={stats['distinct_versions']}",
            flush=True,
        )
        print(
            f"[trace] distillable={stats['distillable_rate']:.0%} "
            f"({stats['distillable_samples']}/{stats['samples']}) "
            "— 老师未消费 RGB 时该值为 0，说明只是在抄规则，蒸馏无收益",
            flush=True,
        )

    if args.strict and not gate_report.passed:
        print("[eval] G0 FAILED (--strict)", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
