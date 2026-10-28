"""Seeded synthetic match generator with *latent* momentum and fatigue regimes.

Fictional clubs and players only. The hidden regimes (who dominates, through which flank,
caused by whose fatigue) shift the event distributions realistically, so Statistical Process
Control can genuinely detect them. Ground truth goes to a sidecar ``*.truth.json`` that the
pipeline never reads; only ``validate.py`` uses it.
"""
from __future__ import annotations
import argparse, json, math, random
from pathlib import Path

CLUBS = {
    "HAR": {"name": "Harrowgate Rovers", "short": "ROV", "color": "#e5484d",
            "players": ["Okafor", "Lindqvist", "Marlowe", "Duarte", "Benn", "Kowal", "Asante", "Ferreira", "Tanaka", "Quill", "Vasquez"]},
    "MIL": {"name": "Millbrook Athletic", "short": "MIL", "color": "#3dd6d0",
            "players": ["Achebe", "Rourke", "Santini", "Halvorsen", "Mbeki", "Doyle", "Ortega", "Pryce", "Nakamura", "Ellery", "Szabo"]},
}
ROLES = [("GK", "C"), ("RB", "R"), ("LB", "L"), ("CB", "C"), ("CB", "C"), ("DM", "C"),
         ("RW", "R"), ("CM", "C"), ("ST", "C"), ("AM", "C"), ("LW", "L")]
PITCH_X, PITCH_Y = 105.0, 68.0
HOME, AWAY = "HAR", "MIL"


def other(team):
    return AWAY if team == HOME else HOME


def lane_y(team, side):
    """Screen convention: HOME attacks +x, its left flank is low y; AWAY is mirrored."""
    if side == "C":
        return 34.0
    left_low = team == HOME
    return 12.0 if (side == "L") == left_low else 56.0


def roster(team, rng):
    out = []
    for i, (n, (role, side)) in enumerate(zip(CLUBS[team]["players"], ROLES)):
        out.append({"id": f"{team}-{i+1}", "name": n, "team": team, "number": i + 1, "role": role, "side": side,
                    "base_speed": round(rng.uniform(6.3, 8.6), 2), "fatigue_rate": round(rng.uniform(0.15, 0.4), 2)})
    return out


def build_regimes(rng, minutes):
    """Timeline of latent regimes: neutral warm-up, random swings, one fatigue-driven collapse."""
    end = minutes * 60
    victim_team = rng.choice([HOME, AWAY])
    victim = f"{victim_team}-{rng.choice([2, 3])}"  # a fullback
    onset = rng.uniform(55, 66) * 60
    regimes, t = [], 0.0
    t = rng.uniform(10, 14) * 60
    regimes.append({"start": 0.0, "end": t, "team": None, "strength": 0.0, "cause": "baseline"})
    while t < onset - 6 * 60:
        dur = rng.uniform(6, 13) * 60
        e = min(t + dur, onset - 60)
        if rng.random() < 0.5:
            regimes.append({"start": t, "end": e, "team": rng.choice([HOME, AWAY]), "strength": round(rng.uniform(0.45, 0.8), 2),
                            "cause": "tactical_press", "channel": rng.choice(["L", "R", "C"])})
        else:
            regimes.append({"start": t, "end": e, "team": None, "strength": 0.0, "cause": "neutral"})
        t = e
    regimes.append({"start": t, "end": onset, "team": None, "strength": 0.0, "cause": "neutral"})
    side = "L" if victim.endswith("-3") else "R"
    fend = min(onset + rng.uniform(13, 19) * 60, end)
    regimes.append({"start": onset, "end": fend, "team": other(victim_team), "strength": round(rng.uniform(0.6, 0.85), 2),
                    "cause": "fatigue", "victim": victim, "channel_team": victim_team, "channel_side": side})
    if fend < end:
        regimes.append({"start": fend, "end": end, "team": None, "strength": 0.0, "cause": "neutral"})
    return regimes, victim, onset


def generate(seed: int = 11, minutes: int = 90, with_truth: bool = False):
    rng = random.Random(seed)
    players = {t: roster(t, rng) for t in CLUBS}
    by_id = {p["id"]: p for t in players.values() for p in t}
    regimes, victim, onset = build_regimes(rng, minutes)
    events, eid, t = [], 0, 0.0
    poss, ball = HOME, [52.5, 34.0]
    end = minutes * 60

    def regime_at(tt):
        for r in regimes:
            if r["start"] <= tt < r["end"]:
                return r
        return regimes[-1]

    def dominance(tt):  # +ve favours HOME
        r = regime_at(tt)
        if not r["team"]:
            return 0.0
        ramp = min(1.0, (tt - r["start"]) / 120)  # regimes build over ~2 minutes
        return r["strength"] * ramp * (1 if r["team"] == HOME else -1)

    def fatigue(pid, tt):
        p = by_id[pid]
        f = p["fatigue_rate"] * tt / end
        if pid == victim and tt > onset:
            f += min(0.45, 0.45 * (tt - onset) / 480)
        return min(f, 0.9)

    def ev(**kw):
        nonlocal eid
        eid += 1
        events.append({"id": eid, "t": round(t, 2), "minute": int(t // 60), "possession": poss, **kw})

    def pick(team, y, exclude=None):
        cands = [p for p in players[team] if p["role"] != "GK" and p["id"] != exclude]
        w = [math.exp(-abs(lane_y(team, p["side"]) - y) / 14) for p in cands]
        return rng.choices(cands, w)[0]

    def change(reason, x, y):
        nonlocal poss
        old, poss = poss, other(poss)
        ev(type="possession_change", team=poss, from_team=old, reason=reason, x=round(x, 1), y=round(y, 1))
        if reason in ("interception", "tackle"):
            # off-ball recovery sprint by the team that just lost the ball (tracking-derived event)
            runner = pick(old, y)
            back = -1 if old == HOME else 1
            dist = rng.uniform(8, 22)
            sp = runner["base_speed"] * 1.05 * (1 - 0.55 * fatigue(runner["id"], t)) * rng.uniform(0.92, 1.08)
            rx = lane_y(old, runner["side"])
            sx = min(max(x + rng.uniform(-8, 8), 1), PITCH_X - 1)
            ex = min(max(sx + back * dist, 1), PITCH_X - 1)
            ev(type="run", player=runner["id"], team=old, x=round(sx, 1), y=round(rx, 1), end_x=round(ex, 1), end_y=round(rx, 1),
               duration=round(max(abs(ex - sx), 1) / sp, 2), intent="recovery")

    ev(type="metadata", phase="kickoff", home=HOME, away=AWAY,
       clubs={k: v["name"] for k, v in CLUBS.items()}, shorts={k: v["short"] for k, v in CLUBS.items()},
       colors={k: v["color"] for k, v in CLUBS.items()},
       players={k: [{kk: p[kk] for kk in ("id", "name", "team", "number", "role", "side")} for p in v] for k, v in players.items()},
       venue="Fernhill Park (fictional)", seed=seed)
    half_done = False
    while True:
        d = dominance(t)
        t += rng.expovariate(1 / (3.7 * (1 - 0.2 * abs(d))))
        if t >= end:
            break
        if not half_done and t >= end / 2:
            half_done = True
            ev(type="metadata", phase="half_time")
        d = dominance(t)
        r = regime_at(t)
        att, dfn = poss, other(poss)
        m = d if att == HOME else -d  # attacking team's momentum
        dirx = 1 if att == HOME else -1
        x0, y0 = ball
        actor = pick(att, y0)
        in_final = (x0 > 70) if dirx == 1 else (x0 < 35)
        fat_pen = 0.0
        if r.get("cause") == "fatigue" and actor["id"] == victim:
            fat_pen = fatigue(victim, t) * 0.5
        weights = {"pass": 6.0, "carry": 1.3, "pressure": 1.8 * (1 + 1.6 * max(-m, 0)), "tackle": 0.8 * (1 + 1.2 * max(-m, 0))}
        kind = rng.choices(list(weights), list(weights.values()))[0]
        if in_final and rng.random() < 0.022 + 0.08 * max(m, 0):
            kind = "shot"
        if kind == "pass":
            # where does the attack go? toward the regime channel when the dominant team attacks
            target_y = lane_y(att, actor["side"]) if rng.random() < 0.5 else 34.0
            if r.get("team") == att and r.get("cause") == "fatigue":
                target_y = lane_y(r["channel_team"], r["channel_side"])
            elif r.get("team") == att and r.get("channel"):
                target_y = lane_y(att, r["channel"])
            dist = abs(rng.gauss(15 + 4 * max(m, 0), 8)) + 3
            fwd = dist * (0.55 + 0.25 * m) * dirx + rng.gauss(0, 6)
            dy = (target_y - y0) * 0.45 + rng.gauss(0, 7)
            x1 = min(max(x0 + fwd, 0.5), PITCH_X - 0.5)
            y1 = min(max(y0 + dy, 0.5), PITCH_Y - 0.5)
            dist = math.hypot(x1 - x0, y1 - y0)
            pressured = rng.random() < 0.22 + 0.3 * max(-m, 0)
            p_ok = 0.87 - dist / 150 - 0.12 * pressured + 0.09 * m - fat_pen
            ok = rng.random() < p_ok
            recv = pick(att, y1, exclude=actor["id"])
            dur = max(dist / rng.uniform(11, 21), 0.3)
            ev(type="pass", player=actor["id"], team=att, receiver=recv["id"] if ok else None,
               x=round(x0, 1), y=round(y0, 1), end_x=round(x1, 1), end_y=round(y1, 1),
               duration=round(dur, 2), outcome="complete" if ok else "incomplete", under_pressure=pressured)
            ball = [x1, y1]
            if not ok:
                t += 0.4
                change("interception", x1, y1)
        elif kind == "carry":
            dist = rng.uniform(5, 24)
            sp = actor["base_speed"] * (1 - 0.55 * fatigue(actor["id"], t)) * rng.uniform(0.85, 1.12)
            x1 = min(max(x0 + dirx * dist, 0.5), PITCH_X - 0.5)
            y1 = min(max(y0 + rng.gauss(0, 4), 0.5), PITCH_Y - 0.5)
            ev(type="carry", player=actor["id"], team=att, x=round(x0, 1), y=round(y0, 1),
               end_x=round(x1, 1), end_y=round(y1, 1), duration=round(math.hypot(x1 - x0, y1 - y0) / sp, 2))
            ball = [x1, y1]
        elif kind == "pressure":
            presser = pick(dfn, y0)
            ev(type="pressure", player=presser["id"], team=dfn, target=actor["id"], x=round(x0, 1), y=round(y0, 1),
               intensity=round(min(1.0, rng.uniform(0.2, 0.75) + 0.3 * max(-m, 0)), 2))
        elif kind == "tackle":
            tackler = pick(dfn, y0)
            won = rng.random() < 0.5 + 0.2 * max(-m, 0) - 0.1 * max(m, 0) + (fat_pen if actor["id"] == victim else 0)
            ev(type="tackle", player=tackler["id"], team=dfn, target=actor["id"], x=round(x0, 1), y=round(y0, 1),
               outcome="won" if won else "lost")
            if won:
                change("tackle", x0, y0)
        else:  # shot
            gx = PITCH_X if dirx == 1 else 0.0
            sx = gx - dirx * rng.uniform(6, 28)
            sy = rng.uniform(20, 48)
            dgoal = math.hypot(gx - sx, 34 - sy)
            xg = round(max(0.02, min(0.6, 0.75 * math.exp(-dgoal / 8) * (1 + 0.6 * max(m, 0)))), 3)
            speed = round(rng.uniform(55, 122), 1)
            u = rng.random()
            outcome = "goal" if u < xg else ("saved" if u < xg + 0.33 else ("blocked" if u < xg + 0.55 else "off_target"))
            ev(type="shot", player=actor["id"], team=att, x=round(sx, 1), y=round(sy, 1), end_x=gx, end_y=34.0,
               speed_kmh=speed, xg=xg, outcome=outcome)
            ball = [52.5, 34.0] if outcome == "goal" else [gx - dirx * 6, 34.0]
            change("kickoff" if outcome == "goal" else "goal_kick", *ball)
    t = max(float(end), t)
    ev(type="metadata", phase="full_time")
    if with_truth:
        return events, {"seed": seed, "regimes": regimes, "fatigue_victim": victim, "fatigue_onset_s": round(onset, 1)}
    return events


def write_jsonl(events, path, truth=None):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    if truth:
        p.with_suffix(".truth.json").write_text(json.dumps(truth, indent=1))
    return p


def main():
    ap = argparse.ArgumentParser(description="Generate a synthetic match (JSONL)")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--minutes", type=int, default=90)
    ap.add_argument("--out", default="data/match.jsonl")
    a = ap.parse_args()
    ev, truth = generate(a.seed, a.minutes, with_truth=True)
    write_jsonl(ev, a.out, truth)
    goals = [e for e in ev if e["type"] == "shot" and e["outcome"] == "goal"]
    print(f"wrote {len(ev)} events, {len(goals)} goals to {a.out} (+ truth sidecar)")


if __name__ == "__main__":
    main()
