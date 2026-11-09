#include "swarm_adapter/directive/directive_codec.h"

#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <map>
#include <string>

namespace swarm_adapter::directive {
namespace {

/// 只为扁平指令对象服务的最小 JSON 扫描器：顶层值保留原文，嵌套值整体跳过。
class Scanner {
public:
    explicit Scanner(std::string_view text) : text_(text) {}

    bool object(std::map<std::string, std::string>& strings,
                std::map<std::string, std::string>& scalars) {
        skip_ws();
        if (!consume('{')) {
            return false;
        }
        skip_ws();
        if (consume('}')) {
            return trailing_ok();
        }
        for (;;) {
            std::string key;
            skip_ws();
            if (!string(key)) {
                return false;
            }
            skip_ws();
            if (!consume(':')) {
                return false;
            }
            skip_ws();
            if (peek() == '"') {
                std::string value;
                if (!string(value)) {
                    return false;
                }
                strings[key] = value;
            } else if (peek() == '{' || peek() == '[') {
                if (!skip_nested()) {
                    return false;
                }
            } else {
                std::string token;
                while (pos_ < text_.size() && text_[pos_] != ',' && text_[pos_] != '}' &&
                       !is_ws(text_[pos_])) {
                    token.push_back(text_[pos_++]);
                }
                if (token.empty()) {
                    return false;
                }
                scalars[key] = token;
            }
            skip_ws();
            if (consume(',')) {
                continue;
            }
            if (consume('}')) {
                return trailing_ok();
            }
            return false;
        }
    }

private:
    static bool is_ws(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }
    char peek() const { return pos_ < text_.size() ? text_[pos_] : '\0'; }
    bool consume(char c) {
        if (peek() == c) {
            ++pos_;
            return true;
        }
        return false;
    }
    void skip_ws() {
        while (pos_ < text_.size() && is_ws(text_[pos_])) {
            ++pos_;
        }
    }
    bool trailing_ok() {
        skip_ws();
        return pos_ == text_.size();
    }

    bool string(std::string& out) {
        if (!consume('"')) {
            return false;
        }
        while (pos_ < text_.size()) {
            const char c = text_[pos_++];
            if (c == '"') {
                return true;
            }
            if (c != '\\') {
                out.push_back(c);
                continue;
            }
            if (pos_ >= text_.size()) {
                return false;
            }
            const char e = text_[pos_++];
            switch (e) {
            case '"': out.push_back('"'); break;
            case '\\': out.push_back('\\'); break;
            case '/': out.push_back('/'); break;
            case 'b': out.push_back('\b'); break;
            case 'f': out.push_back('\f'); break;
            case 'n': out.push_back('\n'); break;
            case 'r': out.push_back('\r'); break;
            case 't': out.push_back('\t'); break;
            case 'u': {
                if (pos_ + 4 > text_.size()) {
                    return false;
                }
                const std::string hex(text_.substr(pos_, 4));
                pos_ += 4;
                char* end = nullptr;
                const long code = std::strtol(hex.c_str(), &end, 16);
                if (end != hex.c_str() + 4) {
                    return false;
                }
                out.push_back(code < 0x80 ? static_cast<char>(code) : '?');
                break;
            }
            default: return false;
            }
        }
        return false;
    }

    bool skip_nested() {
        int depth = 0;
        while (pos_ < text_.size()) {
            const char c = text_[pos_];
            if (c == '"') {
                std::string ignored;
                if (!string(ignored)) {
                    return false;
                }
                continue;
            }
            ++pos_;
            if (c == '{' || c == '[') {
                ++depth;
            } else if (c == '}' || c == ']') {
                if (--depth == 0) {
                    return true;
                }
            }
        }
        return false;
    }

    std::string_view text_;
    std::size_t pos_{};
};

bool parse_u64(const std::map<std::string, std::string>& scalars, const char* key,
               std::uint64_t max, std::uint64_t& out) {
    const auto it = scalars.find(key);
    if (it == scalars.end() || it->second.empty() || it->second[0] == '-') {
        return false;
    }
    errno = 0;
    char* end = nullptr;
    const unsigned long long value = std::strtoull(it->second.c_str(), &end, 10);
    if (errno != 0 || *end != '\0' || value > max) {
        return false;
    }
    out = value;
    return true;
}

bool parse_i64(const std::map<std::string, std::string>& scalars, const char* key,
               std::int64_t& out) {
    const auto it = scalars.find(key);
    if (it == scalars.end() || it->second.empty()) {
        return false;
    }
    errno = 0;
    char* end = nullptr;
    const long long value = std::strtoll(it->second.c_str(), &end, 10);
    if (errno != 0 || *end != '\0') {
        return false;
    }
    out = value;
    return true;
}

bool parse_double(const std::map<std::string, std::string>& scalars, const char* key,
                  double& out) {
    const auto it = scalars.find(key);
    if (it == scalars.end() || it->second.empty()) {
        return false;
    }
    char* end = nullptr;
    const double value = std::strtod(it->second.c_str(), &end);
    if (*end != '\0' || !std::isfinite(value)) {
        return false;
    }
    out = value;
    return true;
}

std::string escape(const std::string& text) {
    std::string out;
    for (const char c : text) {
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (static_cast<unsigned char>(c) < 0x20) {
                char buf[8];
                std::snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned>(c));
                out += buf;
            } else {
                out.push_back(c);
            }
        }
    }
    return out;
}

}  // namespace

ReasonCode decode_task_directive(std::string_view line, TaskDirective& out) {
    std::map<std::string, std::string> strings;
    std::map<std::string, std::string> scalars;
    if (!Scanner(line).object(strings, scalars)) {
        return ReasonCode::InvalidInput;
    }
    const auto schema = strings.find("schema");
    const auto target = strings.find("target_node_id");
    if (schema == strings.end() || schema->second != kTaskDirectiveSchema ||
        target == strings.end()) {
        return ReasonCode::InvalidInput;
    }
    constexpr std::uint64_t kU32 = std::numeric_limits<std::uint32_t>::max();
    constexpr std::uint64_t kU64 = std::numeric_limits<std::uint64_t>::max();
    TaskDirective d;
    std::uint64_t robot_id = 0;
    std::uint64_t session_id = 0;
    if (!parse_u64(scalars, "directive_id", kU64, d.directive_id) ||
        !parse_u64(scalars, "robot_id", kU32, robot_id) ||
        !parse_u64(scalars, "session_id", kU32, session_id) ||
        !parse_u64(scalars, "map_version", kU64, d.map_version) ||
        !parse_u64(scalars, "lease_epoch", kU64, d.lease_epoch) ||
        !parse_i64(scalars, "issued_at_ns", d.issued_at_ns) ||
        !parse_i64(scalars, "ttl_ms", d.ttl_ms) ||
        !parse_double(scalars, "confidence", d.confidence)) {
        return ReasonCode::InvalidInput;
    }
    d.robot_id = static_cast<std::uint32_t>(robot_id);
    d.session_id = static_cast<std::uint32_t>(session_id);
    d.target_node_id = target->second;
    out = d;
    return ReasonCode::Ok;
}

std::string encode_task_directive(const TaskDirective& d) {
    char buf[512];
    std::snprintf(buf, sizeof(buf),
                  "{\"schema\":\"%s\",\"directive_id\":%llu,\"robot_id\":%u,\"session_id\":%u,"
                  "\"map_version\":%llu,\"lease_epoch\":%llu,\"issued_at_ns\":%lld,"
                  "\"ttl_ms\":%lld,\"confidence\":%.17g,\"target_node_id\":\"",
                  kTaskDirectiveSchema, static_cast<unsigned long long>(d.directive_id),
                  d.robot_id, d.session_id, static_cast<unsigned long long>(d.map_version),
                  static_cast<unsigned long long>(d.lease_epoch),
                  static_cast<long long>(d.issued_at_ns), static_cast<long long>(d.ttl_ms),
                  d.confidence);
    return std::string(buf) + escape(d.target_node_id) + "\"}";
}

std::string encode_execution_report(const ExecutionReport& r) {
    char buf[384];
    std::snprintf(buf, sizeof(buf),
                  "{\"schema\":\"%s\",\"directive_id\":%llu,\"robot_id\":%u,\"reason\":\"%s\","
                  "\"reason_code\":%u,\"executed\":%s,\"reported_at_ns\":%lld}",
                  kExecutionReportSchema, static_cast<unsigned long long>(r.directive_id),
                  r.robot_id, reason_name(r.reason), static_cast<unsigned>(r.reason),
                  r.executed ? "true" : "false", static_cast<long long>(r.reported_at_ns));
    return buf;
}

}  // namespace swarm_adapter::directive
