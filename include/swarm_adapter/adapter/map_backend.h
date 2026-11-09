#ifndef SWARM_ADAPTER_ADAPTER_MAP_BACKEND_H
#define SWARM_ADAPTER_ADAPTER_MAP_BACKEND_H

#include "swarm_adapter/fusion/submap_registry.h"

#include <cstdint>

namespace swarm_adapter {

/// 建图后端适配接口。首版实现为 LocalMapBackend（基于 SubmapRegistry）；
/// 接 Swarm-SLAM 等外部后端时实现本接口。
class MapBackend {
public:
    virtual ~MapBackend() = default;
    virtual fusion::RegistryResult submit_submap(const fusion::SubmapDescriptor& submap) = 0;
    virtual fusion::RegistryResult submit_constraint(
        const fusion::RelativeConstraint& constraint) = 0;
    [[nodiscard]] virtual std::uint64_t map_version() const = 0;
};

class LocalMapBackend final : public MapBackend {
public:
    fusion::RegistryResult submit_submap(const fusion::SubmapDescriptor& submap) override {
        return registry_.register_submap(submap);
    }
    fusion::RegistryResult submit_constraint(
        const fusion::RelativeConstraint& constraint) override {
        return registry_.add_constraint(constraint);
    }
    [[nodiscard]] std::uint64_t map_version() const override {
        return registry_.graph_version();
    }

private:
    fusion::SubmapRegistry registry_;
};

}  // namespace swarm_adapter

#endif
