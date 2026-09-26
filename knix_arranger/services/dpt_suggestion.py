"""
DPT-Vorschlag aus Funktion bzw. GA-Bezeichnung (FA-604).

Importierte Projekte haben meist keinen function_name; der Datenpunkttyp
wird dann aus typischen Namensbestandteilen abgeleitet (_ea, _status,
Temp, Helligkeit, …). Ist nichts eindeutig erkennbar, gibt es keinen
Vorschlag – lieber leer als geraten.
"""
from __future__ import annotations
import re

# Kurzbezeichnungen für die Anzeige im Bericht
DPT_LABELS = {
    "DPST-1-1": "1.001 Schalten",
    "DPST-1-7": "1.007 Schritt",
    "DPST-1-8": "1.008 Auf/Ab",
    "DPST-3-7": "3.007 Dimmen",
    "DPST-5-1": "5.001 Prozent",
    "DPST-9-1": "9.001 Temperatur",
    "DPST-9-4": "9.004 Helligkeit (Lux)",
    "DPST-9-5": "9.005 Wind (m/s)",
    "DPST-9-28": "9.028 Wind (km/h)",
    "DPST-17-1": "17.001 Szenennummer",
    "DPST-18-1": "18.001 Szenensteuerung",
    "DPST-20-102": "20.102 HVAC-Betriebsart",
}

# Funktionsnamen aus dem Wizard (entspricht config/dpt_mapping.json)
FUNCTION_TO_DPT = {
    "E/A": "DPST-1-1", "RM": "DPST-1-1",
    "DIM": "DPST-3-7",
    "WERT": "DPST-5-1", "RM WERT": "DPST-5-1",
    "AUF/AB": "DPST-1-8", "BESCHATTUNG": "DPST-1-8",
    "STOPP": "DPST-1-7",
    "IST": "DPST-9-1", "BASIS-SOLL": "DPST-9-1",
}

# (Muster, Vorschlag) – erster Treffer gewinnt, daher Spezielles vor Allgemeinem.
# Der Vorschlag ist ein DPST-Code oder ein fertiger Anzeigetext bei zwei
# gleichwertigen Möglichkeiten.
_NAME_RULES: list[tuple[str, str]] = [
    (r"szene", "DPST-17-1"),
    (r"temp|_ist\b|istwert|sollwert", "DPST-9-1"),
    (r"helligkeit|daemmerung|dämmerung|\blux\b", "DPST-9-4"),
    (r"wind.*km/h", "DPST-9-28"),
    (r"wind", "DPST-9-5"),
    (r"leistung", "9.024 (kW) / 14.056 (W)"),
    (r"ventil|stellgr", "1.001 (PWM) / 5.001 (stetig)"),
    (r"dimm|_dim\b", "DPST-3-7"),
    (r"auf/ab|auf ab|_ab\b", "DPST-1-8"),
    (r"stopp|lamell", "DPST-1-7"),
    (r"position|hoehe|höhe|%|_wert\b", "DPST-5-1"),
    (r"_ea\b|e/a|_status\b|status|stoerung|störung|alarm|regen|rauchmelder"
     r"|kontakt|anwesen|abwesen|sperr|\bpir\b|bewegung", "DPST-1-1"),
]


def dpt_label(dpst: str) -> str:
    return DPT_LABELS.get(dpst, dpt_number(dpst))


def dpt_number(dpst: str) -> str:
    """'DPST-1-22' -> '1.022', 'DPT-9' -> '9.xxx'; Unbekanntes unverändert."""
    m = re.fullmatch(r"DPST-(\d+)-(\d+)", dpst or "")
    if m:
        return f"{int(m.group(1))}.{int(m.group(2)):03d}"
    m = re.fullmatch(r"DPT-(\d+)", dpst or "")
    if m:
        return f"{int(m.group(1))}.xxx"
    return dpst


def suggest_dpt(designation: str, function_name: str = "") -> str:
    """Anzeigetext des vorgeschlagenen DPT oder '' wenn nicht ableitbar."""
    if function_name in FUNCTION_TO_DPT:
        return dpt_label(FUNCTION_TO_DPT[function_name])
    name = (designation or "").strip().lower()
    if not name:
        return ""
    for pattern, result in _NAME_RULES:
        if re.search(pattern, name):
            return dpt_label(result)
    return ""
