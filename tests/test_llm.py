"""LLM gateway tests with mocked HTTP (no network, no tokens)."""
import json
import httpx
import pytest
from match_insights.llm import LLMClient, LLMUnavailable
from match_insights.agents.pundits import PunditAgent
from match_insights.agents.referee import RefereeAgent
from match_insights.state import MatchState

GH = {"GITHUB_MODELS_TOKEN": "test-token", "GITHUB_MODELS_RPM": "100000"}


def completion(text):
    return {"id": "x", "object": "chat.completion", "created": 0, "model": "openai/gpt-4o-mini",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def client(handler, env=GH, **kw):
    return LLMClient(env=env, http_client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, **kw)


def test_provider_precedence():
    assert LLMClient(env={}).provider == "offline"
    assert LLMClient(env={"GITHUB_TOKEN": "t"}).provider == "github-models"
    c = LLMClient(env={"GITHUB_TOKEN": "t", "AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.com/",
                       "AZURE_OPENAI_DEPLOYMENT": "d", "AZURE_OPENAI_API_KEY": "k"})
    assert c.provider == "azure-openai" and c.model == "d"
    with pytest.raises(LLMUnavailable):
        LLMClient(env={}).complete("s", "u")


def test_github_models_request_shape_and_cache():
    seen = []

    def h(req):
        seen.append(req)
        return httpx.Response(200, json=completion("Hola"))
    c = client(h)
    assert c.complete("sys", "hi") == "Hola" and c.complete("sys", "hi") == "Hola"
    assert len(seen) == 1 and c.cache_hits == 1
    req = seen[0]
    assert str(req.url) == "https://models.github.ai/inference/chat/completions"
    assert req.headers["authorization"] == "Bearer test-token"
    assert json.loads(req.content)["model"] == "openai/gpt-4o-mini"
    assert c.status()["provider"] == "github-models"


def test_429_short_backoff_then_success():
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(429, headers={"retry-after": "1"}, json={"error": "rate"}) if n["i"] == 1 else httpx.Response(200, json=completion("ok"))
    c = client(h)
    assert c.complete("s", "u") == "ok" and n["i"] == 2 and c.rate_limited == 1


def test_429_long_window_falls_back_and_skips_calls():
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(429, headers={"retry-after": "60"}, json={"error": "rate"})
    c = client(h)
    with pytest.raises(LLMUnavailable):
        c.complete("s", "u1")
    with pytest.raises(LLMUnavailable):
        c.complete("s", "u2")  # inside the cooldown window: no HTTP call made
    assert n["i"] == 1 and c.status()["rate_limited_for_s"] > 50


def test_request_budget_spacing():
    c = client(lambda r: httpx.Response(200, json=completion("a")), env={"GITHUB_TOKEN": "t", "GITHUB_MODELS_RPM": "1"})
    c.complete("s", "u1")
    with pytest.raises(LLMUnavailable, match="budget"):
        c.complete("s", "u2")


def test_non_json_stub_endpoint_is_unavailable():
    c = client(lambda r: httpx.Response(200, text="OK", headers={"content-type": "text/plain"}))
    with pytest.raises(LLMUnavailable):
        c.complete("s", "u")


def test_llm_pundit_take_is_still_fact_checked():
    take = {"text": "Rovers have 70% of the ball!", "claims": [{"key": "possession.HAR", "value": 70, "shown": "70"}]}
    c = client(lambda r: httpx.Response(200, json=completion(json.dumps(take))))
    st = MatchState()
    st.meta = {"clubs": {"HAR": "Harrowgate Rovers", "MIL": "Millbrook Athletic"}, "shorts": {"HAR": "ROV", "MIL": "MIL"}}
    st.possession_time.update({"HAR": 54, "MIL": 46})
    trig = {"id": 1, "kind": "signal", "t": 600, "team": "HAR", "summary": "swing"}
    out = PunditAgent("expro").run(trig, st.facts(), st, c, None, "ja")
    assert out["source"] == "llm"
    checked = RefereeAgent().check(out, st.facts())
    assert checked["verdict"] == "corrected" and "54%" in checked["text"]


def test_llm_failure_falls_back_to_template():
    c = client(lambda r: httpx.Response(500, json={"error": "boom"}))
    st = MatchState()
    st.meta = {"clubs": {"HAR": "Harrowgate Rovers", "MIL": "Millbrook Athletic"}, "shorts": {}}
    out = PunditAgent("analyst").run({"id": 1, "kind": "goal", "t": 1, "team": "HAR", "summary": "g"}, st.facts(), st, c)
    assert out["source"] == "template"
