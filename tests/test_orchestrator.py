from collections import Counter
from match_insights.agents.personalizer import Profile
from match_insights.agents.producer import ProducerAgent
from match_insights.faults import FaultInjector
from match_insights.generator import generate
from match_insights.orchestrator import Orchestrator
from match_insights.state import MatchState

EVENTS = generate(11)


def run(orch, events=EVENTS):
    msgs = []
    for e in events:
        msgs += orch.process(e)
    return msgs


def test_full_pipeline_offline_produces_all_overlay_layers():
    orch = Orchestrator(Profile("analyst", "HAR", "HAR-3", "es"))
    msgs = run(orch)
    kinds = Counter(m["type"] for m in msgs)
    for k in ("meta", "tick", "chart", "signal", "alert", "whys", "panel", "lower_third", "trace", "focus"):
        assert kinds[k] > 0, k
    goals = sum(1 for e in EVENTS if e["type"] == "shot" and e["outcome"] == "goal")
    assert sum(orch.state.score.values()) == goals
    lt = next(m["data"] for m in msgs if m["type"] == "lower_third")
    assert lt["schema"] == "mcr.overlay/v2" and lt["lang"] == "es" and "display" in lt
    panel = next(m["data"] for m in msgs if m["type"] == "panel")
    assert len(panel["takes"]) == 4 and all(t["verdict"] in ("verified", "corrected") for t in panel["takes"])


def test_fact_checker_catches_simulated_pundit_hallucinations():
    orch = Orchestrator()
    run(orch)
    verdicts = Counter(t["verdict"] for t in orch.state.takes)
    assert verdicts["corrected"] > 0 and verdicts["flagged"] == 0 and verdicts["rejected"] == 0
    for t in orch.state.takes:  # every number on screen now matches the facts snapshot
        assert all(c["status"] in ("verified", "corrected") for c in t["checks"])


def test_recovery_under_heavy_fault_injection_preserves_correctness():
    clean, chaos = Orchestrator(), Orchestrator(faults=FaultInjector(0.35, seed=3))
    run(clean)
    msgs = run(chaos)
    statuses = Counter(s["status"] for m in msgs if m["type"] == "trace" for s in m["data"])
    assert chaos.faults.injected > 1000
    assert statuses["recovered"] > 0 and statuses["fallback"] > 0 and statuses["deferred"] > 0
    # deterministic state survives: score, possession and SPC signals are identical thanks to retry + deferral replay
    assert chaos.state.score == clean.state.score
    assert chaos.state.possession_pct() == clean.state.possession_pct()
    assert [s["t"] for s in chaos.state.signals] == [s["t"] for s in clean.state.signals]
    assert any(m["type"] == "lower_third" for m in msgs)


def test_ingest_rejects_bad_events_without_crashing():
    orch = Orchestrator()
    orch.process(EVENTS[0])
    for bad in ({"type": "bogus"}, {"id": 9, "t": 1, "type": "pass", "x": 500, "y": 3}, "not-a-dict"):
        trace = next(m for m in orch.process(bad) if m["type"] == "trace")
        assert trace["data"][0]["status"] == "rejected"
    assert len(orch.state.errors) == 3
    assert orch.process(EVENTS[1])  # pipeline continues


def test_out_of_order_event_rejected():
    orch = Orchestrator()
    for e in EVENTS[:20]:
        orch.process(e)
    assert next(m for m in orch.process(EVENTS[5]) if m["type"] == "trace")["data"][0]["status"] == "rejected"


def test_producer_rate_limits_and_preempts():
    p, st = ProducerAgent(gap_s=40), MatchState()
    c = lambda pr, t: {"kind": "narration", "t": t, "priority": pr, "text": "x"}  # noqa: E731
    assert p.run([c(0.5, 0)], 0, st)[0]["channel"] == "lower_third"
    assert p.run([c(0.5, 10)], 10, st) == []                       # slot busy -> queued
    assert p.run([c(1.0, 12)], 12, st)[0]["channel"] == "lower_third"  # goal pre-empts
    assert p.run([c(0.15, 13)], 13, st)[0]["channel"] == "ticker"


def test_producer_never_features_unverified_pundit():
    takes = [{"pundit": "expro", "verdict": "flagged"}, {"pundit": "analyst", "verdict": "corrected"}]
    assert ProducerAgent().pick_pundit(takes, preferred="expro") == "analyst"
    assert ProducerAgent().pick_pundit([{"pundit": "x", "verdict": "unchecked"}]) is None


def test_personalizer_focus_and_language():
    orch = Orchestrator(Profile("casual", "MIL", "MIL-9", "fr"))
    msgs = run(orch, EVENTS[:900])
    lts = [m["data"] for m in msgs if m["type"] in ("lower_third", "ticker")]
    assert any(l.get("highlight") in ("club", "focus") for l in lts)
    assert any(m["type"] == "focus" and m["data"]["player"] == "MIL-9" for m in msgs)
    alerts = [m["data"] for m in msgs if m["type"] == "alert"]
    assert alerts and all(a["title"].startswith("BASCULE") for a in alerts)
