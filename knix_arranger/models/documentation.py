"""
Dokumentations-Modelle: Inbetriebnahme-Checkliste, Abnahmeprotokoll
Gemaess FA-1900, FA-2000, FA-2100
"""
from __future__ import annotations
from dataclasses import dataclass, field
import uuid


ITEM_KIND_DEVICE   = "device"     # Geräte-Grundprüfung (Montage, Adresse …)
ITEM_KIND_FUNCTION = "function"   # GA-Funktionsprüfung (Kanal → GA)

RESULT_OPEN   = ""
RESULT_OK     = "OK"
RESULT_DEFECT = "Mangel"
RESULT_NA     = "n/a"

RESULT_CHOICES = [RESULT_OPEN, RESULT_OK, RESULT_DEFECT, RESULT_NA]


@dataclass
class ChecklistItem:
    """Einzelner Pruefpunkt der Inbetriebnahme-Checkliste (FA-1902)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    item_kind: str = ITEM_KIND_DEVICE   # "device" | "function"
    check_type: str = ""      # z.B. "Montage", "Kanal 1"
    description: str = ""     # Beschreibungstext / Funktionsname
    function_ga: str = ""     # GA-Bezeichnung (nur kind=function)
    result: str = RESULT_OPEN # "", "OK", "Mangel", "n/a"
    notes: str = ""
    room_id: str = ""
    be_id: str = ""           # Bedienelement-ID (kann sich bei Rebuild ändern)
    be_type: str = ""         # Stabiler Schlüssel: element_type des BE
    be_number: str = ""       # Stabiler Schlüssel: participant_number des BE
    gewerk_code: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "item_kind": self.item_kind,
            "check_type": self.check_type,
            "description": self.description,
            "function_ga": self.function_ga,
            "result": self.result,
            "notes": self.notes,
            "room_id": self.room_id,
            "be_id": self.be_id,
            "be_type": self.be_type,
            "be_number": self.be_number,
            "gewerk_code": self.gewerk_code,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChecklistItem:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            item_kind=data.get("item_kind", ITEM_KIND_DEVICE),
            check_type=data.get("check_type", ""),
            description=data.get("description", ""),
            function_ga=data.get("function_ga", ""),
            result=data.get("result", RESULT_OPEN),
            notes=data.get("notes", ""),
            room_id=data.get("room_id", ""),
            be_id=data.get("be_id", ""),
            be_type=data.get("be_type", ""),
            be_number=data.get("be_number", ""),
            gewerk_code=data.get("gewerk_code", ""),
        )


@dataclass
class CommissioningChecklist:
    """Inbetriebnahme-Checkliste (FA-1901)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    room_id: str = ""
    room_name: str = ""
    date: str = ""
    technician: str = ""
    items: list[ChecklistItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "room_name": self.room_name,
            "date": self.date,
            "technician": self.technician,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> CommissioningChecklist:
        cl = cls(
            id=data.get("id", str(uuid.uuid4())),
            room_id=data.get("room_id", ""),
            room_name=data.get("room_name", ""),
            date=data.get("date", ""),
            technician=data.get("technician", ""),
        )
        cl.items = [ChecklistItem.from_dict(i) for i in data.get("items", [])]
        return cl


@dataclass
class Defect:
    """Einzelner Mangel (FA-1913)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    number: int = 0
    room_name: str = ""
    gewerk_code: str = ""
    description: str = ""
    priority: str = "unkritisch"  # "kritisch" oder "unkritisch"
    status: str = "offen"         # "offen", "in Bearbeitung", "behoben"
    due_date: str = ""
    resolved_date: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "number": self.number,
            "room_name": self.room_name,
            "gewerk_code": self.gewerk_code,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "due_date": self.due_date,
            "resolved_date": self.resolved_date,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Defect:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            number=data.get("number", 0),
            room_name=data.get("room_name", ""),
            gewerk_code=data.get("gewerk_code", ""),
            description=data.get("description", ""),
            priority=data.get("priority", "unkritisch"),
            status=data.get("status", "offen"),
            due_date=data.get("due_date", ""),
            resolved_date=data.get("resolved_date", ""),
        )


@dataclass
class AcceptanceProtocol:
    """Abnahmeprotokoll (FA-1911)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    date: str = ""
    integrator_name: str = ""
    integrator_role: str = ""
    client_name: str = ""
    result: str = ""              # "Abnahme erfolgt", "Unter Vorbehalt", "Verweigert"
    defects: list[Defect] = field(default_factory=list)
    checklists: list[CommissioningChecklist] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "date": self.date,
            "integrator_name": self.integrator_name,
            "integrator_role": self.integrator_role,
            "client_name": self.client_name,
            "result": self.result,
            "defects": [d.to_dict() for d in self.defects],
            "checklists": [c.to_dict() for c in self.checklists],
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AcceptanceProtocol:
        ap = cls(
            id=data.get("id", str(uuid.uuid4())),
            date=data.get("date", ""),
            integrator_name=data.get("integrator_name", ""),
            integrator_role=data.get("integrator_role", ""),
            client_name=data.get("client_name", ""),
            result=data.get("result", ""),
            notes=data.get("notes", ""),
        )
        ap.defects = [Defect.from_dict(d) for d in data.get("defects", [])]
        ap.checklists = [
            CommissioningChecklist.from_dict(c) for c in data.get("checklists", [])
        ]
        return ap
