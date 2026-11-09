#include "check.h"

#include "swarm_adapter/directive/directive_gate.h"

using namespace swarm_adapter;
using namespace swarm_adapter::directive;

int main() {
    DirectiveGate gate(2);
    const RobotStatus status{1, 7, 5, 2, false};
    TaskDirective d{1, 1, 7, 5, 2, 1'000'000'000, 500, "frontier_3", 0.8};
    const std::int64_t now = 1'100'000'000;

    expect(gate.admit(d, status, now) == ReasonCode::Ok, "valid directive admitted");
    expect(gate.admit(d, status, now) == ReasonCode::Duplicate, "duplicate rejected");

    d.directive_id = 2;
    expect(gate.admit(d, status, 2'000'000'000) == ReasonCode::Expired, "expired rejected");
    d.directive_id = 3;
    d.lease_epoch = 1;
    expect(gate.admit(d, status, now) == ReasonCode::LeaseMismatch, "old lease rejected");
    d.directive_id = 4;
    d.lease_epoch = 2;
    d.map_version = 4;
    expect(gate.admit(d, status, now) == ReasonCode::MapVersionMismatch, "map version");
    d.directive_id = 5;
    d.map_version = 0;
    expect(gate.admit(d, status, now) == ReasonCode::UnknownMapVersion, "unknown map");
    d.directive_id = 6;
    d.map_version = 5;
    RobotStatus held = status;
    held.safety_hold = true;
    expect(gate.admit(d, held, now) == ReasonCode::SafetyHold, "local safety veto");
    d.directive_id = 7;
    d.robot_id = 2;
    expect(gate.admit(d, status, now) == ReasonCode::InvalidInput, "wrong robot");
    return 0;
}
