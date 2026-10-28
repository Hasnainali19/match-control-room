"""Chaos engineering: inject agent failures to demonstrate recovery (retry, fallback, deferral)."""
from __future__ import annotations
import random


class InjectedFault(RuntimeError):
    pass


class FaultInjector:
    KINDS = ("timeout", "exception", "malformed output", "rate limited (429)")

    def __init__(self, rate: float = 0.0, seed: int = 0, targets: set | None = None):
        self.rate = rate
        self.rng = random.Random(seed)
        self.targets = targets
        self.injected = 0

    def maybe_fail(self, agent: str):
        if self.rate <= 0 or agent == "ingest":
            return
        if self.targets and agent.split(".")[0] not in self.targets:
            return
        if self.rng.random() < self.rate:
            self.injected += 1
            raise InjectedFault(f"simulated {self.rng.choice(self.KINDS)} in {agent}")
