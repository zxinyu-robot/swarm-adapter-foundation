from pathlib import Path

from swarm_adapter.features import (
    FEATURE_DIM,
    CommAction,
    LinkFeatures,
    Outcome,
    make_features,
    outcome_utility,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "feature_golden.txt"


def _cases():
    for line in FIXTURE.read_text().splitlines():
        if line and not line.startswith("#"):
            kind, *values = line.split()
            yield kind, values


def test_features_match_cpp_golden():
    count = 0
    for kind, v in _cases():
        if kind != "phi":
            continue
        link = LinkFeatures(*(float(x) for x in v[:4]))
        action = CommAction(float(v[4]), int(v[5]), v[6] == "1")
        expected = [float(x) for x in v[7:]]
        assert len(expected) == FEATURE_DIM
        assert make_features(link, action) == expected
        count += 1
    assert count > 0


def test_utility_matches_cpp_golden():
    count = 0
    for kind, v in _cases():
        if kind != "utility":
            continue
        outcome = Outcome(float(v[0]), float(v[1]), float(v[2]))
        assert abs(outcome_utility(outcome) - float(v[3])) < 1e-12
        count += 1
    assert count > 0


def test_age_ratio_is_clipped():
    link = LinkFeatures(0.0, 0.0, 0.0, 100.0)
    assert make_features(link, CommAction(1.0, 0, False))[4] == 4.0
