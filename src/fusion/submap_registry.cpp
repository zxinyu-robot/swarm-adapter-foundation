#include "swarm_adapter/fusion/submap_registry.h"

#include <cmath>
#include <functional>

namespace swarm_adapter::fusion {
namespace {

void combine(std::size_t& seed, std::size_t value) {
    seed ^= value + 0x9e3779b9U + (seed << 6U) + (seed >> 2U);
}

bool valid_probability(double value) {
    return std::isfinite(value) && value >= 0.0 && value <= 1.0;
}

}  // namespace

std::size_t SubmapIdHash::operator()(const SubmapId& id) const noexcept {
    std::size_t seed = 0;
    combine(seed, std::hash<std::uint32_t>{}(id.robot_id));
    combine(seed, std::hash<std::uint32_t>{}(id.session_id));
    combine(seed, std::hash<std::uint64_t>{}(id.local_id));
    return seed;
}

RegistryResult SubmapRegistry::register_submap(
    const SubmapDescriptor& submap) {
    if (submap.id.robot_id == 0 || submap.id.session_id == 0 ||
        submap.frame_id.empty() || submap.payload_sequence == 0 ||
        !valid_probability(submap.quality)) {
        return {RegistryCode::InvalidInput, graph_version_};
    }
    if (submaps_.count(submap.id) != 0) {
        return {RegistryCode::DuplicateSubmap, graph_version_};
    }
    submaps_.emplace(submap.id, submap);
    return {RegistryCode::Accepted, ++graph_version_};
}

RegistryResult SubmapRegistry::add_constraint(
    const RelativeConstraint& constraint) {
    if (constraint.id == 0 || constraint.from == constraint.to ||
        !valid_probability(constraint.confidence)) {
        return {RegistryCode::InvalidInput, graph_version_};
    }
    for (double covariance : constraint.covariance_diagonal) {
        if (!std::isfinite(covariance) || covariance <= 0.0) {
            return {RegistryCode::InvalidInput, graph_version_};
        }
    }
    for (double value : constraint.translation_xyzw) {
        if (!std::isfinite(value)) {
            return {RegistryCode::InvalidInput, graph_version_};
        }
    }
    if (submaps_.count(constraint.from) == 0 ||
        submaps_.count(constraint.to) == 0) {
        return {RegistryCode::MissingSubmap, graph_version_};
    }
    if (constraint_ids_.count(constraint.id) != 0) {
        return {RegistryCode::DuplicateConstraint, graph_version_};
    }
    constraint_ids_.insert(constraint.id);
    return {RegistryCode::Accepted, ++graph_version_};
}

std::size_t SubmapRegistry::submap_count() const noexcept {
    return submaps_.size();
}

std::size_t SubmapRegistry::constraint_count() const noexcept {
    return constraint_ids_.size();
}

std::uint64_t SubmapRegistry::graph_version() const noexcept {
    return graph_version_;
}

}  // namespace swarm_adapter::fusion
