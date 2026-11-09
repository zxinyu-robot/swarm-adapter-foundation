#ifndef SWARM_ADAPTER_CONTRACT_REASON_CODE_H
#define SWARM_ADAPTER_CONTRACT_REASON_CODE_H

#include <cstdint>

namespace swarm_adapter {

/// 全仓统一的结果码。字段与 proto/swarm_adapter/v1/envelope.proto 的 ReasonCode 一一对应。
enum class ReasonCode : std::uint8_t {
    Ok = 0,
    InvalidInput = 1,
    UnknownMapVersion = 2,
    Expired = 3,
    ClockUnsynchronized = 4,
    Duplicate = 5,
    MissingReference = 6,
    RoundMismatch = 7,
    StalePolicyVersion = 8,
    OutsideSafetyEnvelope = 9,
    ShadowRejected = 10,
    RolledBack = 11,
    LeaseMismatch = 12,
    MapVersionMismatch = 13,
    SafetyHold = 14,
    IoError = 15,
};

/// 返回结果码的稳定字符串名，用于日志和记录文件。
const char* reason_name(ReasonCode code) noexcept;

}  // namespace swarm_adapter

#endif
