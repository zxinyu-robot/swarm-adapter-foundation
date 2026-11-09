#ifndef SWARM_ADAPTER_FUSION_SHARED_FRAME_SLOT_H
#define SWARM_ADAPTER_FUSION_SHARED_FRAME_SLOT_H

#include <cstddef>
#include <cstdint>
#include <semaphore.h>
#include <string>

#include "swarm_adapter/fusion/byte_view.h"

namespace swarm_adapter::fusion {

class SharedFrameSlot {
public:
    enum class Mode { Create, Open };

    class FrameView {
    public:
        FrameView(const FrameView&) = delete;
        FrameView& operator=(const FrameView&) = delete;
        FrameView(FrameView&& other) noexcept;
        FrameView& operator=(FrameView&& other) noexcept;
        ~FrameView();

        [[nodiscard]] std::uint64_t sequence() const noexcept {
            return sequence_;
        }
        [[nodiscard]] ByteView bytes() const noexcept {
            return bytes_;
        }

    private:
        friend class SharedFrameSlot;
        FrameView(
            sem_t* semaphore,
            std::uint64_t sequence,
            ByteView bytes) noexcept;
        void release() noexcept;

        sem_t* semaphore_{SEM_FAILED};
        std::uint64_t sequence_{};
        ByteView bytes_;
    };

    SharedFrameSlot(
        std::string name,
        std::size_t capacity,
        Mode mode,
        bool unlink_on_destroy = false);
    SharedFrameSlot(const SharedFrameSlot&) = delete;
    SharedFrameSlot& operator=(const SharedFrameSlot&) = delete;
    ~SharedFrameSlot();

    std::uint64_t publish(ByteView payload);
    [[nodiscard]] FrameView view_latest() const;
    [[nodiscard]] std::size_t capacity() const noexcept { return capacity_; }

private:
    std::string name_;
    std::string semaphore_name_;
    std::size_t capacity_{};
    int descriptor_{-1};
    sem_t* semaphore_{SEM_FAILED};
    void* mapping_{};
    std::size_t mapping_size_{};
    bool unlink_on_destroy_{};
};

}  // namespace swarm_adapter::fusion

#endif
