"""
DALI-Konfigurationsmodell (FA-2800).

Bildet pro DALI-Gateway die EVG-/Gruppen-/Szenen-Konfiguration ab.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import uuid


# ── DALI Emergency Modes ──────────────────────────────────────────────────────

EMERGENCY_MODES = {
    "sustained":  "Dauerlicht",
    "standby":    "Bereitschaft",
    "auto":       "Automatik",
}


@dataclass
class DaliDevice:
    """Ein DALI-Betriebsgerät (EVG/Leuchte) innerhalb eines Gateways."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    short_address: int = 0          # 0–63
    name: str = ""                  # z.B. "Leuchte Büro 1"
    evg_type: str = ""              # z.B. "Fluoreszenz", "LED", "Notlicht"
    room_id: str = ""               # Verknüpfung mit Room.id
    group_memberships: list[int] = field(default_factory=list)  # DALI-Gruppen 0–15
    is_emergency: bool = False      # FA-2804: Notlicht-EVG
    emergency_mode: str = "auto"   # "sustained" | "standby" | "auto"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "short_address": self.short_address,
            "name": self.name,
            "evg_type": self.evg_type,
            "room_id": self.room_id,
            "group_memberships": list(self.group_memberships),
            "is_emergency": self.is_emergency,
            "emergency_mode": self.emergency_mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DaliDevice:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            short_address=d.get("short_address", 0),
            name=d.get("name", ""),
            evg_type=d.get("evg_type", ""),
            room_id=d.get("room_id", ""),
            group_memberships=list(d.get("group_memberships", [])),
            is_emergency=d.get("is_emergency", False),
            emergency_mode=d.get("emergency_mode", "auto"),
        )


@dataclass
class DaliGroup:
    """Eine DALI-Gruppe (0–15) innerhalb eines Gateways."""
    number: int = 0                    # 0–15
    name: str = ""                     # z.B. "Reihe 1"
    device_addresses: list[int] = field(default_factory=list)  # Short-Adressen
    # KNX-GAs für diese Gruppe (aus Import oder manuelle Zuweisung)
    ga_switch: str = ""               # Schalten Gruppe
    ga_dim: str = ""                  # Dimmen Gruppe
    ga_value: str = ""                # Helligkeitswert Gruppe

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "device_addresses": list(self.device_addresses),
            "ga_switch": self.ga_switch,
            "ga_dim": self.ga_dim,
            "ga_value": self.ga_value,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DaliGroup:
        return cls(
            number=d.get("number", 0),
            name=d.get("name", ""),
            device_addresses=list(d.get("device_addresses", [])),
            ga_switch=d.get("ga_switch", ""),
            ga_dim=d.get("ga_dim", ""),
            ga_value=d.get("ga_value", ""),
        )


@dataclass
class DaliScene:
    """Eine DALI-Szene (0–15)."""
    number: int = 0
    name: str = ""

    def to_dict(self) -> dict:
        return {"number": self.number, "name": self.name}

    @classmethod
    def from_dict(cls, d: dict) -> DaliScene:
        return cls(number=d.get("number", 0), name=d.get("name", ""))


@dataclass
class DaliGateway:
    """DALI-Gateway-Konfiguration (pro Topology-Device mit device_type='gateway' + LDA).

    Verknüpft bis zu 64 EVGs und bis zu 16 Gruppen.
    Die KNX-GAs werden aus der automatisch generierten Struktur übernommen (FA-2803).
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    gateway_device_id: str = ""        # Device.id in der Topologie
    name: str = ""                     # Anzeigename

    devices: list[DaliDevice] = field(default_factory=list)   # max 64
    groups: list[DaliGroup] = field(default_factory=list)     # max 16
    scenes: list[DaliScene] = field(default_factory=list)     # max 16

    # KNX-GAs für die DALI-Steuerung (FA-2803)
    ga_switch_broadcast: str = ""    # Schalten Broadcast
    ga_dim_broadcast: str = ""       # Dimmen Broadcast
    ga_scene: str = ""               # Szenenabruf
    ga_status_value: str = ""        # Status Istwert
    ga_status_fault: str = ""        # Status Störung

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "gateway_device_id": self.gateway_device_id,
            "name": self.name,
            "devices": [d.to_dict() for d in self.devices],
            "groups": [g.to_dict() for g in self.groups],
            "scenes": [s.to_dict() for s in self.scenes],
            "ga_switch_broadcast": self.ga_switch_broadcast,
            "ga_dim_broadcast": self.ga_dim_broadcast,
            "ga_scene": self.ga_scene,
            "ga_status_value": self.ga_status_value,
            "ga_status_fault": self.ga_status_fault,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DaliGateway:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            gateway_device_id=d.get("gateway_device_id", ""),
            name=d.get("name", ""),
            devices=[DaliDevice.from_dict(x) for x in d.get("devices", [])],
            groups=[DaliGroup.from_dict(x) for x in d.get("groups", [])],
            scenes=[DaliScene.from_dict(x) for x in d.get("scenes", [])],
            ga_switch_broadcast=d.get("ga_switch_broadcast", ""),
            ga_dim_broadcast=d.get("ga_dim_broadcast", ""),
            ga_scene=d.get("ga_scene", ""),
            ga_status_value=d.get("ga_status_value", ""),
            ga_status_fault=d.get("ga_status_fault", ""),
        )
