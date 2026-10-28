"""NarratorAgent: short live commentary lines in the fan's language.

Offline: phrase tables (5 languages). Online: Azure OpenAI writes and translates (any language).
"""
from __future__ import annotations
from ..i18n import LANGS, OFFLINE_LANGS, t
from ..llm import LLMUnavailable


class NarratorAgent:
    name = "narrator"
    role = "Write broadcast commentary in the viewer's language"

    def template(self, e, stats, state, lang="en"):
        lang = lang if lang in OFFLINE_LANGS else "en"
        key = "goal" if "goal" in stats["tags"] else e["type"]
        if key not in ("goal", "shot", "pass", "carry", "tackle", "pressure"):
            return ""
        return t(key, lang, player=state.pname(e.get("player")), club=state.club(e.get("team")),
                 speed=stats.get("player_speed_kmh", ""), dist=stats.get("distance_m", ""),
                 outcome=t(f"outcome.{e.get('outcome', 'goal')}", lang))

    def run(self, e, stats, tactics, state, llm=None, lang="en"):
        base = self.template(e, stats, state, lang)
        wants_llm = llm is not None and llm.online and (tactics["importance"] >= 0.5 or lang not in OFFLINE_LANGS)
        if not wants_llm:
            return base, "template"
        try:
            text = llm.complete(
                f"You are a vivid but factual live football commentator. Reply in {LANGS.get(lang, 'English')}, max 20 words. "
                "Teams and players are fictional. Only use numbers given to you.",
                f"Event: {self.template(e, stats, state, 'en')}. Stats: {stats}. Why it matters: {tactics['reasons']}.", 80)
            return text or base, "llm"
        except LLMUnavailable:
            return base, "template"
