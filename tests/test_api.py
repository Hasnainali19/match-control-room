from fastapi.testclient import TestClient
from match_insights.server import app

c = TestClient(app)


def test_health_ready_config():
    assert c.get("/api/health").json()["status"] == "ok"
    r = c.get("/api/ready").json()
    assert r["status"] == "ready" and r["mode"] == "offline-templates"
    cfg = c.get("/api/config").json()
    assert set(cfg["pundits"]) == {"tactician", "analyst", "expro", "superfan"} and "es" in cfg["languages"]


def test_vote():
    assert c.post("/api/vote", json={"pundit": "analyst"}).json()["analyst"] >= 1
    assert c.post("/api/vote", json={"pundit": "nobody"}).status_code == 400


def test_stream_emits_overlays():
    kinds = set()
    with c.stream("GET", "/api/stream?speed=100000&persona=analyst&lang=de") as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                kinds.add(line[7:])
    assert {"session", "meta", "tick", "chart", "signal", "panel", "whys", "lower_third", "trace", "end"} <= kinds


def test_demo_highlights():
    h = c.get("/api/highlights").json()
    assert h["windows"] and any(m["kind"] == "goal" for m in h["moments"])


def test_debug_endpoint_and_sse():
    kinds = set()
    with c.stream("GET", "/api/stream?speed=100000&fault_rate=0.3") as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                kinds.add(line[7:])
    assert "debug" in kinds
    d = c.get("/api/debug").json()
    assert d["session"] and d["findings"] and d["health"] in ("degraded", "critical", "warning")
    assert c.get("/api/debug?session=nope").status_code == 404
