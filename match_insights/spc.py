"""Statistical Process Control primitives: EWMA charts and Western Electric / Nelson rules.

Pure functions, no match knowledge: these are the same rules used on an automotive line.
"""
from __future__ import annotations
import math
from statistics import mean, pstdev

RULES = {
    "WE1": "1 point beyond 3σ",
    "WE2": "2 of 3 beyond 2σ (same side)",
    "WE3": "4 of 5 beyond 1σ (same side)",
    "WE4": "8 in a row on one side of centre",
    "N3": "6 points steadily trending",
    "EWMA": "EWMA beyond control limit",
}


def baseline(values, min_n=5, sigma_floor=1e-6):
    """Return (mean, sigma) of a baseline sample, or None if too short."""
    v = [x for x in values if x is not None]
    if len(v) < min_n:
        return None
    return mean(v), max(pstdev(v), sigma_floor)


def ewma_limits(mu, sigma, lam, i, L=2.7):
    """Exact time-varying EWMA limits for the i-th (1-based) point."""
    w = sigma * L * math.sqrt(lam / (2 - lam) * (1 - (1 - lam) ** (2 * i)))
    return mu - w, mu + w


def check_rules(z, ewma_z=None):
    """Evaluate run rules on a z-score history (newest last). Returns [(rule, direction)].

    direction is +1 (shift up) or -1 (shift down). Each rule requires the newest point
    to participate, so a rule fires when the condition first becomes true.
    """
    out = []
    if not z:
        return out
    last = z[-1]
    sgn = 1 if last > 0 else -1
    if abs(last) > 3:
        out.append(("WE1", sgn))
    l3 = z[-3:]
    if len(l3) == 3 and abs(last) > 2 and sum(1 for v in l3 if v * sgn > 2) >= 2:
        out.append(("WE2", sgn))
    l5 = z[-5:]
    if len(l5) == 5 and abs(last) > 1 and sum(1 for v in l5 if v * sgn > 1) >= 4:
        out.append(("WE3", sgn))
    l8 = z[-8:]
    if len(l8) == 8 and all(v * sgn > 0 for v in l8):
        out.append(("WE4", sgn))
    l6 = z[-6:]
    if len(l6) == 6:
        if all(b > a for a, b in zip(l6, l6[1:])):
            out.append(("N3", 1))
        elif all(b < a for a, b in zip(l6, l6[1:])):
            out.append(("N3", -1))
    if ewma_z is not None and abs(ewma_z) > 1:  # ewma_z is EWMA scaled to its own limit (|.|>1 => beyond)
        out.append(("EWMA", 1 if ewma_z > 0 else -1))
    return out
