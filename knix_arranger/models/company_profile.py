"""
Firmenprofil und Projektinfo (FA-851 bis FA-857)
"""
from __future__ import annotations
from dataclasses import dataclass, field
import uuid

from ..utils.manufacturers import manufacturer_display_name


@dataclass
class CompanyProfile:
    """Firmenprofil des Anwenders (FA-851, FA-852)."""
    company_name: str = ""
    logo_path: str = ""       # Pfad zur Logo-Datei
    user_name: str = ""       # Vor- und Nachname
    role: str = ""            # z.B. "KNX-Systemintegrator"
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    customer_reference: str = ""
    # Stundensaetze (FA-1703)
    hourly_rate_mounting: float = 125.0
    hourly_rate_programming: float = 145.0
    hourly_rate_commissioning: float = 145.0
    hourly_rate_documentation: float = 125.0
    material_markup_percent: float = 15.0
    overhead_per_device: float = 5.0
    # Aufwandsschätzung Kalkulation (FA-1707): Richtwerte angelehnt an die
    # ZVEH-Kalkulationshilfe (KFE) für Elektro-/Informationstechnik-Handwerke,
    # ca. 20-25 Min./Gerät für Projektierung bzw. Inbetriebnahme.
    minutes_programming_per_device: float = 22.0
    minutes_commissioning_per_device: float = 22.0
    commissioning_base_hours: float = 2.0
    # Dokumentation (Revisionspaket, Übergabeunterlagen): kein publizierter
    # Richtwert verfügbar -- niedriger angesetzt als Programmierung, da die
    # Inhalte (GA-Listen, Pläne, Checklisten) bereits automatisch aus dem
    # Projekt generiert werden und v.a. Prüf-/Zusammenstellungsaufwand anfällt.
    minutes_documentation_per_device: float = 5.0
    documentation_base_hours: float = 1.0
    # Bevorzugte Hersteller (FA-1304)
    preferred_manufacturers: list[str] = field(default_factory=list)
    # Standardtexte (FA-1715)
    payment_terms: str = "30 Tage netto"
    quote_validity_days: int = 60

    def to_dict(self) -> dict:
        return {
            "company_name": self.company_name,
            "logo_path": self.logo_path,
            "user_name": self.user_name,
            "role": self.role,
            "address": self.address,
            "phone": self.phone,
            "email": self.email,
            "website": self.website,
            "customer_reference": self.customer_reference,
            "hourly_rate_mounting": self.hourly_rate_mounting,
            "hourly_rate_programming": self.hourly_rate_programming,
            "hourly_rate_commissioning": self.hourly_rate_commissioning,
            "hourly_rate_documentation": self.hourly_rate_documentation,
            "material_markup_percent": self.material_markup_percent,
            "overhead_per_device": self.overhead_per_device,
            "minutes_programming_per_device": self.minutes_programming_per_device,
            "minutes_commissioning_per_device": self.minutes_commissioning_per_device,
            "commissioning_base_hours": self.commissioning_base_hours,
            "minutes_documentation_per_device": self.minutes_documentation_per_device,
            "documentation_base_hours": self.documentation_base_hours,
            "preferred_manufacturers": self.preferred_manufacturers,
            "payment_terms": self.payment_terms,
            "quote_validity_days": self.quote_validity_days,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CompanyProfile:
        return cls(
            company_name=data.get("company_name", ""),
            logo_path=data.get("logo_path", ""),
            user_name=data.get("user_name", ""),
            role=data.get("role", ""),
            address=data.get("address", ""),
            phone=data.get("phone", ""),
            email=data.get("email", ""),
            website=data.get("website", ""),
            customer_reference=data.get("customer_reference", ""),
            hourly_rate_mounting=data.get("hourly_rate_mounting", 125.0),
            hourly_rate_programming=data.get("hourly_rate_programming", 145.0),
            hourly_rate_commissioning=data.get("hourly_rate_commissioning", 145.0),
            hourly_rate_documentation=data.get("hourly_rate_documentation", 125.0),
            material_markup_percent=data.get("material_markup_percent", 15.0),
            overhead_per_device=data.get("overhead_per_device", 5.0),
            minutes_programming_per_device=data.get("minutes_programming_per_device", 22.0),
            minutes_commissioning_per_device=data.get("minutes_commissioning_per_device", 22.0),
            commissioning_base_hours=data.get("commissioning_base_hours", 2.0),
            minutes_documentation_per_device=data.get("minutes_documentation_per_device", 5.0),
            documentation_base_hours=data.get("documentation_base_hours", 1.0),
            preferred_manufacturers=list(dict.fromkeys(
                manufacturer_display_name(m) for m in data.get("preferred_manufacturers", [])
            )),
            payment_terms=data.get("payment_terms", "30 Tage netto"),
            quote_validity_days=data.get("quote_validity_days", 60),
        )


@dataclass
class ProjectInfo:
    """Projektspezifische Angaben (FA-853)."""
    project_name: str = ""
    project_number: str = ""
    client_name: str = ""
    project_address: str = ""
    date: str = ""

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "project_number": self.project_number,
            "client_name": self.client_name,
            "project_address": self.project_address,
            "date": self.date,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectInfo:
        return cls(
            project_name=data.get("project_name", ""),
            project_number=data.get("project_number", ""),
            client_name=data.get("client_name", ""),
            project_address=data.get("project_address", ""),
            date=data.get("date", ""),
        )
