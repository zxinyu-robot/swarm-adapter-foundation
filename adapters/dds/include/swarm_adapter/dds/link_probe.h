#ifndef SWARM_ADAPTER_DDS_LINK_PROBE_H
#define SWARM_ADAPTER_DDS_LINK_PROBE_H

#include "swarm_adapter/dds/dds_transport.h"

#include <cstdint>
#include <cstdio>
#include <string>

namespace swarm_adapter::dds {

/// 链路探测：发送端按窗口在安全边界的候选动作里随机选一个通信配置发送，
/// 接收端算新鲜度并按 decision_id 回传效果，发送端把
/// 链路观测 / 配置决策 / 效果回执写进 RingStrategyStore。
/// 只探索 rate_scale 和 reliable；compression_level 固定为 0（本仓未实现真实压缩）。
struct ProbeConfig {
    std::uint32_t robot_id{1};
    MessageClass message_class{MessageClass::Keyframe};
    double base_rate_hz{20.0};
    std::size_t payload_bytes{2000};
    std::int64_t deadline_ms{200};
    std::int64_t ttl_ms{1000};
    double window_s{2.0};
    std::size_t windows{30};
    std::uint64_t seed{1};
    std::int64_t clock_max_deviation_ns{5'000'000};
    double match_timeout_s{15.0};
    double rx_idle_exit_s{5.0};
    double rx_max_duration_s{0.0};  ///< 0 表示不限
    std::string records_dir;        ///< 发送端分段文件目录；空则不落盘
};

struct ProbeSummary {
    std::size_t outcomes{};
    std::size_t trainable{};
    double mean_delivered{};
    double mean_on_time{};
    std::string segment_path;
};

int run_probe_tx(DdsParticipant& participant, const ProbeConfig& config, ProbeSummary& summary,
                 std::FILE* log);
int run_probe_rx(DdsParticipant& participant, const ProbeConfig& config, std::FILE* log);

}  // namespace swarm_adapter::dds

#endif
