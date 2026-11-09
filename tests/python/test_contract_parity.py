"""proto 枚举与 C++ 枚举逐项一致（名字转 SCREAMING_SNAKE，值相同）。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def cpp_enum(header: str, name: str) -> dict[str, int]:
    text = (ROOT / header).read_text()
    body = re.search(rf"enum class {name}[^{{]*{{(.*?)}};", text, re.S).group(1)
    out = {}
    for key, value in re.findall(r"(\w+)\s*=\s*(\d+)", body):
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", key).upper()
        out[snake] = int(value)
    return out


def proto_enum(proto: str, name: str, prefix: str) -> dict[str, int]:
    text = (ROOT / proto).read_text()
    body = re.search(rf"enum {name}\s*{{(.*?)}}", text, re.S).group(1)
    return {k[len(prefix):]: int(v) for k, v in re.findall(r"(\w+)\s*=\s*(\d+);", body)}


def test_reason_code_parity():
    assert cpp_enum("include/swarm_adapter/contract/reason_code.h", "ReasonCode") == proto_enum(
        "proto/swarm_adapter/v1/envelope.proto", "ReasonCode", "REASON_CODE_"
    )


def test_message_class_parity():
    assert cpp_enum("include/swarm_adapter/contract/envelope.h", "MessageClass") == proto_enum(
        "proto/swarm_adapter/v1/envelope.proto", "MessageClass", "MESSAGE_CLASS_"
    )


def test_gate_state_parity():
    assert cpp_enum("include/swarm_adapter/strategy/policy_gate.h", "GateState") == proto_enum(
        "proto/swarm_adapter/v1/learning.proto", "GateState", "GATE_STATE_"
    )


def test_reliability_parity():
    assert cpp_enum("include/swarm_adapter/contract/topic_policy.h", "Reliability") == proto_enum(
        "proto/swarm_adapter/v1/envelope.proto", "Reliability", "RELIABILITY_"
    )
