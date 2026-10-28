"""Offline phrase tables. Languages beyond these are produced by the LLM when configured."""
LANGS = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese",
         "ar": "Arabic", "hi": "Hindi", "ja": "Japanese", "sw": "Swahili", "ur": "Urdu"}
OFFLINE_LANGS = ("en", "es", "fr", "de", "pt")

P = {
    "goal": {"en": "GOAL! {player} scores for {club}!", "es": "¡GOL! ¡{player} marca para {club}!",
             "fr": "BUT ! {player} marque pour {club} !", "de": "TOR! {player} trifft für {club}!",
             "pt": "GOLO! {player} marca pelo {club}!"},
    "shot": {"en": "{player} shoots, {outcome}.", "es": "{player} dispara: {outcome}.", "fr": "{player} tire : {outcome}.",
             "de": "{player} schießt: {outcome}.", "pt": "{player} remata: {outcome}."},
    "pass": {"en": "{player} threads a {dist} m pass.", "es": "{player} filtra un pase de {dist} m.",
             "fr": "{player} glisse une passe de {dist} m.", "de": "{player} spielt einen {dist}-m-Pass.",
             "pt": "{player} faz um passe de {dist} m."},
    "carry": {"en": "{player} bursts forward at {speed} km/h.", "es": "{player} arranca a {speed} km/h.",
              "fr": "{player} accélère à {speed} km/h.", "de": "{player} sprintet mit {speed} km/h.",
              "pt": "{player} arranca a {speed} km/h."},
    "tackle": {"en": "{player} wins it back for {club}!", "es": "¡{player} recupera para {club}!",
               "fr": "{player} récupère pour {club} !", "de": "{player} erobert den Ball für {club}!",
               "pt": "{player} recupera para o {club}!"},
    "pressure": {"en": "{club} swarm the ball.", "es": "{club} presiona en bloque.", "fr": "{club} étouffe le porteur.",
                 "de": "{club} läuft wild an.", "pt": "{club} pressiona forte."},
    "signal": {"en": "MOMENTUM SHIFT → {club}", "es": "CAMBIO DE INERCIA → {club}", "fr": "BASCULE → {club}",
               "de": "MOMENTUM-WECHSEL → {club}", "pt": "VIRAGEM → {club}"},
    "signal_sub": {"en": "{metric} out of control ({rule})", "es": "{metric} fuera de control ({rule})",
                   "fr": "{metric} hors contrôle ({rule})", "de": "{metric} außer Kontrolle ({rule})",
                   "pt": "{metric} fora de controlo ({rule})"},
    "why": {"en": "Why?", "es": "¿Por qué?", "fr": "Pourquoi ?", "de": "Warum?", "pt": "Porquê?"},
    "countermeasure": {"en": "Countermeasure", "es": "Contramedida", "fr": "Contre-mesure", "de": "Gegenmaßnahme",
                       "pt": "Contramedida"},
    "outcome.saved": {"en": "saved", "es": "atajada", "fr": "arrêté", "de": "gehalten", "pt": "defendido"},
    "outcome.blocked": {"en": "blocked", "es": "bloqueado", "fr": "contré", "de": "geblockt", "pt": "bloqueado"},
    "outcome.off_target": {"en": "wide", "es": "fuera", "fr": "à côté", "de": "daneben", "pt": "ao lado"},
    "outcome.goal": {"en": "goal", "es": "gol", "fr": "but", "de": "Tor", "pt": "golo"},
}
METRIC = {
    "possession": {"en": "Possession share", "es": "Posesión", "fr": "Possession", "de": "Ballbesitz", "pt": "Posse"},
    "tilt": {"en": "Field tilt", "es": "Dominio territorial", "fr": "Domination territoriale", "de": "Feldüberlegenheit", "pt": "Domínio territorial"},
    "pressure": {"en": "Pressing load", "es": "Carga de presión", "fr": "Intensité du pressing", "de": "Pressing-Last", "pt": "Carga de pressão"},
    "completion": {"en": "Pass completion", "es": "Acierto en pases", "fr": "Passes réussies", "de": "Passquote", "pt": "Acerto de passe"},
    "difficulty": {"en": "Pass difficulty", "es": "Dificultad de pase", "fr": "Difficulté des passes", "de": "Passschwierigkeit", "pt": "Dificuldade de passe"},
    "tempo": {"en": "Passing tempo", "es": "Ritmo de pase", "fr": "Tempo des passes", "de": "Passtempo", "pt": "Ritmo de passe"},
}


def t(key, lang, **kw):
    table = P.get(key, {})
    s = table.get(lang) or table.get("en", key)
    return s.format(**kw) if kw else s


def metric(m, lang):
    return METRIC.get(m, {}).get(lang) or METRIC.get(m, {}).get("en", m)
