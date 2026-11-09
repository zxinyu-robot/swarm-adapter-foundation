#ifndef SWARM_ADAPTER_DIRECTIVE_DIRECTIVE_GATE_H
#define SWARM_ADAPTER_DIRECTIVE_DIRECTIVE_GATE_H

#include "swarm_adapter/contract/directive.h"
#include "swarm_adapter/contract/reason_code.h"

#include <cstddef>
#include <cstdint>
#include <deque>
#include <unordered_set>

namespace swarm_adapter::directive {

/// 下行指令准入：调度端只给建议，本机按以下顺序校验，任一不过即拒绝：
/// 身份 → 重复 → 过期 → 租约 epoch → 地图版本 → 本机安全否决。
/// 线程安全：否。
class DirectiveGate {
public:
    explicit DirectiveGate(std::size_t remembered_ids = 1024);

    ReasonCode admit(const TaskDirective& directive, const RobotStatus& status,
                     std::int64_t now_ns);

private:
    std::size_t capacity_;
    std::deque<std::uint64_t> order_;
    std::unordered_set<std::uint64_t> seen_;
};

}  // namespace swarm_adapter::directive

#endif
