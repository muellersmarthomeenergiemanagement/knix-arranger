"""
Sensorprüfung (FA-3107): KNiX hört mit, ob die Sensoren senden und ob ihre
Messwerte plausibel sind -- ohne Person vor Ort.

Geprüft werden je Sensor die sendenden KOs mit GA:
- Messwerte (Temperatur, Feuchte, Helligkeit, Wind, CO2 ...): Wert im
  plausiblen Bereich = OK, ausserhalb = Mangel (bleibt, auch wenn später ein
  plausibler Wert kommt -- ein Fühler, der springt, ist defekt);
- Meldungen (Alarm, Störung, Kontakt, Präsenz): Meldung empfangen = OK, der
  Wert wird nur angezeigt (Alarm-Logik je Hersteller verschieden, z.B.
  «0: Aktiv»).
Bei Tastern und Raumbediengeräten nur die Messwerte (die Tasten prüft der
Tastentest). Viele Sensoren senden nur bei Änderung oder zyklisch; «Werte
abfragen» liest die GAs mit L-Flag. Ohne Meldung bleibt der Prüfpunkt offen.

Ohne Qt; Dialog in ui/dialogs/sensor_test_dialog.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..models.documentation import RESULT_DEFECT, RESULT_OK
from .dpt_values import dpt_parts, numeric_value

KIND_VALUE, KIND_MESSAGE = "Messwert", "Meldung"
STATE_OPEN, STATE_OK, STATE_BAD = "", "ok", "bad"

# Messwerte: Haupttypen mit Zahlenwert
_VALUE_MAINS = (5, 6, 7, 8, 9, 12, 13, 14)
_OUTDOOR = re.compile(r"aussen|außen|wetter|terrasse|balkon|garten|outdoor|dach", re.I)
_HOT = re.compile(r"sauna|hamam|hammam|dampf|infrarot", re.I)
_UNHEATED = re.compile(r"garage|einstellhalle|keller|lift|technik|estrich|remise|carport", re.I)


@dataclass
class SensorPoint:
    """Ein sendendes KO eines Sensors."""
    room_id: str
    room: str                   # "01 Technik"
    be_number: str              # physikalische Adresse
    device: str                 # "1.1.25 · Salva KNX TH"
    name: str                   # KO: "Temp.Sensor: Messwert"
    address: str                # "1/2/1"
    designation: str = ""
    dpt: str = ""
    kind: str = KIND_MESSAGE
    low: float | None = None    # plausibler Bereich (Messwerte)
    high: float | None = None
    unit: str = ""
    readable: bool = False      # L-Flag: «Werte abfragen» liest die GA

    def expected(self) -> str:
        if self.low is None:
            return "Meldung" if self.kind == KIND_MESSAGE else "Wert"
        return f"{_fmt(self.low)} … {_fmt(self.high)} {self.unit}".strip()

    def plausible(self, value: float) -> bool:
        return self.low is None or self.low <= value <= self.high


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"


def plausible_range(dpt: str, name: str, room: str) -> tuple[float, float, str] | None:
    """Plausibler Bereich eines Messwerts nach DPT, KO-Name und Raum."""
    main, sub = dpt_parts(dpt)
    text = f"{name} {room}"
    if (main, sub) == (9, 1) or (main == 9 and not sub and re.search(r"temp", name, re.I)):
        if re.search(r"taupunkt", name, re.I):
            return -30, 40, "°C"
        if _OUTDOOR.search(text):
            return -40, 60, "°C"
        if _HOT.search(text):
            return 5, 110, "°C"
        if _UNHEATED.search(room):
            return -20, 45, "°C"
        return 5, 40, "°C"
    return {
        (9, 4): (0, 200000, "lx"), (7, 13): (0, 65535, "lx"),
        (9, 5): (0, 60, "m/s"), (9, 28): (0, 220, "km/h"),
        (9, 6): (80000, 110000, "Pa"), (9, 7): (1, 100, "%"),
        (9, 8): (300, 5000, "ppm"), (5, 1): (0, 100, "%"),
    }.get((main, sub))


def _flags(co):
    from .ko_links import parse_flags
    return parse_flags(co.flags)


def plan_sensor_points(project, room_ids: set[str] | None = None) -> list[SensorPoint]:
    """Sendende KOs der Sensoren (Räume nach room_ids, alle bei None; Geräte
    ohne Raum nur bei None), in der Reihenfolge der Räume."""
    from .report_sorting import physical_address_key, sorted_rooms
    from .ko_links import READ, TRANSMIT

    gas = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    devices = {d.physical_address: d for a in project.topology.areas
               for line in a.lines for d in line.devices if d.physical_address}
    imported = project.topology.is_imported
    placed: dict[str, tuple] = {}
    for room in sorted_rooms(project.areal):
        for be in room.bedienelemente:
            if be.participant_number and be.is_shown(imported):
                placed.setdefault(be.participant_number, (room, be))
    order = [pa for pa in placed] + sorted(
        (pa for pa in devices if pa not in placed), key=physical_address_key)

    points: list[SensorPoint] = []
    for pa in order:
        device = devices.get(pa)
        if device is None or device.device_type in ("actor", "gateway", "coupler",
                                                      "power_supply"):
            continue
        room, be = placed.get(pa, (None, None))
        if room_ids is not None and (room is None or room.id not in room_ids):
            continue
        operable = bool(be and be.is_operable)
        room_text = f"{room.number} {room.name}".strip() if room else ""
        product = device.product_name or device.product
        title = " · ".join(p for p in (pa, product) if p)
        seen: set[str] = set()
        for co in device.communication_objects:
            if not co.connected_gas or TRANSMIT not in _flags(co):
                continue
            address = co.connected_gas[0]
            if address in seen:
                continue
            ga = gas.get(address)
            dpt = co.data_type if dpt_parts(co.data_type)[0] else (
                ga.datapoint_type if ga is not None else "")
            main = dpt_parts(dpt)[0]
            name = co.name or co.object_function or ""
            if main == 3 or re.match(r"\s*taste\b", name, re.I):
                continue                      # Tasten: Tastentest
            value = main in _VALUE_MAINS or (
                not main and re.search(r"temp|helligkeit|lux|feuchte", name, re.I))
            if operable and not value:
                continue
            seen.add(address)
            point = SensorPoint(
                room_id=room.id if room else "", room=room_text, be_number=pa,
                device=title, name=" ".join(name.split()), address=address,
                designation=" ".join(((ga.designation if ga else "") or "").split()),
                dpt=dpt, kind=KIND_VALUE if value else KIND_MESSAGE,
                readable=READ in _flags(co))
            limits = plausible_range(dpt, name, room_text)
            if limits:
                point.low, point.high, point.unit = limits
            points.append(point)
    return points


@dataclass
class Reading:
    count: int = 0
    value: str = ""             # letzter Wert, Text
    low: float | None = None    # kleinster und grösster Messwert
    high: float | None = None
    bad: str = ""               # erster unplausibler Wert
    others: set[str] = field(default_factory=set)   # andere Absender


class SensorSession:
    """Auswertung der mitgehörten Telegramme."""

    def __init__(self, points: list[SensorPoint]):
        self.points = points
        self.readings = [Reading() for _ in points]
        self.state = [STATE_OPEN] * len(points)
        self._by_address: dict[str, list[int]] = {}
        for i, p in enumerate(points):
            self._by_address.setdefault(p.address, []).append(i)

    def on_telegram(self, telegram, value_text: str = "") -> list[int]:
        """Geänderte Prüfpunkte."""
        if telegram.sent or telegram.service not in ("Write", "Response"):
            return []
        changed = []
        for i in self._by_address.get(telegram.destination, []):
            point, reading = self.points[i], self.readings[i]
            if telegram.source != point.be_number:
                # Zentrale, Logik o.ä. sendet auf die Sensor-GA: nur Hinweis
                if telegram.source and telegram.source not in reading.others:
                    reading.others.add(telegram.source)
                    changed.append(i)
                continue
            reading.count += 1
            reading.value = value_text or telegram.payload
            number = numeric_value(point.dpt, telegram.payload, telegram.size) \
                if point.kind == KIND_VALUE else None
            if number is not None:
                reading.low = number if reading.low is None else min(reading.low, number)
                reading.high = number if reading.high is None else max(reading.high, number)
                if not point.plausible(number) and not reading.bad:
                    reading.bad = reading.value
            self.state[i] = STATE_BAD if reading.bad else STATE_OK
            changed.append(i)
        return changed

    def note(self, i: int) -> str:
        point, reading = self.points[i], self.readings[i]
        if self.state[i] == STATE_BAD:
            return (f"Sensorprüfung: {point.address} = {reading.bad}, ausserhalb "
                    f"{point.expected()}")
        if self.state[i] == STATE_OK:
            span = ""
            if reading.low is not None and reading.high is not None \
                    and reading.low != reading.high:
                span = f" ({_fmt(round(reading.low, 2))} … {_fmt(round(reading.high, 2))})"
            return (f"Sensorprüfung: {point.address} = {reading.value}{span}, "
                    f"{reading.count} Meldung{'en' if reading.count != 1 else ''}")
        return ""

    def to_read(self) -> list[int]:
        """Noch ohne Meldung und lesbar."""
        return [i for i, p in enumerate(self.points)
                if self.state[i] == STATE_OPEN and p.readable]

    def summary(self) -> tuple[int, int, int]:
        """(OK, unplausibel, ohne Meldung)."""
        return (self.state.count(STATE_OK), self.state.count(STATE_BAD),
                self.state.count(STATE_OPEN))


def record_sensor_result(project, point: SensorPoint, ok: bool, note: str,
                         visum: str = "", day: date | None = None) -> int:
    """Ergebnis auf den Prüfpunkt des Sensors mit dieser GA. Gibt die Anzahl
    eingetragener Prüfpunkte zurück (0 ohne Checkliste oder Prüfpunkt)."""
    checklist = next((c for c in project.checklists if c.room_id == point.room_id), None)
    if checklist is None:
        return 0
    count = 0
    for item in checklist.items:
        if (item.be_number == point.be_number
                and item.function_ga.split()[:1] == [point.address]):
            item.set_result(RESULT_OK if ok else RESULT_DEFECT, visum, day)
            item.checked_date = (day or date.today()).isoformat()
            if visum:
                item.checked_by = visum
            item.notes = note
            count += 1
    return count
