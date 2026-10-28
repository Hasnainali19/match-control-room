"""FastAPI backend: per-viewer agent pipelines streamed over Server-Sent Events."""
from __future__ import annotations
import asyncio, json, logging, time, uuid
from collections import Counter
from functools import lru_cache
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .agents.control import METRICS
from .agents.personalizer import Profile
from .agents.pundits import PUNDITS
from .config import ROOT, get_settings
from .faults import FaultInjector
from .generator import CLUBS, generate, write_jsonl
from .i18n import LANGS, OFFLINE_LANGS
from .llm import LLMClient
from .logging_setup import setup_logging
from .orchestrator import Orchestrator

S = get_settings()
setup_logging(S.log_level, S.log_json)
log = logging.getLogger("match_insights.server")
WEB = ROOT / "web"
app = FastAPI(title="Match Control Room", version="2.0.0",
              description="Multi-agent live match intelligence: SPC momentum control, 5-Whys root cause, fact-checked pundit panel.")
app.mount("/static", StaticFiles(directory=WEB), name="static")
VOTES: Counter = Counter()
SESSIONS: dict = {}  # session id -> orchestrator (bounded; for /api/debug)
METRICS_COUNTERS: Counter = Counter()
STARTED = time.time()
LLM = LLMClient(S.llm_timeout_s)


def match_path(seed: int):
    return S.data_dir / f"match_{seed}.jsonl"


@lru_cache(maxsize=16)
def load_match(seed: int) -> tuple:
    p = match_path(seed)
    if not p.exists():
        ev, truth = generate(seed, with_truth=True)
        write_jsonl(ev, p, truth)
    return tuple(json.loads(line) for line in p.open())


@lru_cache(maxsize=16)
def highlights(seed: int) -> dict:
    """Offline pre-pass used by demo mode to find the juicy moments."""
    orch = Orchestrator(llm=_offline_llm(), subgroup_s=S.subgroup_s)
    for e in load_match(seed):
        orch.process(e)
    st = orch.state
    moments = [{"t": g["t"], "kind": "goal", "team": g["team"], "label": f"Goal {st.club(g['team'])}"} for g in st.goals]
    moments += [{"t": a["t"], "kind": "root_cause", "team": a["team_in_control"],
                 "label": f"Momentum → {st.club(a['team_in_control'])}"} for a in st.analyses]
    moments.sort(key=lambda m: m["t"])
    windows = []
    for m in moments:
        a, b = (m["t"] - 30, m["t"] + 25) if m["kind"] == "goal" else (m["t"] - 25, m["t"] + 45)
        if windows and a <= windows[-1][1]:
            windows[-1][1] = max(windows[-1][1], b)
        else:
            windows.append([a, b])
    return {"moments": moments, "windows": windows, "score": st.score}


def _offline_llm():
    return LLMClient(env={})


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    resp = await call_next(request)
    METRICS_COUNTERS["http_requests"] += 1
    if not request.url.path.startswith("/static"):
        log.info(f"{request.method} {request.url.path} {resp.status_code} {round((time.perf_counter() - t0) * 1000, 1)}ms")
    return resp


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
def health():
    """Liveness probe."""
    st = LLM.status()
    return {"status": "ok", "uptime_s": round(time.time() - STARTED), "llm_provider": st["provider"],
            "llm_model": st["model"], "llm_rate_limited_for_s": st["rate_limited_for_s"]}


@app.get("/api/ready")
def ready():
    """Readiness probe: data dir writable; LLM optional (offline fallback)."""
    try:
        S.data_dir.mkdir(parents=True, exist_ok=True)
        (S.data_dir / ".ready").write_text("ok")
    except OSError as ex:
        return JSONResponse({"status": "not_ready", "error": str(ex)}, status_code=503)
    return {"status": "ready", "llm": LLM.status(), "mode": LLM.provider if LLM.online else "offline-templates"}


@app.get("/api/config")
def config():
    return {"clubs": {k: {"name": v["name"], "short": v["short"], "color": v["color"]} for k, v in CLUBS.items()},
            "languages": LANGS, "offline_languages": OFFLINE_LANGS, "llm_online": LLM.online, "llm_provider": LLM.provider,
            "pundits": {k: {kk: v[kk] for kk in ("name", "title", "initials", "style")} for k, v in PUNDITS.items()},
            "metrics": {k: {"label": v[0], "unit": v[1]} for k, v in METRICS.items()}, "default_seed": S.default_seed,
            "subgroup_s": S.subgroup_s}


@app.get("/api/meta")
def meta(seed: int | None = None):
    return load_match(seed or S.default_seed)[0]


@app.get("/api/highlights")
def get_highlights(seed: int | None = None):
    return highlights(seed or S.default_seed)


@app.get("/api/validation")
def validation():
    p = ROOT / "docs" / "validation.json"
    if not p.exists():
        raise HTTPException(404, "run: python -m match_insights.validate")
    return json.loads(p.read_text())


class Vote(BaseModel):
    pundit: str


@app.post("/api/vote")
def vote(v: Vote):
    if v.pundit not in PUNDITS:
        raise HTTPException(400, "unknown pundit")
    VOTES[v.pundit] += 1
    return dict(VOTES)


@app.get("/api/votes")
def votes():
    return dict(VOTES)


@app.get("/api/debug")
def debug(session: str | None = None):
    """Debugger agent report for a stream session (default: the most recent one)."""
    if session and session not in SESSIONS:
        raise HTTPException(404, "unknown or expired session")
    sid = session or (next(reversed(SESSIONS)) if SESSIONS else None)
    if not sid:
        return {"session": None, "health": "idle", "findings": [], "llm": LLM.status()}
    o = SESSIONS[sid]
    return {"session": sid, "minute": int(o.state.clock // 60), **o.debugger.summary(), "llm": LLM.status(),
            "errors_logged": len(o.state.errors)}


@app.get("/api/metrics")
def metrics():
    return {**METRICS_COUNTERS, "llm": LLM.status(), "votes": dict(VOTES)}


def sse(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/stream")
async def stream(request: Request, seed: int | None = None, persona: str = "casual", club: str | None = None,
                 player: str | None = None, lang: str = "en", pundit: str | None = None,
                 speed: float = Query(30.0, gt=0, le=100000), fault_rate: float = Query(0.0, ge=0, le=0.9),
                 demo: bool = False, start_min: float = Query(0.0, ge=0, le=90)):
    seed = seed or S.default_seed
    events = load_match(seed)
    session = uuid.uuid4().hex[:8]
    prof = Profile(persona if persona in ("casual", "analyst") else "casual", club or None, player or None,
                   lang if lang in LANGS else "en", pundit or None)
    orch = Orchestrator(prof, llm=LLM, faults=FaultInjector(fault_rate, seed=seed), subgroup_s=S.subgroup_s,
                        airtime_gap_s=S.airtime_gap_s, votes=VOTES)
    hl = highlights(seed) if demo else None
    SESSIONS[session] = orch
    while len(SESSIONS) > 20:
        SESSIONS.pop(next(iter(SESSIONS)))
    METRICS_COUNTERS["streams_started"] += 1
    log.info("stream start", extra={"session": session})

    def in_window(t):
        return any(a <= t <= b for a, b in hl["windows"])

    async def gen():
        METRICS_COUNTERS["streams_active"] += 1
        try:
            yield sse("session", {"session": session, "profile": prof.dict(), "seed": seed, "demo": demo,
                                  "highlights": hl, "llm": LLM.status(), "fault_rate": fault_rate})
            prev_t, skipped = 0.0, 0
            for i, e in enumerate(events):
                if i % 50 == 0 and await request.is_disconnected():
                    return
                live = (not demo or in_window(e["t"])) and e["t"] >= start_min * 60
                if live:
                    rate = 8.0 if demo else speed
                    await asyncio.sleep(min(max(e["t"] - prev_t, 0) / rate, S.max_stream_gap_s))
                elif skipped % 25 == 0:
                    await asyncio.sleep(0.004)
                prev_t = e["t"]
                msgs = await asyncio.to_thread(orch.process, e)
                skipped += not live
                for m in msgs:
                    k = m["type"]
                    if not live and k in ("lower_third", "ticker", "focus", "trace", "tick") and not (k == "tick" and skipped % 20 == 0):
                        continue
                    yield sse(k, m["data"])
            yield sse("end", {"score": orch.state.score, "signals": len(orch.state.signals), "errors": len(orch.state.errors)})
        finally:
            METRICS_COUNTERS["streams_active"] -= 1
            log.info("stream end", extra={"session": session})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
