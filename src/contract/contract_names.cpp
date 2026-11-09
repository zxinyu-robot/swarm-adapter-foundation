#include "swarm_adapter/contract/envelope.h"
#include "swarm_adapter/contract/reason_code.h"

namespace swarm_adapter {

const char* reason_name(ReasonCode code) noexcept {
    switch (code) {
        case ReasonCode::Ok: return "ok";
        case ReasonCode::InvalidInput: return "invalid_input";
        case ReasonCode::UnknownMapVersion: return "unknown_map_version";
        case ReasonCode::Expired: return "expired";
        case ReasonCode::ClockUnsynchronized: return "clock_unsynchronized";
        case ReasonCode::Duplicate: return "duplicate";
        case ReasonCode::MissingReference: return "missing_reference";
        case ReasonCode::RoundMismatch: return "round_mismatch";
        case ReasonCode::StalePolicyVersion: return "stale_policy_version";
        case ReasonCode::OutsideSafetyEnvelope: return "outside_safety_envelope";
        case ReasonCode::ShadowRejected: return "shadow_rejected";
        case ReasonCode::RolledBack: return "rolled_back";
        case ReasonCode::LeaseMismatch: return "lease_mismatch";
        case ReasonCode::MapVersionMismatch: return "map_version_mismatch";
        case ReasonCode::SafetyHold: return "safety_hold";
        case ReasonCode::IoError: return "io_error";
    }
    return "unknown";
}

const char* message_class_name(MessageClass value) noexcept {
    switch (value) {
        case MessageClass::Pose: return "pose";
        case MessageClass::Health: return "health";
        case MessageClass::Keyframe: return "keyframe";
        case MessageClass::Submap: return "submap";
        case MessageClass::Mission: return "mission";
        case MessageClass::LearningUpdate: return "learning_update";
        case MessageClass::Directive: return "directive";
    }
    return "unknown";
}

}  // namespace swarm_adapter
