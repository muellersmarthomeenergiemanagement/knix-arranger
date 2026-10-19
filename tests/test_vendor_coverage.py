"""
Wie gut versteht KNiX die Herstellerdateien? Gemessen an typischen KO-Texten
echter KNXPROD-Dateien (tests/data/ko_samples.json.gz, je Hersteller/Aktortyp):

- Kanäle erkannt: device_channels findet Kanäle mit KOs (Kanal A, Ausgang 1,
  Sortie 1, C1, Motor 1, …);
- Hauptfunktion: der erste Kanal liefert für die Hauptfunktion des Gewerks
  (E/A, AUF/AB, Stellgrösse) einen KO;
- Funktionen: Anteil der GA-Funktionen des Gewerks mit KO.

Die Mindestwerte sichern den erreichten Stand: eine Änderung, die die
Erkennung verschlechtert, fällt hier auf. Bei Verbesserungen anheben.
Ausgabe der Detailwerte: pytest tests/test_vendor_coverage.py -s
"""
from __future__ import annotations

import collections
import gzip
import json
import os

import pytest

from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.actor_channels import Circuit, device_channels, suggested_co_map
from knix_arranger.services.address_generator import AddressGenerator

_SAMPLES = os.path.join(os.path.dirname(__file__), "data", "ko_samples.json.gz")
_TYPE_TO_GEWERK = {"Schaltaktor": "L", "Dimmaktor": "LD", "Jalousieaktor": "J",
                   "Heizungsaktor": "H", "Schalt-/Jalousieaktor": "J"}


def _functions() -> dict[str, list[str]]:
    catalog = KnxProject().gewerk_catalog
    gen = AddressGenerator(catalog, variant="A")
    result = {}
    for device_type, code in _TYPE_TO_GEWERK.items():
        schema = gen._base_schema(catalog.get(code))
        result[device_type] = [(e.function, e.dpt) for e in schema.entries
                               if e.function and not e.is_reserve]
    return result


def measure() -> dict:
    """Kennzahlen je Typ und gesamt."""
    with gzip.open(_SAMPLES, "rt", encoding="utf-8") as f:
        samples = json.load(f)["products"]
    functions = _functions()
    stats: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for sample in samples:
        device_type = sample["device_type"]
        # Je KO: Nummer, Name, Objektfunktion, DPT[, Grösse, Flags]
        device = Device(product=device_type, communication_objects=[
            CommunicationObject(object_number=row[0], name=row[1], object_function=row[2],
                                data_type=row[3],
                                object_size=row[4] if len(row) > 4 else "",
                                flags=row[5] if len(row) > 5 else "")
            for row in sample["com_objects"]])
        channels = [ch for ch in device_channels(device) if ch.com_objects]
        for key in (device_type, "gesamt"):
            stats[key]["Produkte"] += 1
            if not channels:
                continue
            stats[key]["Kanäle"] += 1
        if not channels:
            continue
        wanted = functions[device_type]
        circuit = Circuit(key="x", room_number="", room_name="",
                          gewerk_code=_TYPE_TO_GEWERK[device_type], element_number=1,
                          channel=channels[0].number, functions=[(f, "") for f, _d in wanted],
                          dpts=dict(wanted))
        selection = suggested_co_map(channels[0], circuit)
        for key in (device_type, "gesamt"):
            stats[key]["Hauptfunktion"] += wanted[0][0] in selection
            stats[key]["Funktionen"] += len(selection)
            stats[key]["Funktionen gesamt"] += len(wanted)
    return stats


def _print(stats):
    print(f"\n{'Typ':24} {'Produkte':>8} {'Kanäle':>7} {'Haupt':>6} {'Funkt.':>7}")
    for key, c in sorted(stats.items()):
        share = (100 * c["Funktionen"] / c["Funktionen gesamt"]) if c["Funktionen gesamt"] else 0
        print(f"{key:24} {c['Produkte']:8} {c['Kanäle']:7} {c['Hauptfunktion']:6} {share:6.0f}%")


# Erreichter Stand (Anteil an allen Produkten der Sammlung)
# 2026-10-13: 35/44 Kanäle, 24/44 Hauptfunktion (vorher 21 bzw. 6)
# 2026-10-19: Objektfunktion, deutsche Texte und Grösse aus der Herstellerdatei
#             (READER_VERSION 2): 35/44 Kanäle, 32/44 Hauptfunktion, 87 % Funktionen
_MIN_CHANNELS = 0.75
_MIN_MAIN = 0.70
_MIN_FUNCTIONS = 0.85


def test_vendor_coverage_does_not_regress():
    stats = measure()
    _print(stats)
    total = stats["gesamt"]
    assert total["Kanäle"] / total["Produkte"] >= _MIN_CHANNELS
    assert total["Hauptfunktion"] / total["Produkte"] >= _MIN_MAIN
    assert total["Funktionen"] / total["Funktionen gesamt"] >= _MIN_FUNCTIONS
