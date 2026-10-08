"""
Raumblatt für den Bericht "Raumbuch KNX" (FA-908).

Je Raum die Elemente der Gewerke mit Bezeichnung, bedienender Taste bzw.
Sensor ("Bedient von"), schaltendem Aktorkanal ("Ausgang") und den
Gruppenadressen als Bereiche, dazu die KNX-Geräte im Raum. Gilt für geplante
und importierte Projekte: Taste und Ausgang kommen über die Gruppenadressen
aus dem Belegungsplan (geplant aus der Planung, importiert aus den
Kommunikationsobjekten), die Bezeichnung aus der Planung oder dem GA-Namen.

Reine Datenoperation ohne Qt und ohne PDF.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .report_sorting import group_address_key, physical_address_key

# Geräte im Verteiler erscheinen beim Element unter "Ausgang", nicht im Raum
_NOT_IN_ROOM = ("actor", "gateway", "coupler", "power_supply")


@dataclass
class ElementRow:
    gewerk_code: str        # "" bei Mittelgruppen ohne Gewerk und Zentral
    gewerk_name: str
    category: str
    number: int             # 0 = ohne Elementnummer
    label: str              # Bezeichnung / Klartext
    operated_by: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    ga_ranges: str = ""
    ga_count: int = 0
    unoperated: bool = False
    central: bool = False


@dataclass
class DeviceRow:
    physical_address: str
    kind: str               # "Tastereinheit", "Raumthermostat", ...
    product: str            # Hersteller · Bestellnr. bzw. Produktname
    usage: str              # "8 Tasten belegt" / "Sollwert, Betriebsart"


@dataclass
class RoomSheet:
    room: object
    elements: list[ElementRow]
    devices: list[DeviceRow]
    distributions: list[str]   # Einbauorte der Aktoren (Verteiler)

    @property
    def ga_count(self) -> int:
        return sum(e.ga_count for e in self.elements)

    @property
    def element_count(self) -> int:
        return sum(1 for e in self.elements if not e.central)


# Lücken bis zu dieser Grösse (Reserven eines Blocks) gehören zum Bereich
_MAX_GAP = 4


def ga_ranges(addresses: list[str]) -> str:
    """Adressen als Bereiche: ["1/0/20", "1/0/21", "1/0/25", "1/6/20"] ->
    "1/0/20–25 · 1/6/20". Kleine Lücken (Reserven) werden überbrückt."""
    parts: list[str] = []
    run: list[tuple[int, int, int]] = []

    def flush():
        if not run:
            return
        h, m, s0 = run[0]
        s1 = run[-1][2]
        parts.append(f"{h}/{m}/{s0}" if s0 == s1 else f"{h}/{m}/{s0}–{s1}")
        run.clear()

    for address in sorted(set(addresses), key=group_address_key):
        try:
            h, m, s = (int(x) for x in address.split("/"))
        except ValueError:
            flush()
            parts.append(address)
            continue
        if run and (run[-1][0], run[-1][1]) == (h, m) and s - run[-1][2] <= _MAX_GAP + 1:
            run.append((h, m, s))
        else:
            flush()
            run.append((h, m, s))
    flush()
    return " · ".join(parts)


_PARENS = re.compile(r"\(([^()]*)\)\s*$")


def klartext_from_gas(gas: list, room) -> str:
    """Bezeichnung aus dem GA-Namen (importierte Projekte): Text in der
    letzten Klammer ohne Zone und Raumname, sonst die GA-Beschreibung."""
    for ga in gas:
        m = _PARENS.search((ga.designation or "").strip())
        if not m:
            continue
        text = " ".join(m.group(1).split())
        if " / " in text:
            text = text.split(" / ", 1)[1]
        for prefix in (f"{room.number} {room.name}", room.name):
            if prefix and text.lower().startswith(prefix.lower()):
                text = text[len(prefix):].strip()
        if text:
            return text
    for ga in gas:
        desc = " ".join((ga.description or "").split())
        if desc:
            return desc
    return ""


def _channel_text(channels: list[str], dali: bool = False) -> str:
    """Kanäle eines Geräts kompakt: ["4", "5", "6", "9"] -> "K4–6, K9";
    Gruppen der DALI-Konfiguration "Gr. 3–4"."""
    prefix = "Gr. " if dali else "K"
    numbers = sorted({int(c) for c in channels if c.isdigit()})
    others = sorted({c for c in channels if c and not c.isdigit()})
    parts: list[str] = []
    start = prev = None
    for n in numbers + [None]:
        if n is not None and prev is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            parts.append(f"{prefix}{start}" if start == prev else f"{prefix}{start}–{prev}")
        start = prev = n
    parts += [f"{prefix}{c}" for c in others]
    return ", ".join(parts)


def _outputs_text(found: dict[tuple[str, str, bool], list[str]]) -> list[str]:
    """Je Aktor eine Zeile "Typ Adresse · Kanäle" (DALI: Gruppen)."""
    lines = []
    for (actor_type, address, dali), channels in found.items():
        head = " ".join(p for p in (actor_type, address) if p)
        channel = _channel_text(channels, dali)
        lines.append(head + (f" · {channel}" if channel else ""))
    return lines


def _operator_text(row) -> str:
    taste = row.taste_label or ""
    what = taste if taste.startswith(("Taste", "Kanal", "K")) else row.sensor_type
    return " ".join(p for p in (row.physical_address, what) if p)


def build_room_sheets(project, groups: dict, catalog, plan) -> list[RoomSheet]:
    """groups: Ergebnis von ReportService._room_gewerk_groups (room.id ->
    {(Kategorie, Label, Element, Kurzform): [GA]}), plan: Belegungsplan."""
    from .operation_check import unoperated_elements
    from .report_service import _gewerk_category_sort_key

    from .report_service import _clean_location
    outputs_by_ga: dict[str, list] = {}
    for row in plan.actor_rows:
        if row.ga_address:
            outputs_by_ga.setdefault(row.ga_address, []).append(row)
    operators_by_ga: dict[str, list[tuple[str, str]]] = {}
    usage_by_pa: dict[str, list[str]] = {}
    for row in plan.sensor_rows:
        if row.is_feedback:
            continue
        if row.ga_address:
            operators_by_ga.setdefault(row.ga_address, []).append(
                (row.physical_address, _operator_text(row)))
        if row.taste_label:
            labels = usage_by_pa.setdefault(row.physical_address, [])
            if row.taste_label not in labels:
                labels.append(row.taste_label)
    unoperated = {(u.room_id, u.gewerk_code, u.element_number)
                  for u in unoperated_elements(project)}

    devices_by_room: dict[str, list] = {}
    for area in project.topology.areas:
        for line in area.lines:
            for dev in line.devices:
                if dev.room_id and dev.device_type not in _NOT_IN_ROOM:
                    devices_by_room.setdefault(dev.room_id, []).append(dev)

    sheets: list[RoomSheet] = []
    for room in project.all_rooms:
        items = groups.get(room.id, {})
        devices = devices_by_room.get(room.id, [])
        if not items and not devices:
            continue
        elements: list[ElementRow] = []
        distributions: list[str] = []
        # Zentralfunktionen werden im ganzen Haus bedient: im Raumblatt nur
        # die Taster und Sensoren dieses Raums
        room_pas = ({d.physical_address for d in devices}
                    | {be.participant_number for be in room.bedienelemente
                       if be.participant_number})
        for (category, label, element, short), gas in items.items():
            central = category == "zentral"
            gewerk = catalog.get(short) if (short and not central) else None
            addresses = [ga.address for ga in gas]
            found: dict[tuple[str, str, bool], list[str]] = {}
            operated: list[str] = []
            for address in addresses:
                for row in outputs_by_ga.get(address, []):
                    dali = row.dali_group is not None
                    channels = found.setdefault((row.actor_type, row.physical_address, dali), [])
                    channel = (str(row.dali_group) if row.dali_group is not None
                               else row.channel_number)
                    if channel and channel not in channels:
                        channels.append(channel)
                    for location in (row.uv_location or "").split(","):
                        location = _clean_location(location)
                        if location and location not in distributions:
                            distributions.append(location)
                for pa, text in operators_by_ga.get(address, []):
                    if central and pa not in room_pas:
                        continue
                    if text not in operated:
                        operated.append(text)
            text = ""
            if gewerk and element:
                text = room.gewerk_element_label(short, element)
            if not text and not central:
                text = klartext_from_gas(gas, room)
            elements.append(ElementRow(
                gewerk_code=short if gewerk else "",
                gewerk_name=gewerk.name if gewerk else label,
                category=category,
                number=element if gewerk else 0,
                label=text,
                operated_by=operated,
                outputs=_outputs_text(found),
                ga_ranges=ga_ranges(addresses),
                ga_count=len(gas),
                unoperated=(room.id, short, element) in unoperated,
                central=central,
            ))
        elements.sort(key=lambda e: (e.central, _gewerk_category_sort_key(e.category),
                                     e.gewerk_name, e.number))
        sheets.append(RoomSheet(
            room=room,
            elements=elements,
            devices=[_device_row(d, usage_by_pa.get(d.physical_address, []))
                     for d in sorted(devices, key=lambda d: physical_address_key(
                         d.physical_address))],
            distributions=distributions,
        ))
    return sheets


def _device_row(device, usage: list[str]) -> DeviceRow:
    product = " · ".join(p for p in (device.manufacturer, device.order_number) if p)
    if device.product_name and device.product_name != device.product:
        product = " · ".join(p for p in (device.product_name, product) if p)
    if not product:
        product = "kein Produkt zugewiesen"
    tasten = [u for u in usage if u.startswith("Taste")]
    others = [u for u in usage if not u.startswith("Taste")]
    parts = [f"{len(tasten)} {'Taste' if len(tasten) == 1 else 'Tasten'} belegt"] if tasten else []
    text = ", ".join(parts + others)
    return DeviceRow(
        physical_address=device.physical_address or "–",
        kind=device.product or device.product_name or device.device_type,
        product=product,
        usage=text,
    )
