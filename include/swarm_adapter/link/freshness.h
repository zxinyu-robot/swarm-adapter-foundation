#ifndef SWARM_ADAPTER_LINK_FRESHNESS_H
#define SWARM_ADAPTER_LINK_FRESHNESS_H

#include "swarm_adapter/contract/envelope.h"
#include "swarm_adapter/contract/reason_code.h"
#include "swarm_adapter/link/clock_offset_estimator.h"

#include <cstdint>

namespace swarm_adapter::link {

/// 接收端算出的一条消息的新鲜度。
struct FreshnessSample {
    MessageClass message_class{MessageClass::Pose};
    std::int64_t age_ns{};
    std::int64_t deadline_ns{};
    double age_ratio{};
    bool on_time{};
    std::int64_t clock_uncertainty_ns{};
    bool trainable{};
};

/// 新鲜度 = 接收时间 - 发送时间 - 时钟偏差。
///
/// 只在接收端计算。时钟未同步或误差超过上限的样本仍会返回统计值，
/// 但 trainable = false，不进入本地训练集。
class FreshnessEvaluator {
public:
    explicit FreshnessEvaluator(std::int64_t max_clock_uncertainty_ns = 2'000'000);

    /// @param envelope 收到的信封。
    /// @param receive_time_ns 接收端本地时间（纳秒）。
    /// @param clock 发送端到接收端的时钟偏差估计。
    /// @param deadline_ms 该类消息的时效要求（来自当前 TopicPolicy）。
    /// @param out 输出样本，任何返回码下都会被填写。
    /// @return Ok；或 InvalidInput / UnknownMapVersion / Expired / ClockUnsynchronized。
    ReasonCode evaluate(
        const MessageEnvelope& envelope,
        std::int64_t receive_time_ns,
        const ClockEstimate& clock,
        std::int64_t deadline_ms,
        FreshnessSample& out) const;

private:
    std::int64_t max_clock_uncertainty_ns_;
};

}  // namespace swarm_adapter::link

#endif
