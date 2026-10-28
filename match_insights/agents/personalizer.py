"""PersonalizerAgent: one broadcast, many viewers. Adapts depth, focus and language."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from ..i18n import metric as metric_name, t


@dataclass
class Profile:
    persona: str = "casual"       # "casual" | "analyst"
    club: str | None = None       # favourite club code
    player: str | None = None     # focus-mode player id
    lang: str = "en"
    pundit: str | None = None     # preferred pundit key

    def dict(self):
        return asdict(self)


class PersonalizerAgent:
    name = "personalizer"
    role = "Re-rank and rewrite each candidate overlay for this viewer"

    def run(self, candidates, e, state, profile: Profile):
        out = []
        for c in candidates:
            c = dict(c)
            p = c["priority"]
            team, players = c.get("team"), c.get("players", [])
            if profile.club and team == profile.club:
                p += 0.1
                c["highlight"] = "club"
            if profile.player and profile.player in players:
                p += 0.35
                c["highlight"] = "focus"
            if c["kind"] == "signal":
                s = c["signal"]
                club = state.club(s["momentum_to"])
                c["title"] = t("signal", profile.lang, club=club)
                if profile.persona == "analyst":
                    short = state.meta.get("shorts", {}).get(s["team"], s["team"])
                    c["subtitle"] = f"{short} · " + t("signal_sub", profile.lang, metric=metric_name(s["metric"], profile.lang), rule=s["rule"]) + \
                        f" · {s['x']}{s['unit']} vs CL {s['cl']} [{s['lcl']}, {s['ucl']}] · z={s['z']}"
                    p += 0.1
                else:
                    good = profile.club in (None, s["momentum_to"])
                    c["subtitle"] = ("🔥 " if good else "⚠️ ") + metric_name(s["metric"], profile.lang)
            if c["kind"] == "narration" and profile.persona == "casual" and not set(c.get("tags", [])) & {"goal", "big_chance", "sprint", "rocket", "turnover"}:
                p -= 0.15
            if c["kind"] == "narration" and profile.persona == "analyst":
                c["detail"] = c.get("metrics")
            c["priority"] = round(max(0.0, min(1.0, p)), 2)
            out.append(c)
        return out

    def focus_card(self, state, pid):
        s = state.player.get(pid)
        if not s:
            return None
        recent = [v for tt, v in s["carries"] if tt >= state.clock - 900]
        early = [v for tt, v in s["carries"] if tt < 1800]
        return {"player": pid, "name": state.pname(pid), "role": state.players.get(pid, {}).get("role"),
                "team": state.players.get(pid, {}).get("team"), "touches": s["touches"], "passes": s["passes"],
                "pass_acc": round(100 * s["passes_ok"] / s["passes"]) if s["passes"] else None,
                "dist_m": round(s["dist_m"]), "top_kmh": round(s["top_kmh"], 1), "pressed": s["pressed"], "lost": s["lost"],
                "recent_kmh": round(sum(recent) / len(recent), 1) if recent else None,
                "early_kmh": round(sum(early) / len(early), 1) if early else None}
