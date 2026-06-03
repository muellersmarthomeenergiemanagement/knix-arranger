"""
KNX-Topologie-Modelle: Bereich, Linie, Gerät, Kommunikationsobjekt
Gemaess FA-200, FA-221-223
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class CommunicationObject:
    """KNX-Kommunikationsobjekt eines Geräts (FA-515)."""
    object_number: int = 0
    name: str = ""                # z.B. "Ausgang A"
    object_function: str = ""     # z.B. "Schalten"
    priority: str = "Niedrig"
    flags: str = ""               # z.B. "K-SUEA-"
    data_type: str = ""           # z.B. "1 bit"
    connected_gas: list[str] = field(default_factory=list)  # z.B. ["3/0/65"]

    def to_dict(self) -> dict:
        return {
            "object_number": self.object_number,
            "name": self.name,
            "object_function": self.object_function,
            "priority": self.priority,
            "flags": self.flags,
            "data_type": self.data_type,
            "connected_gas": self.connected_gas,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CommunicationObject:
        return cls(
            object_number=data.get("object_number", 0),
            name=data.get("name", ""),
            object_function=data.get("object_function", ""),
            priority=data.get("priority", "Niedrig"),
            flags=data.get("flags", ""),
            data_type=data.get("data_type", ""),
            connected_gas=data.get("connected_gas", []),
        )


@dataclass
class Device:
    """KNX-Busteilnehmer/Gerät auf einer Linie (FA-514)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    physical_address: str = ""    # Format B.L.T, z.B. "1.1.1"
    manufacturer: str = ""
    order_number: str = ""
    product: str = ""             # Gerätetyp-Bezeichnung, z.B. "Schaltaktor 8-fach"
    product_name: str = ""        # Hersteller-Produktbezeichnung (nach manueller Zuweisung)
    application_program: str = ""
    installation_location: str = ""  # Einbauort, z.B. "UV2 (Steigzone)"
    serial_number: str = ""
    datasheets: list[str] = field(default_factory=list)
    communication_objects: list[CommunicationObject] = field(default_factory=list)
    # Typ: "actor", "sensor", "coupler", "power_supply", "gateway", "other"
    # "gateway" = Fremdsystem-Schnittstelle (DALI-Gateway, Modbus-KNX-Gateway, IP-KNX-Gateway)
    #             fuer Gewerke mit interface_type="gateway" (FA-1307)
    device_type: str = "other"
    # Optionale Zuordnung zu einem Raum (room.id) – wird beim Import gesetzt
    room_id: str = ""
    # Manuell aufgeteilt (kanalbasierter Split) – schützt vor Wizard-Überschreibung
    manually_split: bool = False
    # Manuell durch Benutzer hinzugefügt (nicht auto-generiert)
    manually_added: bool = False
    # Manuell zugewiesene Funktionen (Gewerk-Codes, z.B. ["L", "J"] + "SZ" für Szenen)
    manual_functions: list[str] = field(default_factory=list)
    # Physikalische Adresse wurde in das Gerät programmiert (ETS-Download).
    # Solange dieses Flag gesetzt ist, wird die Teilnehmernummer nie automatisch
    # geändert – auch nicht bei Topologie-Neuberechnungen.
    is_programmed: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "physical_address": self.physical_address,
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product": self.product,
            "product_name": self.product_name,
            "application_program": self.application_program,
            "installation_location": self.installation_location,
            "serial_number": self.serial_number,
            "datasheets": self.datasheets,
            "communication_objects": [co.to_dict() for co in self.communication_objects],
            "device_type": self.device_type,
            "room_id": self.room_id,
            "manually_split": self.manually_split,
            "manually_added": self.manually_added,
            "manual_functions": self.manual_functions,
            "is_programmed": self.is_programmed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Device:
        d = cls(
            id=data.get("id", str(uuid.uuid4())),
            physical_address=data.get("physical_address", ""),
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product=data.get("product", ""),
            product_name=data.get("product_name", ""),
            application_program=data.get("application_program", ""),
            installation_location=data.get("installation_location", ""),
            serial_number=data.get("serial_number", ""),
            datasheets=data.get("datasheets", []),
            device_type=data.get("device_type", "other"),
            room_id=data.get("room_id", ""),
            manually_split=data.get("manually_split", False),
            manually_added=data.get("manually_added", False),
            manual_functions=data.get("manual_functions", []),
            is_programmed=data.get("is_programmed", False),
        )
        d.communication_objects = [
            CommunicationObject.from_dict(co)
            for co in data.get("communication_objects", [])
        ]
        return d


@dataclass
class Line:
    """KNX-Linie (kleinste topologische Einheit)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    line_number: int = 0          # 0-15
    name: str = ""                # z.B. "Erdgeschoss"
    coupler_address: str = ""     # z.B. "1.1.0" (Linienkoppler)
    assigned_floor_ids: list[str] = field(default_factory=list)
    assigned_room_ids: list[str] = field(default_factory=list)
    uv_location: str = ""         # Zugeordnete UV, z.B. "UV2"
    devices: list[Device] = field(default_factory=list)
    # Berechnet
    device_count: int = 0
    recommended_power_supply: bool = True  # T-06: jede Linie braucht SV
    # Leitungslaengen (FA-2601)
    topology_form: str = "Linie"            # "Linie" | "Stern" | "Baum"
    trunk_length: float = 0.0              # Stammleitung in Metern
    branch_lengths: list[float] = field(default_factory=list)  # Stichleitungen in Metern

    def update_device_count(self):
        self.device_count = len(self.devices)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "line_number": self.line_number,
            "name": self.name,
            "coupler_address": self.coupler_address,
            "assigned_floor_ids": self.assigned_floor_ids,
            "assigned_room_ids": self.assigned_room_ids,
            "uv_location": self.uv_location,
            "devices": [d.to_dict() for d in self.devices],
            "device_count": self.device_count,
            "topology_form": self.topology_form,
            "trunk_length": self.trunk_length,
            "branch_lengths": self.branch_lengths,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Line:
        line = cls(
            id=data.get("id", str(uuid.uuid4())),
            line_number=data.get("line_number", 0),
            name=data.get("name", ""),
            coupler_address=data.get("coupler_address", ""),
            assigned_floor_ids=data.get("assigned_floor_ids", []),
            assigned_room_ids=data.get("assigned_room_ids", []),
            uv_location=data.get("uv_location", ""),
            device_count=data.get("device_count", 0),
            topology_form=data.get("topology_form", "Linie"),
            trunk_length=float(data.get("trunk_length", 0.0)),
            branch_lengths=[float(v) for v in data.get("branch_lengths", [])],
        )
        line.devices = [Device.from_dict(d) for d in data.get("devices", [])]
        return line


@dataclass
class Area:
    """KNX-Bereich (Zusammenfassung von Linien)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    area_number: int = 0          # 1-15
    name: str = ""                # z.B. "Westfluegel"
    coupler_address: str = ""     # Bereichskoppler B.0.0
    backbone_type: str = "TP"     # "TP" oder "IP"
    lines: list[Line] = field(default_factory=list)
    # Speisegerät für die Bereichslinie (T-06) – nur bei mehreren Bereichen
    backbone_power_supply: Optional[Device] = field(default=None)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "area_number": self.area_number,
            "name": self.name,
            "coupler_address": self.coupler_address,
            "backbone_type": self.backbone_type,
            "lines": [l.to_dict() for l in self.lines],
            "backbone_power_supply": (
                self.backbone_power_supply.to_dict()
                if self.backbone_power_supply else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Area:
        a = cls(
            id=data.get("id", str(uuid.uuid4())),
            area_number=data.get("area_number", 0),
            name=data.get("name", ""),
            coupler_address=data.get("coupler_address", ""),
            backbone_type=data.get("backbone_type", "TP"),
        )
        a.lines = [Line.from_dict(l) for l in data.get("lines", [])]
        bps = data.get("backbone_power_supply")
        a.backbone_power_supply = Device.from_dict(bps) if bps else None
        return a


@dataclass
class Topology:
    """Gesamte KNX-Topologie eines Projekts."""
    areas: list[Area] = field(default_factory=list)
    topology_mode: str = "TP-256"  # "TP-64" oder "TP-256"
    backbone_type: str = "TP"      # "TP" oder "IP"
    # True, wenn die Topologie aus einer ETS-Datei importiert wurde.
    # Verhindert versehentliches Überschreiben durch den Wizard (FA-ImportGuard).
    is_imported: bool = False

    # Konstanten (T-01 bis T-11)
    MAX_DEVICES_TP256: int = 256
    MAX_DEVICES_TP64: int = 64
    RECOMMENDED_DEVICES: int = 85   # T-03
    MAX_REALIZED_DEVICES: int = 100 # T-03
    MAX_LINES_PER_AREA: int = 15    # T-04
    MAX_AREAS: int = 15             # T-05

    @property
    def max_devices_per_line(self) -> int:
        if self.topology_mode == "TP-64":
            return self.MAX_DEVICES_TP64
        return self.MAX_DEVICES_TP256

    def to_dict(self) -> dict:
        return {
            "areas": [a.to_dict() for a in self.areas],
            "topology_mode": self.topology_mode,
            "backbone_type": self.backbone_type,
            "is_imported": self.is_imported,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Topology:
        t = cls(
            topology_mode=data.get("topology_mode", "TP-256"),
            backbone_type=data.get("backbone_type", "TP"),
            is_imported=data.get("is_imported", False),
        )
        t.areas = [Area.from_dict(a) for a in data.get("areas", [])]
        return t
