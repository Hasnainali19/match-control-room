"""ControlAgent: rolling SPC control charts per team -> 'out of control' momentum signals.

Every ``subgroup_s`` seconds of match time a subgroup closes and one point per team and
metric is added. Each point is standardised against a rolling baseline (the previous
~16 subgroups, excluding the two newest), then checked with Western Electric / Nelson
run rules and an EWMA chart. A favourable shift for a team is a momentum signal.
"""
from __future__ import annotations
import math
from collections import defaultdict
from ..spc import RULES, baseline, check_rules

TEAMS = ("HAR", "MIL")
METRICS = {  # key: (label, unit, sigma floor, is_share)
    "possession": ("Possession share", "%", 4.0, True),
    "tilt": ("Field tilt", "%", 6.0, True),
    "pressure": ("Pressing load", "/min", 0.25, False),
    "completion": ("Pass completion", "%", 3.0, False),
    "difficulty": ("Pass difficulty", "", 0.02, False),
    "tempo": ("Passing tempo", "/min", 0.8, False),
}
LAM, L_EWMA = 0.3, 2.7
EWMA_LIM = L_EWMA * math.sqrt(LAM / (2 - LAM))
SEVERITY = {"WE1": 3, "WE2": 3, "EWMA": 2, "WE3": 2, "N3": 1, "WE4": 1}


def other(t):
    return "MIL" if t == "HAR" else "HAR"


class ControlAgent:
    name = "control"
    role = "Run live control charts and flag momentum shifts with SPC run rules"

    def __init__(self, subgroup_s=90.0, warmup=5, window=20, cooldown_s=360, lag=4):
        self.sg, self.warmup, self.window, self.cooldown, self.lag = subgroup_s, warmup, window, cooldown_s, lag
        self.next_close = subgroup_s
        self.k = 0
        self._reset_acc()
        self._poss, self._last_t = "HAR", 0.0  # Control keeps its own possession clock (replay-safe)
        self._ewma = defaultdict(float)
        self._last_signal = {}
        self._sid = 0

    def _reset_acc(self):
        self.acc = {t: {"att": 0, "comp": 0, "diff": 0.0, "press": 0.0, "final": 0, "poss_s": 0.0} for t in TEAMS}

    def _accumulate(self, e):
        self.acc[self._poss]["poss_s"] += max(0.0, e["t"] - self._last_t)
        self._last_t = e["t"]
        if e["type"] == "possession_change":
            self._poss = e["team"]
        team = e.get("team")
        if team not in TEAMS:
            return
        a = self.acc[team]
        typ = e["type"]
        if typ == "pass":
            from .stats import distance, pass_difficulty, progressive
            a["att"] += 1
            a["comp"] += e["outcome"] == "complete"
            d = distance(e["x"], e["y"], e["end_x"], e["end_y"])
            a["diff"] += pass_difficulty(d, e.get("under_pressure"), progressive(team, e["x"], e["end_x"]))
        elif typ == "pressure":
            a["press"] += e["intensity"]
        if typ in ("pass", "carry", "shot") and "x" in e:
            if (team == "HAR" and e["x"] >= 70) or (team == "MIL" and e["x"] <= 35):
                a["final"] += 1

    def _close(self, state):
        mins = self.sg / 60
        poss = {t: self.acc[t]["poss_s"] for t in TEAMS}
        ptot = sum(poss.values()) or 1
        ftot = sum(self.acc[t]["final"] for t in TEAMS) or 1
        vals = {}
        for t in TEAMS:
            a = self.acc[t]
            vals[t] = {
                "possession": round(100 * poss[t] / ptot, 1),
                "tilt": round(100 * a["final"] / ftot, 1),
                "pressure": round(a["press"] / mins, 2),
                "completion": round(100 * a["comp"] / a["att"], 1) if a["att"] >= 3 else None,
                "difficulty": round(a["diff"] / a["att"], 3) if a["att"] >= 3 else None,
                "tempo": round(a["att"] / mins, 2),
            }
        self.k += 1
        points, signals = [], []
        t_end = self.next_close
        for t in TEAMS:
            charts = state.charts.setdefault(t, {m: [] for m in list(METRICS) + ["momentum"]})
            zsum, zn = 0.0, 0
            for m, (label, unit, floor, share) in METRICS.items():
                pts = charts[m]
                x = vals[t][m]
                hist = pts[-(self.window + self.lag):-self.lag] if len(pts) > self.lag else []
                base = baseline([p["x"] for p in hist], self.warmup, floor)
                pt = {"k": self.k, "t": t_end, "minute": round(t_end / 60, 1), "x": x}
                if base and x is not None:
                    mu, sd = base
                    sd = max(sd, floor)
                    z = (x - mu) / sd
                    key = (t, m)
                    self._ewma[key] = LAM * z + (1 - LAM) * self._ewma[key]
                    hi_cap = 100.0 if unit == "%" else (1.0 if m == "difficulty" else float("inf"))
                    clip = lambda v: round(min(max(v, 0.0), hi_cap), 2)  # noqa: E731 - physical bounds
                    pt.update(z=round(z, 2), cl=round(mu, 2), ucl=clip(mu + 3 * sd), lcl=clip(mu - 3 * sd),
                              ewma=clip(mu + self._ewma[key] * sd), ewma_ucl=clip(mu + EWMA_LIM * sd),
                              ewma_lcl=clip(mu - EWMA_LIM * sd))
                    zsum += z * (0.5 if m == "difficulty" else 1)
                    zn += 1
                pts.append(pt)
                points.append({"team": t, "metric": m, **pt})
                if "z" in pt and not (share and t == "MIL"):
                    zs = [p["z"] for p in pts if "z" in p]
                    fired = check_rules(zs, self._ewma[(t, m)] / EWMA_LIM)
                    if fired:
                        rule, direction = max(fired, key=lambda r: SEVERITY[r[0]])
                        momentum_to = t if direction > 0 else other(t)
                        ck = (momentum_to, m)
                        if t_end - self._last_signal.get(ck, -1e9) >= self.cooldown:
                            self._last_signal[ck] = t_end
                            self._sid += 1
                            signals.append({"id": self._sid, "t": t_end, "minute": int(t_end // 60), "team": t, "metric": m,
                                            "metric_label": label, "unit": unit, "rule": rule, "rule_text": RULES[rule],
                                            "rules_fired": [r for r, _ in fired], "direction": direction,
                                            "momentum_to": momentum_to, "z": pt["z"], "x": x, "cl": pt["cl"],
                                            "ucl": pt["ucl"], "lcl": pt["lcl"], "severity": SEVERITY[rule]})
            mom = round(max(-3, min(3, zsum / zn)), 2) if zn else 0.0
            state.momentum[t] = mom
            charts["momentum"].append({"k": self.k, "t": t_end, "minute": round(t_end / 60, 1), "x": mom, "cl": 0,
                                       "ucl": 1.5, "lcl": -1.5, "z": mom})
            points.append({"team": t, "metric": "momentum", **charts["momentum"][-1]})
        # a swing = 2+ metrics agreeing within the last 3 subgroups
        for s in signals:
            pool = [x for x in state.signals[-12:] + signals if x["severity"] >= 2 and x["momentum_to"] == s["momentum_to"]
                    and 0 <= s["t"] - x["t"] <= 2 * self.sg]
            agree = {x["metric"] for x in pool}
            s["corroborating_metrics"] = sorted(agree)
            s["swing"] = len(agree) >= 2 and s["severity"] >= 2
        state.signals.extend(signals)
        self._reset_acc()
        self.next_close += self.sg
        return points, signals

    def run(self, e, state):
        points, signals = [], []
        if e["type"] == "metadata" and "home" in e:
            self._poss = e["home"]
        while e["t"] >= self.next_close:
            p, s = self._close(state)
            points += p
            signals += s
        self._accumulate(e)
        return {"points": points, "signals": signals}
