"""
Kundenprofil pro Projekt (FA-851 analog, projektspezifisch)
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ClientProfile:
    """Kundenprofil – wird pro Projekt gespeichert."""
    name: str = ""             # Auftraggeber / Kundenname
    object_address: str = ""   # Objekt / Bauvorhaben (Adresse des Projekts)
    contact_address: str = ""  # Postadresse des Kunden
    phone: str = ""
    email: str = ""
    website: str = ""
    photo_path: str = ""       # Pfad zum Projektfoto / Kundenfoto
    photo_rotation: int = 0    # Drehung in Grad (0 / 90 / 180 / 270)
    photo_source: str = ""     # Quellenangabe zum Foto (erscheint im Bericht darunter)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "object_address": self.object_address,
            "contact_address": self.contact_address,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "photo_path": self.photo_path,
            "photo_rotation": self.photo_rotation,
            "photo_source": self.photo_source,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ClientProfile:
        return cls(
            name=data.get("name", ""),
            object_address=data.get("object_address", ""),
            contact_address=data.get("contact_address", ""),
            phone=data.get("phone", ""),
            email=data.get("email", ""),
            website=data.get("website", ""),
            photo_path=data.get("photo_path", ""),
            photo_rotation=data.get("photo_rotation", 0),
            photo_source=data.get("photo_source", ""),
            notes=data.get("notes", ""),
        )
