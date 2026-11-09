#include "swarm_adapter/fusion/shared_frame_slot.h"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <system_error>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>

namespace swarm_adapter::fusion {
namespace {

constexpr std::uint64_t kMagic = 0x4D524D465553494FULL;

struct alignas(64) FrameHeader {
    std::uint64_t magic{};
    std::uint64_t capacity{};
    std::uint64_t sequence{};
    std::uint64_t payload_size{};
    std::uint64_t checksum{};
};

std::uint64_t checksum(ByteView bytes) {
    std::uint64_t value = 1469598103934665603ULL;
    for (std::byte byte : bytes) {
        value ^= static_cast<std::uint8_t>(byte);
        value *= 1099511628211ULL;
    }
    return value;
}

[[noreturn]] void throw_system_error(const char* operation) {
    throw std::system_error(errno, std::generic_category(), operation);
}

void lock_semaphore(sem_t* semaphore) {
    while (::sem_wait(semaphore) != 0) {
        if (errno != EINTR) {
            throw_system_error("sem_wait");
        }
    }
}

}  // namespace

SharedFrameSlot::FrameView::FrameView(
    sem_t* semaphore,
    std::uint64_t sequence,
    ByteView bytes) noexcept
    : semaphore_(semaphore), sequence_(sequence), bytes_(bytes) {}

SharedFrameSlot::FrameView::FrameView(FrameView&& other) noexcept
    : semaphore_(std::exchange(other.semaphore_, SEM_FAILED)),
      sequence_(other.sequence_),
      bytes_(other.bytes_) {
    other.bytes_ = {};
}

SharedFrameSlot::FrameView& SharedFrameSlot::FrameView::operator=(
    FrameView&& other) noexcept {
    if (this != &other) {
        release();
        semaphore_ = std::exchange(other.semaphore_, SEM_FAILED);
        sequence_ = other.sequence_;
        bytes_ = other.bytes_;
        other.bytes_ = {};
    }
    return *this;
}

SharedFrameSlot::FrameView::~FrameView() {
    release();
}

void SharedFrameSlot::FrameView::release() noexcept {
    if (semaphore_ != SEM_FAILED) {
        (void)::sem_post(semaphore_);
        semaphore_ = SEM_FAILED;
        bytes_ = {};
    }
}

SharedFrameSlot::SharedFrameSlot(
    std::string name,
    std::size_t capacity,
    Mode mode,
    bool unlink_on_destroy)
    : name_(std::move(name)),
      semaphore_name_(name_ + "_lock"),
      capacity_(capacity),
      mapping_size_(sizeof(FrameHeader) + capacity),
      unlink_on_destroy_(unlink_on_destroy) {
    if (name_.empty() || name_.front() != '/' || capacity_ == 0) {
        throw std::invalid_argument(
            "shared-memory name must start with '/' and capacity must be positive");
    }

    const int flags =
        mode == Mode::Create ? O_CREAT | O_EXCL | O_RDWR : O_RDWR;
    descriptor_ = ::shm_open(name_.c_str(), flags, 0600);
    if (descriptor_ < 0) {
        throw_system_error("shm_open");
    }

    if (mode == Mode::Create &&
        ::ftruncate(descriptor_, static_cast<off_t>(mapping_size_)) != 0) {
        const int saved_errno = errno;
        ::close(descriptor_);
        descriptor_ = -1;
        ::shm_unlink(name_.c_str());
        errno = saved_errno;
        throw_system_error("ftruncate");
    }

    struct stat status {};
    if (::fstat(descriptor_, &status) != 0 ||
        status.st_size < static_cast<off_t>(sizeof(FrameHeader))) {
        const int saved_errno = errno;
        ::close(descriptor_);
        descriptor_ = -1;
        errno = saved_errno;
        throw_system_error("fstat");
    }
    mapping_size_ = static_cast<std::size_t>(status.st_size);

    mapping_ = ::mmap(
        nullptr,
        mapping_size_,
        PROT_READ | PROT_WRITE,
        MAP_SHARED,
        descriptor_,
        0);
    if (mapping_ == MAP_FAILED) {
        mapping_ = nullptr;
        const int saved_errno = errno;
        ::close(descriptor_);
        descriptor_ = -1;
        errno = saved_errno;
        throw_system_error("mmap");
    }

    const int semaphore_flags = mode == Mode::Create ? O_CREAT | O_EXCL : 0;
    semaphore_ = ::sem_open(
        semaphore_name_.c_str(), semaphore_flags, 0600, 1);
    if (semaphore_ == SEM_FAILED) {
        const int saved_errno = errno;
        ::munmap(mapping_, mapping_size_);
        ::close(descriptor_);
        mapping_ = nullptr;
        descriptor_ = -1;
        if (mode == Mode::Create) {
            ::shm_unlink(name_.c_str());
        }
        errno = saved_errno;
        throw_system_error("sem_open");
    }

    auto* header = static_cast<FrameHeader*>(mapping_);
    if (mode == Mode::Create) {
        std::memset(mapping_, 0, mapping_size_);
        header->magic = kMagic;
        header->capacity = capacity_;
    } else {
        if (header->magic != kMagic ||
            header->capacity + sizeof(FrameHeader) > mapping_size_) {
            ::munmap(mapping_, mapping_size_);
            ::close(descriptor_);
            ::sem_close(semaphore_);
            mapping_ = nullptr;
            descriptor_ = -1;
            semaphore_ = SEM_FAILED;
            throw std::runtime_error("invalid shared frame slot header");
        }
        capacity_ = static_cast<std::size_t>(header->capacity);
    }
}

SharedFrameSlot::~SharedFrameSlot() {
    if (mapping_ != nullptr) {
        ::munmap(mapping_, mapping_size_);
    }
    if (descriptor_ >= 0) {
        ::close(descriptor_);
    }
    if (semaphore_ != SEM_FAILED) {
        ::sem_close(semaphore_);
    }
    if (unlink_on_destroy_) {
        ::shm_unlink(name_.c_str());
        ::sem_unlink(semaphore_name_.c_str());
    }
}

std::uint64_t SharedFrameSlot::publish(
    ByteView payload) {
    if (payload.size() > capacity_) {
        throw std::length_error("shared frame payload exceeds slot capacity");
    }
    lock_semaphore(semaphore_);

    auto* header = static_cast<FrameHeader*>(mapping_);
    auto* destination =
        reinterpret_cast<std::byte*>(mapping_) + sizeof(FrameHeader);
    std::memcpy(destination, payload.data(), payload.size());
    header->payload_size = payload.size();
    header->checksum = checksum(payload);
    ++header->sequence;
    const std::uint64_t sequence = header->sequence;
    (void)::sem_post(semaphore_);
    return sequence;
}

SharedFrameSlot::FrameView SharedFrameSlot::view_latest() const {
    lock_semaphore(semaphore_);

    const auto* header = static_cast<const FrameHeader*>(mapping_);
    if (header->magic != kMagic || header->payload_size > capacity_) {
        (void)::sem_post(semaphore_);
        throw std::runtime_error("corrupt shared frame slot");
    }
    const auto* payload =
        reinterpret_cast<const std::byte*>(mapping_) + sizeof(FrameHeader);
    const ByteView bytes(
        payload, static_cast<std::size_t>(header->payload_size));
    if (checksum(bytes) != header->checksum) {
        (void)::sem_post(semaphore_);
        throw std::runtime_error("shared frame checksum mismatch");
    }
    return FrameView(semaphore_, header->sequence, bytes);
}

}  // namespace swarm_adapter::fusion
