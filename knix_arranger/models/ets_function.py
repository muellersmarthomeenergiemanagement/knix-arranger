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
