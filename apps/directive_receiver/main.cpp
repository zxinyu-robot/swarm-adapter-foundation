// 机器人端下行指令参考接收器：TCP 收一行 TaskDirective（JSONL），
// 经 DirectiveGate 准入后回一行 ExecutionReport。不接执行后端，
// 因此 executed 恒为 false；reason == Ok 表示准入通过、可交给 RobotBackend。
#include "swarm_adapter/directive/directive_codec.h"
#include "swarm_adapter/directive/directive_gate.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

using namespace swarm_adapter;

namespace {

std::int64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

bool read_line(int fd, std::string& line) {
    constexpr std::size_t kMaxLine = 1 << 20;
    char buf[4096];
    while (line.size() < kMaxLine) {
        const ssize_t n = recv(fd, buf, sizeof(buf), 0);
        if (n <= 0) {
            return !line.empty();
        }
        line.append(buf, static_cast<std::size_t>(n));
        const auto nl = line.find('\n');
        if (nl != std::string::npos) {
            line.resize(nl);
            return true;
        }
    }
    return false;
}

int usage() {
    std::fprintf(stderr,
                 "usage: swarm_directive_receiver --port P --robot-id N --session-id N\n"
                 "  --map-version N --lease-epoch N [--safety-hold 0|1] [--max-connections N]\n");
    return 64;
}

}  // namespace

int main(int argc, char** argv) {
    int port = 9879;
    long max_connections = 0;
    RobotStatus status;
    status.lease_epoch = 1;
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::string key = argv[i];
        const unsigned long long v = std::strtoull(argv[i + 1], nullptr, 10);
        if (key == "--port") {
            port = static_cast<int>(v);
        } else if (key == "--robot-id") {
            status.robot_id = static_cast<std::uint32_t>(v);
        } else if (key == "--session-id") {
            status.session_id = static_cast<std::uint32_t>(v);
        } else if (key == "--map-version") {
            status.map_version = v;
        } else if (key == "--lease-epoch") {
            status.lease_epoch = v;
        } else if (key == "--safety-hold") {
            status.safety_hold = v != 0;
        } else if (key == "--max-connections") {
            max_connections = static_cast<long>(v);
        } else {
            return usage();
        }
    }

    const int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) {
        std::perror("socket");
        return 2;
    }
    const int yes = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(static_cast<std::uint16_t>(port));
    if (bind(server, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0 ||
        listen(server, 8) != 0) {
        std::perror("bind/listen");
        return 2;
    }
    std::printf("directive receiver: port=%d robot=%u session=%u map_version=%llu lease=%llu\n",
                port, status.robot_id, status.session_id,
                static_cast<unsigned long long>(status.map_version),
                static_cast<unsigned long long>(status.lease_epoch));
    std::fflush(stdout);

    directive::DirectiveGate gate;
    for (long served = 0; max_connections == 0 || served < max_connections; ++served) {
        const int client = accept(server, nullptr, nullptr);
        if (client < 0) {
            continue;
        }
        std::string line;
        ExecutionReport report;
        report.robot_id = status.robot_id;
        TaskDirective d;
        if (!read_line(client, line)) {
            report.reason = ReasonCode::InvalidInput;
        } else {
            report.reason = directive::decode_task_directive(line, d);
            if (report.reason == ReasonCode::Ok) {
                report.directive_id = d.directive_id;
                report.reason = gate.admit(d, status, now_ns());
            }
        }
        report.executed = false;
        report.reported_at_ns = now_ns();
        const std::string reply = directive::encode_execution_report(report) + "\n";
        send(client, reply.data(), reply.size(), 0);
        close(client);
        std::printf("directive %llu target=%s -> %s\n",
                    static_cast<unsigned long long>(report.directive_id), d.target_node_id.c_str(),
                    reason_name(report.reason));
        std::fflush(stdout);
    }
    close(server);
    return 0;
}
