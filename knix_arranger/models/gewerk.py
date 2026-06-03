"""
Gewerk-Modelle und Katalog (FA-301, FA-302, FA-303)
33 Gewerke gemaess KNX Swiss Projektrichtlinien Kap. 10.1
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os


@dataclass
class Gewerk:
    """Ein KNX-Gewerk mit Kürzel und Standard-GA-Anzahl."""
    code: str = ""            # Kürzel, z.B. "LD"
    name: str = ""            # z.B. "Licht dimmbar"
    ga_count: int = 5         # Anzahl GA pro Element (5 oder 10)
    block_size: int = 5       # Blockgroesse (5 oder 10)
    middle_group: int = 0     # Standard-Mittelgruppe (0=Licht, 1=Jalousie, 2=Heizung...)
    category: str = ""        # "licht", "jalousie", "heizung", "alarm", "allgemein"
    is_custom: bool = False   # Benutzerdefiniertes Gewerk (FA-303)
    # Schnittstellentyp (FA-1307, FA-1408):
    #   "actor"         – Standard-KNX-Aktor (Schalt-, Dimm-, Jalousieaktor etc.)
    #   "gateway"       – Fremdsystem-Schnittstelle (DALI-GW, Modbus-GW, IP-GW); LDA, MM, WP
    #   "system_sensor" – Gewerkeuebergreifender Sensor ohne Raumzuordnung; W (Wetterstation)
    interface_type: str = "actor"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "ga_count": self.ga_count,
            "block_size": self.block_size,
            "middle_group": self.middle_group,
            "category": self.category,
            "is_custom": self.is_custom,
            "interface_type": self.interface_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Gewerk:
        return cls(
            code=data.get("code", ""),
            name=data.get("name", ""),
            ga_count=data.get("ga_count", 5),
            block_size=data.get("block_size", 5),
            middle_group=data.get("middle_group", 0),
            category=data.get("category", ""),
            is_custom=data.get("is_custom", False),
            interface_type=data.get("interface_type", "actor"),
        )


class GewerkCatalog:
    """Verwaltung aller Gewerke (Standard + benutzerdefiniert)."""

    def __init__(self):
        self.gewerke: dict[str, Gewerk] = {}

    def load_from_json(self, filepath: str):
        """Lädt Gewerke aus JSON-Konfigurationsdatei."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("gewerke", []):
            g = Gewerk.from_dict(entry)
            self.gewerke[g.code] = g

    def load_defaults(self):
        """Lädt den Standard-Gewerke-Katalog aus der config-Datei."""
        config_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
        )
        filepath = os.path.join(config_dir, "gewerke_catalog.json")
        if os.path.exists(filepath):
            self.load_from_json(filepath)

    def get(self, code: str) -> Gewerk | None:
        return self.gewerke.get(code)

    def add_custom(self, gewerk: Gewerk):
        """Fügt ein benutzerdefiniertes Gewerk hinzu (FA-303)."""
        gewerk.is_custom = True
        self.gewerke[gewerk.code] = gewerk

    def all_codes(self) -> list[str]:
        return sorted(self.gewerke.keys())

    def all_gewerke(self) -> list[Gewerk]:
        return list(self.gewerke.values())

    def to_dict(self) -> dict:
        return {
            "gewerke": [g.to_dict() for g in self.gewerke.values()]
        }
