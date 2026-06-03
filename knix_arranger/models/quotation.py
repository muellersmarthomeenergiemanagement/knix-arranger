"""
Offert-Modelle: Lieferant, Offertanfrage, Kundenofferte
Gemaess FA-1600, FA-1700
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import uuid


@dataclass
class Supplier:
    """Lieferant/Händler (FA-1601)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    company_name: str = ""
    contact_person: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    website: str = ""
    customer_number: str = ""
    category: str = ""        # "Hersteller", "Großhändler", "Fachhandel"
    brands: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "company_name": self.company_name,
            "contact_person": self.contact_person,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "website": self.website,
            "customer_number": self.customer_number,
            "category": self.category,
            "brands": self.brands,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Supplier:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            company_name=data.get("company_name", ""),
            contact_person=data.get("contact_person", ""),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            address=data.get("address", ""),
            website=data.get("website", ""),
            customer_number=data.get("customer_number", ""),
            category=data.get("category", ""),
            brands=data.get("brands", []),
            notes=data.get("notes", ""),
        )


@dataclass
class QuotationItem:
    """Einzelne Position einer Offertanfrage."""
    position: int = 0
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    quantity: int = 1
    unit: str = "Stk."
    unit_price: float = 0.0
    total_price: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "unit": self.unit,
            "unit_price": self.unit_price,
            "total_price": self.total_price,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> QuotationItem:
        return cls(
            position=data.get("position", 0),
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product_name=data.get("product_name", ""),
            quantity=data.get("quantity", 1),
            unit=data.get("unit", "Stk."),
            unit_price=data.get("unit_price", 0.0),
            total_price=data.get("total_price", 0.0),
            notes=data.get("notes", ""),
        )


@dataclass
class QuotationRequest:
    """Offertanfrage an einen Lieferanten (FA-1611)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_number: str = ""  # Automatisch generiert
    supplier_id: str = ""
    date_created: str = ""
    date_sent: str = ""
    delivery_date_requested: str = ""
    status: str = "Entwurf"   # Entwurf, Versendet, Erhalten, Zugeschlagen, Abgelehnt
    items: list[QuotationItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_number": self.request_number,
            "supplier_id": self.supplier_id,
            "date_created": self.date_created,
            "date_sent": self.date_sent,
            "delivery_date_requested": self.delivery_date_requested,
            "status": self.status,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> QuotationRequest:
        qr = cls(
            id=data.get("id", str(uuid.uuid4())),
            request_number=data.get("request_number", ""),
            supplier_id=data.get("supplier_id", ""),
            date_created=data.get("date_created", ""),
            date_sent=data.get("date_sent", ""),
            delivery_date_requested=data.get("delivery_date_requested", ""),
            status=data.get("status", "Entwurf"),
        )
        qr.items = [QuotationItem.from_dict(i) for i in data.get("items", [])]
        return qr


@dataclass
class CustomerQuote:
    """Kundenofferte für den Bauherrn (FA-1700)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    quote_number: str = ""        # z.B. "OF-2026-001"
    revision: str = "A"           # Rev. A, B, C...
    date_created: str = ""
    status: str = "Entwurf"       # Entwurf, Versendet, Akzeptiert, Abgelehnt, Ueberarbeitung
    customer_name: str = ""
    customer_address: str = ""
    # Kosten
    material_total: float = 0.0
    material_markup_percent: float = 15.0
    labor_mounting_hours: float = 0.0
    labor_programming_hours: float = 0.0
    labor_commissioning_hours: float = 0.0
    hourly_rate_mounting: float = 125.0
    hourly_rate_programming: float = 145.0
    hourly_rate_commissioning: float = 145.0
    overhead_costs: float = 0.0
    discount_percent: float = 0.0
    vat_percent: float = 8.1     # CH MwSt.
    validity_days: int = 60
    payment_terms: str = "30 Tage netto"
    items: list[QuotationItem] = field(default_factory=list)
    # Ist-Werte für Nachkalkulation (FA-2201)
    actual_material_cost: float = 0.0
    actual_mounting_hours: float = 0.0
    actual_programming_hours: float = 0.0
    actual_commissioning_hours: float = 0.0
    actual_overhead_costs: float = 0.0

    @property
    def material_with_markup(self) -> float:
        return self.material_total * (1 + self.material_markup_percent / 100)

    @property
    def labor_total(self) -> float:
        return (
            self.labor_mounting_hours * self.hourly_rate_mounting
            + self.labor_programming_hours * self.hourly_rate_programming
            + self.labor_commissioning_hours * self.hourly_rate_commissioning
        )

    @property
    def subtotal(self) -> float:
        return self.material_with_markup + self.labor_total + self.overhead_costs

    @property
    def discount_amount(self) -> float:
        return self.subtotal * self.discount_percent / 100

    @property
    def net_total(self) -> float:
        return self.subtotal - self.discount_amount

    @property
    def vat_amount(self) -> float:
        return self.net_total * self.vat_percent / 100

    @property
    def grand_total(self) -> float:
        return self.net_total + self.vat_amount

    # Nachkalkulation: Berechnete Ist-Werte (FA-2202)

    @property
    def actual_labor_total(self) -> float:
        return (
            self.actual_mounting_hours * self.hourly_rate_mounting
            + self.actual_programming_hours * self.hourly_rate_programming
            + self.actual_commissioning_hours * self.hourly_rate_commissioning
        )

    @property
    def actual_total(self) -> float:
        return self.actual_material_cost + self.actual_labor_total + self.actual_overhead_costs

    @property
    def delta_material(self) -> float:
        return self.actual_material_cost - self.material_with_markup

    @property
    def delta_labor(self) -> float:
        return self.actual_labor_total - self.labor_total

    @property
    def delta_total(self) -> float:
        return self.actual_total - self.net_total

    @property
    def delta_percent(self) -> float:
        if self.net_total > 0:
            return (self.delta_total / self.net_total) * 100
        return 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "quote_number": self.quote_number,
            "revision": self.revision,
            "date_created": self.date_created,
            "status": self.status,
            "customer_name": self.customer_name,
            "customer_address": self.customer_address,
            "material_total": self.material_total,
            "material_markup_percent": self.material_markup_percent,
            "labor_mounting_hours": self.labor_mounting_hours,
            "labor_programming_hours": self.labor_programming_hours,
            "labor_commissioning_hours": self.labor_commissioning_hours,
            "hourly_rate_mounting": self.hourly_rate_mounting,
            "hourly_rate_programming": self.hourly_rate_programming,
            "hourly_rate_commissioning": self.hourly_rate_commissioning,
            "overhead_costs": self.overhead_costs,
            "discount_percent": self.discount_percent,
            "vat_percent": self.vat_percent,
            "validity_days": self.validity_days,
            "payment_terms": self.payment_terms,
            "items": [i.to_dict() for i in self.items],
            "actual_material_cost": self.actual_material_cost,
            "actual_mounting_hours": self.actual_mounting_hours,
            "actual_programming_hours": self.actual_programming_hours,
            "actual_commissioning_hours": self.actual_commissioning_hours,
            "actual_overhead_costs": self.actual_overhead_costs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CustomerQuote:
        cq = cls(
            id=data.get("id", str(uuid.uuid4())),
            quote_number=data.get("quote_number", ""),
            revision=data.get("revision", "A"),
            date_created=data.get("date_created", ""),
            status=data.get("status", "Entwurf"),
            customer_name=data.get("customer_name", ""),
            customer_address=data.get("customer_address", ""),
            material_total=data.get("material_total", 0.0),
            material_markup_percent=data.get("material_markup_percent", 15.0),
            labor_mounting_hours=data.get("labor_mounting_hours", 0.0),
            labor_programming_hours=data.get("labor_programming_hours", 0.0),
            labor_commissioning_hours=data.get("labor_commissioning_hours", 0.0),
            hourly_rate_mounting=data.get("hourly_rate_mounting", 125.0),
            hourly_rate_programming=data.get("hourly_rate_programming", 145.0),
            hourly_rate_commissioning=data.get("hourly_rate_commissioning", 145.0),
            overhead_costs=data.get("overhead_costs", 0.0),
            discount_percent=data.get("discount_percent", 0.0),
            vat_percent=data.get("vat_percent", 8.1),
            validity_days=data.get("validity_days", 60),
            payment_terms=data.get("payment_terms", "30 Tage netto"),
            actual_material_cost=data.get("actual_material_cost", 0.0),
            actual_mounting_hours=data.get("actual_mounting_hours", 0.0),
            actual_programming_hours=data.get("actual_programming_hours", 0.0),
            actual_commissioning_hours=data.get("actual_commissioning_hours", 0.0),
            actual_overhead_costs=data.get("actual_overhead_costs", 0.0),
        )
        cq.items = [QuotationItem.from_dict(i) for i in data.get("items", [])]
        return cq
