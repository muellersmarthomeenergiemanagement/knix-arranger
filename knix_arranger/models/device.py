"""
Geräte-Modelle: Aktor, Sensor, Produktinfo
Gemaess FA-1200, FA-1300, FA-1400
"""
from __future__ import annotations
from dataclasses import dataclass, field
import uuid


@dataclass
class ProductInfo:
    """Produktinformation für Aktoren und Sensoren (FA-1205)."""
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    application_program: str = ""
    price: float = 0.0
    datasheets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "manufacturer": self.manufacturer,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "application_program": self.application_program,
            "price": self.price,
            "datasheets": self.datasheets,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProductInfo:
        return cls(
            manufacturer=data.get("manufacturer", ""),
            order_number=data.get("order_number", ""),
            product_name=data.get("product_name", ""),
            application_program=data.get("application_program", ""),
            price=data.get("price", 0.0),
            datasheets=data.get("datasheets", []),
        )


@dataclass
class Actor:
    """KNX-Aktor (FA-1301, FA-1302)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    actor_type: str = ""          # z.B. "Schaltaktor", "Dimmaktor", "Jalousieaktor"
    channels: int = 1             # Anzahl Kanäle, z.B. 4, 8, 12
    product: ProductInfo = field(default_factory=ProductInfo)
    line_id: str = ""             # Zugeordnete Linie
    uv_location: str = ""         # z.B. "UV2 (Steigzone)"
    # Kanalzuordnungen
    channel_gewerk_map: dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actor_type": self.actor_type,
            "channels": self.channels,
            "product": self.product.to_dict(),
            "line_id": self.line_id,
            "uv_location": self.uv_location,
            "channel_gewerk_map": self.channel_gewerk_map,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Actor:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            actor_type=data.get("actor_type", ""),
            channels=data.get("channels", 1),
            product=ProductInfo.from_dict(data.get("product", {})),
            line_id=data.get("line_id", ""),
            uv_location=data.get("uv_location", ""),
            channel_gewerk_map=data.get("channel_gewerk_map", {}),
        )


@dataclass
class Sensor:
    """KNX-Sensor (FA-1401)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sensor_type: str = ""         # z.B. "Tastereinheit", "Präsenzmelder", "Raumthermostat"
    product: ProductInfo = field(default_factory=ProductInfo)
    room_id: str = ""             # Zugeordneter Raum
    buttons_channels: int = 1     # Anzahl Tasten/Kanäle
    # Physischer Taster-Index (1 = Standard, 2 = zweiter Taster, …)
    taster_index: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sensor_type": self.sensor_type,
            "product": self.product.to_dict(),
            "room_id": self.room_id,
            "buttons_channels": self.buttons_channels,
            "taster_index": self.taster_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Sensor:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            sensor_type=data.get("sensor_type", ""),
            product=ProductInfo.from_dict(data.get("product", {})),
            room_id=data.get("room_id", ""),
            buttons_channels=data.get("buttons_channels", 1),
            taster_index=data.get("taster_index", 1),
        )


# Standard-Aktortyp-Zuordnung nach Gewerk (FA-1301)
# Gateway-Gewerke (FA-1307): LDA, MM, WP liefern ein Schnittstellengeraet statt eines klassischen Aktors.
GEWERK_TO_ACTOR_TYPE = {
    # Licht
    "L":   "Schaltaktor",
    "LD":  "Dimmaktor",
    "LDA": "DALI-Gateway",          # FA-1307: Gateway
    "LC":  "RGB-Dimmaktor",
    "LCT": "Tunable-White-Aktor",
    "LCW": "RGBW-Dimmaktor",
    "DMX": "DMX-KNX-Gateway",       # Gateway
    "S":   "Schaltaktor",
    "SD":  "Dimmaktor",
    # Jalousie/Beschattung
    "J":   "Jalousieaktor",
    "R":   "Jalousieaktor",
    "M":   "Jalousieaktor",
    "T":   "Jalousieaktor",
    "DF":  "Jalousieaktor",
    # Heizung/Klima
    "H":   "Heizungsaktor",
    "WP":  "Modbus-KNX-Gateway",    # FA-1307: Gateway
    # Lueftung
    "LU":  "KWL-KNX-Gateway",       # Gateway
    "KL":  "Klima-KNX-Gateway",     # Gateway
    # Energie
    "EV":  "Wallbox-KNX-Gateway",   # Gateway
    "PV":  "PV-KNX-Gateway",        # Gateway
    "SP":  "Speicher-KNX-Gateway",  # Gateway
    # Allgemein
    "V":   "Schaltaktor",
    "G":   "Schaltaktor",
    "BW":  "Schaltaktor",
    "BL":  "Schaltaktor",
    "P":   "Schaltaktor",
    "MM":  "KNX-Schnittstelle",     # FA-1307: Gateway
}

# FA-1307: Aktortypen, die als Device mit device_type="gateway" geplant werden.
GATEWAY_ACTOR_TYPES: frozenset[str] = frozenset({
    "DALI-Gateway",
    "DMX-KNX-Gateway",
    "KNX-Schnittstelle",
    "Modbus-KNX-Gateway",
    "KWL-KNX-Gateway",
    "Klima-KNX-Gateway",
    "Wallbox-KNX-Gateway",
    "PV-KNX-Gateway",
    "Speicher-KNX-Gateway",
})

# Standard-Sensortyp-Zuordnung nach Gewerk (FA-1401)
GEWERK_TO_SENSOR_TYPE = {
    # Licht: Tastereinheit
    "L":   "Tastereinheit",
    "LD":  "Tastereinheit",
    "LDA": "Tastereinheit",
    "LC":  "Tastereinheit",
    "LCT": "Tastereinheit",
    "LCW": "Tastereinheit",
    "DMX": "Tastereinheit",
    "S":   "Tastereinheit",
    "SD":  "Tastereinheit",
    # Jalousie: Tastereinheit
    "J":   "Tastereinheit",
    "R":   "Tastereinheit",
    "M":   "Tastereinheit",
    "T":   "Tastereinheit",
    # Heizung/Klima: Thermostat
    "H":   "Raumthermostat",
    "KL":  "Raumthermostat",
    # Alarm/Kontakte
    "A":   "Bewegungsmelder",
    "FK":  "Fensterkontakt",
    "TK":  "Türkontakt",
    "RK":  "Riegelkontakt",
    # Systemsensoren
    "W":   "Wetterstation",
    "E":   "Energiezähler",
    "TF": "Temperaturfuehler",
}
