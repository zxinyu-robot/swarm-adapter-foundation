#ifndef SWARM_ADAPTER_FUSION_BYTE_VIEW_H
#define SWARM_ADAPTER_FUSION_BYTE_VIEW_H

#include <cstddef>
#include <string>

namespace swarm_adapter::fusion {

/// 只读字节视图（C++17 下替代 std::span<const std::byte>）。不拥有内存。
class ByteView {
public:
    constexpr ByteView() noexcept = default;
    constexpr ByteView(const std::byte* data, std::size_t size) noexcept
        : data_(data), size_(size) {}

    static ByteView of(const std::string& text) noexcept {
        return {reinterpret_cast<const std::byte*>(text.data()), text.size()};
    }

    [[nodiscard]] constexpr const std::byte* data() const noexcept { return data_; }
    [[nodiscard]] constexpr std::size_t size() const noexcept { return size_; }
    [[nodiscard]] constexpr bool empty() const noexcept { return size_ == 0; }
    [[nodiscard]] constexpr const std::byte* begin() const noexcept { return data_; }
    [[nodiscard]] constexpr const std::byte* end() const noexcept { return data_ + size_; }

private:
    const std::byte* data_{nullptr};
    std::size_t size_{0};
};

}  // namespace swarm_adapter::fusion

#endif
