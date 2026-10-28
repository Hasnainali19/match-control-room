import math
from match_insights.agents.stats import StatsAgent, distance, pass_difficulty, speed_kmh
from match_insights.generator import generate
from match_insights.state import MatchState


def test_distance_and_speed():
    assert distance(0, 0, 3, 4) == 5
    assert math.isclose(speed_kmh(10, 1), 36.0)
    assert speed_kmh(10, 0) == 0


def test_pass_difficulty_monotonic_and_bounded():
    assert pass_difficulty(40, True, 20) > pass_difficulty(10, False, 0)
    assert 0 <= pass_difficulty(500, True, 500) <= 1


def test_pass_stats_and_accuracy():
    s, a = MatchState(), StatsAgent()
    base = dict(type="pass", team="HAR", player="HAR-2", x=10, y=34, end_x=50, end_y=34, duration=2.0)
    r1 = a.run({**base, "id": 1, "t": 1, "outcome": "complete"}, s)
    r2 = a.run({**base, "id": 2, "t": 2, "outcome": "incomplete"}, s)
    assert r1["distance_m"] == 40 and r1["ball_speed_kmh"] == 72.0
    assert r1["progressive_m"] == 40 and "long_pass" in r1["tags"]
    assert r2["team_accuracy"] == 0.5 and s.pass_acc("HAR") == 50


def test_sprint_tag_and_rocket_shot():
    s, a = MatchState(), StatsAgent()
    r = a.run(dict(id=1, t=1, type="run", team="MIL", player="MIL-3", x=50, y=30, end_x=30, end_y=30, duration=2.0), s)
    assert r["player_speed_kmh"] == 36.0 and "sprint" in r["tags"] and s.player["MIL-3"]["top_kmh"] == 36.0
    r = a.run(dict(id=2, t=2, type="shot", team="MIL", player="MIL-9", x=10, y=34, end_x=0, end_y=34,
                   speed_kmh=110, xg=0.3, outcome="goal"), s)
    assert {"goal", "rocket"} <= set(r["tags"]) and s.shots["MIL"]["xg"] == 0.3


def test_generator_is_deterministic_and_realistic():
    a, b = generate(7), generate(7)
    assert a == b
    assert 5400 <= a[-1]["t"] < 5410 and 1200 < len(a) < 3000
    assert all(0 <= e["x"] <= 105 and 0 <= e["y"] <= 68 for e in a if "x" in e)
    passes = [e for e in a if e["type"] == "pass"]
    acc = sum(e["outcome"] == "complete" for e in passes) / len(passes)
    assert 0.65 < acc < 0.9
    ev, truth = generate(7, with_truth=True)
    assert truth["fatigue_victim"].split("-")[1] in ("2", "3") and any(r["cause"] == "fatigue" for r in truth["regimes"])
