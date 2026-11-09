// 跨机链路探测：一端 tx、一端 rx，网络由 CYCLONEDDS_URI 配置。
// 用法见 adapters/dds/README.md。
#include "swarm_adapter/dds/link_probe.h"

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

using namespace swarm_adapter;
using namespace swarm_adapter::dds;

namespace {

bool parse_class(const char* text, MessageClass& out) {
    for (int i = 0; i <= static_cast<int>(MessageClass::Directive); ++i) {
        const auto c = static_cast<MessageClass>(i);
        const char* name = message_class_name(c);
        std::size_t k = 0;
        while (name[k] != '\0' && text[k] != '\0' &&
               std::tolower(static_cast<unsigned char>(name[k])) ==
                   std::tolower(static_cast<unsigned char>(text[k]))) {
            ++k;
        }
        if (name[k] == '\0' && text[k] == '\0') {
            out = c;
            return true;
        }
    }
    return false;
}

int usage() {
    std::fprintf(stderr,
                 "usage: swarm_link_probe tx|rx [--robot N] [--class keyframe] [--rate HZ]\n"
                 "  [--payload BYTES] [--deadline-ms MS] [--ttl-ms MS] [--window-s S]\n"
                 "  [--windows N] [--seed N] [--records DIR] [--clock-max-dev-ms MS]\n"
                 "  [--match-timeout-s S] [--idle-exit-s S] [--duration-s S]\n");
    return 64;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        return usage();
    }
    const std::string role = argv[1];
    if (role != "tx" && role != "rx") {
        return usage();
    }
    ProbeConfig config;
    for (int i = 2; i + 1 < argc; i += 2) {
        const std::string key = argv[i];
        const char* value = argv[i + 1];
        if (key == "--robot") {
            config.robot_id = static_cast<std::uint32_t>(std::strtoul(value, nullptr, 10));
        } else if (key == "--class") {
            if (!parse_class(value, config.message_class)) {
                return usage();
            }
        } else if (key == "--rate") {
            config.base_rate_hz = std::atof(value);
        } else if (key == "--payload") {
            config.payload_bytes = std::strtoul(value, nullptr, 10);
        } else if (key == "--deadline-ms") {
            config.deadline_ms = std::atoll(value);
        } else if (key == "--ttl-ms") {
            config.ttl_ms = std::atoll(value);
        } else if (key == "--window-s") {
            config.window_s = std::atof(value);
        } else if (key == "--windows") {
            config.windows = std::strtoul(value, nullptr, 10);
        } else if (key == "--seed") {
            config.seed = std::strtoull(value, nullptr, 10);
        } else if (key == "--records") {
            config.records_dir = value;
        } else if (key == "--clock-max-dev-ms") {
            config.clock_max_deviation_ns = std::atoll(value) * 1'000'000;
        } else if (key == "--match-timeout-s") {
            config.match_timeout_s = std::atof(value);
        } else if (key == "--idle-exit-s") {
            config.rx_idle_exit_s = std::atof(value);
        } else if (key == "--duration-s") {
            config.rx_max_duration_s = std::atof(value);
        } else {
            return usage();
        }
    }
    DdsParticipant participant;
    if (!participant.ok()) {
        std::fprintf(stderr, "failed to create DDS participant\n");
        return 2;
    }
    if (role == "rx") {
        return run_probe_rx(participant, config, stdout);
    }
    ProbeSummary summary;
    const int rc = run_probe_tx(participant, config, summary, stdout);
    std::printf("tx: outcomes=%zu trainable=%zu mean_delivered=%.3f mean_on_time=%.3f records=%s\n",
                summary.outcomes, summary.trainable, summary.mean_delivered, summary.mean_on_time,
                summary.segment_path.empty() ? "-" : summary.segment_path.c_str());
    return rc;
}
