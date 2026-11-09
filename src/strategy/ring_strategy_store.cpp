#include "swarm_adapter/strategy/ring_strategy_store.h"

#include <algorithm>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace swarm_adapter::strategy {
namespace {

std::ostringstream json_stream() {
    std::ostringstream out;
    out << std::setprecision(std::numeric_limits<double>::max_digits10);
    return out;
}

void write_features(std::ostringstream& out, const LinkFeatures& f) {
    out << "\"packet_loss_ratio\":" << f.packet_loss_ratio
        << ",\"latency_s\":" << f.latency_s
        << ",\"queue_fill_ratio\":" << f.queue_fill_ratio
        << ",\"age_ratio\":" << f.age_ratio;
}

std::string to_json(const LinkObservationRecord& r) {
    auto out = json_stream();
    out << "{\"table\":\"link_observation\",\"record_id\":" << r.record_id
        << ",\"time_ns\":" << r.time_ns << ",\"robot_id\":" << r.robot_id
        << ",\"message_class\":\"" << message_class_name(r.message_class)
        << "\",\"network_mode\":\"" << network_mode_tag_name(r.network_mode) << "\",";
    write_features(out, r.features);
    out << '}';
    return out.str();
}

std::string to_json(const ConfigDecisionRecord& r) {
    auto out = json_stream();
    out << "{\"table\":\"config_decision\",\"decision_id\":" << r.decision_id
        << ",\"time_ns\":" << r.time_ns << ",\"robot_id\":" << r.robot_id
        << ",\"message_class\":\"" << message_class_name(r.message_class) << "\",";
    write_features(out, r.features);
    out << ",\"rate_scale\":" << r.action.rate_scale
        << ",\"compression_level\":" << r.action.compression_level
        << ",\"reliable\":" << (r.action.reliable ? "true" : "false")
        << ",\"source\":\"" << decision_source_name(r.source)
        << "\",\"policy_version\":" << r.policy_version << '}';
    return out.str();
}

std::string to_json(const OutcomeRecord& r) {
    auto out = json_stream();
    out << "{\"table\":\"outcome\",\"decision_id\":" << r.decision_id
        << ",\"time_ns\":" << r.time_ns
        << ",\"delivered_ratio\":" << r.outcome.delivered_ratio
        << ",\"on_time_ratio\":" << r.outcome.on_time_ratio
        << ",\"bandwidth_ratio\":" << r.outcome.bandwidth_ratio
        << ",\"clock_uncertainty_ns\":" << r.clock_uncertainty_ns
        << ",\"trainable\":" << (r.trainable ? "true" : "false") << '}';
    return out.str();
}

std::string to_json(const PolicyVersionRecord& r) {
    auto out = json_stream();
    out << "{\"table\":\"policy_version\",\"time_ns\":" << r.time_ns
        << ",\"policy_version\":" << r.event.policy_version
        << ",\"round_id\":" << r.event.round_id
        << ",\"state\":\"" << gate_state_name(r.event.state)
        << "\",\"reason\":\"" << reason_name(r.event.reason)
        << "\",\"candidate_mse\":" << r.event.candidate_mse
        << ",\"active_mse\":" << r.event.active_mse << '}';
    return out.str();
}

}  // namespace

const char* network_mode_tag_name(NetworkModeTag mode) noexcept {
    switch (mode) {
        case NetworkModeTag::Healthy: return "healthy";
        case NetworkModeTag::Constrained: return "constrained";
        case NetworkModeTag::Critical: return "critical";
    }
    return "unknown";
}

const char* decision_source_name(DecisionSource source) noexcept {
    switch (source) {
        case DecisionSource::LocalRule: return "local_rule";
        case DecisionSource::FederatedPolicy: return "federated_policy";
    }
    return "unknown";
}

RingStrategyStore::RingStrategyStore(std::size_t capacity_per_table)
    : capacity_(capacity_per_table) {
    if (capacity_ == 0) {
        throw std::invalid_argument("strategy store capacity must be positive");
    }
}

ReasonCode RingStrategyStore::append(const LinkObservationRecord& record) {
    if (record.robot_id == 0 || !valid(record.features)) {
        return ReasonCode::InvalidInput;
    }
    if (observations_.size() == capacity_) {
        observations_.pop_front();
    }
    observations_.push_back(record);
    pending_lines_.push_back(to_json(record));
    return ReasonCode::Ok;
}

ReasonCode RingStrategyStore::append(const ConfigDecisionRecord& record) {
    if (record.decision_id == 0 || record.robot_id == 0 || !valid(record.features) ||
        !valid(record.action) ||
        (record.source == DecisionSource::FederatedPolicy && record.policy_version == 0)) {
        return ReasonCode::InvalidInput;
    }
    if (decision_ids_.count(record.decision_id) != 0) {
        return ReasonCode::Duplicate;
    }
    if (decisions_.size() == capacity_) {
        drop_oldest_decision();
    }
    decisions_.push_back(record);
    decision_ids_.insert(record.decision_id);
    pending_lines_.push_back(to_json(record));
    return ReasonCode::Ok;
}

ReasonCode RingStrategyStore::append(const OutcomeRecord& record) {
    if (!valid(record.outcome) || record.clock_uncertainty_ns < 0) {
        return ReasonCode::InvalidInput;
    }
    if (decision_ids_.count(record.decision_id) == 0) {
        return ReasonCode::MissingReference;
    }
    if (outcomes_.count(record.decision_id) != 0) {
        return ReasonCode::Duplicate;
    }
    outcomes_.emplace(record.decision_id, record);
    pending_lines_.push_back(to_json(record));
    return ReasonCode::Ok;
}

ReasonCode RingStrategyStore::append(const PolicyVersionRecord& record) {
    if (policy_events_.size() == capacity_) {
        policy_events_.pop_front();
    }
    policy_events_.push_back(record);
    pending_lines_.push_back(to_json(record));
    return ReasonCode::Ok;
}

void RingStrategyStore::drop_oldest_decision() {
    const std::uint64_t id = decisions_.front().decision_id;
    decisions_.pop_front();
    decision_ids_.erase(id);
    outcomes_.erase(id);
}

std::vector<TrainingSample> RingStrategyStore::samples(
    std::uint64_t min_version,
    std::uint64_t max_version) const {
    std::vector<TrainingSample> out;
    for (const ConfigDecisionRecord& decision : decisions_) {
        if (decision.policy_version < min_version || decision.policy_version > max_version) {
            continue;
        }
        const auto found = outcomes_.find(decision.decision_id);
        if (found == outcomes_.end() || !found->second.trainable) {
            continue;
        }
        out.push_back({decision, found->second});
    }
    return out;
}

std::size_t RingStrategyStore::evict_older_than(std::int64_t cutoff_ns) {
    std::size_t evicted = 0;
    while (!observations_.empty() && observations_.front().time_ns < cutoff_ns) {
        observations_.pop_front();
        ++evicted;
    }
    while (!decisions_.empty() && decisions_.front().time_ns < cutoff_ns) {
        evicted += outcomes_.count(decisions_.front().decision_id) + 1;
        drop_oldest_decision();
    }
    while (!policy_events_.empty() && policy_events_.front().time_ns < cutoff_ns) {
        policy_events_.pop_front();
        ++evicted;
    }
    return evicted;
}

ReasonCode RingStrategyStore::flush_segment(
    const std::string& directory,
    std::string& written_path) {
    written_path.clear();
    if (pending_lines_.empty()) {
        return ReasonCode::Ok;
    }
    std::ostringstream name;
    name << directory << "/segment_" << std::setw(6) << std::setfill('0') << next_segment_
         << ".jsonl";
    const std::string path = name.str();
    {
        std::ofstream out(path, std::ios::app);
        if (!out) {
            return ReasonCode::IoError;
        }
        for (const std::string& line : pending_lines_) {
            out << line << '\n';
        }
        if (!out) {
            return ReasonCode::IoError;
        }
    }
    pending_lines_.clear();
    ++next_segment_;
    written_path = path;
    return ReasonCode::Ok;
}

}  // namespace swarm_adapter::strategy
