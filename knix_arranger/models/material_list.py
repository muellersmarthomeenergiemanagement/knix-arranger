"""
Materiallisten-Datenmodell (FA-2301 bis FA-2308)
Enthält alle KNX-Geräte des Projekts mit Hersteller, Bestellnummer und Menge.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re
import uuid


def parse_channel_count(device_type: str) -> int:
    """Extrahiert die Kanalanzahl aus einem Gerätetyp-String.

    Beispiele:
        "Schaltaktor 8-fach"  → 8
        "Dimmaktor 4-fach"    → 4
        "Jalousieaktor 2-fach" → 2
        "Linienkoppler"       → 0  (keine Kanalangabe)
    """
    if not device_type:
        return 0
    match = re.search(r'(\d+)\s*-\s*fach', device_type, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 0


def split_device_type(device_type: str, new_channels: int) -> str:
    """Ersetzt die Kanalanzahl in einem Gerätetyp-String.

    Beispiel: split_device_type("Schaltaktor 16-fach", 8) → "Schaltaktor 8-fach"
    """
    if not device_type:
        return device_type
    return re.sub(r'\d+(\s*-\s*fach)', f'{new_channels}\\1', device_type, flags=re.IGNORECASE)

# Kategorien für die Materialliste
MATERIAL_CATEGORIES = [
    "Aktor",
    "Sensor",
    "Gateway / Schnittstellen",   # FA-1308: LDA, MM, WP
    "Linienkoppler",
    "Bereichskoppler",
    "IP-Router",
    "Netzteil",
    "DALI-Gateway",
    "Sonstiges",
]


@dataclass
class MaterialEntry:
    """Eine Position in der Materialliste (FA-2301)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    quantity: int = 1
    category: str = "Sonstiges"       # aus MATERIAL_CATEGORIES
    device_type: str = ""             # z.B. "Schaltaktor 8-fach"
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    unit_price: float = 0.0
    source: str = "manual"            # "wizard_auto" | "manual"
    note: str = ""
    installation_location: str = ""   # Einbauort, z.B. "UV2 Wohnbereich" oder Raumbezeichnung
    # Topologie-Verknüpfung (FA-2309)
    line_id: str = ""                 # Topology.Line.id
    line_name: str = ""               # z.B. "1.1.0 Erdgeschoss"
    physical_addresses: list[str] = field(default_factory=list)  # z.B. ["1.1.1"]
    device_id: str = ""               # Topology.Device.id – für Produktrückkopplung
    # Kanalvalidierung
    required_channels: int = 0        # Benötigte Kanäle (aus Platzhalter-Typ, z.B. 16 bei "Schaltaktor 16-fach")
    assigned_channels: int = 0        # Kanäle des zugewiesenen physischen Produkts
    # GA-Bedarf aus KNXPROD-ComObjects
    ga_min: int = 0                   # Minimaler GA-Bedarf (Basis-ComObjects je Gerät)
    ga_max: int = 0                   # Maximaler GA-Bedarf (alle aktiven ComObjects je Gerät)
    # KNX Secure (FA-2705)
    secure_supported: bool = False    # True wenn Gerät KNX Secure (TP/IP) unterstützt

    @property
    def total_price(self) -> float:
        return self.quantity * self.unit_price

    @property
    def channel_deficit(self) -> int:
        """Fehlende Kanäle für diesen Eintrag gesamt (0 = vollständig abgedeckt).

        Berücksichtigt quantity: quantity × assigned_channels wird mit
        required_channels verglichen. Beispiele:
          required=16, qty=1, assigned=8  → 16 − 1×8  = 8  (Defizit)
          required=16, qty=2, assigned=8  → 16 − 2×8  = 0  (gedeckt)
          required=8,  qty=1, assigned=4  → 8  − 1×4  = 4  (Defizit)
          required=8,  qty=2, assigned=4  → 8  − 2×4  = 0  (gedeckt)
        """
        if self.required_channels > 0 and self.assigned_channels > 0:
            return max(0, self.required_channels - self.quantity * self.assigned_channels)
        return 0

    @property
    def physical_address_display(self) -> str:
        """
        Gibt physikalische Adressen als kompakten String zurück.
        Sequentielle Adressen werden als Range dargestellt: "1.1.1 – 1.1.3"
        Nicht-sequentielle als komma-separierte Liste.
        """
        if not self.physical_addresses:
            return ""
        if len(self.physical_addresses) == 1:
            return self.physical_addresses[0]

        # Prüfen ob alle Adressen auf derselben Linie und sequentiell sind
        try:
            parsed = [tuple(int(x) for x in a.split(".")) for a in self.physical_addresses]
            areas = {p[0] for p in parsed}
            lines = {p[1] for p in parsed}
            participants = sorted(p[2] for p in parsed)

            if len(areas) == 1 and len(lines) == 1:
                a, l = parsed[0][0], parsed[0][1]
                # Sequentiell prüfen
                if participants == list(range(participants[0], participants[-1] + 1)):
                    return f"{a}.{l}.{participants[0]} – {a}.{l}.{participants[-1]}"
        except (ValueError, IndexError):
            pass

        return ", ".join(self.physical_addresses)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "quantity": self.quantity,
            "category": self.category,
            "device_type": self.device_type,
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "unit_price": self.unit_price,
            "source": self.source,
            "note": self.note,
            "installation_location": self.installation_location,
            "line_id": self.line_id,
            "line_name": self.line_name,
            "physical_addresses": self.physical_addresses,
            "device_id": self.device_id,
            "required_channels": self.required_channels,
            "assigned_channels": self.assigned_channels,
            "ga_min": self.ga_min,
            "ga_max": self.ga_max,
            "secure_supported": self.secure_supported,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MaterialEntry:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            quantity=data.get("quantity", 1),
            category=data.get("category", "Sonstiges"),
            device_type=data.get("device_type", ""),
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product_name=data.get("product_name", ""),
            unit_price=data.get("unit_price", 0.0),
            source=data.get("source", "manual"),
            note=data.get("note", ""),
            installation_location=data.get("installation_location", ""),
            line_id=data.get("line_id", ""),
            line_name=data.get("line_name", ""),
            physical_addresses=data.get("physical_addresses", []),
            device_id=data.get("device_id", ""),
            required_channels=data.get("required_channels", 0),
            assigned_channels=data.get("assigned_channels", 0),
            ga_min=data.get("ga_min", 0),
            ga_max=data.get("ga_max", 0),
            secure_supported=data.get("secure_supported", False),
        )


@dataclass
class MaterialList:
    """Vollständige Materialliste eines KNX-Projekts (FA-2302)."""
    entries: list[MaterialEntry] = field(default_factory=list)

    # --- Abfragen ---

    def by_category(self, category: str) -> list[MaterialEntry]:
        return [e for e in self.entries if e.category == category]

    @property
    def total_price(self) -> float:
        return sum(e.total_price for e in self.entries)

    @property
    def total_quantity(self) -> int:
        return sum(e.quantity for e in self.entries)

    def is_empty(self) -> bool:
        return len(self.entries) == 0

    # --- Bearbeitung ---

    def add(self, entry: MaterialEntry):
        """Fügt eine Position hinzu oder erhöht die Menge bei gleichem Produkt."""
        existing = self._find_matching(entry)
        if existing:
            existing.quantity += entry.quantity
        else:
            self.entries.append(entry)

    def add_or_update(self, entry: MaterialEntry):
        """Fügt hinzu oder ersetzt bei gleicher ID."""
        for i, e in enumerate(self.entries):
            if e.id == entry.id:
                self.entries[i] = entry
                return
        self.entries.append(entry)

    def remove(self, entry_id: str):
        self.entries = [e for e in self.entries if e.id != entry_id]

    def clear_auto_entries(self):
        """Entfernt alle automatisch ermittelten Positionen (Wizard-Re-Run)."""
        self.entries = [e for e in self.entries if e.source != "wizard_auto"]

    def _find_matching(self, entry: MaterialEntry) -> MaterialEntry | None:
        """Sucht nach Eintrag mit gleichem Produkt (für Mengenaggregation)."""
        if not entry.order_number:
            return None
        for e in self.entries:
            if (e.order_number == entry.order_number
                    and e.manufacturer == entry.manufacturer
                    and e.source == entry.source):
                return e
        return None

    # --- Serialisierung ---

    def to_dict(self) -> dict:
        return {"entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, data: dict) -> MaterialList:
        return cls(
            entries=[MaterialEntry.from_dict(e) for e in data.get("entries", [])]
        )
