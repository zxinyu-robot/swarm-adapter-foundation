#ifndef SWARM_ADAPTER_DIRECTIVE_DIRECTIVE_CODEC_H
#define SWARM_ADAPTER_DIRECTIVE_DIRECTIVE_CODEC_H

#include "swarm_adapter/contract/directive.h"
#include "swarm_adapter/contract/reason_code.h"

#include <string>
#include <string_view>

namespace swarm_adapter::directive {

/// 下行指令的 JSONL 线格式（一行一个 JSON 对象）。字段与 proto TaskDirective 一致；
/// 边侧可以附带任意嵌套字段（如原始语义指令 "semantic"），解码时跳过。
inline constexpr const char* kTaskDirectiveSchema = "swarm_adapter.task_directive.v1";
inline constexpr const char* kExecutionReportSchema = "swarm_adapter.execution_report.v1";

/// 缺字段、类型不符、无符号字段为负或越界、schema 不匹配都返回 InvalidInput。
ReasonCode decode_task_directive(std::string_view line, TaskDirective& out);

std::string encode_task_directive(const TaskDirective& directive);
std::string encode_execution_report(const ExecutionReport& report);

}  // namespace swarm_adapter::directive

#endif
