#!/usr/bin/env python3
"""Gazebo 线评测：GG5–GG8 + edge directive sink."""
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
from gazebo.bridge.uplink_bridge import run_gazebo_scenario  # noqa: E402
from gazebo.gates import check_gg5_sensors, check_gg6_pose, check_gg9_scan_frontier, evaluate_gg8  # noqa: E402
from sim.directive_sink import DirectiveSink  # noqa: E402
from sim.eval_runner import _align_ok_from_directive, _bundle_from_tick, _find_directive_for_version, write_report  # noqa: E402
from sim.metrics import ScenarioReport, TickMetrics, validate_directive  # noqa: E402
from sim.schedulers import pick_geom_baseline, pick_layer_fusion_stub, pick_mock_style  # noqa: E402

SCENARIO_DIR = ROOT / "sim" / "scenarios"
REPORT_DIR = ROOT / "gazebo" / "reports"
MODEL_SDF = ROOT / "gazebo" / "models" / "go2_stand" / "model.sdf"
LAYER_FUSION_REQUIRED = frozenset({"structure", "vision", "task"})


def run_one_scenario(
    scenario_path: Path,
    *,
    edge_host: str,
    subgraph_port: int,
    rgb_port: int,
    directive_port: int,
    sink: DirectiveSink,
    scheduler_label: str = "layer_fusion_stub",
    mode: str = "live",
    version_offset: int = 0,
    frontier_source: str = "scenario",
) -> tuple[ScenarioReport, list[str]]:
    sink.clear()
    tick_log = run_gazebo_scenario(
        scenario_path,
        edge_host=edge_host,
        subgraph_port=subgraph_port,
        rgb_port=rgb_port,
        connect_timeout=5.0,
        mode=mode,
        version_offset=version_offset,
        frontier_source=frontier_source,
    )
    n = len(tick_log)
    if not sink.wait_count(n, timeout_s=max(8.0, n * 3.0 + 2.0)):
        print(f"[gazebo_eval] WARN: expected {n} directives, got {len(sink.records())}", flush=True)
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
        multimodal_ready = bundle.ready_for(
            "streamvln" if scheduler_label == "streamvln" else "layer_fusion_stub"
        )

        report.ticks.append(
            TickMetrics(
                version=ver,
                expected_frontier=expected,
                mock_pick=pick_mock_style(subgraph),
                geom_pick=pick_geom_baseline(subgraph),
                fusion_pick=pick_layer_fusion_stub(bundle),
                directive_pick=directive_pick,
                align_ok=align_ok,
                layers_aligned=[x.value for x in bundle.layers_aligned],
                multimodal_ready=multimodal_ready,
                latency_ms=latency_ms,
                directive_valid=valid,
                vln_actions=vln_actions,
                expected_vln_actions=list(expected_vln) if expected_vln else None,
                vln_action_match=vln_match,
            )
        )
    frontier_from = [str(t.get("frontier_from", "")) for t in tick_log]
    return report, frontier_from


def write_gazebo_report(
    reports: list[ScenarioReport],
    gate_report: Any,
    gg5: Any,
    gg6: Any,
    out_dir: Path,
    *,
    scheduler: str,
    mode: str,
    frontier_source: str = "scenario",
    gg9: Any = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scheduler": scheduler,
        "mode": mode,
        "frontier_source": frontier_source,
        "gg_passed": gate_report.passed and gg5.passed,
        "gg5": {"name": gg5.name, "passed": gg5.passed, "detail": gg5.detail},
        "gg6": {"name": gg6.name, "passed": gg6.passed, "detail": gg6.detail},
    }
    if gg9 is not None:
        summary["gg9"] = {"name": gg9.name, "passed": gg9.passed, "detail": gg9.detail}
    summary["gates"] = [
        {"name": g.name, "passed": g.passed, "detail": g.detail} for g in gate_report.results
    ]
    summary["scenarios"] = [r.to_dict() for r in reports]
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Gazebo 仿真评测报告",
        "",
        f"生成时间：{summary['generated_at']}",
        f"模式：`{mode}` · scheduler：`{scheduler}` · frontier：`{frontier_source}`",
        f"**GG 通过**：{'✅' if summary['gg_passed'] else '❌'}",
        "",
        "## GG Gate",
        "",
        f"- {'✅' if gg5.passed else '❌'} **{gg5.name}**：{gg5.detail}",
        f"- {'✅' if gg6.passed else '❌'} **{gg6.name}**：{gg6.detail}",
    ]
    if gg9 is not None:
        lines.append(f"- {'✅' if gg9.passed else '❌'} **{gg9.name}**：{gg9.detail}")
    for g in gate_report.results:
        lines.append(f"- {'✅' if g.passed else '❌'} **{g.name}**：{g.detail}")

    lines.extend(["", "## 场景", ""])
    for r in reports:
        lines.append(
            f"- **{r.name}**：directive@1={r.frontier_top1_acc:.0%} "
            f"align={r.align_hit_rate:.0%} ready={r.multimodal_ready_rate:.0%}"
        )
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Gazebo GG5–GG8 eval")
    p.add_argument("--scenario", action="append")
    p.add_argument("--edge-host", default="127.0.0.1")
    p.add_argument("--subgraph-port", type=int, default=9877)
    p.add_argument("--rgb-port", type=int, default=9878)
    p.add_argument("--directive-port", type=int, default=9879)
    p.add_argument("--scheduler", default="layer_fusion_stub")
    p.add_argument("--mode", choices=("live", "scenario"), default="live")
    p.add_argument("--frontier-source", choices=("scenario", "scan", "hybrid"), default="scenario")
    p.add_argument("--skip-edge-check", action="store_true")
    p.add_argument("--skip-gg6", action="store_true", help="scenario 模式跳过 live pose")
    p.add_argument("--strict", action="store_true")
    args = p.parse_args()

    gg5 = check_gg5_sensors(MODEL_SDF)
    if args.mode == "scenario" or args.skip_gg6:
        from sim.gates import GateResult

        gg6 = GateResult("GG6_pose", True, f"skipped (mode={args.mode})")
    else:
        gg6 = check_gg6_pose()

    paths = [Path(s) for s in args.scenario] if args.scenario else [SCENARIO_DIR / "corridor_3frontiers.json"]

    if not args.skip_edge_check:
        import socket

        for port in (args.subgraph_port, args.rgb_port):
            try:
                with socket.create_connection((args.edge_host, port), timeout=1.0):
                    break
            except OSError:
                raise SystemExit(f"边侧未监听 {args.edge_host}:{port}")

    sink = DirectiveSink(host=args.edge_host, port=args.directive_port)
    sink.start()

    reports: list[ScenarioReport] = []
    all_frontier_from: list[str] = []
    for idx, path in enumerate(paths):
        print(f"[gazebo_eval] scenario={path.name} mode={args.mode} frontier={args.frontier_source}", flush=True)
        report, ff = run_one_scenario(
            path,
            edge_host=args.edge_host,
            subgraph_port=args.subgraph_port,
            rgb_port=args.rgb_port,
            directive_port=args.directive_port,
            sink=sink,
            scheduler_label=args.scheduler,
            mode=args.mode,
            version_offset=idx * 1000,
            frontier_source=args.frontier_source,
        )
        reports.append(report)
        all_frontier_from.extend(ff)

    gate_report = evaluate_gg8(reports, scheduler=args.scheduler)
    gg9 = None
    if args.frontier_source in ("scan", "hybrid"):
        gg9 = check_gg9_scan_frontier(all_frontier_from)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORT_DIR / ts
    write_gazebo_report(
        reports,
        gate_report,
        gg5,
        gg6,
        out_dir,
        scheduler=args.scheduler,
        mode=args.mode,
        frontier_source=args.frontier_source,
        gg9=gg9,
    )

    all_pass = gg5.passed and gg6.passed and gate_report.passed
    if gg9 is not None:
        all_pass = all_pass and gg9.passed
    print(f"[gazebo_eval] report -> {out_dir}", flush=True)
    print(f"  GG5={gg5.passed} GG6={gg6.passed} GG7-8={gate_report.passed}", flush=True)
    for g in [gg5, gg6, *([] if gg9 is None else [gg9]), *gate_report.results]:
        mark = "PASS" if g.passed else "FAIL"
        print(f"  [{mark}] {g.name}: {g.detail}", flush=True)

    if args.strict and not all_pass:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
