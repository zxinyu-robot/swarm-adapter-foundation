#include "swarm_adapter/fusion/shared_frame_slot.h"
#include "swarm_adapter/fusion/submap_registry.h"

#include <cstdlib>
#include <iostream>
#include <string>
#include <unistd.h>

namespace {

void expect(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << "FAILED: " << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main() {
    using namespace swarm_adapter::fusion;

    const std::string name =
        "/swarm_adapter_test_" + std::to_string(::getpid());
    SharedFrameSlot writer(name, 128, SharedFrameSlot::Mode::Create, true);
    SharedFrameSlot reader(name, 128, SharedFrameSlot::Mode::Open);
    const std::string payload = "point-cloud-keyframe";
    expect(
        writer.publish(ByteView::of(payload)) == 1,
        "first shared frame should have sequence one");
    {
        const auto view = reader.view_latest();
        expect(view.sequence() == 1, "reader should see latest sequence");
        expect(view.bytes().size() == payload.size(), "payload size should match");
    }

    SubmapRegistry registry;
    const SubmapId a{1, 1, 1};
    const SubmapId b{2, 1, 1};
    expect(
        static_cast<bool>(
            registry.register_submap({a, 1, "a", 1, 10, 0.9})),
        "first submap should register");
    expect(
        static_cast<bool>(
            registry.register_submap({b, 2, "b", 1, 20, 0.8})),
        "second submap should register");
    expect(
        registry.register_submap({a, 1, "a", 1, 10, 0.9}).code ==
            RegistryCode::DuplicateSubmap,
        "duplicate submap should be rejected");

    const RelativeConstraint constraint{
        1,
        a,
        b,
        {1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0},
        {0.1, 0.1, 0.1, 0.1, 0.1, 0.1},
        0.9,
    };
    expect(
        static_cast<bool>(registry.add_constraint(constraint)),
        "constraint should register");
    expect(
        registry.add_constraint(constraint).code ==
            RegistryCode::DuplicateConstraint,
        "duplicate constraint should be rejected");
    expect(registry.graph_version() == 3, "accepted operations should version graph");
    return 0;
}
