"""
DPT-Anzeigenamen der ETS (deutsch) -> DPT-Kennung.

Der GA-Report der ETS (Gruppenadressen.xlsx) liefert in der Spalte
Datentyp nur den Anzeigenamen ("Schalten", "Auf/Ab"), die knxproj die
Kennung ("DPST-1-1"). Zuordnung aus Chalet Franziska 2005 (2026-10-28):
gleiche GA in Report und knxproj, jeder Name eindeutig. Ohne Untertyp
zeigt die ETS nur die Grösse ("1 bit") -- 1 Bit ist immer DPT 1, die
grösseren Grössen sind mehrdeutig und bleiben ohne DPT.

Für alle übrigen Namen gilt die Tabelle aus dem KNX-Stamm
(data/knx_dpt_names.json, tools/update_dpt_names.py). Der Topologie-Report
schreibt beim KO auch «Haupttyp, Untertyp» («1-Bit, Freigeben») oder
mehrere DPTs («Schalten, Schalten»); mehrdeutige Namen («Temperatur (°C)»
bei DPT 9 und 14) entscheidet die Grösse des KOs.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache

logger = logging.getLogger("knix_arranger.ets_dpt_names")

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


@lru_cache(maxsize=1)
def dpt_table() -> dict[str, dict]:
    """DPT-Kennung -> {"main", "bits", "text", "main_text"} aus dem KNX-Stamm."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "knx_dpt_names.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"DPT-Tabelle nicht lesbar: {e}")
        return {}


@lru_cache(maxsize=1)
def _by_name() -> tuple[dict[str, list[str]], dict[str, str]]:
    """(Name -> Untertypen, Haupttyp-Name -> Haupttyp)."""
    subs: dict[str, list[str]] = {}
    mains: dict[str, str] = {}
    for dpt_id, entry in dpt_table().items():
        if dpt_id.startswith("DPST-"):
            subs.setdefault(entry["text"].casefold(), []).append(dpt_id)
        else:
            mains.setdefault(entry["text"].casefold(), dpt_id)
    return subs, mains


def _number(dpt_id: str) -> tuple[int, int]:
    parts = dpt_id.split("-")[1:]
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else -1
    except (ValueError, IndexError):
        return 999, 999


def _hand(key: str, bits: int) -> str:
    """Geprüfte Zuordnung, wenn die Grösse des KOs dazu passt
    («Temperatur (°C)» mit 4 Byte ist DPT 14, nicht 9)."""
    found = ETS_DPT_NAMES.get(key, "")
    if found and bits and dpt_table().get(found, {}).get("bits", bits) != bits:
        return ""
    return found


def _lookup(name: str, bits: int = 0, main: str = "") -> str:
    key = " ".join(name.split()).casefold()
    if not main and _hand(key, bits):
        return _hand(key, bits)
    candidates = _by_name()[0].get(key, [])
    table = dpt_table()
    if main:
        candidates = [c for c in candidates if table[c]["main"] == main]
    if bits and len(candidates) > 1:
        candidates = [c for c in candidates if table[c]["bits"] == bits] or candidates
    if len(candidates) == 1:
        return candidates[0]
    return ""


_IDS = re.compile(r"\b(DPST-\d+-\d+|DPT-\d+)\b")


def ets_dpt_id(text: str, bits: int = 0) -> str:
    """Kennung zu einem DPT-Text: Kennungen bleiben (bei mehreren die erste
    genaue: «DPT-9 DPST-9-1» -> DPST-9-1), bekannte Anzeigenamen werden
    übersetzt, reine Grössenangaben ab 1 Byte werden leer, Unbekanntes
    bleibt wie es ist. bits: Grösse des KOs für mehrdeutige Namen."""
    value = (text or "").strip()
    if value.upper().startswith(("DPST-", "DPT-")):
        ids = _IDS.findall(value.upper())
        if not ids:
            return value
        return next((i for i in ids if i.startswith("DPST-")), ids[0])
    key = value.lower()
    if key in _SIZE_ONLY:
        return ""
    if _hand(key, bits):
        return _hand(key, bits)
    found = _lookup(value, bits) or _by_name()[1].get(" ".join(value.split()).casefold(), "")
    if found:
        return found
    # «Haupttyp, Untertyp» bzw. mehrere Untertypen «Schalten, Schalten»
    if ", " in value:
        first, rest = value.split(", ", 1)
        main = _by_name()[1].get(" ".join(first.split()).casefold(), "")
        if main:
            return _lookup(rest, bits, main) or main
        return _lookup(first, bits) or value
    return value


def dpt_text(dpt_id: str) -> str:
    """Anzeige wie in der ETS: «1.008 Auf/Ab», ohne Untertyp «1.x 1-Bit»."""
    entry = dpt_table().get(dpt_id)
    if not entry:
        return dpt_id or ""
    main, sub = _number(dpt_id)
    number = f"{main}.{sub:03d}" if sub >= 0 else f"{main}.x"
    return f"{number} {entry['text']}"
