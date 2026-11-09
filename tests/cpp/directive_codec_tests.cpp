#include "check.h"
#include "swarm_adapter/directive/directive_codec.h"

#include <string>

using namespace swarm_adapter;
using namespace swarm_adapter::directive;

namespace {

TaskDirective sample() {
    TaskDirective d;
    d.directive_id = 18446744073709551615ULL;
    d.robot_id = 4294967295U;
    d.session_id = 123456;
    d.map_version = 9;
    d.lease_epoch = 2;
    d.issued_at_ns = 1'700'000'000'123'456'789LL;
    d.ttl_ms = 30000;
    d.target_node_id = "node \"a\"\\1";
    d.confidence = 0.85;
    return d;
}

std::string with(const std::string& key, const std::string& value) {
    return "{\"schema\":\"swarm_adapter.task_directive.v1\",\"directive_id\":1,\"robot_id\":1,"
           "\"session_id\":1,\"map_version\":1,\"lease_epoch\":1,\"issued_at_ns\":1,\"ttl_ms\":1,"
           "\"confidence\":0.5,\"target_node_id\":\"n\",\"" +
           key + "\":" + value + "}";
}

void test_round_trip() {
    const TaskDirective d = sample();
    TaskDirective back;
    expect(decode_task_directive(encode_task_directive(d), back) == ReasonCode::Ok, "decode");
    expect(back.directive_id == d.directive_id && back.robot_id == d.robot_id, "u64/u32 max");
    expect(back.session_id == d.session_id && back.map_version == d.map_version, "ids");
    expect(back.lease_epoch == d.lease_epoch && back.issued_at_ns == d.issued_at_ns, "lease/time");
    expect(back.ttl_ms == d.ttl_ms && back.confidence == d.confidence, "ttl/confidence");
    expect(back.target_node_id == d.target_node_id, "escaped target");
}

void test_skips_nested_semantic() {
    const std::string line = with(
        "semantic",
        "{\"instruction\":\"找到厨房\",\"ids\":[\"a\",{\"b\":\"}]\"}],\"n\":null,\"ok\":true}");
    TaskDirective d;
    expect(decode_task_directive(line, d) == ReasonCode::Ok, "nested semantic skipped");
    expect(d.target_node_id == "n" && d.confidence == 0.5, "flat fields kept");
}

void test_rejects_bad_input() {
    TaskDirective d;
    expect(decode_task_directive("", d) == ReasonCode::InvalidInput, "empty");
    expect(decode_task_directive("{\"schema\":\"x\"}", d) == ReasonCode::InvalidInput, "schema");
    std::string wrong_schema = encode_task_directive(sample());
    wrong_schema.replace(wrong_schema.find("v1"), 2, "v9");
    expect(decode_task_directive(wrong_schema, d) == ReasonCode::InvalidInput, "schema version");
    std::string missing = encode_task_directive(sample());
    missing.replace(missing.find("\"confidence\""), 1, "\"x");
    expect(decode_task_directive(missing, d) == ReasonCode::InvalidInput, "missing confidence");
    std::string negative = encode_task_directive(sample());
    negative.replace(negative.find("\"robot_id\":4294967295"), 21, "\"robot_id\":-1");
    expect(decode_task_directive(negative, d) == ReasonCode::InvalidInput, "negative unsigned");
    std::string overflow = encode_task_directive(sample());
    overflow.replace(overflow.find("\"robot_id\":4294967295"), 21, "\"robot_id\":4294967296");
    expect(decode_task_directive(overflow, d) == ReasonCode::InvalidInput, "u32 overflow");
    expect(decode_task_directive(encode_task_directive(sample()) + "x", d) ==
               ReasonCode::InvalidInput,
           "trailing garbage");
    expect(decode_task_directive(with("ttl_ms", "1.5"), d) == ReasonCode::InvalidInput, "non-integer ttl");
}

void test_report() {
    ExecutionReport r;
    r.directive_id = 7;
    r.robot_id = 3;
    r.reason = ReasonCode::MapVersionMismatch;
    r.reported_at_ns = 42;
    const std::string text = encode_execution_report(r);
    expect(text.find("\"reason\":\"" + std::string(reason_name(r.reason)) + "\"") !=
               std::string::npos,
           "reason name");
    expect(text.find("\"reason_code\":13") != std::string::npos, "reason code");
    expect(text.find("\"executed\":false") != std::string::npos, "executed");
}

}  // namespace

int main() {
    test_round_trip();
    test_skips_nested_semantic();
    test_rejects_bad_input();
    test_report();
    return 0;
}
