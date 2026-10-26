"""
Busstrom je Linie (FA-613b).

Die Spannungsversorgung einer Linie begrenzt nicht nur die Zahl der
Teilnehmer, sondern vor allem deren Stromaufnahme. Prognose je Linie:

- Strom je Gerät aus den Herstellerdaten (Hardware «BusCurrent» in der
  KNXPROD bzw. .knxproj, am Gerät als Device.bus_current), sonst aus dem
  Produktkatalog, sonst Richtwert 10 mA (64 Teilnehmer à 10 mA = 640 mA).
- Kapazität der Spannungsversorgungen der Linie aus dem Produktnamen
  («640mA»), sonst aus den Herstellerdaten (bei Speisungen der
  Ausgangsstrom, aber oft 0/1/leer), sonst 640 mA angenommen.
- Geräte ohne Busadresse (B.L.-: Spannungsversorgung, Drossel) zählen nicht.

BusCurrent ist der Höchstwert laut Hersteller: die Prognose liegt eher auf
der sicheren Seite, ist aber keine Messung. Spannungsabfall über die
Leitungslänge rechnet sie nicht.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

from ..models.topology import is_power_supply

DEFAULT_DEVICE_MA = 10.0      # Richtwert je Gerät ohne Herstellerangabe
DEFAULT_SUPPLY_MA = 640       # Spannungsversorgung ohne erkennbare Grösse
RESERVE_LIMIT = 0.8           # ab 80 % Auslastung: zu wenig Reserve
_MIN_SUPPLY_MA = 160          # kleinere BusCurrent-Werte einer SV sind keine Ausgangsgrösse
_SUPPLY_MA_RE = re.compile(r"(\d{3,4})\s*mA", re.IGNORECASE)


def parse_bus_current(value) -> float:
    """BusCurrent aus der Hersteller-XML ("10", "5.0000000e+000") in mA; 0 = unbekannt."""
    try:
        current = float(value)
    except (TypeError, ValueError):
        return 0.0
    return current if current > 0 else 0.0


def device_current(device, catalog=None) -> tuple[float, bool]:
    """(mA, aus Herstellerdaten) eines Busteilnehmers; ohne Angabe der Richtwert."""
    if device.bus_current > 0:
        return device.bus_current, True
    if catalog is not None and device.order_number:
        try:
            current = catalog.bus_current_of(
                device.manufacturer, device.order_number, device.product_name)
        except Exception:
            current = 0.0
        if current > 0:
            return current, True
    return DEFAULT_DEVICE_MA, False


def supply_capacity(device) -> tuple[int, bool]:
    """(mA, erkannt) einer Spannungsversorgung; nicht erkannt = 640 mA angenommen."""
    for text in (device.product_name, device.product, device.order_number):
        m = _SUPPLY_MA_RE.search(text or "")
        if m:
            return int(m.group(1)), True
    if device.bus_current >= _MIN_SUPPLY_MA:
        return int(device.bus_current), True
    return DEFAULT_SUPPLY_MA, False


def is_consumer(device) -> bool:
    """Busteilnehmer, der Strom aus der Linie bezieht."""
    return not is_power_supply(device) and not device.physical_address.endswith("-")


@dataclass
class LineCurrent:
    data_ma: float = 0.0          # Summe aus Herstellerdaten
    estimated_ma: float = 0.0     # Summe der Richtwerte
    estimated_count: int = 0      # Geräte ohne Herstellerangabe
    consumer_count: int = 0
    supply_ma: int = 0            # Summe der Spannungsversorgungen (0 = keine)
    supply_assumed: bool = False  # mind. eine SV ohne erkennbare Grösse

    @property
    def total_ma(self) -> float:
        return self.data_ma + self.estimated_ma

    @property
    def load(self) -> float | None:
        """Auslastung 0..n, None ohne Spannungsversorgung."""
        return self.total_ma / self.supply_ma if self.supply_ma else None

    @property
    def overloaded(self) -> bool:
        return self.load is not None and self.load > 1.0

    @property
    def low_reserve(self) -> bool:
        return self.load is not None and RESERVE_LIMIT < self.load <= 1.0

    def summary(self) -> str:
        """'310 / 640 mA (48 %)' bzw. '310 mA, keine Spannungsversorgung'."""
        total = f"{self.total_ma:.0f}"
        if not self.supply_ma:
            return f"{total} mA, keine Spannungsversorgung"
        return f"{total} / {self.supply_ma} mA ({self.load * 100:.0f} %)"

    def estimate_note(self) -> str:
        """'davon 60 mA geschätzt (6 Geräte ohne Herstellerangabe)' oder ''."""
        if not self.estimated_count:
            return ""
        devices = "1 Gerät" if self.estimated_count == 1 else f"{self.estimated_count} Geräte"
        return (f"davon {self.estimated_ma:.0f} mA geschätzt "
                f"({devices} ohne Herstellerangabe)")


def line_current(line, catalog=None) -> LineCurrent:
    result = LineCurrent()
    for device in line.devices:
        if is_power_supply(device):
            capacity, known = supply_capacity(device)
            result.supply_ma += capacity
            result.supply_assumed |= not known
            continue
        if not is_consumer(device):
            continue
        result.consumer_count += 1
        current, from_data = device_current(device, catalog)
        if from_data:
            result.data_ma += current
        else:
            result.estimated_ma += current
            result.estimated_count += 1
    return result


def shared_catalog_or_none():
    """Produktkatalog der Sitzung für fehlende Stromwerte (None, wenn nicht ladbar)."""
    try:
        from .product_sync import shared_catalog
        return shared_catalog()
    except Exception:
        return None
