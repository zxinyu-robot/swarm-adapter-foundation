"""Qwen2.5-VL 边侧推理客户端."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

from edge.multimodal_layers import AlignedBundle
from edge.qwen_vl.prompt import build_user_prompt, parse_model_json, sanitize_inference
from edge.qwen_vl.rgb_decode import payload_to_image
from edge.qwen_vl.stub import stub_infer
from edge.schedulers import pick_layer_fusion_stub


@dataclass
class QwenVLInferenceResult:
    candidate_frontier_ids: list[str]
    target_subgraph_node_id: str
    exploration_bias: str
    confidence: float
    room_found: bool
    found_room_type: str
    natural_language_explanation: str
    source: str = "qwen_vl"

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, source: str = "qwen_vl") -> "QwenVLInferenceResult":
        return cls(
            candidate_frontier_ids=list(d.get("candidate_frontier_ids") or ["bt_next_subgoal"]),
            target_subgraph_node_id=str(d.get("target_subgraph_node_id", "")),
            exploration_bias=str(d.get("exploration_bias", "BIAS_TOWARD_SUBGRAPH_NODE")),
            confidence=float(d.get("confidence", 0.85)),
            room_found=bool(d.get("room_found", False)),
            found_room_type=str(d.get("found_room_type", "")),
            natural_language_explanation=str(d.get("natural_language_explanation", "")),
            source=source,
        )


class QwenVLClient:
    """Lazy-load Qwen2.5-VL；stub=True 时用 CPU 规则（仿真/无 GPU）."""

    def __init__(
        self,
        *,
        model_id: str = "Qwen/Qwen2.5-VL-3B-Instruct",
        device: str = "cuda:0",
        load_in_4bit: bool = True,
        max_new_tokens: int = 512,
        min_interval_s: float = 0.5,
        stub: bool = False,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.load_in_4bit = load_in_4bit
        self.max_new_tokens = max_new_tokens
        self.min_interval_s = min_interval_s
        self.stub = stub
        self._model: Any = None
        self._processor: Any = None
        self._lock = threading.Lock()
        self._last_infer_mono = 0.0

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

        kwargs: dict[str, Any] = {
            "torch_dtype": torch.bfloat16,
            "device_map": "auto" if self.device == "auto" else None,
        }
        if self.load_in_4bit:
            kwargs["load_in_4bit"] = True
        if self.device != "auto":
            kwargs["device_map"] = {"": self.device}

        print(f"[qwen_vl] loading {self.model_id} 4bit={self.load_in_4bit} ...", flush=True)
        self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(self.model_id, **kwargs)
        self._processor = AutoProcessor.from_pretrained(self.model_id)
        if self.device != "auto" and not self.load_in_4bit:
            self._model = self._model.to(self.device)
        print("[qwen_vl] model ready", flush=True)

    def infer(
        self,
        subgraph: dict[str, Any],
        bundle: AlignedBundle,
        instruction: str,
    ) -> QwenVLInferenceResult:
        with self._lock:
            elapsed = time.monotonic() - self._last_infer_mono
            if elapsed < self.min_interval_s:
                time.sleep(self.min_interval_s - elapsed)

            fallback = pick_layer_fusion_stub(bundle) if bundle.ready_for("layer_fusion_stub") else "bt_next_subgoal"

            if self.stub:
                raw = stub_infer(subgraph, bundle, instruction)
                self._last_infer_mono = time.monotonic()
                return QwenVLInferenceResult.from_dict(raw, source="qwen_vl_stub")

            try:
                result = self._infer_gpu(subgraph, bundle, instruction, fallback_pick=fallback)
                self._last_infer_mono = time.monotonic()
                return result
            except Exception as exc:  # noqa: BLE001 — 降级不得拖垮网关
                print(f"[qwen_vl] infer failed, fallback stub: {exc}", flush=True)
                raw = stub_infer(subgraph, bundle, instruction)
                self._last_infer_mono = time.monotonic()
                out = QwenVLInferenceResult.from_dict(raw, source="qwen_vl_fallback")
                out.natural_language_explanation = f"[fallback after error] {out.natural_language_explanation}"
                return out

    def _infer_gpu(
        self,
        subgraph: dict[str, Any],
        bundle: AlignedBundle,
        instruction: str,
        *,
        fallback_pick: str,
    ) -> QwenVLInferenceResult:
        self._ensure_model()
        assert self._model is not None and self._processor is not None

        meta = bundle.vision_meta or {}
        payload = bundle.vision_payload or b""
        image = payload_to_image(payload, meta)
        prompt_text = build_user_prompt(instruction=instruction, subgraph=subgraph)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt_text},
                ],
            }
        ]

        text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._processor(text=[text], images=[image], return_tensors="pt")
        inputs = inputs.to(self._model.device)

        generated = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens)
        trimmed = [out[len(inp) :] for inp, out in zip(inputs.input_ids, generated)]
        response = self._processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )[0]

        parsed = parse_model_json(response)
        sanitized = sanitize_inference(parsed, subgraph, fallback_pick=fallback_pick)
        print(
            f"[qwen_vl] pick={sanitized['candidate_frontier_ids'][:3]} "
            f"conf={sanitized['confidence']:.2f}",
            flush=True,
        )
        return QwenVLInferenceResult.from_dict(sanitized, source="qwen_vl")
