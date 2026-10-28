"""DebuggerAgent: a watchdog over the other agents.

It reads (never writes) the shared state, the per-event trace spans and the LLM gateway status,
and turns anomalies into de-duplicated *findings* with a severity, likely cause and suggested fix:

* agent faults: retries, fallbacks, deferrals, hard failures, retry storms (degraded pipeline)
* latency: slow agent calls
* data validation: rejected events, stats out of physical range, possession not summing to 100
* stream health: stalled feed (long gap in match time)
* LLM health: failures, rate limiting, open circuit breaker

It is defensive by design: every check is isolated, and the orchestrator calls it inside its own
guard, so a bug here can never take down the broadcast pipeline.
"""
from __future__ import annotations
from collections import Counter, deque

SEVERITIES = ("info", "warning", "error", "critical")
RANGES = {  # metric -> (min, max, unit)  physical sanity limits
    "player_speed_kmh": (0, 40, "km/h"),
    "ball_speed_kmh": (0, 130, "km/h"),
    "shot_speed_kmh": (20, 140, "km/h"),
    "distance_m": (0, 110, "m"),
    "xg": (0, 1, ""),
    "difficulty": (0, 1, ""),
}
FIX = {
    "retry": ("Transient fault inside the agent (timeout / 429 / exception).", "No action: retry recovered it. Investigate if the rate keeps rising."),
    "fallback": ("Agent failed after all retries; a safe degraded output was used.", "Check the agent's dependency (LLM quota, input shape). Fallback keeps the broadcast safe."),
    "deferred": ("Control agent unavailable; events queued for replay.", "Charts will catch up automatically on the next successful run."),
    "failed": ("Agent failed with no fallback defined.", "Add a fallback for this agent or fix the root exception."),
    "rejected": ("Feed sent an invalid, out-of-order or off-pitch event.", "Check the upstream feed/provider; Ingest dropped the event safely."),
    "latency": ("Agent call slower than budget (LLM round trip, CPU contention or long backlog).", "Lower LLM usage, raise the timeout, or scale out replicas."),
    "range": ("A computed metric is outside physical limits — bad coordinates/timestamps or a stats bug.", "Inspect the source event; add an Ingest validation rule for it."),
    "possession": ("Possession shares do not add up to 100%.", "Check the Ingest possession clock for missing possession_change events."),
    "stall": ("No events for a long stretch of match time — feed stalled or gap in data.", "Check the feed connection; the UI keeps the last state meanwhile."),
    "storm": ("Many agents are degrading at once — pipeline under stress (chaos mode or an outage).", "Turn chaos off / check the LLM provider and resources. Deterministic outputs remain correct."),
    "llm_fail": ("LLM provider calls are failing.", "Verify endpoint/model/token; templates are being used meanwhile."),
    "llm_rate": ("LLM provider rate limit hit (HTTP 429).", "Reduce LLM calls (importance threshold) or raise the quota; templates cover the gap."),
    "llm_circuit": ("Circuit breaker open after repeated LLM failures.", "Wait for the cooldown; check provider status."),
}


class DebuggerAgent:
    name = "debugger"
    role = "Watch traces, data and the LLM gateway; classify anomalies and suggest fixes"

    def __init__(self, latency_ms=250.0, stall_s=90.0, storm_window=60, storm_rate=0.15, repeat_s=120.0):
        self.latency_ms, self.stall_s, self.repeat_s = latency_ms, stall_s, repeat_s
        self.storm_window, self.storm_rate = storm_window, storm_rate
        self.findings: dict[str, dict] = {}
        self.recent = deque(maxlen=storm_window)
        self.counts = Counter()
        self._last_t = None
        self._llm = {"failures": 0, "rate_limited": 0}
        self._seq = 0
        self.internal_errors = 0

    # ------------------------------------------------------------------ helpers
    def _raise(self, key, t, severity, category, agent, title, detail, fix_key, event_id=None):
        """Create or update a finding; returns it when it should be (re-)published."""
        f = self.findings.get(key)
        if f:
            f["count"] += 1
            f["last_t"] = t
            f["detail"] = detail
            if SEVERITIES.index(severity) > SEVERITIES.index(f["severity"]):
                f["severity"] = severity
                f["_published"] = -1e9
            if t - f["_published"] < self.repeat_s:
                return None
        else:
            self._seq += 1
            cause, fix = FIX[fix_key]
            f = self.findings[key] = {"id": self._seq, "key": key, "first_t": t, "last_t": t, "minute": int(t // 60),
                                      "severity": severity, "category": category, "agent": agent, "title": title,
                                      "detail": detail, "cause": cause, "fix": fix, "count": 1, "event_id": event_id,
                                      "_published": -1e9}
        f["_published"] = t
        f["minute"] = int(t // 60)
        return {k: v for k, v in f.items() if not k.startswith("_")}

    # ------------------------------------------------------------------ checks
    def _check_spans(self, spans, t):
        out = []
        for s in spans:
            self.recent.append(s["status"])
            st, agent = s["status"], s["agent"]
            self.counts[st] += 1
            if st == "recovered":
                out.append(self._raise(f"retry:{agent}", t, "info", "agent", agent, f"{agent} recovered by retry",
                                       f"{s['attempts']} attempts — {s.get('note', '')}", "retry", s["event_id"]))
            elif st in ("fallback", "deferred", "failed"):
                sev = {"fallback": "warning", "deferred": "warning", "failed": "error"}[st]
                out.append(self._raise(f"{st}:{agent}", t, sev, "agent", agent, f"{agent} {st}",
                                       s.get("note", ""), st, s["event_id"]))
            elif st == "rejected":
                out.append(self._raise("rejected:ingest", t, "warning", "data", "ingest", "Invalid event rejected",
                                       s.get("note", ""), "rejected", s["event_id"]))
            if s.get("ms", 0) > self.latency_ms:
                out.append(self._raise(f"latency:{agent}", t, "warning", "latency", agent, f"{agent} slow ({s['ms']:.0f} ms)",
                                       f"budget {self.latency_ms:.0f} ms", "latency", s["event_id"]))
        bad = sum(1 for x in self.recent if x in ("fallback", "deferred", "failed"))
        if len(self.recent) >= self.storm_window and bad / len(self.recent) >= self.storm_rate:
            out.append(self._raise("storm", t, "critical" if bad / len(self.recent) >= 0.3 else "error", "pipeline", "orchestrator",
                                   "Pipeline degraded", f"{bad}/{len(self.recent)} recent agent calls degraded", "storm"))
        return out

    def _check_stats(self, e, stats, state, t):
        out = []
        if stats:
            for k, (lo, hi, unit) in RANGES.items():
                v = stats.get(k, (stats.get("metrics") or {}).get(k))
                if isinstance(v, (int, float)) and not (lo <= v <= hi):
                    out.append(self._raise(f"range:{k}", t, "error", "data", "stats", f"{k} out of range: {v}{unit}",
                                           f"event {e.get('id')} ({e.get('type')}); expected {lo}–{hi}{unit}", "range", e.get("id")))
        pos = state.possession_pct()
        if pos and t > 300 and abs(sum(pos.values()) - 100) > 2:
            out.append(self._raise("possession", t, "warning", "data", "ingest", "Possession does not sum to 100%",
                                   str(pos), "possession"))
        return out

    def _check_stream(self, e, t):
        out = []
        if self._last_t is not None and t - self._last_t > self.stall_s:
            out.append(self._raise("stall", t, "warning", "stream", "ingest", f"Feed stalled for {t - self._last_t:.0f}s of match time",
                                   f"between {self._last_t:.0f}s and {t:.0f}s", "stall", e.get("id")))
        self._last_t = t
        return out

    def _check_llm(self, llm, t):
        out = []
        st = llm.status() if llm is not None and hasattr(llm, "status") else None
        if not st or not st.get("online"):
            return out
        if st["failures"] > self._llm["failures"]:
            out.append(self._raise("llm_fail", t, "warning", "llm", st.get("provider", "llm"), "LLM call failed",
                                   f"{st['failures']} failures / {st['calls']} calls", "llm_fail"))
        if st.get("rate_limited", 0) > self._llm["rate_limited"]:
            out.append(self._raise("llm_rate", t, "warning", "llm", st.get("provider", "llm"), "LLM rate limited (429)",
                                   f"cooldown {st.get('rate_limited_for_s', 0)}s", "llm_rate"))
        if st.get("circuit_open"):
            out.append(self._raise("llm_circuit", t, "error", "llm", st.get("provider", "llm"), "LLM circuit breaker open",
                                   f"{st['failures']} failures", "llm_circuit"))
        self._llm = {"failures": st["failures"], "rate_limited": st.get("rate_limited", 0)}
        return out

    # ------------------------------------------------------------------ entry point
    def run(self, e, spans, stats, state, llm=None):
        """Return newly published findings. Never raises."""
        t = (e.get("t") if isinstance(e, dict) else None) or state.clock
        published = []
        for check in (lambda: self._check_spans(spans, t),
                      lambda: self._check_stats(e, stats, state, t) if isinstance(e, dict) and "t" in e else [],
                      lambda: self._check_stream(e, t) if isinstance(e, dict) and e.get("type") not in (None, "metadata") else [],
                      lambda: self._check_llm(llm, t)):
            try:
                published += [f for f in check() if f]
            except Exception:  # noqa: BLE001 - the watchdog must never hurt the pipeline
                self.internal_errors += 1
        return published

    def summary(self):
        items = sorted(({k: v for k, v in f.items() if not k.startswith("_")} for f in self.findings.values()),
                       key=lambda f: (-SEVERITIES.index(f["severity"]), -f["last_t"]))
        by_sev = Counter(f["severity"] for f in items)
        health = "critical" if by_sev["critical"] else "degraded" if by_sev["error"] else "warning" if by_sev["warning"] else "healthy"
        return {"health": health, "by_severity": {s: by_sev.get(s, 0) for s in SEVERITIES}, "span_status": dict(self.counts),
                "internal_errors": self.internal_errors, "findings": items}
