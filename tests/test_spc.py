from match_insights.agents.control import ControlAgent
from match_insights.generator import generate
from match_insights.spc import baseline, check_rules, ewma_limits
from match_insights.state import MatchState
from match_insights.agents.ingest import IngestAgent


def rules(z, e=None):
    return {r for r, _ in check_rules(z, e)}


def test_we1_beyond_3_sigma():
    assert check_rules([0.1, -0.2, 3.4]) == [("WE1", 1)]
    assert ("WE1", -1) in check_rules([0, -3.5])


def test_we2_two_of_three_beyond_2_sigma():
    assert "WE2" in rules([2.3, 0.1, 2.5])
    assert "WE2" not in rules([2.3, 0.1, -2.5])  # different sides
    assert "WE2" not in rules([2.3, 2.5, 0.1])   # newest point must participate


def test_we3_four_of_five_beyond_1_sigma():
    assert "WE3" in rules([1.2, 1.5, 0.2, 1.1, 1.3])
    assert "WE3" not in rules([1.2, 1.5, 0.2, -1.1, 1.3])


def test_we4_eight_on_one_side_and_n3_trend():
    assert "WE4" in rules([0.2] * 8)
    assert "WE4" not in rules([0.2] * 7 + [-0.1])
    assert ("N3", 1) in check_rules([-1, -0.5, 0, 0.3, 0.6, 0.9])
    assert ("N3", -1) in check_rules([1, 0.5, 0, -0.3, -0.6, -0.9])


def test_in_control_process_is_quiet():
    assert check_rules([0.3, -0.5, 0.8, -0.2, 0.1, -0.9, 0.4], 0.2) == []


def test_ewma_rule_and_limits_widen_to_asymptote():
    assert ("EWMA", -1) in check_rules([0.1], -1.2)
    lo1, hi1 = ewma_limits(50, 10, 0.3, 1)
    lo9, hi9 = ewma_limits(50, 10, 0.3, 50)
    assert hi1 < hi9 and abs((hi9 - 50) - 2.7 * 10 * (0.3 / 1.7) ** 0.5) < 1e-6


def test_baseline_needs_min_points():
    assert baseline([1, 2, 3], min_n=5) is None
    mu, sd = baseline([1, 2, 3, 4, 5], min_n=5)
    assert mu == 3 and sd > 0


def test_control_agent_detects_injected_fatigue_regime():
    """End to end: the latent fatigue regime injected by the generator is flagged for the right team."""
    hits = 0
    for seed in range(1, 11):
        ev, truth = generate(seed, with_truth=True)
        fr = next(r for r in truth["regimes"] if r["cause"] == "fatigue")
        s, I, C = MatchState(), IngestAgent(), ControlAgent()
        for e in ev:
            I.run(e, s); C.run(e, s)
        hits += any(x["momentum_to"] == fr["team"] and fr["start"] <= x["t"] <= fr["end"] + 60 for x in s.signals)
        for t, charts in s.charts.items():
            for m, pts in charts.items():
                for p in pts:
                    if "ucl" in p and m != "momentum":
                        assert p["lcl"] <= p["cl"] <= p["ucl"]
    assert hits >= 8
