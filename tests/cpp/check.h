#ifndef SWARM_ADAPTER_TESTS_CHECK_H
#define SWARM_ADAPTER_TESTS_CHECK_H

#include <cstdlib>
#include <iostream>
#include <string>

inline void expect(bool condition, const std::string& message) {
    if (!condition) {
        std::cerr << "FAILED: " << message << '\n';
        std::exit(1);
    }
}

#endif
