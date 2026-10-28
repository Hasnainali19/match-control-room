from match_insights.agents.referee import RefereeAgent

FACTS = {"possession.HAR": 54, "xg.HAR": 1.23, "shots.MIL": 7, "chart.HAR.tilt": 61.5}


def test_verified_claim():
    r = RefereeAgent().check({"text": "Rovers have 54% of the ball.", "claims": [{"key": "possession.HAR", "value": 54, "shown": "54"}]}, FACTS)
    assert r["verdict"] == "verified" and r["text"] == "Rovers have 54% of the ball."


def test_within_tolerance_is_verified():
    r = RefereeAgent().check({"text": "About 55%.", "claims": [{"key": "possession.HAR", "value": 55, "shown": "55"}]}, FACTS)
    assert r["verdict"] == "verified"


def test_wrong_number_is_corrected_in_text():
    r = RefereeAgent().check({"text": "Rovers have 70% of the ball!", "claims": [{"key": "possession.HAR", "value": 70, "shown": "70"}]}, FACTS)
    assert r["verdict"] == "corrected"
    assert r["text"] == "Rovers have 54% of the ball!" and r["original_text"] == "Rovers have 70% of the ball!"
    assert r["checks"][0]["was"] == 70 and r["checks"][0]["true"] == 54


def test_counts_are_exact():
    r = RefereeAgent().check({"text": "8 shots.", "claims": [{"key": "shots.MIL", "value": 8, "shown": "8"}]}, FACTS)
    assert r["verdict"] == "corrected" and r["text"] == "7 shots."


def test_unknown_fact_is_rejected():
    r = RefereeAgent().check({"text": "They ran 120 km.", "claims": [{"key": "distance.team", "value": 120, "shown": "120"}]}, FACTS)
    assert r["verdict"] == "rejected"


def test_unbacked_number_is_flagged():
    r = RefereeAgent().check({"text": "xG 1.23 and 9 corners.", "claims": [{"key": "xg.HAR", "value": 1.23, "shown": "1.23"}]}, FACTS)
    assert r["verdict"] == "flagged" and r["unbacked_numbers"] == ["9"]


def test_xg_tolerance():
    ok = RefereeAgent().check({"text": "1.2 xG", "claims": [{"key": "xg.HAR", "value": 1.2, "shown": "1.2"}]}, FACTS)
    bad = RefereeAgent().check({"text": "2.1 xG", "claims": [{"key": "xg.HAR", "value": 2.1, "shown": "2.1"}]}, FACTS)
    assert ok["verdict"] == "verified" and bad["verdict"] == "corrected" and bad["text"] == "1.23 xG"
