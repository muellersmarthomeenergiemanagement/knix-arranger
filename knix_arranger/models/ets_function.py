"""
ETS6-Funktionen (FA-529): in der ETS je Raum angelegte Funktionen
("Jalousien Raum", "Leselampen", ...) mit ihren Gruppenadressen.

Reine ETS-Daten: werden bei jedem .knxproj-Import neu eingelesen und hängen
am Raum. Die Rolle steht so in der ETS ("SwitchOnOff", "MoveUpDown" ...);
eine GA, die schon zu einer anderen Funktion gehört, trägt dort statt der
Rolle eine GUID -- die ersetzt der Import durch die Rolle der anderen
Funktion (siehe KnxprojImportService._resolve_function_refs).
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field


@dataclass
class EtsFunctionRef:
    """Eine Gruppenadresse einer ETS-Funktion."""
    role: str = ""            # ETS-Rolle, z.B. "SwitchOnOff"; "" = unbekannt
    address: str = ""         # "12/1/6"; "" = GA nicht gefunden
    ga_name: str = ""         # Bezeichnung der GA in der ETS
    datapoint_type: str = ""  # "DPST-1-1"

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "address": self.address,
            "ga_name": self.ga_name,
            "datapoint_type": self.datapoint_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EtsFunctionRef:
        return cls(
            role=data.get("role", ""),
            address=data.get("address", ""),
            ga_name=data.get("ga_name", ""),
            datapoint_type=data.get("datapoint_type", ""),
        )


@dataclass
class EtsFunction:
    """Eine Funktion der ETS (Gebäudeansicht, Raum > Funktion)."""
    name: str = ""
    function_type: str = ""   # "FT-7"
    refs: list[EtsFunctionRef] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "function_type": self.function_type,
            "refs": [r.to_dict() for r in self.refs],
        }

    @classmethod
    def from_dict(cls, data: dict) -> EtsFunction:
        return cls(
            name=data.get("name", ""),
            function_type=data.get("function_type", ""),
            refs=[EtsFunctionRef.from_dict(r) for r in data.get("refs", [])],
        )


@dataclass
class FunctionMember:
    """Ein Element eines Gewerks, das die Funktion mitbedient."""
    assignment_id: str = ""   # GewerkAssignment.id
    element_number: int = 1

    def to_dict(self) -> dict:
        return {"assignment_id": self.assignment_id, "element_number": self.element_number}

    @classmethod
    def from_dict(cls, data: dict) -> FunctionMember:
        return cls(data.get("assignment_id", ""), data.get("element_number", 1))


@dataclass
class CustomPoint:
    """Eigener Funktionspunkt einer Funktion (z.B. "SZENE"), von KNiX
    angelegt wie die Standardpunkte des Typs."""
    function: str = ""        # Name in der Bezeichnung, z.B. "SZENE"
    dpt: str = "DPST-1-1"

    def to_dict(self) -> dict:
        return {"function": self.function, "dpt": self.dpt}

    @classmethod
    def from_dict(cls, data: dict) -> CustomPoint:
        return cls(data.get("function", ""), data.get("dpt", "DPST-1-1"))


@dataclass
class KnixFunction:
    """In KNiX geplante Funktion (FA-530): Gruppenbedienung mehrerer Elemente
    eines Raums oder einer Zone, z.B. "Fensterfront" für drei Jalousien.

    Die Funktion hat eigene GAs (GroupAddress.function_id) in der HG des
    Stockwerks, MG des Gewerks ab UG 250 rückwärts -- reine Befehls-GAs, keine
    Rückmeldung. Sie werden zusätzlich zu den GAs der Elemente auf deren
    Aktorkanäle verknüpft und lassen sich auf Tasten legen.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    function_type: str = "FT-7"
    room_id: str = ""         # Raum, oder leer bei einer Zone
    zone_id: str = ""         # Apartment.id bei einer Funktion der Zone
    number: int = 1           # "F1" in der Bezeichnung, je Ort fortlaufend
    members: list[FunctionMember] = field(default_factory=list)
    # Aus einer Gruppenbedienung der ETS übernommen (FA-531): Funktionspunkt
    # -> "Adresse  Bezeichnung" der bestehenden GA. Dann plant KNiX keine
    # eigenen GAs; nach einem Re-Import findet es die GAs darüber wieder.
    ets_gas: dict[str, str] = field(default_factory=dict)
    # GAs je Funktion anpassen: Standardpunkte des Typs, die wegfallen
    # (None = alte Übernahme mit ets_gas: alle Standardpunkte ausser diesen),
    # eigene Punkte, die KNiX zusätzlich anlegt, und bestehende GAs, die die
    # Funktion mitbenutzt (Funktionspunkt -> "Adresse  Bezeichnung"; die GA
    # bleibt, was sie ist, z.B. eine Element- oder Zentral-GA)
    omitted: list[str] | None = field(default_factory=list)
    custom_points: list[CustomPoint] = field(default_factory=list)
    linked_gas: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "function_type": self.function_type,
            "room_id": self.room_id, "zone_id": self.zone_id, "number": self.number,
            "members": [m.to_dict() for m in self.members],
            **({"ets_gas": dict(self.ets_gas)} if self.ets_gas else {}),
            **({"omitted": list(self.omitted)} if self.omitted else {}),
            **({"custom_points": [p.to_dict() for p in self.custom_points]}
               if self.custom_points else {}),
            **({"linked_gas": dict(self.linked_gas)} if self.linked_gas else {}),
        }

    @classmethod
    def from_dict(cls, data: dict) -> KnixFunction:
        return cls(
            id=data.get("id") or str(uuid.uuid4()),
            name=data.get("name", ""),
            function_type=data.get("function_type", "FT-7"),
            room_id=data.get("room_id", ""),
            zone_id=data.get("zone_id", ""),
            number=data.get("number", 1),
            members=[FunctionMember.from_dict(m) for m in data.get("members", [])],
            ets_gas=dict(data.get("ets_gas") or {}),
            # Übernahme vor 1.4.18: nur die GAs aus der ETS
            omitted=(list(data["omitted"]) if "omitted" in data
                     else None if data.get("ets_gas") else []),
            custom_points=[CustomPoint.from_dict(p) for p in data.get("custom_points", [])],
            linked_gas=dict(data.get("linked_gas") or {}),
        )
