"""边侧多模态分层对齐."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from edge.multimodal_layers import AlignedBundle, LayerId, TaskLayer, parse_task_from_subgraph

if TYPE_CHECKING:
    from edge.store import EdgeStore, RgbFrame


def align_bundle(store: "EdgeStore", subgraph_version: int) -> Optional[AlignedBundle]:
    sg = store.latest_subgraph
    if sg is None or int(sg.get("version", -1)) != subgraph_version:
        return None

    present: list[LayerId] = [LayerId.STRUCTURE]
    aligned: list[LayerId] = [LayerId.STRUCTURE]

    task = parse_task_from_subgraph(sg)
    if task:
        present.append(LayerId.TASK)
        aligned.append(LayerId.TASK)

    rgb_frame: Optional["RgbFrame"] = store.aligned_rgb(subgraph_version)
    vision_meta = None
    vision_payload = None
    if rgb_frame is not None:
        present.append(LayerId.VISION)
        vision_meta = rgb_frame.meta
        vision_payload = rgb_frame.payload
        if int(rgb_frame.meta.get("subgraph_version", -1)) == subgraph_version:
            aligned.append(LayerId.VISION)

    return AlignedBundle(
        session_id=str(sg.get("session_id", "")),
        version=subgraph_version,
        timestamp_ns=int(sg.get("timestamp_ns", 0)),
        structure=sg,
        vision_meta=vision_meta,
        vision_payload=vision_payload,
        task=task,
        layers_present=present,
        layers_aligned=aligned,
    )
