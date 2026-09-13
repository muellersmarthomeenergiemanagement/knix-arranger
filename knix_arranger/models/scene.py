"""
Szenen-Modelle (FA-1800)
"""
from __future__ import annotations
from dataclasses import dataclass, field
import uuid


@dataclass
class SceneAction:
    """Einzelne Aktion innerhalb einer Szene (FA-1802)."""
    group_address: str = ""   # Betroffene GA, z.B. "LD_E01_01 WERT"
    value: str = ""           # Zu sendender Wert, z.B. "20%"
    delay_seconds: float = 0  # Optionale Verzögerung
    # Numerische KNX-Adresse (z.B. "0/4/101") der verknuepften GroupAddress --
    # nur befuellt, wenn die Aktion von der Szenen-Erkennung (FA-1808) aus
    # einer echten importierten GA abgeleitet wurde; bei manuell angelegten
    # Aktionen bleibt es leer, da group_address dort nur ein Freitext-Label ist.
    ga_address: str = ""

    def to_dict(self) -> dict:
        return {
            "group_address": self.group_address,
            "value": self.value,
            "delay_seconds": self.delay_seconds,
            "ga_address": self.ga_address,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SceneAction:
        return cls(
            group_address=data.get("group_address", ""),
            value=data.get("value", ""),
            delay_seconds=data.get("delay_seconds", 0),
            ga_address=data.get("ga_address", ""),
        )


@dataclass
class Scene:
    """KNX-Szene (FA-1801)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""            # z.B. "Kino"
    scene_number: int = 0     # KNX-Szenennummer (1-64)
    scope: str = ""           # "room", "apartment", "zone", "central"
    scope_id: str = ""        # ID des Raums/Wohnung/Zone
    trigger: str = ""         # z.B. "Taster Eingang, Taste 4 lang"
    actions: list[SceneAction] = field(default_factory=list)
    # Herkunft (FA-1808): automatisch aus einem ETS-Import erkannte Szenen
    # tragen hier die Quelle, damit sie bei der GA-Neugenerierung nicht
    # dupliziert werden (siehe address_generator._create_central_main_group).
    is_detected: bool = False
    detection_kind: str = ""      # "dpt" | "folder" | "pattern"
    # Numerische Adressen ("0/4/1") der Quell-GA(s), NICHT GroupAddress.id --
    # diese wird bei jedem Import neu vergeben (Zufalls-UUID) und waere nach
    # einem Re-Import verwaist; die Adresse bleibt stabil.
    source_ga_addresses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "scene_number": self.scene_number,
            "scope": self.scope,
            "scope_id": self.scope_id,
            "trigger": self.trigger,
            "actions": [a.to_dict() for a in self.actions],
            "is_detected": self.is_detected,
            "detection_kind": self.detection_kind,
            "source_ga_addresses": list(self.source_ga_addresses),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Scene:
        s = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            scene_number=data.get("scene_number", 0),
            scope=data.get("scope", ""),
            scope_id=data.get("scope_id", ""),
            trigger=data.get("trigger", ""),
            is_detected=data.get("is_detected", False),
            detection_kind=data.get("detection_kind", ""),
        )
        s.actions = [SceneAction.from_dict(a) for a in data.get("actions", [])]
        s.source_ga_addresses = list(data.get("source_ga_addresses", []))
        return s
