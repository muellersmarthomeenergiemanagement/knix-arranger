"""
Internationalisierung (NFA-151, NFA-152, NFA-153, NFA-156)
Uebersetzungsfunktion tr() für externe Sprachdateien.
Locale-Formatierung für Datum, Währung und Zahlen.
"""
import json
import os
from datetime import datetime
from typing import Optional

_current_language = "de"
_translations: dict = {}
_terms: dict = {}


def _get_i18n_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n"
    )


def load_language(lang: str = "de"):
    """Lädt eine Sprachdatei (NFA-153)."""
    global _current_language, _translations, _terms
    _current_language = lang
    i18n_dir = _get_i18n_dir()

    lang_file = os.path.join(i18n_dir, f"{lang}.json")
    if os.path.exists(lang_file):
        with open(lang_file, "r", encoding="utf-8") as f:
            _translations = json.load(f)
    else:
        _translations = {}

    terms_file = os.path.join(i18n_dir, f"terms_{lang}.json")
    if os.path.exists(terms_file):
        with open(terms_file, "r", encoding="utf-8") as f:
            _terms = json.load(f).get("terms", {})


def tr(key: str, default: Optional[str] = None) -> str:
    """
    Uebersetzungsfunktion.
    Key-Format: "section.key", z.B. "menu.file", "wizard.step1_title"
    """
    parts = key.split(".", 1)
    if len(parts) == 2:
        section, subkey = parts
        value = _translations.get(section, {}).get(subkey)
        if value is not None:
            return value
    # Fallback: direkter Key
    value = _translations.get(key)
    if value is not None:
        return value
    return default if default is not None else key


def term(name: str) -> str:
    """Gibt die Erklärung eines KNX-Fachbegriffs zurück (NFA-155)."""
    return _terms.get(name, name)


def get_current_language() -> str:
    return _current_language


def available_languages() -> list[str]:
    """Gibt die verfügbaren Sprachen zurück."""
    i18n_dir = _get_i18n_dir()
    languages = []
    if os.path.exists(i18n_dir):
        for f in os.listdir(i18n_dir):
            if f.endswith(".json") and not f.startswith("terms_"):
                languages.append(f.replace(".json", ""))
    return sorted(languages)


# Locale-Formate nach Sprache (NFA-156)
LOCALE_FORMATS = {
    "de": {"date": "%d.%m.%Y", "thousand_sep": "'", "decimal_sep": ".", "currency": "CHF"},
    "fr": {"date": "%d/%m/%Y", "thousand_sep": " ", "decimal_sep": ",", "currency": "CHF"},
    "en": {"date": "%m/%d/%Y", "thousand_sep": ",", "decimal_sep": ".", "currency": "CHF"},
}


def format_date(dt: datetime | None = None) -> str:
    """Formatiert ein Datum nach aktueller Sprache (NFA-156)."""
    if dt is None:
        dt = datetime.now()
    fmt = LOCALE_FORMATS.get(_current_language, LOCALE_FORMATS["de"])
    return dt.strftime(fmt["date"])


def format_number(value: float, decimals: int = 2) -> str:
    """Formatiert eine Zahl nach aktueller Sprache (NFA-156)."""
    fmt = LOCALE_FORMATS.get(_current_language, LOCALE_FORMATS["de"])
    tsep = fmt["thousand_sep"]
    dsep = fmt["decimal_sep"]

    # Vorzeichen behandeln
    negative = value < 0
    value = abs(value)

    # Dezimalstellen
    int_part = int(value)
    dec_part = round(value - int_part, decimals)
    dec_str = f"{dec_part:.{decimals}f}"[2:]  # ohne "0."

    # Tausender-Trennzeichen
    int_str = str(int_part)
    groups = []
    while int_str:
        groups.append(int_str[-3:])
        int_str = int_str[:-3]
    int_formatted = tsep.join(reversed(groups))

    result = f"{int_formatted}{dsep}{dec_str}" if decimals > 0 else int_formatted
    return f"-{result}" if negative else result


def format_currency(amount: float) -> str:
    """Formatiert einen Währungsbetrag nach aktueller Sprache (NFA-156)."""
    fmt = LOCALE_FORMATS.get(_current_language, LOCALE_FORMATS["de"])
    return f"{fmt['currency']} {format_number(amount, 2)}"


# Beim Import automatisch Deutsch laden
load_language("de")
