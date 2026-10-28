"""Validate Control-agent signals against hidden ground truth across many seeds.

Measures (1) detection of latent momentum regimes, (2) false alarms, and (3) whether
signals precede goals (lead time) compared with a random-timing baseline.
"""
from __future__ import annotations
import argparse, json, random, statistics as st
from .generator import generate
from .state import MatchState
from .agents.ingest import IngestAgent
from .agents.stats import StatsAgent
from .agents.control import ControlAgent
from .agents.root_cause import RootCauseAgent

HORIZON = 10 * 60


def run_seed(seed, subgroup_s=90.0):
    ev, truth = generate(seed, with_truth=True)
    s, I, S, C, R = MatchState(), IngestAgent(), StatsAgent(), ControlAgent(subgroup_s), RootCauseAgent()
    last = {}
    for e in ev:
        I.run(e, s); S.run(e, s)
        for sig in C.run(e, s)["signals"]:  # same RCA trigger policy as the orchestrator
            if sig["swing"] and sig["t"] - last.get(sig["momentum_to"], -1e9) >= 300:
                last[sig["momentum_to"]] = sig["t"]
                R.run(sig, s)
    return s, truth


def score_seed(s, truth, swing_only=True, rng=None):
    sig = [x for x in s.signals if x["swing"] or not swing_only]
    regs = [r for r in truth["regimes"] if r["team"]]
    det = []
    for r in regs:
        hits = [x for x in sig if x["momentum_to"] == r["team"] and r["start"] <= x["t"] <= r["end"] + 60]
        det.append({"cause": r["cause"], "detected": bool(hits), "delay_s": (hits[0]["t"] - r["start"]) if hits else None})
    false = [x for x in sig if not any(r["team"] == x["momentum_to"] and r["start"] <= x["t"] <= r["end"] + 180 for r in regs)]

    def goal_hits(times):
        out = []
        for g in s.goals:
            prior = [t for t, team in times if team == g["team"] and g["t"] - HORIZON <= t < g["t"]]
            out.append(g["t"] - max(prior) if prior else None)
        return out
    def followed(times):
        return [any(g["team"] == team and t < g["t"] <= t + HORIZON for g in s.goals) for t, team in times]
    fol = followed([(x["t"], x["momentum_to"]) for x in sig])
    rand_fol = followed([(rng.uniform(600, 5400), rng.choice(["HAR", "MIL"])) for _ in range(300)]) if rng else []
    leads = goal_hits([(x["t"], x["momentum_to"]) for x in sig])
    rand_hits = []
    if rng and sig:
        for _ in range(50):
            fake = [(rng.uniform(600, 5400), x["momentum_to"]) for x in sig]
            rand_hits += [h is not None for h in goal_hits(fake)]
    fr = [r for r in regs if r["cause"] == "fatigue"][0]
    rca = [a for a in s.analyses if fr["start"] <= a["t"] <= fr["end"] + 60 and a["team_in_control"] == fr["team"]]
    rca_eval = {"analysed": bool(rca), "named_victim": any(a["player"] == truth["fatigue_victim"] for a in rca),
                "fatigue_cause": any(a["player"] == truth["fatigue_victim"] and a["cause"] == "fatigue" for a in rca),
                "false_fatigue": sum(1 for a in s.analyses if a["cause"] == "fatigue" and not (fr["start"] <= a["t"] <= fr["end"] + 60))}
    return {"rca": rca_eval, "regimes": det, "false_alarms": len(false), "signals": len(sig), "goal_leads": leads, "rand_hits": rand_hits, "followed": fol, "rand_followed": rand_fol}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--subgroup", type=float, default=90.0)
    ap.add_argument("--all-signals", action="store_true")
    ap.add_argument("--out", default="docs/validation.json")
    a = ap.parse_args()
    rng = random.Random(0)
    rcas = []
    det, fat, delays, fa, nsig, leads, rh, fol, rfol = [], [], [], [], [], [], [], [], []
    for seed in range(1, a.seeds + 1):
        s, tr = run_seed(seed, a.subgroup)
        r = score_seed(s, tr, not a.all_signals, rng)
        det += [d["detected"] for d in r["regimes"]]
        fat += [d["detected"] for d in r["regimes"] if d["cause"] == "fatigue"]
        delays += [d["delay_s"] for d in r["regimes"] if d["delay_s"] is not None]
        fa.append(r["false_alarms"]); nsig.append(r["signals"]); leads += r["goal_leads"]; rh += r["rand_hits"]
        rcas.append(r["rca"])
        fol += r["followed"]; rfol += r["rand_followed"]
    hit = [x for x in leads if x is not None]
    res = {
        "seeds": a.seeds, "subgroup_s": a.subgroup, "signal_type": "all" if a.all_signals else "swing (>=2 metrics agree)",
        "regime_detection_rate": round(sum(det) / len(det), 3), "fatigue_regime_detection_rate": round(sum(fat) / len(fat), 3),
        "median_detection_delay_min": round(st.median(delays) / 60, 1) if delays else None,
        "signals_per_match": round(st.mean(nsig), 1), "false_alarms_per_match": round(st.mean(fa), 1),
        "precision": round(1 - sum(fa) / max(sum(nsig), 1), 3),
        "p_goal_within_10min_after_signal": round(sum(fol) / max(len(fol), 1), 3),
        "p_goal_within_10min_random_time": round(sum(rfol) / max(len(rfol), 1), 3),
        "lift": round((sum(fol) / max(len(fol), 1)) / max(sum(rfol) / max(len(rfol), 1), 1e-9), 2),
        "rca_fatigue_spell_analysed": round(sum(x["analysed"] for x in rcas) / len(rcas), 3),
        "rca_named_true_fatigued_player": round(sum(x["named_victim"] for x in rcas) / len(rcas), 3),
        "rca_named_player_and_fatigue_cause": round(sum(x["fatigue_cause"] for x in rcas) / len(rcas), 3),
        "rca_false_fatigue_diagnoses_per_match": round(sum(x["false_fatigue"] for x in rcas) / len(rcas), 2),
        "goals": len(leads), "goals_preceded_by_signal_10min": round(len(hit) / len(leads), 3),
        "goals_preceded_random_timing_baseline": round(sum(rh) / len(rh), 3) if rh else None,
        "median_lead_time_min": round(st.median(hit) / 60, 1) if hit else None,
    }
    print(json.dumps(res, indent=1))
    if a.out:
        from pathlib import Path
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
