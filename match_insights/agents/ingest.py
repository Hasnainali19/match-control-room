"""IngestAgent: validates raw events, normalises them and owns the match clock and score."""
from __future__ import annotations

REQUIRED = {"id", "t", "type"}
VALID = {"metadata", "pass", "shot", "tackle", "pressure", "carry", "run", "possession_change"}
COORD = {"pass", "shot", "tackle", "pressure", "carry", "run", "possession_change"}


class IngestAgent:
    name = "ingest"
    role = "Validate the live feed, keep the clock, possession and score"

    def run(self, e: dict, state):
        if not isinstance(e, dict) or not REQUIRED <= e.keys() or e["type"] not in VALID:
            raise ValueError(f"invalid event: {str(e)[:120]}")
        if e["t"] + 1e-6 < state.clock:
            raise ValueError(f"out-of-order event {e['id']} at {e['t']} < {state.clock}")
        if e["type"] in COORD and not (0 <= e.get("x", -1) <= 105 and 0 <= e.get("y", -1) <= 68):
            raise ValueError(f"event {e['id']} has coordinates off the pitch")
        if e["type"] == "metadata" and "players" in e:
            state.meta = e
            for team in e["players"].values():
                for p in team:
                    state.players[p["id"]] = p
            state.current_possession = e.get("home")
        if state.current_possession:
            state.possession_time[state.current_possession] += max(0.0, e["t"] - state.last_poss_t)
        state.last_poss_t = e["t"]
        if e["type"] == "possession_change":
            state.current_possession = e["team"]
        if e["type"] == "shot" and e.get("outcome") == "goal":
            state.score[e["team"]] = state.score.get(e["team"], 0) + 1
            state.goals.append({"t": e["t"], "team": e["team"], "player": e["player"], "event_id": e["id"]})
        state.clock = e["t"]
        state.recent.append(e)
        return e
