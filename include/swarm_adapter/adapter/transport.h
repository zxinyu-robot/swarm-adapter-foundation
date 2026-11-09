#ifndef SWARM_ADAPTER_ADAPTER_TRANSPORT_H
#define SWARM_ADAPTER_ADAPTER_TRANSPORT_H

#include "swarm_adapter/contract/envelope.h"
#include "swarm_adapter/contract/reason_code.h"
#include "swarm_adapter/contract/topic_policy.h"
#include "swarm_adapter/fusion/byte_view.h"

namespace swarm_adapter {

/// 传输适配接口：怎么传。实现可以是进程内、共享内存、DDS、gRPC。
/// publish 不得阻塞超过 policy.deadline_ms；payload 只在调用期间有效（借用）。
class Transport {
public:
    virtual ~Transport() = default;
    virtual ReasonCode publish(const MessageEnvelope& envelope, const TopicPolicy& policy,
                               fusion::ByteView payload) = 0;
};

}  // namespace swarm_adapter

#endif
