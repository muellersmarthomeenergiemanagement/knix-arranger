"""
Sprache der Bedienungsanleitung (FA-2006).

Textbausteine liegen in i18n/manual_<sprache>.json:
- "texts": feste Texte mit Schlüssel (Überschriften, Einleitung, Tipps …),
  {name} sind Platzhalter. Fehlt ein Schlüssel, gilt der deutsche Text.
- "phrases": die deutschen Wendungen der automatisch erzeugten Bedienungstexte
  ("kurz drücken: Ein · lang drücken: heller") und ihre Übersetzung. Die
  Erzeugung arbeitet intern auf Deutsch; übersetzt wird erst bei der Ausgabe,
  ganze Wörter, längste Wendung zuerst. Projektdaten (Raumnamen, Bezeichnungen
  aus der ETS) bleiben, wie sie erfasst sind.
"""
from __future__ import annotations
from datetime import datetime
from functools import lru_cache
import json
import os
import re

MANUAL_LANGUAGES = ("de", "fr", "it", "en")
DEFAULT_LANGUAGE = "de"

_I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n")
_WORD = r"[\wäöüÄÖÜàâçéèêëîïôùûüÿ]"


@lru_cache(maxsize=None)
def _load(lang: str) -> dict:
    path = os.path.join(_I18N_DIR, f"manual_{lang}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def language_name(lang: str) -> str:
    return _load(lang).get("language_name", lang)


class ManualLanguage:
    """Textbausteine und Übersetzung für eine Sprache der Anleitung."""

    def __init__(self, lang: str = DEFAULT_LANGUAGE):
        self.lang = lang if lang in MANUAL_LANGUAGES else DEFAULT_LANGUAGE
        data = _load(self.lang)
        self._texts = {**_load(DEFAULT_LANGUAGE).get("texts", {}), **data.get("texts", {})}
        self.date_format = data.get("date_format", "%d.%m.%Y")
        phrases = data.get("phrases", {}) if self.lang != DEFAULT_LANGUAGE else {}
        self._phrases = phrases
        self._pattern = None
        if phrases:
            ordered = sorted(phrases, key=len, reverse=True)
            self._pattern = re.compile(
                "|".join(f"(?<!{_WORD}){re.escape(p)}(?!{_WORD})" for p in ordered))

    def text(self, key: str, /, **values) -> str:
        """Fester Text; {platzhalter} werden mit values gefüllt."""
        value = self._texts.get(key, key)
        return value.format(**values) if values else value

    def phrase(self, text: str) -> str:
        """Automatisch erzeugten deutschen Text übersetzen (ganze Wörter)."""
        if not self._pattern or not text:
            return text
        return self._pattern.sub(lambda m: self._phrases[m.group(0)], text)

    def date(self, when: datetime | None = None) -> str:
        """Datum nach Sprachregion (NFA-156): de/it 06.10.2026, fr/en 06/10/2026."""
        return (when or datetime.now()).strftime(self.date_format)
