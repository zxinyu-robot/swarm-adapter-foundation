#ifndef SWARM_ADAPTER_STRATEGY_FEATURES_H
#define SWARM_ADAPTER_STRATEGY_FEATURES_H

#include <array>
#include <cstddef>

namespace swarm_adapter::strategy {

/// 链路状况 + 新鲜度，作为策略输入。全部来自通信层；
/// 不包含任何状态估计（滤波器）内部量。
struct LinkFeatures {
    double packet_loss_ratio{};
    double latency_s{};
    double queue_fill_ratio{};
    double age_ratio{};
};

/// 策略可以选择的通信动作，作用在 TopicPolicy 上。
struct CommAction {
    double rate_scale{1.0};
    int compression_level{};
    bool reliable{};
};

/// 一次执行后的效果回执（接收端统计）。
struct Outcome {
    double delivered_ratio{};
    double on_time_ratio{};
    double bandwidth_ratio{};
};

constexpr std::size_t kFeatureDim = 12;
constexpr int kMaxCompressionLevel = 9;
constexpr double kMaxAgeRatio = 4.0;

using FeatureVector = std::array<double, kFeatureDim>;

/// 特征向量 phi(x, a)。定义见 docs/contracts.md，
/// Python 端 swarm_adapter.features 必须逐位一致（tests/fixtures/feature_golden.txt）。
FeatureVector make_features(const LinkFeatures& link, const CommAction& action);

/// 效果效用：准时率 - 0.2 * 带宽占用 - 0.5 * (1 - 送达率)。
double outcome_utility(const Outcome& outcome);

bool valid(const LinkFeatures& link) noexcept;
bool valid(const CommAction& action) noexcept;
bool valid(const Outcome& outcome) noexcept;

}  // namespace swarm_adapter::strategy

#endif
