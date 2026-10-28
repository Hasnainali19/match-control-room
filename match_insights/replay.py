"""CLI: replay a JSONL match through the agent graph; prints broadcast messages as JSONL."""
import argparse, json, sys
from collections import Counter
from .agents.personalizer import Profile
from .faults import FaultInjector
from .orchestrator import Orchestrator

BROADCAST = {"lower_third", "alert", "whys", "panel", "ticker", "focus", "phase"}


def main():
    import logging
    logging.basicConfig(level=logging.ERROR)
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--persona", default="casual")
    ap.add_argument("--club"); ap.add_argument("--player"); ap.add_argument("--pundit")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--fault-rate", type=float, default=0.0)
    ap.add_argument("--types", default=",".join(sorted(BROADCAST)))
    a = ap.parse_args()
    orch = Orchestrator(Profile(a.persona, a.club, a.player, a.lang, a.pundit), faults=FaultInjector(a.fault_rate, seed=1))
    want, counts, status = set(a.types.split(",")), Counter(), Counter()
    for line in open(a.path):
        for m in orch.process(json.loads(line)):
            counts[m["type"]] += 1
            if m["type"] == "trace":
                status.update(s["status"] for s in m["data"])
            if m["type"] in want:
                sys.stdout.write(json.dumps(m, ensure_ascii=False) + "\n")
    st = orch.state
    print(f"# score={st.score} signals={len(st.signals)} analyses={len(st.analyses)} takes={len(st.takes)} "
          f"verdicts={dict(Counter(t['verdict'] for t in st.takes))} messages={dict(counts)} spans={dict(status)} "
          f"injected_faults={orch.faults.injected}", file=sys.stderr)


if __name__ == "__main__":
    main()
