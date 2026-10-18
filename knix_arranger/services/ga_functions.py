"""
Funktionen einer Gruppenadresse mit DPT und Rolle (FA-1003c).

Die Funktion (GroupAddress.function_name, z.B. "E/A", "RM", "STELLGROESSE")
bestimmt, welches KO eines Aktors die GA bekommt und was die Validierung
erwartet. Jede Funktion hat eine Rolle:

- Befehl:        wird gesendet, damit etwas geschieht (E/A, DIM, AUF/AB, Szene)
- Rückmeldung:   Status eines Aktors (RM, STATUS ...)
- Messwert:      Sensor oder Gerät meldet einen Wert/Zustand (IST, Wind, Störung)

Reine Daten ohne Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

COMMAND = "befehl"
FEEDBACK = "rueckmeldung"
MEASUREMENT = "messwert"

ROLE_LABELS = {
    COMMAND: "Befehl",
    FEEDBACK: "Rückmeldung",
    MEASUREMENT: "Messwert",
}


@dataclass(frozen=True)
class GaFunction:
    name: str       # wie in der GA-Bezeichnung, z.B. "E/A"
    dpt: str        # Vorschlag, z.B. "DPST-1-1"
    role: str       # COMMAND | FEEDBACK | MEASUREMENT
    group: str      # Bereich für die Auswahlliste


# Reihenfolge = Reihenfolge in der Auswahlliste
_FUNCTIONS: tuple[GaFunction, ...] = (
    # Schalten / Licht
    GaFunction("E/A", "DPST-1-1", COMMAND, "Schalten"),
    GaFunction("RM", "DPST-1-1", FEEDBACK, "Schalten"),
    GaFunction("DIM", "DPST-3-7", COMMAND, "Schalten"),
    GaFunction("WERT", "DPST-5-1", COMMAND, "Schalten"),
    GaFunction("RM WERT", "DPST-5-1", FEEDBACK, "Schalten"),
    GaFunction("FARBTEMPERATUR", "DPT-7-600", COMMAND, "Schalten"),
    GaFunction("RM CCT", "DPT-7-600", FEEDBACK, "Schalten"),
    GaFunction("FARBE RGB", "DPST-232-600", COMMAND, "Schalten"),
    GaFunction("FARBE RGBW", "DPST-251-600", COMMAND, "Schalten"),
    GaFunction("RM FARBE", "DPST-232-600", FEEDBACK, "Schalten"),
    GaFunction("SPERREN", "DPST-1-1", COMMAND, "Schalten"),
    GaFunction("FREIGABE", "DPST-1-1", COMMAND, "Schalten"),
    GaFunction("SZENE", "DPST-18-1", COMMAND, "Schalten"),
    GaFunction("STATUS", "DPST-1-1", FEEDBACK, "Schalten"),
    # Beschattung
    GaFunction("AUF/AB", "DPST-1-8", COMMAND, "Beschattung"),
    GaFunction("STOPP", "DPST-1-7", COMMAND, "Beschattung"),
    GaFunction("POSITION HOEHE", "DPST-5-1", COMMAND, "Beschattung"),
    GaFunction("POSITION LAMELLEN", "DPST-5-1", COMMAND, "Beschattung"),
    GaFunction("STATUS POSITION HOEHE", "DPST-5-1", FEEDBACK, "Beschattung"),
    GaFunction("STATUS POSITION LAMELLEN", "DPST-5-1", FEEDBACK, "Beschattung"),
    GaFunction("BESCHATTUNG", "DPST-1-8", COMMAND, "Beschattung"),
    # Heizung / Klima / Lüftung
    GaFunction("STELLGROESSE", "DPST-5-1", COMMAND, "Heizung"),
    GaFunction("IST", "DPST-9-1", MEASUREMENT, "Heizung"),
    GaFunction("BASIS-SOLL", "DPST-9-1", COMMAND, "Heizung"),
    GaFunction("SOLLWERT", "DPT-9-1", COMMAND, "Heizung"),
    GaFunction("RM AKTUELLER SOLLWERT", "DPST-9-1", FEEDBACK, "Heizung"),
    GaFunction("RM SOLLWERT", "DPT-9-1", FEEDBACK, "Heizung"),
    GaFunction("UMSCHALTEN BETRIEBSART", "DPST-20-102", COMMAND, "Heizung"),
    GaFunction("STATUS BETRIEBSART", "DPST-20-102", FEEDBACK, "Heizung"),
    GaFunction("BETRIEBSART", "DPST-5-1", COMMAND, "Heizung"),
    GaFunction("STATUS BETRIEB", "DPT-20-105", FEEDBACK, "Heizung"),
    GaFunction("STUFE", "DPST-5-1", COMMAND, "Heizung"),
    GaFunction("STATUS STUFE", "DPST-5-1", FEEDBACK, "Heizung"),
    GaFunction("VENTILATOR", "DPST-5-1", COMMAND, "Heizung"),
    GaFunction("BYPASS", "DPST-1-1", COMMAND, "Heizung"),
    GaFunction("VORLAUFTEMPERATUR SOLL", "DPST-9-1", COMMAND, "Heizung"),
    GaFunction("VORLAUFTEMPERATUR IST", "DPST-9-1", MEASUREMENT, "Heizung"),
    GaFunction("RUECKLAUFTEMPERATUR", "DPST-9-1", MEASUREMENT, "Heizung"),
    GaFunction("WARMWASSER SOLL", "DPST-9-1", COMMAND, "Heizung"),
    GaFunction("WARMWASSER IST", "DPST-9-1", MEASUREMENT, "Heizung"),
    GaFunction("FEUCHTE", "DPT-9-7", MEASUREMENT, "Heizung"),
    GaFunction("CO2", "DPT-9-8", MEASUREMENT, "Heizung"),
    GaFunction("FILTER", "DPST-1-1", MEASUREMENT, "Heizung"),
    GaFunction("STOERUNG", "DPST-1-1", MEASUREMENT, "Heizung"),
    # Wetter
    GaFunction("TEMPERATUR AUSSEN", "DPST-9-1", MEASUREMENT, "Wetter"),
    GaFunction("AUSSENTEMPERATUR", "DPST-9-1", MEASUREMENT, "Wetter"),
    GaFunction("WIND GESCHWINDIGKEIT", "DPST-9-5", MEASUREMENT, "Wetter"),
    GaFunction("WIND ALARM", "DPST-1-5", MEASUREMENT, "Wetter"),
    GaFunction("REGEN", "DPST-1-5", MEASUREMENT, "Wetter"),
    GaFunction("FROST ALARM", "DPST-1-5", MEASUREMENT, "Wetter"),
    GaFunction("DAEMMERUNG", "DPST-9-4", MEASUREMENT, "Wetter"),
    GaFunction("HELLIGKEIT", "DPST-5-1", MEASUREMENT, "Wetter"),
    # Energie
    GaFunction("LEISTUNG", "DPST-9-24", MEASUREMENT, "Energie"),
    GaFunction("LEISTUNG IST", "DPT-9-1", MEASUREMENT, "Energie"),
    GaFunction("ENERGIE", "DPT-9-1", MEASUREMENT, "Energie"),
    GaFunction("EINSPEISUNG", "DPT-9-1", MEASUREMENT, "Energie"),
    GaFunction("ERTRAG TAG", "DPT-9-1", MEASUREMENT, "Energie"),
    GaFunction("ERTRAG GESAMT", "DPT-9-1", MEASUREMENT, "Energie"),
    GaFunction("SOC", "DPST-5-1", MEASUREMENT, "Energie"),
    GaFunction("LADESTAND", "DPST-5-1", MEASUREMENT, "Energie"),
    GaFunction("LADELEISTUNG", "DPT-9-1", COMMAND, "Energie"),
    GaFunction("LADELEISTUNG SOLL", "DPT-9-1", COMMAND, "Energie"),
    GaFunction("LADELEISTUNG IST", "DPT-9-1", MEASUREMENT, "Energie"),
    GaFunction("ENTLADELEISTUNG", "DPT-9-1", MEASUREMENT, "Energie"),
    GaFunction("LADEMODUS", "DPST-5-1", COMMAND, "Energie"),
    GaFunction("LIMIT", "DPST-5-1", COMMAND, "Energie"),
    GaFunction("MODUS", "DPST-5-1", COMMAND, "Energie"),
    # Multimedia
    GaFunction("EIN/AUS", "DPST-1-1", COMMAND, "Multimedia"),
    GaFunction("LAUTSTAERKE", "DPST-5-1", COMMAND, "Multimedia"),
    GaFunction("QUELLE", "DPST-5-1", COMMAND, "Multimedia"),
    GaFunction("PLAY/PAUSE", "DPST-1-1", COMMAND, "Multimedia"),
)

_BY_NAME = {f.name: f for f in _FUNCTIONS}

# Wörter unbekannter Funktionen, die auf eine Rückmeldung hindeuten
_FEEDBACK_WORDS = frozenset({"STATUS", "RM", "INFO", "FEEDBACK", "RUECKMELDUNG",
                             "RÜCKMELDUNG", "ZUSTAND"})
# Namensteile unbekannter Funktionen, die auf einen Messwert hindeuten
_MEASUREMENT_HINTS = ("IST", "TEMPERATUR", "HELLIGKEIT", "WIND", "ALARM",
                      "STOERUNG", "ENERGIE", "LEISTUNG", "FEUCHTE", "ZAEHLER")


def all_functions() -> tuple[GaFunction, ...]:
    return _FUNCTIONS


def find(name: str) -> GaFunction | None:
    return _BY_NAME.get((name or "").strip().upper())


def suggested_dpt(name: str) -> str:
    """DPT-Vorschlag einer Funktion, "" wenn unbekannt."""
    function = find(name)
    return function.dpt if function else ""


def role_of(name: str) -> str:
    """Rolle einer Funktion; unbekannte nach dem Namen, "" ohne Funktion."""
    name = (name or "").strip().upper()
    if not name:
        return ""
    function = _BY_NAME.get(name)
    if function:
        return function.role
    if name == "RM" or name.startswith(("RM ", "STATUS")):
        return FEEDBACK
    words = name.replace("-", " ").replace(":", " ").replace("/", " ").split()
    # Herstellertexte, z.B. Revox "Room 1: Volume value Status", "Track Info 1"
    if any(w in _FEEDBACK_WORDS for w in words):
        return FEEDBACK
    if any(hint in words or name.endswith(" " + hint) for hint in _MEASUREMENT_HINTS):
        return MEASUREMENT
    return COMMAND


def is_known_command(name: str) -> bool:
    """Bekannte Befehlsfunktion (E/A, DIM, AUF/AB …) -- nicht nur nach dem
    Namen vermutet wie bei Herstellertexten («System» = In-Betrieb-Telegramm
    des ABB-Binäreingangs)."""
    function = _BY_NAME.get((name or "").strip().upper())
    return function is not None and function.role == COMMAND


def role_label(name: str) -> str:
    return ROLE_LABELS.get(role_of(name), "")
