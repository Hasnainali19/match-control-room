"""Shared blackboard. Every agent reads it; each agent owns (writes) only its own section."""
from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass, field


def _dd_pass():
    return defaultdict(lambda: {"att": 0, "comp": 0})


@dataclass
class MatchState:
    # --- Ingest-owned
    meta: dict = field(default_factory=dict)
    players: dict = field(default_factory=dict)
    clock: float = 0.0
    score: dict = field(default_factory=lambda: {"HAR": 0, "MIL": 0})
    goals: list = field(default_factory=list)
    possession_time: dict = field(default_factory=lambda: defaultdict(float))
    current_possession: str | None = None
    last_poss_t: float = 0.0
    recent: deque = field(default_factory=lambda: deque(maxlen=600))
    # --- Stats-owned
    passes: dict = field(default_factory=_dd_pass)
    shots: dict = field(default_factory=lambda: defaultdict(lambda: {"n": 0, "xg": 0.0, "on_target": 0}))
    player: dict = field(default_factory=lambda: defaultdict(lambda: {"dist_m": 0.0, "top_kmh": 0.0, "carries": [], "passes": 0,
                                                                      "passes_ok": 0, "pressed": 0, "lost": 0, "touches": 0}))
    # --- Control-owned
    charts: dict = field(default_factory=dict)       # team -> metric -> [points]
    momentum: dict = field(default_factory=dict)     # team -> latest momentum index
    signals: list = field(default_factory=list)
    # --- Root-cause / Panel / Producer owned
    analyses: list = field(default_factory=list)
    takes: list = field(default_factory=list)
    on_air: list = field(default_factory=list)
    # --- Orchestrator-owned
    traces: deque = field(default_factory=lambda: deque(maxlen=400))
    errors: list = field(default_factory=list)

    def pname(self, pid):
        return self.players.get(pid, {}).get("name", pid or "?")

    def club(self, code):
        return self.meta.get("clubs", {}).get(code, code or "?")

    def possession_pct(self):
        tot = sum(self.possession_time.values()) or 1
        return {k: round(100 * v / tot) for k, v in self.possession_time.items()}

    def pass_acc(self, team):
        p = self.passes[team]
        return round(100 * p["comp"] / p["att"]) if p["att"] else 0

    def facts(self) -> dict:
        """Ground-truth facts any agent may cite; the Referee checks claims against these."""
        f = {"minute": int(self.clock // 60)}
        pos = self.possession_pct()
        for t in ("HAR", "MIL"):
            f[f"score.{t}"] = self.score.get(t, 0)
            f[f"possession.{t}"] = pos.get(t, 50)
            f[f"pass_acc.{t}"] = self.pass_acc(t)
            f[f"shots.{t}"] = self.shots[t]["n"]
            f[f"xg.{t}"] = round(self.shots[t]["xg"], 2)
            for m, pts in self.charts.get(t, {}).items():
                if pts:
                    f[f"chart.{t}.{m}"] = pts[-1]["x"]
        for pid, s in self.player.items():
            f[f"player.{pid}.top_kmh"] = round(s["top_kmh"], 1)
            f[f"player.{pid}.dist_m"] = round(s["dist_m"])
        return f
