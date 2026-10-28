from match_insights.agents.debugger import DebuggerAgent
from match_insights.faults import FaultInjector
from match_insights.generator import generate
from match_insights.orchestrator import Orchestrator
from match_insights.state import MatchState

EV = generate(11)


def span(agent, status, ms=1.0, note="x"):
    return {"event_id": 1, "t": 100, "agent": agent, "status": status, "attempts": 3, "ms": ms, "handoff": None, "note": note}


def test_clean_match_is_quiet():
    o = Orchestrator()
    msgs = [m for e in EV for m in o.process(e)]
    s = o.debugger.summary()
    assert s["by_severity"]["error"] == 0 and s["by_severity"]["critical"] == 0 and s["internal_errors"] == 0
    assert not [m for m in msgs if m["type"] == "debug" and m["data"]["severity"] in ("error", "critical")]


def test_chaos_is_detected_and_classified():
    o = Orchestrator(faults=FaultInjector(0.3, seed=2))
    msgs = [m for e in EV for m in o.process(e)]
    s = o.debugger.summary()
    cats = {f["key"].split(":")[0] for f in s["findings"]}
    assert {"retry", "fallback", "deferred"} <= cats and s["health"] in ("degraded", "critical")
    dbg = [m["data"] for m in msgs if m["type"] == "debug"]
    assert dbg and all(d["cause"] and d["fix"] and "minute" in d and d["agent"] for d in dbg)
    # de-duplication: far fewer published findings than faults
    assert len(dbg) < o.faults.injected / 5


def test_bad_events_and_out_of_range_stats():
    d, st = DebuggerAgent(), MatchState()
    f = d.run({"id": 5, "t": 400, "type": "carry"}, [span("ingest", "rejected")], {"player_speed_kmh": 71.0}, st)
    keys = {x["key"] for x in f}
    assert "rejected:ingest" in keys and "range:player_speed_kmh" in keys
    assert next(x for x in f if x["key"] == "range:player_speed_kmh")["severity"] == "error"


def test_stall_latency_and_dedupe():
    d, st = DebuggerAgent(latency_ms=100), MatchState()
    d.run({"id": 1, "t": 10, "type": "pass"}, [], None, st)
    f = d.run({"id": 2, "t": 400, "type": "pass"}, [span("narrator", "ok", ms=900)], None, st)
    assert {"stall", "latency:narrator"} <= {x["key"] for x in f}
    again = d.run({"id": 3, "t": 410, "type": "pass"}, [span("narrator", "ok", ms=900)], None, st)
    assert not again and d.findings["latency:narrator"]["count"] == 2  # counted, not re-published


def test_llm_health_detection():
    class FakeLLM:
        def __init__(self): self.s = {"online": True, "provider": "github-models", "failures": 0, "calls": 1, "rate_limited": 0, "circuit_open": False}
        def status(self): return dict(self.s)
    llm, d, st = FakeLLM(), DebuggerAgent(), MatchState()
    d.run({"id": 1, "t": 1, "type": "pass"}, [], None, st, llm)
    llm.s.update(failures=3, rate_limited=1, circuit_open=True)
    keys = {x["key"] for x in d.run({"id": 2, "t": 2, "type": "pass"}, [], None, st, llm)}
    assert {"llm_fail", "llm_rate", "llm_circuit"} <= keys


def test_debugger_bug_never_breaks_pipeline(monkeypatch):
    o = Orchestrator()
    monkeypatch.setattr(o.debugger, "run", lambda *a, **k: 1 / 0)
    out = [m for e in EV[:200] for m in o.process(e)]
    assert any(m["type"] == "tick" for m in out) and o.debugger.internal_errors == 199 + 1


def test_internal_check_errors_are_contained():
    d = DebuggerAgent()
    out = d.run({"id": 1, "t": 1, "type": "pass"}, [span("x", "ok")], {"xg": "bad"}, None)  # state=None breaks a check
    assert isinstance(out, list) and d.internal_errors >= 1
