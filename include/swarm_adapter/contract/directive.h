#ifndef SWARM_ADAPTER_CONTRACT_DIRECTIVE_H
#define SWARM_ADAPTER_CONTRACT_DIRECTIVE_H

#include "swarm_adapter/contract/reason_code.h"

#include <cstdint>
#include <string>

namespace swarm_adapter {

/// 调度端下发给单台机器人的任务指令。调度端只有建议权，
/// 机器人本机安全模块（safety_hold）可以否决。
struct TaskDirective {
    std::uint64_t directive_id{};
    std::uint32_t robot_id{};
    std::uint32_t session_id{};
    std::uint64_t map_version{};
    std::uint64_t lease_epoch{};
    std::int64_t issued_at_ns{};
    std::int64_t ttl_ms{};
    std::string target_node_id;
    double confidence{};
};

/// 机器人当前状态快照，由 RobotBackend 提供。
struct RobotStatus {
    std::uint32_t robot_id{};
    std::uint32_t session_id{};
    std::uint64_t map_version{};
    std::uint64_t lease_epoch{};
    bool safety_hold{};
};

/// 指令执行回执，回传给调度端。
struct ExecutionReport {
    std::uint64_t directive_id{};
    std::uint32_t robot_id{};
    ReasonCode reason{ReasonCode::Ok};
    bool executed{};
    std::int64_t reported_at_ns{};
};

}  // namespace swarm_adapter

#endif
