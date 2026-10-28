"""ProducerAgent: the broadcast director. Decides what goes on air, when, and for how long.

Rate-limits the lower third, lets urgent items pre-empt, queues the rest, sends minor items
to the ticker and picks the featured pundit (viewer choice > vote leader > best verified).
"""
from __future__ import annotations

ON_AIR_VERDICTS = ("verified", "corrected")
EDITORIAL = {"signal": "alert", "whys": "whys", "panel": "panel"}
DURATION = {"goal": 14, "signal": 12, "whys": 16, "panel": 14, "narration": 6}


class ProducerAgent:
    name = "producer"
    role = "Direct the broadcast: rate-limit, prioritise and compose the on-screen overlay"

    def __init__(self, gap_s=40.0):
        self.gap_s = gap_s
        self.slot_until = -1.0
        self.slot_priority = 0.0
        self.queue = []

    def pick_pundit(self, takes, preferred=None, votes=None):
        ok = [x for x in takes if x["verdict"] in ON_AIR_VERDICTS]
        if not ok:
            return None
        if preferred:
            for x in ok:
                if x["pundit"] == preferred:
                    return x["pundit"]
        if votes and any(votes.values()):
            for k in sorted(votes, key=votes.get, reverse=True):
                if any(x["pundit"] == k for x in ok):
                    return k
        order = {"verified": 0, "corrected": 1}
        return sorted(ok, key=lambda x: order[x["verdict"]])[0]["pundit"]

    def run(self, candidates, now, state):
        decisions = []
        self.queue = [c for c in self.queue if now - c["t"] <= 90]
        for c in sorted(candidates, key=lambda c: -c["priority"]):
            free = now >= self.slot_until
            if c["kind"] in EDITORIAL:
                decisions.append({"channel": EDITORIAL[c["kind"]], "item": c,
                                  "display": {"start_s": now, "duration_s": DURATION[c["kind"]]}})
                continue
            if c["priority"] < 0.25:
                if c["priority"] >= 0.1 and c.get("text"):
                    decisions.append({"channel": "ticker", "item": c})
                continue
            if free or c["priority"] >= self.slot_priority + 0.25:
                dur = DURATION.get(c["kind"], 6) * (1.5 if c["priority"] >= 0.9 else 1)
                self.slot_until, self.slot_priority = now + max(dur, self.gap_s if c["priority"] < 0.9 else dur), c["priority"]
                decisions.append({"channel": "lower_third", "item": c, "display": {"start_s": now, "duration_s": dur}})
            elif c["priority"] >= 0.45:
                self.queue.append(c)
                self.queue = sorted(self.queue, key=lambda c: -c["priority"])[:3]
            elif c.get("text"):
                decisions.append({"channel": "ticker", "item": c})
        if now >= self.slot_until and self.queue and not any(d["channel"] == "lower_third" for d in decisions):
            c = self.queue.pop(0)
            dur = DURATION.get(c["kind"], 6)
            self.slot_until, self.slot_priority = now + max(dur, self.gap_s), c["priority"]
            decisions.append({"channel": "lower_third", "item": c, "display": {"start_s": now, "duration_s": dur}, "from_queue": True})
        state.on_air.extend(d for d in decisions if d["channel"] == "lower_third")
        return decisions

    def fallback(self, candidates, now):
        """Degraded mode: air only the single most important candidate."""
        if not candidates:
            return []
        c = max(candidates, key=lambda c: c["priority"])
        return [{"channel": "lower_third", "item": c, "display": {"start_s": now, "duration_s": 6}, "degraded": True}]
