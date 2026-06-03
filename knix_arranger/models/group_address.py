"""
Gruppenadress-Modelle: Hauptgruppe, Mittelgruppe, Untergruppe
Gemaess FA-400, FA-411, FA-421-423, FA-431-436
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class GroupAddress:
    """Eine einzelne KNX-Gruppenadresse (Untergruppe)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    main_group: int = 0       # 0-31
    middle_group: int = 0     # 0-7
    sub_group: int = 0        # 0-255
    designation: str = ""     # z.B. "LD_E05_01 E/A (Eingang Decke)"
    central: str = ""         # "" oder "true"
    unfiltered: str = ""
    description: str = ""     # Freitext
    datapoint_type: str = ""  # z.B. "DPST-1-1"
    security: str = "Auto"
    # Zusatzfelder
    gewerk_code: str = ""     # z.B. "LD"
    room_number: str = ""     # z.B. "E01"
    room_id: str = ""         # UUID des Raums (eindeutig, verhindert Kollisionen bei gleicher room_number)
    element_number: int = 0   # z.B. 1
    function_name: str = ""   # z.B. "E/A", "DIM", "WERT"
    is_placeholder: bool = False  # Reserve-Platzhalter (FA-434)
    is_manual: bool = False       # Manuell hinzugefügt (kein Auto-GA)

    @property
    def address(self) -> str:
        """Vollständige Gruppenadresse als String."""
        return f"{self.main_group}/{self.middle_group}/{self.sub_group}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "main_group": self.main_group,
            "middle_group": self.middle_group,
            "sub_group": self.sub_group,
            "designation": self.designation,
            "central": self.central,
            "unfiltered": self.unfiltered,
            "description": self.description,
            "datapoint_type": self.datapoint_type,
            "security": self.security,
            "gewerk_code": self.gewerk_code,
            "room_number": self.room_number,
            "room_id": self.room_id,
            "element_number": self.element_number,
            "function_name": self.function_name,
            "is_placeholder": self.is_placeholder,
            "is_manual": self.is_manual,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GroupAddress:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            main_group=data.get("main_group", 0),
            middle_group=data.get("middle_group", 0),
            sub_group=data.get("sub_group", 0),
            designation=data.get("designation", ""),
            central=data.get("central", ""),
            unfiltered=data.get("unfiltered", ""),
            description=data.get("description", ""),
            datapoint_type=data.get("datapoint_type", ""),
            security=data.get("security", "Auto"),
            gewerk_code=data.get("gewerk_code", ""),
            room_number=data.get("room_number", ""),
            room_id=data.get("room_id") or "",
            element_number=data.get("element_number", 0),
            function_name=data.get("function_name", ""),
            is_placeholder=data.get("is_placeholder", False),
            is_manual=data.get("is_manual", False),
        )


@dataclass
class MiddleGroup:
    """Mittelgruppe (FA-421)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    number: int = 0           # 0-7
    name: str = ""            # z.B. "Licht", "Jalousie"
    group_addresses: list[GroupAddress] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "number": self.number,
            "name": self.name,
            "group_addresses": [ga.to_dict() for ga in self.group_addresses],
        }

    @classmethod
    def from_dict(cls, data: dict) -> MiddleGroup:
        mg = cls(
            id=data.get("id", str(uuid.uuid4())),
            number=data.get("number", 0),
            name=data.get("name", ""),
        )
        mg.group_addresses = [
            GroupAddress.from_dict(ga) for ga in data.get("group_addresses", [])
        ]
        return mg


@dataclass
class MainGroup:
    """Hauptgruppe (FA-411)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    number: int = 0           # 0-31
    name: str = ""            # z.B. "Zentral", "EG", "1.OG"
    middle_groups: list[MiddleGroup] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "number": self.number,
            "name": self.name,
            "middle_groups": [mg.to_dict() for mg in self.middle_groups],
        }

    @classmethod
    def from_dict(cls, data: dict) -> MainGroup:
        hg = cls(
            id=data.get("id", str(uuid.uuid4())),
            number=data.get("number", 0),
            name=data.get("name", ""),
        )
        hg.middle_groups = [
            MiddleGroup.from_dict(mg) for mg in data.get("middle_groups", [])
        ]
        return hg


@dataclass
class GroupAddressStructure:
    """Gesamte Gruppenadress-Struktur eines Projekts."""
    main_groups: list[MainGroup] = field(default_factory=list)
    variant: str = "A"   # "A" oder "B" (FA-421)
    source: str = ""     # "topology" | "ga_report" | "csv" — bestimmt Merge-Priorität

    def all_addresses(self) -> list[GroupAddress]:
        """Alle Gruppenadressen flach."""
        result = []
        for mg in self.main_groups:
            for midg in mg.middle_groups:
                result.extend(midg.group_addresses)
        return result

    def find_address(self, main: int, middle: int, sub: int) -> Optional[GroupAddress]:
        for mg in self.main_groups:
            if mg.number == main:
                for midg in mg.middle_groups:
                    if midg.number == middle:
                        for ga in midg.group_addresses:
                            if ga.sub_group == sub:
                                return ga
        return None

    def to_dict(self) -> dict:
        return {
            "main_groups": [mg.to_dict() for mg in self.main_groups],
            "variant": self.variant,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GroupAddressStructure:
        gas = cls(variant=data.get("variant", "A"), source=data.get("source", ""))
        gas.main_groups = [
            MainGroup.from_dict(mg) for mg in data.get("main_groups", [])
        ]
        return gas


# Mittelgruppen-Zuordnung (FA-421)
MIDDLE_GROUP_NAMES_A = {
    0: "Licht",
    1: "Jalousie",
    2: "Heizung / HLK",
    3: "Alarm",
    4: "Allgemein",
    5: "Frei",
    6: "Frei",
    7: "Frei",
}

MIDDLE_GROUP_NAMES_B = {
    0: "Licht",
    1: "Jalousie",
    2: "Heizung / HLK",
    3: "Alarm",
    4: "Allgemein",
    5: "Frei",
    6: "Rückmeldungen Licht",
    7: "Rückmeldungen Jalousie",
}

# Zentraladressen MG-Zuordnung (FA-442)
CENTRAL_MIDDLE_GROUPS = {
    0: "Licht",
    1: "Jalousie",
    2: "Heizung",
    4: "Szenen",
    5: "Wetterstation",
}
