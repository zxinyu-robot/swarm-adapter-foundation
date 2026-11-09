#include "swarm_adapter/strategy/policy_model.h"

#include <cmath>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>

namespace swarm_adapter::strategy {
namespace {

constexpr const char* kHeader = "swarm_adapter.policy v1";

}  // namespace

bool valid(const PolicyWeights& policy) noexcept {
    if (policy.policy_version == 0) {
        return false;
    }
    for (double w : policy.weights) {
        if (!std::isfinite(w)) {
            return false;
        }
    }
    return true;
}

double predict_utility(
    const PolicyWeights& policy,
    const LinkFeatures& link,
    const CommAction& action) {
    const FeatureVector phi = make_features(link, action);
    double sum = 0.0;
    for (std::size_t i = 0; i < kFeatureDim; ++i) {
        sum += policy.weights[i] * phi[i];
    }
    return sum;
}

ReasonCode load_policy_file(const std::string& path, PolicyWeights& out) {
    std::ifstream in(path);
    if (!in) {
        return ReasonCode::IoError;
    }
    std::string header;
    if (!std::getline(in, header) || header != kHeader) {
        return ReasonCode::InvalidInput;
    }
    PolicyWeights parsed;
    bool has_version = false;
    bool has_round = false;
    bool has_weights = false;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }
        std::istringstream fields(line);
        std::string key;
        fields >> key;
        if (key == "policy_version") {
            has_version = static_cast<bool>(fields >> parsed.policy_version);
        } else if (key == "round_id") {
            has_round = static_cast<bool>(fields >> parsed.round_id);
        } else if (key == "feature_dim") {
            std::size_t dim = 0;
            if (!(fields >> dim) || dim != kFeatureDim) {
                return ReasonCode::InvalidInput;
            }
        } else if (key == "weights") {
            for (double& w : parsed.weights) {
                if (!(fields >> w)) {
                    return ReasonCode::InvalidInput;
                }
            }
            double extra = 0.0;
            if (fields >> extra) {
                return ReasonCode::InvalidInput;
            }
            has_weights = true;
        } else {
            return ReasonCode::InvalidInput;
        }
    }
    if (!has_version || !has_round || !has_weights || !valid(parsed)) {
        return ReasonCode::InvalidInput;
    }
    out = parsed;
    return ReasonCode::Ok;
}

ReasonCode save_policy_file(const std::string& path, const PolicyWeights& policy) {
    if (!valid(policy)) {
        return ReasonCode::InvalidInput;
    }
    const std::string temporary = path + ".tmp";
    {
        std::ofstream out(temporary, std::ios::trunc);
        if (!out) {
            return ReasonCode::IoError;
        }
        out << kHeader << '\n'
            << "policy_version " << policy.policy_version << '\n'
            << "round_id " << policy.round_id << '\n'
            << "feature_dim " << kFeatureDim << '\n'
            << "weights" << std::setprecision(std::numeric_limits<double>::max_digits10);
        for (double w : policy.weights) {
            out << ' ' << w;
        }
        out << '\n';
        if (!out) {
            return ReasonCode::IoError;
        }
    }
    if (std::rename(temporary.c_str(), path.c_str()) != 0) {
        return ReasonCode::IoError;
    }
    return ReasonCode::Ok;
}

}  // namespace swarm_adapter::strategy
