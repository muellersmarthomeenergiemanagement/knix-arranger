"""
Erweiterung im Bestand (FA-642): neue Elemente in einer bestehenden Anlage.

Wie die Umbau-Variante einer Linie steht die Erweiterung neben dem
Ist-Stand: KNiX schlägt Adressen, Namen und Aktorkanäle vor, die ETS setzt
sie um, ein Re-Import übernimmt sie. Auswertung in services/extension_service.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime

# Namensschema der neuen GAs
NAMING_AUTO = "auto"        # Schema der Anlage, wo erkennbar, sonst KNX Swiss
NAMING_PLANT = "plant"      # immer Schema der Anlage (ohne Vorlage: KNX Swiss)
NAMING_SWISS = "swiss"      # immer KNX Swiss


@dataclass
class ExtensionItem:
    room_id: str = ""
    gewerk_code: str = ""
    count: int = 1
    label: str = ""             # Klartext, z.B. "Fenster West"
    operation: str = ""         # Bedienung, z.B. "neuer Taster", "Visualisierung"

    def to_dict(self) -> dict:
        return {"room_id": self.room_id, "gewerk_code": self.gewerk_code,
                "count": self.count, "label": self.label, "operation": self.operation}

    @classmethod
    def from_dict(cls, data: dict) -> ExtensionItem:
        return cls(room_id=data.get("room_id", ""), gewerk_code=data.get("gewerk_code", ""),
                   count=int(data.get("count", 1) or 1), label=data.get("label", ""),
                   operation=data.get("operation", ""))


@dataclass
class ExtensionPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    created: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    naming: str = NAMING_AUTO
    items: list[ExtensionItem] = field(default_factory=list)

    @property
    def comment(self) -> str:
        """Kennzeichnung der neuen GAs (Kommentar bzw. Beschreibung in der ETS)."""
        return f"KNiX Erweiterung {self.created[:7]} {self.name}".strip()

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "created": self.created,
                "naming": self.naming, "items": [i.to_dict() for i in self.items]}

    @classmethod
    def from_dict(cls, data: dict) -> ExtensionPlan:
        return cls(id=data.get("id") or str(uuid.uuid4()), name=data.get("name", ""),
                   created=data.get("created", ""), naming=data.get("naming", NAMING_AUTO),
                   items=[ExtensionItem.from_dict(i) for i in data.get("items", [])])
