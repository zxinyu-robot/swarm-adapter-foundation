#include "swarm_adapter/directive/directive_gate.h"

#include <cmath>
#include <stdexcept>

namespace swarm_adapter::directive {

DirectiveGate::DirectiveGate(std::size_t remembered_ids) : capacity_(remembered_ids) {
    if (capacity_ == 0) {
        throw std::invalid_argument("directive gate capacity must be positive");
    }
}

ReasonCode DirectiveGate::admit(
    const TaskDirective& directive,
    const RobotStatus& status,
    std::int64_t now_ns) {
    if (directive.directive_id == 0 || directive.robot_id != status.robot_id ||
        directive.session_id != status.session_id || directive.ttl_ms <= 0 ||
        !std::isfinite(directive.confidence) || directive.confidence < 0.0 ||
        directive.confidence > 1.0) {
        return ReasonCode::InvalidInput;
    }
    if (seen_.count(directive.directive_id) != 0) {
        return ReasonCode::Duplicate;
    }
    if (order_.size() == capacity_) {
        seen_.erase(order_.front());
        order_.pop_front();
    }
    order_.push_back(directive.directive_id);
    seen_.insert(directive.directive_id);

    if (directive.map_version == 0) {
        return ReasonCode::UnknownMapVersion;
    }
    if (now_ns - directive.issued_at_ns > directive.ttl_ms * 1'000'000) {
        return ReasonCode::Expired;
    }
    if (directive.lease_epoch != status.lease_epoch) {
        return ReasonCode::LeaseMismatch;
    }
    if (directive.map_version != status.map_version) {
        return ReasonCode::MapVersionMismatch;
    }
    if (status.safety_hold) {
        return ReasonCode::SafetyHold;
    }
    return ReasonCode::Ok;
}

}  // namespace swarm_adapter::directive
