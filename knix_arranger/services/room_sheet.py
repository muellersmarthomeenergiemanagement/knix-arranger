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
    # Kanalnamen des Herstellers ("Kanal C", "Motor 3") ohne Kürzel
    parts += others
    return ", ".join(parts)


def _outputs_text(found: dict[tuple[str, str, bool, str], list[str]]) -> list[str]:
    """Je Aktor eine Zeile "Typ Adresse · Kanäle · Verteiler" (DALI: Gruppen)."""
    lines = []
    for (actor_type, address, dali, location), channels in found.items():
        head = " ".join(p for p in (actor_type, address) if p)
        parts = [head, _channel_text(channels, dali), location]
        lines.append(" · ".join(p for p in parts if p))
    return lines


def short_location(location: str, designations: dict[str, str] | None = None) -> str:
    """Kurzname des Verteilers für die Ausgangszeile: die Bezeichnung aus
    Schritt 4 (Elektroverteilungen, vom Integrator bearbeitbar), sonst der
    Typ: "HV (HV Technikraum)" -> "HV T" bzw. "HV". Der volle Name steht im
    Kopf des Raums."""
    if designations and designations.get(location):
        return designations[location]
    return location.split(" (", 1)[0].strip()


def verteiler_designations(project) -> dict[str, str]:
    """Einbauort-Text eines Verteilers ("HV (HV Technikraum)") -> seine
    Bezeichnung ("HV T"); Verteiler ohne Bezeichnung fehlen."""
    from .report_service import _clean_location
    from .verteiler_service import verteiler_label
    return {_clean_location(verteiler_label(vt, room)): vt.designation.strip()
            for room in project.all_rooms for vt in room.verteiler
            if vt.designation.strip()}


def _room_text(room) -> str:
    return " ".join(p for p in (room.number, room.name) if p)


# Taste_label der Melder und Kontakte (ein Kanal je Funktion)
_SENSOR_CHANNEL_LABELS = ("Ausgang", "Kontakt")


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
    rooms_by_id = {room.id: room for room in project.all_rooms}
    designations = verteiler_designations(project)
    # Raum je Gruppenadresse (wie im Raumblatt zugeordnet, ohne Zentral) und
    # je Taster/Sensor -- für "Bedient von" aus einem anderen Raum
    room_of_ga: dict[str, str] = {}
    for room_id, items in groups.items():
        for (category, _label, _element, _short), gas in items.items():
            if category != "zentral":
                for ga in gas:
                    room_of_ga.setdefault(ga.address, room_id)
    devices_by_room: dict[str, list] = {}
    room_of_pa: dict[str, str] = {}
    for area in project.topology.areas:
        for line in area.lines:
            for dev in line.devices:
                if dev.room_id and dev.device_type not in _NOT_IN_ROOM:
                    devices_by_room.setdefault(dev.room_id, []).append(dev)
                    if dev.physical_address:
                        room_of_pa.setdefault(dev.physical_address, dev.room_id)
    for room in project.all_rooms:
        for be in room.bedienelemente:
            if be.participant_number and not be.suppressed:
                room_of_pa.setdefault(be.participant_number, room.id)

    operators_by_ga: dict[str, list[tuple[str, str]]] = {}
    usage_by_pa: dict[str, list[str]] = {}
    channels_by_pa: dict[str, set] = {}
    foreign_by_pa: dict[str, dict[str, set[str]]] = {}   # pa -> Raum -> Tasten
    for row in plan.sensor_rows:
        if row.is_feedback:
            continue
        if row.ga_address:
            operators_by_ga.setdefault(row.ga_address, []).append(
                (row.physical_address, _operator_text(row)))
            target = room_of_ga.get(row.ga_address)
            own = room_of_pa.get(row.physical_address)
            if (target and own and target != own and row.taste_label
                    and row.taste_label.startswith("Taste")):
                foreign_by_pa.setdefault(row.physical_address, {}).setdefault(
                    target, set()).add(row.taste_label)
        if row.taste_label in _SENSOR_CHANNEL_LABELS or row.taste_label.startswith("Kanal"):
            key = row.taste_label if row.taste_label.startswith("Kanal") else row.ga_address
            channels_by_pa.setdefault(row.physical_address, set()).add(key)
        elif row.taste_label:
            labels = usage_by_pa.setdefault(row.physical_address, [])
            if row.taste_label not in labels:
                labels.append(row.taste_label)
    unoperated = {(u.room_id, u.gewerk_code, u.element_number)
                  for u in unoperated_elements(project)}

    # Funktionen (FA-530): eigene Zeile im Raum der Funktion; ihre Bedienung
    # steht auch bei den Elementen ("1.1.101 Taste 7 · Funktion Balkon")
    from .ets_function_plan import function_elements, function_ga_map, members_text
    function_addresses: dict[str, list[str]] = {
        f.id: [ga.address for ga in function_ga_map(project, f).values()]
        for f in getattr(project, "functions", [])}
    functions_by_room: dict[str, list] = {}
    member_functions: dict[tuple[str, str, int], list] = {}
    elements_of = function_elements(project)
    for function in getattr(project, "functions", []):
        home, members = elements_of.get(function.id, ("", []))
        functions_by_room.setdefault(home, []).append((function, members))
        for member in members:
            member_functions.setdefault(member, []).append(function)

    def operators(room, addresses: list[str], room_pas=None, suffix: str = "") -> list[str]:
        result: list[str] = []
        for address in addresses:
            for pa, text in operators_by_ga.get(address, []):
                if room_pas is not None and pa not in room_pas:
                    continue
                other = rooms_by_id.get(room_of_pa.get(pa, ""))
                if other is not None and other.id != room.id:
                    text = f"{text} · {_room_text(other)}"
                text += suffix
                if text not in result:
                    result.append(text)
        return result

    sheets: list[RoomSheet] = []
    for room in project.all_rooms:
        items = groups.get(room.id, {})
        devices = devices_by_room.get(room.id, [])
        if not items and not devices and room.id not in functions_by_room:
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
            found: dict[tuple[str, str, bool, str], list[str]] = {}
            operated: list[str] = []
            for address in addresses:
                for row in outputs_by_ga.get(address, []):
                    dali = row.dali_group is not None
                    locations = [loc for loc in (_clean_location(part) for part in
                                                 (row.uv_location or "").split(",")) if loc]
                    for location in locations:
                        if location not in distributions:
                            distributions.append(location)
                    uv_short = ", ".join(dict.fromkeys(
                        short_location(loc, designations) for loc in locations))
                    channels = found.setdefault(
                        (row.actor_type, row.physical_address, dali, uv_short), [])
                    channel = (str(row.dali_group) if row.dali_group is not None
                               else row.channel_name or row.channel_number)
                    if channel and channel not in channels:
                        channels.append(channel)
                for text in operators(room, [address], room_pas if central else None):
                    if text not in operated:
                        operated.append(text)
            if gewerk and element:
                for function in member_functions.get((room.id, short, element), []):
                    for text in operators(room, function_addresses.get(function.id, []),
                                          suffix=f" · Funktion {function.name}"):
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
        for function, members in functions_by_room.get(room.id, []):
            addresses = function_addresses.get(function.id, [])
            found = {}
            for address in addresses:
                for row in outputs_by_ga.get(address, []):
                    uv_short = ", ".join(dict.fromkeys(
                        short_location(loc, designations) for loc in
                        (_clean_location(p) for p in (row.uv_location or "").split(",")) if loc))
                    channels = found.setdefault(
                        (row.actor_type, row.physical_address, row.dali_group is not None,
                         uv_short), [])
                    channel = (str(row.dali_group) if row.dali_group is not None
                               else row.channel_name or row.channel_number)
                    if channel and channel not in channels:
                        channels.append(channel)
            numbers = members_text(members)
            elements.append(ElementRow(
                gewerk_code="", gewerk_name="Funktion", category="funktion",
                number=function.number,
                label=f"{function.name} ({numbers})" if numbers else function.name,
                operated_by=operators(room, addresses),
                outputs=_outputs_text(found),
                ga_ranges=ga_ranges(addresses),
                ga_count=len(addresses),
            ))
        elements.sort(key=lambda e: (e.central, _gewerk_category_sort_key(e.category),
                                     e.gewerk_name, e.number))
        sheets.append(RoomSheet(
            room=room,
            elements=elements,
            devices=[_device_row(d, usage_by_pa.get(d.physical_address, []),
                                 len(channels_by_pa.get(d.physical_address, ())),
                                 {_room_text(rooms_by_id[rid]): len(keys) for rid, keys in
                                  foreign_by_pa.get(d.physical_address, {}).items()
                                  if rid in rooms_by_id})
                     for d in sorted(devices, key=lambda d: physical_address_key(
                         d.physical_address))],
            distributions=distributions,
        ))
    return sheets


def _device_row(device, usage: list[str], channels: int = 0,
                foreign: dict[str, int] | None = None) -> DeviceRow:
    """foreign: Raum -> Anzahl Tasten, die Elemente eines anderen Raums
    bedienen ("2 Tasten belegt, davon 1 für CUG02 Technik")."""
    product = " · ".join(p for p in (device.manufacturer, device.order_number) if p)
    if device.product_name and device.product_name != device.product:
        product = " · ".join(p for p in (device.product_name, product) if p)
    if not product:
        product = "kein Produkt zugewiesen"
    tasten = [u for u in usage if u.startswith("Taste")]
    others = [u for u in usage if not u.startswith("Taste")]
    parts = []
    if tasten:
        text = f"{len(tasten)} {'Taste' if len(tasten) == 1 else 'Tasten'} belegt"
        if foreign:
            text += ", davon " + ", ".join(f"{n} für {name}"
                                           for name, n in sorted(foreign.items()))
        parts.append(text)
    if channels:
        parts.append(f"{channels} {'Kanal' if channels == 1 else 'Kanäle'} belegt")
    text = ", ".join(parts + others)
    return DeviceRow(
        physical_address=device.physical_address or "–",
        kind=device.product or device.product_name or device.device_type,
        product=product,
        usage=text,
    )
