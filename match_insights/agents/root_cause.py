"""RootCauseAgent: a live Lean '5 Whys' on each momentum signal, built only from event evidence.

Each 'why' carries the numbers it is based on (evidence) so the Referee can audit it.
"""
from __future__ import annotations
from statistics import mean
from ..i18n import metric as metric_name
from ..llm import LLMUnavailable

LANE_NAMES = {"L": "left flank", "C": "middle", "R": "right flank"}


def other(t):
    return "MIL" if t == "HAR" else "HAR"


def poss(name):
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def lane_of(team, y):
    """Lane from the perspective of `team` (HAR attacks +x, its left flank is low y)."""
    if 22.7 <= y <= 45.3:
        return "C"
    low_is_left = team == "HAR"
    return "L" if (y < 22.7) == low_is_left else "R"


class RootCauseAgent:
    name = "root_cause"
    role = "Explain a momentum signal with an evidence-backed 5 Whys and a countermeasure"

    def __init__(self, window_s=420):
        self.window_s = window_s

    def run(self, sig, state, llm=None, lang="en"):
        G, Lt = sig["momentum_to"], other(sig["momentum_to"])
        t1, t0 = sig["t"], sig["t"] - self.window_s
        win = [e for e in state.recent if t0 <= e["t"] <= t1]
        gname, lname = state.club(G), state.club(Lt)
        whys, claims = [], []
        # Why 1: what changed on the chart
        chart_team = sig["team"]
        val_txt = f"{sig['x']}{sig['unit']}"
        whys.append({"q": f"Why is {gname} in control?",
                     "a": f"{metric_name(sig['metric'], 'en')} for {state.club(chart_team)} hit {val_txt} against a normal "
                          f"{sig['cl']}{sig['unit']} — {sig['rule_text']}.",
                     "evidence": {"value": sig["x"], "centre": sig["cl"], "ucl": sig["ucl"], "lcl": sig["lcl"], "rule": sig["rule"]}})
        claims.append({"key": f"chart.{chart_team}.{sig['metric']}", "value": sig["x"], "shown": str(sig["x"])})
        # Why 2: where on the pitch (lanes from the losing team's perspective)
        att = [e for e in win if e.get("team") == G and e["type"] in ("pass", "carry", "shot", "tackle") and "y" in e]
        lanes = {"L": 0, "C": 0, "R": 0}
        for e in att:
            lanes[lane_of(Lt, e.get("end_y", e["y"]))] += 1
        lane = max(lanes, key=lanes.get)
        share = round(100 * lanes[lane] / max(sum(lanes.values()), 1))
        whys.append({"q": "Why there?", "a": f"{share}% of {poss(gname)} actions in the last {self.window_s // 60} minutes targeted "
                                             f"{poss(lname)} {LANE_NAMES[lane]}.", "evidence": {"lane": lane, "share_pct": share, "n": sum(lanes.values())}})
        # Why 3: who is under the most stress in that lane
        stress = {}
        for e in win:
            if e["type"] == "pressure" and e["team"] == G:
                stress.setdefault(e["target"], [0, 0])[0] += 1
            if e["type"] == "tackle" and e["team"] == G and e["outcome"] == "won":
                stress.setdefault(e["target"], [0, 0])[1] += 1
            if e["type"] == "pass" and e["team"] == Lt and e["outcome"] == "incomplete":
                stress.setdefault(e["player"], [0, 0])[1] += 1
        lane_players = [p for p, info in state.players.items() if info.get("team") == Lt and info.get("side") == lane and info.get("role") != "GK"]
        pool = {p: v for p, v in stress.items() if p in lane_players} or {p: v for p, v in stress.items() if state.players.get(p, {}).get("team") == Lt}

        def drop_pct(pid):
            sp = state.player[pid]["carries"] if pid in state.player else []
            e_ = [v for tt, v in sp if tt < min(30 * 60, t0)]
            l_ = [v for tt, v in sp if tt >= t1 - 15 * 60]
            return max(0.0, 100 * (mean(e_) - mean(l_)) / mean(e_)) if len(e_) >= 3 and len(l_) >= 2 else 0.0
        # stress score = involvement in losses + physical decline (a Lean 'gemba' check on the player)
        for p in lane_players:
            pool.setdefault(p, [0, 0])
        who = max(pool, key=lambda p: pool[p][0] + 2 * pool[p][1] + (drop_pct(p) / 4 if t1 >= 45 * 60 else 0)) if pool else None
        pressed, lost = pool.get(who, [0, 0]) if who else (0, 0)
        role = state.players.get(who, {}).get("role", "")
        whys.append({"q": "Why is it working?", "a": f"{state.pname(who)} ({role}) is the pressure point: pressed {pressed}× and lost the ball {lost}× in that spell.",
                     "evidence": {"player": who, "pressed": pressed, "lost": lost}})
        # Why 4: physical condition (fatigue) of that player, from carry speeds
        carries = state.player[who]["carries"] if who else []
        early = [v for tt, v in carries if tt < min(30 * 60, t0)]
        late = [v for tt, v in carries if tt >= t1 - 15 * 60]
        cause = "press"
        if len(early) >= 3 and len(late) >= 2 and t1 >= 45 * 60:
            e_avg, l_avg = round(mean(early), 1), round(mean(late), 1)
            drop = round(100 * (e_avg - l_avg) / e_avg)
            if drop >= 10:
                cause = "fatigue"
                whys.append({"q": f"Why is {state.pname(who)} struggling?", "a": f"His sprint speed fell from {e_avg} to {l_avg} km/h (−{drop}%): fatigue.",
                             "evidence": {"early_kmh": e_avg, "late_kmh": l_avg, "drop_pct": drop}})
        if cause != "fatigue":
            def comp(evts):
                ps = [e for e in evts if e["type"] == "pass" and e["team"] == Lt]
                return round(100 * sum(e["outcome"] == "complete" for e in ps) / len(ps)) if ps else None
            before = comp([e for e in state.recent if e["t"] < t0])
            during = comp(win)
            gp = sum(1 for e in win if e["type"] == "pressure" and e["team"] == G)
            whys.append({"q": f"Why can't {lname} play out?",
                         "a": f"{lname} completed {during}% of passes in this spell vs {before}% before, facing {gp} {gname} presses."
                         if during is not None and before is not None else f"{gname} pressed {gp}× in the spell.",
                         "evidence": {"comp_during": during, "comp_before": before, "presses": gp}})
        # Why 5: root cause + countermeasure (the Lean bit)
        if cause == "fatigue":
            root = f"Root cause: {lname} have not rotated or covered a tiring {role} — the system relies on his recovery runs."
            cm = f"Substitute {state.pname(who)} or drop a midfielder into the {LANE_NAMES[lane]}."
        elif sig["metric"] in ("pressure", "completion", "difficulty"):
            root = f"Root cause: {poss(lname)} build-up cannot beat {gname}'s press through the {LANE_NAMES[lane]}."
            cm = "Go longer to bypass the first press line and reset the shape."
        else:
            root = f"Root cause: {lname} are being pinned back — no outlet to relieve pressure on the {LANE_NAMES[lane]}."
            cm = "Slow the tempo, keep the ball centrally and push the line up together."
        whys.append({"q": "And why does that matter?", "a": root, "evidence": {"cause": cause}})
        out = {"signal_id": sig["id"], "t": sig["t"], "minute": sig["minute"], "team_in_control": G, "team_under_stress": Lt,
               "lane": lane, "player": who, "cause": cause, "whys": whys[:5], "countermeasure": cm, "claims": claims, "source": "rules"}
        if llm is not None and llm.online and lang != "en":
            try:
                tr = llm.complete_json("Translate the football analysis values to the target language. Keep every number unchanged. "
                                       "Return {\"whys\":[{\"q\":..,\"a\":..}],\"countermeasure\":..}",
                                       f"Target: {lang}. Data: {{'whys': {[{'q': w['q'], 'a': w['a']} for w in out['whys']]}, 'countermeasure': {cm!r}}}")
                for w, tw in zip(out["whys"], tr.get("whys", [])):
                    w["q"], w["a"] = tw.get("q", w["q"]), tw.get("a", w["a"])
                out["countermeasure"] = tr.get("countermeasure", cm)
                out["source"] = "rules+llm"
            except (LLMUnavailable, ValueError, AttributeError):
                pass
        state.analyses.append(out)
        return out
