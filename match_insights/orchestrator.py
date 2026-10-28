"""Orchestrator: runs the agent graph per event over a shared blackboard (MatchState).

Graph (handoffs):
  Ingest -> Stats -> Tactics -> Narrator ─┐
                └-> Control --(signal)--> RootCause ─┐
  (goal | swing signal) ---------------> Pundit Panel x4 -> Referee
  all candidates -> Personalizer -> Producer -> overlay messages

Recovery policy, per agent: retry with backoff -> fallback (degraded but safe) ->
deferral (Control replays missed events later) and the LLM circuit breaker.
Every agent call becomes a trace span shown in the UI's Agent Ops panel.
"""
from __future__ import annotations
import contextlib, logging, time
from .agents.control import ControlAgent
from .agents.debugger import DebuggerAgent
from .agents.ingest import IngestAgent
from .agents.narrator import NarratorAgent
from .agents.personalizer import PersonalizerAgent, Profile
from .agents.producer import ProducerAgent
from .agents.pundits import PUNDITS, PunditAgent
from .agents.referee import RefereeAgent
from .agents.root_cause import LANE_NAMES, RootCauseAgent
from .agents.stats import StatsAgent
from .agents.tactics import TacticsAgent
from .faults import FaultInjector
from .llm import LLMClient
from .logging_setup import tracer
from .state import MatchState

log = logging.getLogger("match_insights.orchestrator")
SCHEMA = "mcr.overlay/v2"
_TRACER = tracer()  # OpenTelemetry -> Azure Monitor when configured; no-op otherwise


class Orchestrator:
    def __init__(self, profile: Profile | None = None, llm: LLMClient | None = None, faults: FaultInjector | None = None,
                 subgroup_s: float = 90.0, airtime_gap_s: float = 40.0, votes: dict | None = None, retries: int = 2):
        self.state = MatchState()
        self.profile = profile or Profile()
        self.llm = llm or LLMClient()
        self.faults = faults or FaultInjector(0)
        self.votes = votes if votes is not None else {}
        self.retries = retries
        self.ingest, self.stats, self.tactics = IngestAgent(), StatsAgent(), TacticsAgent()
        self.narrator, self.control, self.root_cause = NarratorAgent(), ControlAgent(subgroup_s), RootCauseAgent()
        self.pundits = [PunditAgent(k) for k in PUNDITS]
        self.referee, self.personalizer, self.producer = RefereeAgent(), PersonalizerAgent(), ProducerAgent(airtime_gap_s)
        self.debugger = DebuggerAgent()
        self.control_backlog: list = []
        self._last_rca = {}
        self._trigger_id = 0
        self._spans: list = []
        self._eid = None

    # ------------------------------------------------------------------ recovery
    def call(self, agent: str, fn, fallback=None, handoff: str | None = None, retries: int | None = None):
        """Run one agent step with fault injection, retry+backoff, fallback and tracing."""
        retries = self.retries if retries is None else retries
        t0, err = time.perf_counter(), None
        for attempt in range(retries + 1):
            try:
                span = _TRACER.start_as_current_span(f"agent.{agent}") if _TRACER else contextlib.nullcontext()
                with span:
                    self.faults.maybe_fail(agent)
                    out = fn()
                self._span(agent, "ok" if attempt == 0 else "recovered", attempt + 1, t0, handoff, err)
                return out
            except Exception as ex:  # noqa: BLE001 - any agent failure is recoverable by policy
                err = str(ex)[:160]
                self.state.errors.append({"agent": agent, "event_id": self._eid, "attempt": attempt + 1, "error": err})
                if attempt < retries:
                    time.sleep(0.002 * (2 ** attempt))
        status = "fallback" if fallback else "failed"
        self._span(agent, status, retries + 1, t0, handoff, err)
        log.warning("agent degraded", extra={"agent": agent, "event_id": self._eid, "status": status, "attempts": retries + 1})
        return fallback() if fallback else None

    def _span(self, agent, status, attempts, t0, handoff, note=None):
        s = {"event_id": self._eid, "t": self.state.clock, "agent": agent, "status": status, "attempts": attempts,
             "ms": round((time.perf_counter() - t0) * 1000, 2), "handoff": handoff}
        if note and status != "ok":
            s["note"] = note
        self._spans.append(s)
        self.state.traces.append(s)

    # ------------------------------------------------------------------ pipeline
    def process(self, e: dict) -> list[dict]:
        """Process one raw event. Returns a list of typed messages {type, data}."""
        self._last_stats = None
        msgs = self._process(e)
        try:  # the Debugger watches everything but can never break the pipeline
            for f in self.debugger.run(e, self._spans, self._last_stats, self.state, self.llm):
                msgs.append({"type": "debug", "data": f})
        except Exception:  # noqa: BLE001
            self.debugger.internal_errors += 1
        return msgs

    def _process(self, e: dict) -> list[dict]:
        self._spans, msgs, st = [], [], self.state
        self._eid = e.get("id") if isinstance(e, dict) else None
        t0 = time.perf_counter()
        try:
            e = self.ingest.run(e, st)
            self._span("ingest", "ok", 1, t0, "stats")
        except ValueError as ex:
            st.errors.append({"agent": "ingest", "event_id": self._eid, "error": str(ex)[:160]})
            self._span("ingest", "rejected", 1, t0, None, str(ex)[:160])
            return [{"type": "trace", "data": self._spans}]
        if e["type"] == "metadata":
            if "players" in e:
                msgs.append({"type": "meta", "data": e})
            else:
                if e.get("phase") == "full_time" and self.control_backlog:
                    # final flush: replay anything Control deferred so end-of-match charts are complete
                    def flush():
                        for be in self.control_backlog:
                            self.control.run(be, st)
                    if self.call("control", flush, retries=5) is not None or not self.faults.rate:
                        self._spans[-1]["note"] = f"final flush replayed {len(self.control_backlog)} event(s)"
                        self.control_backlog = []
                msgs.append({"type": "phase", "data": {"phase": e["phase"], "t": e["t"], "score": dict(st.score)}})
            msgs.append({"type": "trace", "data": self._spans})
            return msgs
        prof = self.profile
        stats = self.call("stats", lambda: self.stats.run(e, st), handoff="tactics",
                          fallback=lambda: {"event_id": e["id"], "type": e["type"], "t": e["t"], "tags": [], "score": dict(st.score),
                                            "possession_pct": st.possession_pct()})
        tac = self.call("tactics", lambda: self.tactics.run(e, stats, st), handoff="narrator",
                        fallback=lambda: {"phase": "unknown", "chaos_index": 0, "tempo_events_per_s": 0, "pressing_team": None,
                                          "reasons": [], "importance": 0.3 if "goal" in stats["tags"] else 0.05})
        self._last_stats = stats
        if "goal" in stats["tags"]:
            tac["importance"] = 1.0  # a goal is always top priority, even in degraded mode
        text, src = self.call("narrator", lambda: self.narrator.run(e, stats, tac, st, self.llm, prof.lang), handoff="personalizer",
                              fallback=lambda: (self.narrator.template(e, stats, st, prof.lang), "template"))
        msgs.append({"type": "tick", "data": self._tick(e, stats)})
        candidates = []
        if text:
            candidates.append({"kind": "narration", "t": e["t"], "priority": tac["importance"], "text": text, "text_source": src,
                               "team": e.get("team"), "players": [p for p in (e.get("player"), e.get("receiver"), e.get("target")) if p],
                               "tags": stats["tags"], "metrics": {k: v for k, v in stats.items() if k not in ("event_id", "type", "t", "tags", "score", "possession_pct")},
                               "tactics": tac, "event_type": e["type"], "anchor": {"x": e.get("x"), "y": e.get("y")}})
        # --- Control (with deferral: if it fails, the event is replayed on the next successful run)
        self.control_backlog.append(e)

        def run_control():
            res = {"points": [], "signals": []}
            for be in self.control_backlog:
                r = self.control.run(be, st)
                res["points"] += r["points"]
                res["signals"] += r["signals"]
            return res
        ctl = self.call("control", run_control, handoff="root_cause", retries=1)
        if ctl is None:
            self._spans[-1]["status"] = "deferred"
            self._spans[-1]["note"] = f"{len(self.control_backlog)} event(s) queued for replay"
            ctl = {"points": [], "signals": []}
        else:
            if len(self.control_backlog) > 1:
                self._spans[-1]["note"] = f"replayed {len(self.control_backlog) - 1} deferred event(s)"
            self.control_backlog = []
        if ctl["points"]:
            msgs.append({"type": "chart", "data": {"points": ctl["points"], "momentum": dict(st.momentum)}})
        triggers = []
        for sig in ctl["signals"]:
            msgs.append({"type": "signal", "data": sig})
            candidates.append({"kind": "signal", "t": sig["t"], "priority": 0.75 if sig["swing"] else 0.45, "signal": sig,
                               "team": sig["momentum_to"], "players": []})
            if sig["swing"] and sig["t"] - self._last_rca.get(sig["momentum_to"], -1e9) >= 300:
                self._last_rca[sig["momentum_to"]] = sig["t"]
                rca = self.call("root_cause", lambda s=sig: self.root_cause.run(s, st, self.llm, prof.lang), handoff="pundits",
                                fallback=lambda s=sig: {"signal_id": s["id"], "t": s["t"], "minute": s["minute"], "team_in_control": s["momentum_to"],
                                                        "whys": [{"q": "Why?", "a": f"{s['metric_label']} shifted ({s['rule_text']}). Detailed analysis unavailable."}],
                                                        "countermeasure": None, "claims": [], "player": None, "lane": "C", "degraded": True})
                candidates.append({"kind": "whys", "t": sig["t"], "priority": 0.7, "analysis": rca, "team": sig["momentum_to"],
                                   "players": [rca.get("player")] if rca.get("player") else []})
                self._trigger_id += 1
                triggers.append({"id": self._trigger_id, "kind": "signal", "t": sig["t"], "team": sig["momentum_to"],
                                 "lane_name": LANE_NAMES.get(rca.get("lane"), ""),
                                 "summary": f"{st.club(sig['momentum_to'])} take control: {sig['metric_label']} {sig['rule_text']}"})
        if "goal" in stats["tags"]:
            self._trigger_id += 1
            triggers.append({"id": self._trigger_id, "kind": "goal", "t": e["t"], "team": e["team"],
                             "summary": f"Goal by {st.pname(e['player'])} for {st.club(e['team'])}, score {st.score}"})
        for trig in triggers:
            facts = st.facts()
            takes = []
            for p in self.pundits:
                tk = self.call(p.name, lambda p=p: p.run(trig, facts, st, self.llm, prof.club, prof.lang), handoff="referee",
                               fallback=lambda p=p: p.template(trig, facts, st, prof.club, "en") and {
                                   "pundit": p.key, "name": p.profile["name"], "title": p.profile["title"], "initials": p.profile["initials"],
                                   "trigger": trig["kind"], "trigger_id": trig["id"], "t": trig["t"],
                                   "text": p.template(trig, facts, st, prof.club, prof.lang)[0],
                                   "claims": p.template(trig, facts, st, prof.club, prof.lang)[1], "source": "template"})
                if tk:
                    takes.append(tk)
            checked = self.call("referee", lambda: self.referee.run(takes, facts), handoff="producer",
                                fallback=lambda: [{**x, "verdict": "unchecked", "checks": []} for x in takes])
            st.takes.extend(checked)
            candidates.append({"kind": "panel", "t": trig["t"], "priority": 0.65, "trigger": trig, "takes": checked,
                               "team": trig["team"], "players": []})
        if not candidates:
            msgs.append({"type": "trace", "data": self._spans})
            return msgs
        personal = self.call("personalizer", lambda: self.personalizer.run(candidates, e, st, prof), handoff="producer",
                             fallback=lambda: candidates)
        for c in personal:
            if c["kind"] == "panel":
                c["featured"] = self.producer.pick_pundit(c["takes"], prof.pundit, self.votes)
        decisions = self.call("producer", lambda: self.producer.run(personal, e["t"], st), handoff=None,
                              fallback=lambda: self.producer.fallback(personal, e["t"]))
        for d in decisions:
            item = d["item"]
            msgs.append({"type": d["channel"], "data": {
                "schema": SCHEMA, "channel": d["channel"], "kind": item["kind"], "match_time_s": e["t"], "clock": self.clock(item["t"]),
                "display": {**d.get("display", {"start_s": e["t"], "duration_s": 6}), "anchor": item.get("anchor")},
                "priority": item["priority"], "highlight": item.get("highlight"), "lang": prof.lang, "persona": prof.persona,
                "degraded": d.get("degraded", False), **{k: v for k, v in item.items() if k not in ("priority", "highlight")}}})
        if prof.player and prof.player in (e.get("player"), e.get("target"), e.get("receiver")):
            card = self.personalizer.focus_card(st, prof.player)
            if card:
                msgs.append({"type": "focus", "data": card})
        msgs.append({"type": "trace", "data": self._spans})
        return msgs

    @staticmethod
    def clock(t):
        return f"{int(t // 60):02d}:{int(t % 60):02d}"

    def _tick(self, e, stats):
        st = self.state
        d = {k: e.get(k) for k in ("id", "t", "type", "team", "player", "x", "y", "end_x", "end_y", "outcome", "target") if e.get(k) is not None}
        d.update(clock=self.clock(e["t"]), score=dict(st.score), possession_pct=st.possession_pct(), tags=stats.get("tags", []),
                 player_name=st.pname(e.get("player")) if e.get("player") else None)
        return d
