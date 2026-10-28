"""RefereeAgent (fact-checker): verifies every numeric claim against the shared state.

Verdicts per take:
  verified  - all claims match the facts (within tolerance)
  corrected - a claim was wrong; the number in the text is replaced with the true value
  rejected  - a claim cites a fact that does not exist
  flagged   - the text contains numbers that are not backed by any claim (possible hallucination)
"""
from __future__ import annotations
import re

NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")


def tolerance(key: str, true):
    if key.startswith(("possession.", "pass_acc.", "chart.")) and "difficulty" not in key:
        return 2.0
    if key.startswith("xg.") or "difficulty" in key:
        return 0.06
    if key.startswith(("score.", "shots.", "minute")):
        return 0
    return abs(true) * 0.05


def fmt(v):
    return str(round(v, 2)) if isinstance(v, float) and not float(v).is_integer() else str(int(round(v)))


class RefereeAgent:
    name = "referee"
    role = "Fact-check every number pundits and analysts put on screen"

    def check(self, item: dict, facts: dict) -> dict:
        text = item.get("text", "")
        results, verdict = [], "verified"
        for c in item.get("claims", []):
            key, claimed = c.get("key"), c.get("value")
            if key not in facts or not isinstance(claimed, (int, float)):
                results.append({**c, "status": "rejected", "reason": "unknown fact"})
                verdict = "rejected"
                continue
            true = facts[key]
            if abs(true - claimed) <= tolerance(key, true):
                results.append({**c, "status": "verified", "true": true})
            else:
                shown = str(c.get("shown", claimed))
                if shown in text:
                    text = text.replace(shown, fmt(true), 1)
                results.append({**c, "status": "corrected", "true": true, "was": claimed})
                if verdict == "verified":
                    verdict = "corrected"
        backed = {str(c.get("shown", c.get("value"))) for c in item.get("claims", [])} | {fmt(r["true"]) for r in results if "true" in r}
        stray = [n for n in NUM.findall(text) if n not in backed]
        if stray and verdict in ("verified", "corrected"):
            verdict = "flagged"
        return {**item, "text": text, "original_text": item.get("text"), "verdict": verdict, "checks": results, "unbacked_numbers": stray}

    def run(self, items, facts):
        return [self.check(i, facts) for i in items]
