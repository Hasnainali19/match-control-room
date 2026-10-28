"""TacticsAgent: explains WHY an individual moment matters (control vs chaos, pressure, rhythm)."""
from __future__ import annotations


class TacticsAgent:
    name = "tactics"
    role = "Classify the phase of play and score how much this moment matters"

    def run(self, e, stats, state):
        recent = list(state.recent)[-20:]
        changes = sum(1 for r in recent if r["type"] == "possession_change")
        passes = [r for r in recent if r["type"] == "pass"]
        comp = sum(r["outcome"] == "complete" for r in passes) / len(passes) if passes else 1
        chaos = round(min(1.0, changes / 6 * 0.6 + (1 - comp) * 0.4), 2)
        press = {}
        for p in recent:
            if p["type"] == "pressure":
                press[p["team"]] = press.get(p["team"], 0) + p["intensity"]
        gaps = [b["t"] - a["t"] for a, b in zip(recent, recent[1:])]
        tempo = round(len(gaps) / sum(gaps), 2) if gaps and sum(gaps) > 0 else 0.0
        reasons = []
        tags = stats["tags"]
        if "goal" in tags:
            reasons.append("goal changes the game state")
        if "big_chance" in tags:
            reasons.append(f"big chance ({stats.get('xg')} xG)")
        if "turnover" in tags:
            reasons.append("turnover flips the attack")
        if "high_press" in tags:
            reasons.append("intense press forcing a decision")
        if "hard_pass" in tags:
            reasons.append("difficult pass completed")
        if "rocket" in tags:
            reasons.append("shot struck with exceptional pace")
        if "sprint" in tags:
            reasons.append("burst of pace breaks the line")
        imp = 0.12 * len(reasons) + (0.75 if "goal" in tags else 0) + (0.3 if e["type"] == "shot" else 0)
        return {"phase": "chaos" if chaos >= 0.5 else "control", "chaos_index": chaos, "tempo_events_per_s": tempo,
                "pressing_team": max(press, key=press.get) if press else None, "reasons": reasons,
                "importance": round(min(1.0, imp), 2)}
