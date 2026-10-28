"""StatsAgent: deterministic, explainable metrics. Never uses an LLM (numbers must be exact)."""
from __future__ import annotations
import math

SPRINT_KMH = 25.0
LONG_PASS_M = 30.0
FAST_SHOT_KMH = 100.0
HIGH_PRESS = 0.8
GOAL = {"HAR": (105.0, 34.0), "MIL": (0.0, 34.0)}


def distance(x0, y0, x1, y1):
    return math.hypot(x1 - x0, y1 - y0)


def speed_kmh(dist_m, dur_s):
    return 0.0 if dur_s <= 0 else dist_m / dur_s * 3.6


def pass_difficulty(dist, under_pressure, progressive_m):
    """0..1. Longer, pressured and more progressive passes are harder."""
    d = min(dist / 50, 1) * 0.5 + (0.25 if under_pressure else 0) + min(max(progressive_m, 0) / 40, 1) * 0.25
    return round(min(d, 1.0), 3)


def progressive(team, x0, x1):
    gx, _ = GOAL.get(team, (105.0, 34.0))
    return abs(gx - x0) - abs(gx - x1)


class StatsAgent:
    name = "stats"
    role = "Turn raw events into exact metrics and threshold tags"

    def run(self, e, state):
        out = {"event_id": e["id"], "type": e["type"], "t": e["t"], "tags": []}
        typ = e["type"]
        if e.get("player"):
            state.player[e["player"]]["touches"] += 1
        if typ == "pass":
            d = distance(e["x"], e["y"], e["end_x"], e["end_y"])
            prog = progressive(e["team"], e["x"], e["end_x"])
            p = state.passes[e["team"]]
            p["att"] += 1
            ok = e["outcome"] == "complete"
            p["comp"] += ok
            ps = state.player[e["player"]]
            ps["passes"] += 1
            ps["passes_ok"] += ok
            ps["lost"] += not ok
            diff = pass_difficulty(d, e.get("under_pressure"), prog)
            out.update(distance_m=round(d, 1), ball_speed_kmh=round(speed_kmh(d, e["duration"]), 1),
                       progressive_m=round(prog, 1), difficulty=diff, team_accuracy=round(p["comp"] / p["att"], 3))
            if d >= LONG_PASS_M:
                out["tags"].append("long_pass")
            if diff >= 0.6 and ok:
                out["tags"].append("hard_pass")
        elif typ in ("carry", "run"):
            d = distance(e["x"], e["y"], e["end_x"], e["end_y"])
            v = speed_kmh(d, e["duration"])
            ps = state.player[e["player"]]
            ps["dist_m"] += d  # distance covered at speed (carries + recovery runs)
            ps["top_kmh"] = max(ps["top_kmh"], v)
            ps["carries"].append((e["t"], round(v, 1)))
            out.update(distance_m=round(d, 1), player_speed_kmh=round(v, 1), player_total_m=round(ps["dist_m"], 1))
            if v >= SPRINT_KMH:
                out["tags"].append("sprint")
        elif typ == "shot":
            s = state.shots[e["team"]]
            s["n"] += 1
            s["xg"] += e["xg"]
            s["on_target"] += e["outcome"] in ("goal", "saved")
            out.update(shot_speed_kmh=e["speed_kmh"], xg=e["xg"], team_xg=round(s["xg"], 2),
                       distance_to_goal_m=round(distance(e["x"], e["y"], e["end_x"], e["end_y"]), 1))
            if e["outcome"] == "goal":
                out["tags"].append("goal")
            elif e["xg"] >= 0.25:
                out["tags"].append("big_chance")
            if e["speed_kmh"] >= FAST_SHOT_KMH:
                out["tags"].append("rocket")
        elif typ == "pressure":
            state.player[e["target"]]["pressed"] += 1
            if e["intensity"] >= HIGH_PRESS:
                out["tags"].append("high_press")
        elif typ == "tackle":
            if e["outcome"] == "won":
                out["tags"].append("turnover")
                state.player[e["target"]]["lost"] += 1
        out["score"] = dict(state.score)
        out["possession_pct"] = state.possession_pct()
        return out
