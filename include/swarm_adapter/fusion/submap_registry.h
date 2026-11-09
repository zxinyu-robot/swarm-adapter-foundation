#ifndef SWARM_ADAPTER_FUSION_SUBMAP_REGISTRY_H
#define SWARM_ADAPTER_FUSION_SUBMAP_REGISTRY_H

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <unordered_set>

namespace swarm_adapter::fusion {

struct SubmapId {
    std::uint32_t robot_id{};
    std::uint32_t session_id{};
    std::uint64_t local_id{};
};

inline bool operator==(const SubmapId& a, const SubmapId& b) noexcept {
    return a.robot_id == b.robot_id && a.session_id == b.session_id &&
           a.local_id == b.local_id;
}

inline bool operator!=(const SubmapId& a, const SubmapId& b) noexcept {
    return !(a == b);
}

struct SubmapIdHash {
    std::size_t operator()(const SubmapId& id) const noexcept;
};

struct SubmapDescriptor {
    SubmapId id;
    std::int64_t timestamp_ns{};
    std::string frame_id;
    std::uint64_t payload_sequence{};
    std::uint64_t payload_checksum{};
    double quality{};
};

struct RelativeConstraint {
    std::uint64_t id{};
    SubmapId from;
    SubmapId to;
    std::array<double, 7> translation_xyzw{};
    std::array<double, 6> covariance_diagonal{};
    double confidence{};
};

enum class RegistryCode {
    Accepted,
    DuplicateSubmap,
    DuplicateConstraint,
    MissingSubmap,
    InvalidInput,
};

struct RegistryResult {
    RegistryCode code{RegistryCode::Accepted};
    std::uint64_t graph_version{};
    explicit operator bool() const noexcept {
        return code == RegistryCode::Accepted;
    }
};

class SubmapRegistry {
public:
    RegistryResult register_submap(const SubmapDescriptor& submap);
    RegistryResult add_constraint(const RelativeConstraint& constraint);

    [[nodiscard]] std::size_t submap_count() const noexcept;
    [[nodiscard]] std::size_t constraint_count() const noexcept;
    [[nodiscard]] std::uint64_t graph_version() const noexcept;

private:
    std::unordered_map<SubmapId, SubmapDescriptor, SubmapIdHash> submaps_;
    std::unordered_set<std::uint64_t> constraint_ids_;
    std::uint64_t graph_version_{};
};

}  // namespace swarm_adapter::fusion

#endif
