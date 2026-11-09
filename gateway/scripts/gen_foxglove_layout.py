#!/usr/bin/env python3
"""从 foxglove-sdk 生成 Studio 可导入的 layout JSON（monitor/layouts/rgb_ws_monitor.json）."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "monitor" / "layouts" / "rgb_ws_monitor.json"


def build_layout() -> dict:
    import foxglove.layouts as fl

    map_3d = fl.ThreeDeePanel(
        config=fl.ThreeDeeConfig(
            fixed_frame="map",
            follow_mode="follow-none",
            camera_state=fl.ThreeDeeCameraState(
                perspective=False,
                distance=15.0,
                phi=0.7853981633974483,
                theta_offset=0.7853981633974483,
                target=(0.0, 0.0, 0.0),
            ),
            topics={
                "/map/subgraph": fl.BaseRendererSceneUpdateTopicSettings(visible=True),
                "/map/robot": fl.BaseRendererSceneUpdateTopicSettings(visible=True),
                "/submap/stitched": fl.BaseRendererPointCloudTopicSettings(
                    visible=True,
                    decay_time=0,
                    point_size=2.5,
                    point_shape="circle",
                    color_field="intensity",
                    color_mode="colormap",
                    color_map="turbo",
                ),
            },
            layers={
                "rgb-ws-grid": fl.BaseRendererGridLayerSettings(
                    visible=True,
                    frame_id="map",
                    label="Grid",
                    size=30,
                    divisions=15,
                    line_width=0.5,
                    color="#ffffff44",
                )
            },
        ),
        title="子图地图",
    )

    rgb_image = fl.ImagePanel(
        config=fl.ImageConfig(image_mode=fl.ImageModeConfig(image_topic="/vision/rgb")),
        title="RGB 关键帧",
    )

    directive_log = fl.LogPanel(
        config=fl.LogConfig(
            topic_to_render="/model/directive_out",
            min_log_level=1,
            show_name=True,
            show_time=True,
            font_size=12,
        ),
        title="SemanticDirective",
    )

    input_log = fl.LogPanel(
        config=fl.LogConfig(
            topic_to_render="/model/scheduler_input",
            min_log_level=1,
            show_name=True,
            show_time=True,
            font_size=12,
        ),
        title="调度器输入",
    )

    link_log = fl.LogPanel(
        config=fl.LogConfig(
            topic_to_render="/network/link_status",
            min_log_level=1,
            show_name=True,
            show_time=True,
            font_size=12,
        ),
        title="边端链路",
    )

    root = fl.SplitContainer(
        direction="row",
        items=[
            fl.SplitItem(proportion=0.62, content=map_3d),
            fl.SplitItem(
                proportion=0.38,
                content=fl.SplitContainer(
                    direction="column",
                    items=[
                        fl.SplitItem(proportion=0.38, content=rgb_image),
                        fl.SplitItem(proportion=0.22, content=directive_log),
                        fl.SplitItem(
                            proportion=0.40,
                            content=fl.SplitContainer(
                                direction="row",
                                items=[
                                    fl.SplitItem(proportion=0.5, content=input_log),
                                    fl.SplitItem(proportion=0.5, content=link_log),
                                ],
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )

    # Studio import 使用 configById + mosaic layout；仓库内 json 为手写 Studio 格式。
    # 此处返回 programmatic layout，供校验；实际写入仍用 committed studio json。
    return json.loads(fl.Layout(content=root).to_json())


def main() -> int:
    if not OUT.exists():
        print(f"layout 文件不存在: {OUT}", file=sys.stderr)
        return 1
    current = json.loads(OUT.read_text(encoding="utf-8"))
    generated = build_layout()
    topics = generated["content"]["items"][0]["content"]["config"]["topics"]
    for topic, cfg in topics.items():
        if topic in current["configById"]["3D!rgbws01"]["topics"]:
            current["configById"]["3D!rgbws01"]["topics"][topic].update(cfg)
    OUT.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
