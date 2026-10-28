"""Pundit Panel: four specialist agents with distinct voices and biases.

Each pundit returns a take: free text plus *structured claims* ({key, value, shown}) that
reference fact keys on the shared state. Offline, takes come from templates; the Ex-Pro
and the Superfan occasionally misremember numbers (deterministic, seeded) so the Referee's
fact-checking is visible in the demo. Online, Azure OpenAI writes the takes in JSON mode.
"""
from __future__ import annotations
import hashlib
from ..i18n import LANGS
from ..llm import LLMUnavailable

PUNDITS = {
    "tactician": {"name": "Inés Varga", "title": "Tactician", "initials": "IV", "bias": None, "fib": 0.0,
                  "style": "precise, structural, talks about shape, lanes and pressing triggers"},
    "analyst": {"name": "Dr. Priya Nair", "title": "Data Analyst", "initials": "PN", "bias": None, "fib": 0.0,
                "style": "numbers-first, cites xG, possession and control-chart signals, cautious"},
    "expro": {"name": "Den Okoro", "title": "Ex-Pro", "initials": "DO", "bias": None, "fib": 0.4,
              "style": "former midfielder, gut feel, dressing-room stories, rounds numbers up"},
    "superfan": {"name": "Kaz", "title": "Club Superfan", "initials": "KZ", "bias": "fan", "fib": 0.35,
                 "style": "passionate, one-eyed supporter of the viewer's club, exaggerates good news"},
}

TPL = {
    "tactician": {
        "signal": {"en": "Structural shift: {G} are overloading {L}'s {lane} — {Gs} field tilt is at {tilt}%.",
                   "es": "Cambio estructural: {G} sobrecarga a {L} ({lane}); dominio territorial del {tilt}%.",
                   "fr": "Bascule structurelle : {G} surcharge {L} ({lane}), domination territoriale à {tilt}%."},
        "goal": {"en": "Patient build-up rewarded: {S} completing {acc}% of passes, then one decisive action.",
                 "es": "Premio a la paciencia: {S} acierta el {acc}% de sus pases y golpea.",
                 "fr": "La patience paie : {S} réussit {acc}% de ses passes, puis frappe."}},
    "analyst": {
        "signal": {"en": "The control chart called it: {Gs} xG {xg} vs {Ls} {xgl}, and {pos}% of the ball for {G}.",
                   "es": "El gráfico de control lo anticipó: xG {Gs} {xg} contra {Ls} {xgl}, y {pos}% de posesión.",
                   "fr": "La carte de contrôle l'avait vu : xG {Gs} {xg} contre {Ls} {xgl}, {pos}% de possession."},
        "goal": {"en": "{S} now on {xg} xG from {shots} shots — the scoreline is broadly fair.",
                 "es": "{S} suma {xg} xG en {shots} tiros: el marcador es justo.",
                 "fr": "{S} à {xg} xG sur {shots} tirs : le score est logique."}},
    "expro": {
        "signal": {"en": "I've been that player — when your legs go, you're done. {G} have had {pos}% of the ball, it's one-way traffic.",
                   "es": "Yo he estado ahí: cuando no hay piernas, se acabó. {G} tiene el {pos}% del balón.",
                   "fr": "J'ai connu ça : quand les jambes lâchent, c'est fini. {G} a {pos}% du ballon."},
        "goal": {"en": "Coming all game! {S} have had {shots} shots — you knew one would go in.",
                 "es": "¡Se veía venir! {S} lleva {shots} tiros.",
                 "fr": "Ça devait arriver ! {S} a tenté {shots} tirs."}},
    "superfan": {
        "signal": {"en": "{F} FOREVER! We've had {fpos}% of the ball — we'll bounce back!",
                   "es": "¡{F} PARA SIEMPRE! ¡Tenemos el {fpos}% del balón!",
                   "fr": "{F} POUR TOUJOURS ! On a {fpos}% du ballon !"},
        "goal": {"en": "{F}! {fshots} shots and still going — I'm not sitting down!",
                 "es": "¡{F}! ¡{fshots} tiros y seguimos!",
                 "fr": "{F} ! {fshots} tirs, on continue !"}},
}


def _det(seed: str) -> float:
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def other(t):
    return "MIL" if t == "HAR" else "HAR"


class PunditAgent:
    def __init__(self, key):
        self.key = key
        self.name = f"pundit.{key}"
        self.profile = PUNDITS[key]
        self.role = f"{self.profile['title']}: {self.profile['style']}"

    def _fib(self, value, trigger_id, field):
        """Deterministic 'misremembering' (offline demo of hallucination + fact-check)."""
        if self.profile["fib"] and _det(f"{self.key}{trigger_id}{field}") < self.profile["fib"]:
            if isinstance(value, float) and value < 10:
                return round(value * 1.6 + 0.3, 2)
            return min(int(round(value * 1.25 + 4)), 99)
        return value

    def template(self, trigger, facts, state, fan_club, lang):
        kind = trigger["kind"]
        G = trigger["team"]
        Lt = other(G)
        F = fan_club or G
        tid = trigger["id"]
        lane = trigger.get("lane_name", "")
        vals, claims = {}, []

        def claim(name, key, fib=True):
            v = facts.get(key, 0)
            shown_v = self._fib(v, tid, name) if fib else v
            vals[name] = shown_v
            claims.append({"key": key, "value": shown_v, "shown": str(shown_v)})
        if self.key == "tactician":
            if kind == "signal":
                claim("tilt", f"chart.{G}.tilt")
            else:
                claim("acc", f"pass_acc.{G}")
        elif self.key == "analyst":
            if kind == "signal":
                claim("xg", f"xg.{G}"); claim("xgl", f"xg.{Lt}"); claim("pos", f"possession.{G}")
            else:
                claim("xg", f"xg.{G}"); claim("shots", f"shots.{G}")
        elif self.key == "expro":
            claim("pos" if kind == "signal" else "shots", f"possession.{G}" if kind == "signal" else f"shots.{G}")
        else:
            claim("fpos" if kind == "signal" else "fshots", f"possession.{F}" if kind == "signal" else f"shots.{F}")
        lang_t = lang if lang in ("en", "es", "fr") else "en"
        text = TPL[self.key][kind][lang_t].format(
            G=state.club(G), L=state.club(Lt), S=state.club(G), F=state.club(F).split()[0],
            Gs=state.meta.get("shorts", {}).get(G, G), Ls=state.meta.get("shorts", {}).get(Lt, Lt), lane=lane, **vals)
        return text, claims

    def run(self, trigger, facts, state, llm=None, fan_club=None, lang="en"):
        p = self.profile
        base = {"pundit": self.key, "name": p["name"], "title": p["title"], "initials": p["initials"],
                "trigger": trigger["kind"], "trigger_id": trigger["id"], "t": trigger["t"]}
        if llm is not None and llm.online:
            try:
                fact_keys = {k: v for k, v in facts.items() if not k.startswith("player.")}
                bias = f" You passionately support {state.club(fan_club)}." if p["bias"] and fan_club else ""
                r = llm.complete_json(
                    f"You are {p['name']}, a TV football pundit ({p['style']}).{bias} Teams are fictional. "
                    f"Write in {LANGS.get(lang, 'English')}, max 30 words. Any number you mention MUST come from the facts and "
                    "be listed in claims as {\"key\": <fact key>, \"value\": <number>, \"shown\": <exact text in your sentence>}. "
                    "Return {\"text\": str, \"claims\": [...]}.",
                    f"Moment: {trigger['summary']}. Facts: {fact_keys}")
                return {**base, "text": r["text"], "claims": r.get("claims", []), "source": "llm"}
            except (LLMUnavailable, ValueError, KeyError, TypeError):
                pass
        text, claims = self.template(trigger, facts, state, fan_club, lang)
        return {**base, "text": text, "claims": claims, "source": "template"}
