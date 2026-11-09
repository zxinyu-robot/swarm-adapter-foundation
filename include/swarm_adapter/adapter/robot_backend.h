#ifndef SWARM_ADAPTER_ADAPTER_ROBOT_BACKEND_H
#define SWARM_ADAPTER_ADAPTER_ROBOT_BACKEND_H

#include "swarm_adapter/contract/directive.h"
#include "swarm_adapter/contract/reason_code.h"

namespace swarm_adapter {

/// 具体机器人适配接口（Go2、无人机等）。execute 只会收到已通过 DirectiveGate 的指令。
class RobotBackend {
public:
    virtual ~RobotBackend() = default;
    [[nodiscard]] virtual RobotStatus status() const = 0;
    virtual ReasonCode execute(const TaskDirective& directive) = 0;
};

}  // namespace swarm_adapter

#endif
