"""
DPT-Anzeigenamen der ETS (deutsch) -> DPT-Kennung.

Der GA-Report der ETS (Gruppenadressen.xlsx) liefert in der Spalte
Datentyp nur den Anzeigenamen ("Schalten", "Auf/Ab"), die knxproj die
Kennung ("DPST-1-1"). Zuordnung aus Chalet Franziska 2005 (2026-10-28):
gleiche GA in Report und knxproj, jeder Name eindeutig. Ohne Untertyp
zeigt die ETS nur die Grösse ("1 bit") -- 1 Bit ist immer DPT 1, die
grösseren Grössen sind mehrdeutig und bleiben ohne DPT.
"""
from __future__ import annotations

ETS_DPT_NAMES: dict[str, str] = {
    "schalten": "DPST-1-1",
    "boolesch": "DPST-1-2",
    "freigeben": "DPST-1-3",
    "alarm": "DPST-1-5",
    "binärer wert": "DPST-1-6",
    "schritt": "DPST-1-7",
    "auf/ab": "DPST-1-8",
    "öffnen/schließen": "DPST-1-9",
    "öffnen/schliessen": "DPST-1-9",
    "status": "DPST-1-11",
    "szene": "DPST-1-22",
    "rollladen/jalousie modus": "DPST-1-23",
    "dimmer schritt": "DPST-3-7",
    "prozent (0..100%)": "DPST-5-1",
    "zählimpulse (0..255)": "DPST-5-10",
    "status mit modus": "DPST-6-20",
    "zeit (h)": "DPST-7-7",
    "zeitdifferenz (h)": "DPST-8-7",
    "temperatur (°c)": "DPST-9-1",
    "temperaturdifferenz (k)": "DPST-9-2",
    "lux (lux)": "DPST-9-4",
    "helligkeit (lux)": "DPST-9-4",
    "geschwindigkeit (m/s)": "DPST-9-5",
    "feuchtigkeit (%)": "DPST-9-7",
    "coefficient": "DPST-9-31",
    "tageszeit": "DPST-10-1",
    "datum": "DPST-11-1",
    "zählimpulse (vorzeichenlos)": "DPST-12-1",
    "wirkarbeit (kwh)": "DPST-13-13",
    "zeichen (iso 8859-1)": "DPST-16-1",
    "szenen nummer": "DPST-17-1",
    "szenensteuerung": "DPST-18-1",
    "szeneninformation": "DPST-26-1",
    "1 bit": "DPT-1",
}

#: Nur Grösse, Haupttyp mehrdeutig
_SIZE_ONLY = frozenset({"1 byte", "1-byte", "2 bytes", "2-byte", "4 bytes", "4-byte"})


def ets_dpt_id(text: str) -> str:
    """Kennung zu einem DPT-Text: Kennungen bleiben, bekannte Anzeigenamen
    werden übersetzt, reine Grössenangaben ab 1 Byte werden leer,
    Unbekanntes bleibt wie es ist."""
    value = (text or "").strip()
    if value.upper().startswith(("DPST-", "DPT-")):
        return value
    key = value.lower()
    if key in _SIZE_ONLY:
        return ""
    return ETS_DPT_NAMES.get(key, value)
