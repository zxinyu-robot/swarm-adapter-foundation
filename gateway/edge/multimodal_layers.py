"""多模态数据分层定义与对齐（边侧 + 仿真共用）."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class LayerId(str, Enum):
    """边侧调度器消费的分层输入；层越高越偏语义，越低越偏几何."""

    STRUCTURE = "structure"  # L0 稀疏子图：pose / frontier / topology
    VISION = "vision"  # L1 RGB 关键帧（MSRGB）
    TASK = "task"  # L2 任务语义：自然语言指令 / 目标描述


SCHEDULER_REQUIRED_LAYERS: dict[str, tuple[LayerId, ...]] = {
    "mock": (LayerId.STRUCTURE,),
    "geom_baseline": (LayerId.STRUCTURE,),
    "layer_fusion_stub": (LayerId.STRUCTURE, LayerId.VISION, LayerId.TASK),
    "qwen_vl": (LayerId.STRUCTURE, LayerId.VISION, LayerId.TASK),
    "streamvln": (LayerId.VISION, LayerId.TASK),
}


@dataclass
class TaskLayer:
    instruction: str
    goal_room_type: str = ""
    language: str = "zh"


@dataclass
class LayeredTick:
    """单 tick 多模态分层快照（端侧产生，边侧对齐消费）."""

    session_id: str
    version: int
    timestamp_ns: int
    structure: dict[str, Any]
    vision_meta: dict[str, Any]
    vision_payload: bytes
    task: TaskLayer
    present_layers: list[LayerId] = field(default_factory=list)

    def manifest(self) -> dict[str, Any]:
        return {
            "join_key": {
                "session_id": self.session_id,
                "subgraph_version": self.version,
                "timestamp_ns": self.timestamp_ns,
            },
            "present": [layer.value for layer in self.present_layers],
            "schemas": {
                LayerId.STRUCTURE.value: self.structure.get("schema", ""),
                LayerId.VISION.value: self.vision_meta.get("schema", ""),
                LayerId.TASK.value: "motionslam.task_context.v1",
            },
        }


@dataclass
class AlignedBundle:
    """边侧 Aligner 输出：按 join_key 对齐后的分层输入包."""

    session_id: str
    version: int
    timestamp_ns: int
    structure: dict[str, Any]
    vision_meta: Optional[dict[str, Any]] = None
    vision_payload: Optional[bytes] = None
    task: Optional[TaskLayer] = None
    layers_present: list[LayerId] = field(default_factory=list)
    layers_aligned: list[LayerId] = field(default_factory=list)

    def ready_for(self, scheduler: str) -> bool:
        required = SCHEDULER_REQUIRED_LAYERS.get(scheduler, (LayerId.STRUCTURE,))
        return all(layer in self.layers_aligned for layer in required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "session_id": self.session_id,
            "layers_present": [x.value for x in self.layers_present],
            "layers_aligned": [x.value for x in self.layers_aligned],
            "ready_qwen_vl": self.ready_for("qwen_vl"),
            "task_instruction": self.task.instruction if self.task else "",
            "vision_rgb_tag": (self.vision_meta or {}).get("rgb_tag", ""),
        }


def attach_layers_to_subgraph(subgraph: dict[str, Any], tick: LayeredTick) -> dict[str, Any]:
    out = dict(subgraph)
    out["multimodal_layers"] = tick.manifest()
    out["task_context"] = {
        "schema": "motionslam.task_context.v1",
        "instruction": tick.task.instruction,
        "goal_room_type": tick.task.goal_room_type,
        "language": tick.task.language,
    }
    return out


def parse_task_from_subgraph(subgraph: dict[str, Any]) -> Optional[TaskLayer]:
    tc = subgraph.get("task_context")
    if not isinstance(tc, dict):
        return None
    inst = str(tc.get("instruction", "")).strip()
    if not inst:
        return None
    return TaskLayer(
        instruction=inst,
        goal_room_type=str(tc.get("goal_room_type", "")),
        language=str(tc.get("language", "zh")),
    )
