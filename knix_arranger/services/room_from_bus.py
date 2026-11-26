"""
Räume aus dem Bus (FA-3105c): Taster und Sensoren mit den Aktorkanälen, die
sie über gemeinsame GAs bedienen, zu Raumvorschlägen zusammenfassen und vor
Ort per Tastendruck einem Raum zuordnen.

Ein Aktorkanal (Gerät + Kanal aus dem KO-Namen, wie bei «Bedeutung
ergänzen», FA-3108c) hängt an einem Taster, wenn beide an derselben GA
liegen. Zentral-GAs (drei und mehr Aktorkanäle) und Szenen verbinden nicht:
sie gehören keinem Raum. Der Raum eines Tasters bzw. Sensors steht am Gerät
(Korrekturschicht FA-616a bei importierten Projekten), der Raum eines
Aktorkanals an seinen GAs; deren Name bekommt den Raum an Stelle der
Geräteadresse («J_1.1.4_01 AUF/AB (Motor C)» -> «J_EG_05_01 AUF/AB (Wohnen
Motor C)»). Das Aktorgerät selbst bleibt im Verteiler.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Geräte, die bedienen oder messen (Raum am Gerät)
_NOT_OPERATORS = ("actor", "gateway", "coupler", "power_supply")


@dataclass
class Channel:
    """Aktorkanal mit seinen GAs (ohne Zentral-GAs)."""
    device_address: str
    channel: str
    gewerk: str = ""
    addresses: list[str] = field(default_factory=list)
    # Funktion -> GA ("E/A" -> "0/2/3", "RM" -> "0/2/4"), für «Lasten suchen»
    functions: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.device_address, self.channel)

    @property
    def label(self) -> str:
        return f"{self.device_address} {self.channel}"


@dataclass
class Operator:
    """Taster oder Sensor: Gerät, eigene GAs (Messwerte u.ä.), bediente Kanäle."""
    device: object
    addresses: list[str] = field(default_factory=list)
    channels: list[tuple[str, str]] = field(default_factory=list)
    # GAs, auf denen ein Telegramm dieses Geräts einen Tastendruck (bzw.
    # Bewegung) bedeutet: sendende KOs ohne Messwerte und Meldungen
    key_gas: set[str] = field(default_factory=set)

    @property
    def address(self) -> str:
        return self.device.physical_address


# KOs, die von selbst senden: Messwerte, Alarme, Störungen
_NOT_A_KEY = re.compile(
    r"temperatur|feuchte|humid|helligkeit|\blux\b|co2|taupunkt|messwert|wind|\bregen|"
    r"luftdruck|\bdruck\b|\bled|"
    r"alarm|st[öo]rung|warnung|batterie|leck|rauch|fehler|zyklisch|sollwert|ist-?wert",
    re.IGNORECASE)


def is_key_object(co) -> bool:
    """KO eines Tasters/Präsenzmelders, das beim Betätigen sendet: Senden-
    Flag (wenn bekannt), kein Messwert (DPT 7/9/12-14, 2 Byte und mehr),
    keine Meldung."""
    from .ko_links import parse_flags
    flags = parse_flags(co.flags) if co.flags else ""
    if flags and "Ü" not in flags:
        return False
    match = re.match(r"DPS?T-(\d+)", co.data_type or "")
    if match and int(match.group(1)) in (7, 9, 12, 13, 14):
        return False
    size = (co.object_size or "").strip().lower()
    if size and not (size.startswith("1 bit") or size.startswith("4 bit")
                     or size.startswith("1 byte")):
        return False
    return not _NOT_A_KEY.search(f"{co.name} {co.object_function}")


@dataclass
class RoomPlan:
    operators: dict[str, Operator] = field(default_factory=dict)
    channels: dict[tuple[str, str], Channel] = field(default_factory=dict)
    # Raumvorschläge: Gruppen aus Tastern/Sensoren und Kanälen, die über
    # gemeinsame GAs zusammenhängen
    groups: list[tuple[list[str], list[tuple[str, str]]]] = field(default_factory=list)

    def orphan_channels(self) -> list[Channel]:
        """Aktorkanäle, die kein Taster bedient (nur zentral, Visualisierung …)."""
        used = {key for op in self.operators.values() for key in op.channels}
        return [c for key, c in self.channels.items() if key not in used]

    def operators_of(self, key: tuple[str, str]) -> list[Operator]:
        return [op for op in self.operators.values() if key in op.channels]


def _is_scene(ga, co) -> bool:
    dpt = (ga.datapoint_type or co.data_type or "")
    return bool(re.match(r"DPS?T-(17|18)\b", dpt)) or (ga.function_name or "") == "SZENE"


def analyse(project) -> RoomPlan:
    """Taster/Sensoren, Aktorkanäle und Raumvorschläge aus den Verknüpfungen."""
    from .device_scan import project_devices
    from .ets_function_plan import ko_functions
    from .ga_meaning import (
        CENTRAL_CHANNELS, _anchors, _channel, _channel_gewerk, _function_of, clean_dpt,
    )
    plan = RoomPlan()
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    anchors, receivers = _anchors(project)
    device_functions = ko_functions(project)
    gewerk_cache: dict = {}

    central: set[str] = set()
    for address, entries in receivers.items():
        if len({(d.physical_address, _channel(c)) for d, c in entries}) >= CENTRAL_CHANNELS:
            central.add(address)

    # Kanäle: GAs, deren Bedeutung ein Aktor-/Gateway-KO trägt
    channel_of: dict[str, tuple[str, str]] = {}
    for address, (device, co, _rank) in anchors.items():
        ga = by_address.get(address)
        if ga is None or address in central or device.device_type not in ("actor", "gateway"):
            continue
        if _is_scene(ga, co):
            continue
        name = _channel(co)
        key = (device.physical_address, name)
        channel = plan.channels.get(key)
        if channel is None:
            channel = Channel(device.physical_address, name,
                              ga.gewerk_code or _channel_gewerk(device, name, gewerk_cache))
            plan.channels[key] = channel
        channel.addresses.append(address)
        channel_of[address] = key
        # Bedeutung vom Gerät vor dem Namen (FA-531a), dann KO-Text/DPT
        function = device_functions.get(address) or ga.function_name or _function_of(
            co, "", clean_dpt(ga.datapoint_type) or clean_dpt(co.data_type))
        if function:
            channel.functions.setdefault(function, address)
    _merge_motors(plan, channel_of)
    for channel in plan.channels.values():
        channel.addresses.sort(key=_ga_key)

    # GAs vieler Taster (LED-Nachtabsenkung u.ä.) gehören keinem Raum
    shared: dict[str, int] = {}
    for device in project_devices(project):
        if device.device_type in _NOT_OPERATORS:
            continue
        for address in {a for co in device.communication_objects for a in co.connected_gas}:
            shared[address] = shared.get(address, 0) + 1
    central |= {a for a, count in shared.items() if count >= CENTRAL_CHANNELS}

    for device in project_devices(project):
        if device.device_type in _NOT_OPERATORS or not device.physical_address:
            continue
        operator = Operator(device)
        for co in device.communication_objects:
            if co.connected_gas and is_key_object(co):
                operator.key_gas.update(co.connected_gas)
            for address in co.connected_gas:
                key = channel_of.get(address)
                if key is not None:
                    if key not in operator.channels:
                        operator.channels.append(key)
                elif address in by_address and address not in central:
                    anchor = anchors.get(address)
                    if anchor is not None and anchor[0] is device \
                            and address not in operator.addresses:
                        operator.addresses.append(address)
        if operator.channels or operator.addresses or device.communication_objects:
            plan.operators[device.physical_address] = operator
    plan.groups = _groups(plan)
    return plan


_MOTOR = re.compile(r"\((M\d+)\)", re.IGNORECASE)


def _merge_motors(plan: RoomPlan, channel_of: dict) -> None:
    """Ein Motor, ein Kanal: «Bedienung Storen (M1)» und «Sonnenschutz (M1)»
    (Status) desselben Geräts zusammenfassen -- unter dem Namen mit den
    Befehls-GAs."""
    by_motor: dict[tuple[str, str], list[Channel]] = {}
    for channel in plan.channels.values():
        match = _MOTOR.search(channel.channel)
        if match:
            by_motor.setdefault((channel.device_address, match.group(1).upper()), []) \
                .append(channel)
    for channels in by_motor.values():
        if len(channels) < 2:
            continue
        channels.sort(key=lambda c: ("AUF/AB" not in c.functions, -len(c.addresses)))
        main = channels[0]
        for other in channels[1:]:
            for address in other.addresses:
                main.addresses.append(address)
                channel_of[address] = main.key
            for function, address in other.functions.items():
                main.functions.setdefault(function, address)
            if not main.gewerk:
                main.gewerk = other.gewerk
            del plan.channels[other.key]


# Zeitfenster nach einem Tastendruck: Logik (Server, Szenen) und Status der
# Aktoren folgen in dieser Zeit
FOLLOW_SECONDS = 4.0


def channels_in_telegrams(plan: RoomPlan, addresses) -> list[tuple[str, str]]:
    """Aktorkanäle, deren GAs in den Telegrammen nach einem Tastendruck
    vorkommen (Befehl über einen Logikserver, Status des Aktors)."""
    seen = set(addresses)
    return [key for key, channel in plan.channels.items()
            if any(a in seen for a in channel.addresses)]


# Grundrauschen: was vor dem Start in dieser Zeit mehrmals gesendet wurde
NOISE_SECONDS = 120.0


def noise_pairs(history, now=None) -> set[tuple[str, str]]:
    """(Absender, GA), die vor dem Start regelmässig gesendet wurden
    (zyklische Sender, Logikserver): mindestens zweimal in NOISE_SECONDS."""
    from collections import Counter
    from datetime import datetime
    now = now or datetime.now()
    counts = Counter()
    for telegram in history:
        if getattr(telegram, "sent", False) or telegram.service != "Write":
            continue
        if (now - telegram.time).total_seconds() <= NOISE_SECONDS:
            counts[(telegram.source, telegram.destination)] += 1
    return {pair for pair, count in counts.items() if count >= 2}


@dataclass
class Press:
    """Ein Taster, der während der Aufnahme betätigt wurde."""
    address: str
    count: int = 0
    gas: set[str] = field(default_factory=set)
    followed: set[str] = field(default_factory=set)    # GAs in den Sekunden danach
    manual: bool = False


class RoomSession:
    """Rundgang in einem Raum (FA-3105c): Tastendrücke aufnehmen (nur
    Tasten-KOs, ohne Grundrauschen), danach die Aktorkanäle vorschlagen."""

    def __init__(self, plan: RoomPlan, history=(), now=None):
        self.plan = plan
        self.noise = noise_pairs(history, now)
        self.pressed: dict[str, Press] = {}
        self.removed: set[str] = set()
        # mit «Lasten suchen» in diesem Raum gefunden
        self.found: list[tuple[str, str]] = []
        self.ignored = 0
        self._last: tuple[str, float] | None = None

    def feed(self, telegram, seconds: float) -> str:
        """Telegramm auswerten (seconds = monotone Empfangszeit). Gibt die
        Adresse des Tasters zurück, wenn es ein Tastendruck war, sonst ""."""
        if getattr(telegram, "sent", False):
            return ""
        source, destination = telegram.source, telegram.destination
        operator = self.plan.operators.get(source)
        if operator is not None and telegram.service == "Write" \
                and destination in operator.key_gas:
            if (source, destination) in self.noise or source in self.removed:
                self.ignored += 1
                return ""
            press = self.pressed.setdefault(source, Press(source))
            press.count += 1
            press.gas.add(destination)
            self._last = (source, seconds)
            return source
        if self._last is not None and seconds - self._last[1] <= FOLLOW_SECONDS:
            press = self.pressed.get(self._last[0])
            if press is not None:
                press.followed.add(destination)
        return ""

    def add(self, address: str) -> None:
        """Taster von Hand dazunehmen (ohne Bus oder nicht gedrückt)."""
        if address in self.plan.operators:
            self.removed.discard(address)
            self.pressed.setdefault(address, Press(address, manual=True))

    def remove(self, address: str) -> None:
        """Gehört nicht in diesen Raum (Taste im Nachbarraum gedrückt)."""
        self.pressed.pop(address, None)
        self.removed.add(address)

    def candidates(self) -> list[tuple[tuple[str, str], str]]:
        """[(Kanal, Herkunft)]: verknüpft mit einem gedrückten Taster bzw.
        «nach Tastendruck» (Logikserver, Status)."""
        result: dict[tuple[str, str], str] = {}
        for press in self.pressed.values():
            for key in self.plan.operators[press.address].channels:
                result.setdefault(key, "verknüpft")
        for press in self.pressed.values():
            for key in channels_in_telegrams(self.plan, press.followed):
                result.setdefault(key, "nach Tastendruck")
        for key in self.found:
            result.setdefault(key, "Last gefunden")
        return list(result.items())


# ── Lasten suchen ────────────────────────────────────────────────────────

def open_channels(project, plan: RoomPlan) -> list[Channel]:
    """Aktorkanäle ohne Raum, nach Gerät und Kanal."""
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    result = []
    for channel in plan.channels.values():
        rooms = {by_address[a].room_id for a in channel.addresses if a in by_address}
        if len(rooms) != 1 or not rooms.pop():
            result.append(channel)
    result.sort(key=lambda c: (_pa_key(c.device_address), c.channel))
    return result


def load_probe(project, channel: Channel):
    """Prüfschritt für «Lasten suchen» (FA-3105c): kurz schalten wie beim
    Funktionstest (FA-3104) -- Licht Ein/Aus, Dimmer 50 %/0 %, Storen Ab -
    Stopp / Auf - Stopp. Alarm, Wetter, Tor, Türe und Fenster nie; Gewerke
    ohne sichtbare Last (Heizung, Energie …) ebenso. skip nennt den Grund."""
    from .function_test import (
        BLIND_CODES, EXCLUDED_CODES, KIND_BLIND, KIND_DIM, KIND_SWITCH, SWITCH_CODES,
        TestStep,
    )
    code = channel.gewerk or "SF"
    catalog = getattr(project, "gewerk_catalog", None)
    gewerk = catalog.get(code) if hasattr(catalog, "get") else None
    step = TestStep(room_id="", room="", gewerk_code=code, label=channel.label,
                    place=channel.label)
    functions = channel.functions
    if getattr(gewerk, "category", "") == "alarm" or code in EXCLUDED_CODES:
        step.skip = "nie automatisch (Sicherheit)"
    elif code in BLIND_CODES or "AUF/AB" in functions:
        # auch Schaltaktor-Ausgänge im Storenbetrieb («Ausgänge 1-2»)
        if "AUF/AB" in functions and "STOPP" in functions:
            step.kind = KIND_BLIND
            step.gewerk_code = code if code in BLIND_CODES else "J"
            step.commands = {"AUF/AB": functions["AUF/AB"], "STOPP": functions["STOPP"]}
        else:
            # ohne Stopp führe der Behang ganz durch
            step.skip = "ohne GA STOPP" if "AUF/AB" in functions else "ohne GA AUF/AB"
    elif code not in SWITCH_CODES:
        step.skip = "keine sichtbare Last"
    elif "E/A" in functions:
        step.kind = KIND_SWITCH
        step.commands = {"E/A": functions["E/A"]}
    elif "WERT" in functions:
        step.kind = KIND_DIM
        step.commands = {"WERT": functions["WERT"]}
    else:
        step.skip = "ohne GA E/A bzw. WERT"
    return step


def probe_actions(step) -> list:
    """Ablauf eines Prüfschritts: wie im Funktionstest, aber immer fragen
    (ohne Warten auf eine Rückmeldung) -- es geht um den Ort, nicht um den
    Aktor."""
    actions = step.actions()
    result = []
    for index, action in enumerate(actions):
        following = actions[index + 1] if index + 1 < len(actions) else None
        if action.kind == "wait" and following is not None and following.kind == "ask":
            continue
        result.append(action)
    return result


def progress(project, plan: RoomPlan) -> tuple[int, int, int, int]:
    """(Taster mit Raum, Taster, Kanäle mit Raum, Kanäle)."""
    operators = sum(1 for op in plan.operators.values() if op.device.room_id)
    channels = sum(1 for c in plan.channels.values() if channel_room(project, c))
    return operators, len(plan.operators), channels, len(plan.channels)


def _groups(plan: RoomPlan) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """Zusammenhängende Taster und Kanäle (Union-Find), nach erster Adresse."""
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for pa, operator in plan.operators.items():
        find(("op", pa))
        for key in operator.channels:
            parent[find(("op", pa))] = find(("ch", key))
    members: dict = {}
    for pa in plan.operators:
        members.setdefault(find(("op", pa)), ([], []))[0].append(pa)
    for key in plan.channels:
        if ("ch", key) in parent:
            members.setdefault(find(("ch", key)), ([], []))[1].append(key)
    groups = [(sorted(ops, key=_pa_key), sorted(chs, key=lambda k: (_pa_key(k[0]), k[1])))
              for ops, chs in members.values() if ops]
    groups.sort(key=lambda g: _pa_key(g[0][0]))
    return groups


def _pa_key(address: str):
    return tuple(int(p) if p.isdigit() else 0 for p in address.split("."))


def _ga_key(address: str):
    return tuple(int(p) if p.isdigit() else 0 for p in address.split("/"))


# ── Räume ────────────────────────────────────────────────────────────────

def room_label(project, room_id: str) -> str:
    """«EG 05 Wohnen» bzw. "" ohne Raum; mit Zone und Gebäude, wo nötig."""
    if not room_id:
        return ""
    return next((label for label, _f, room in all_rooms(project) if room.id == room_id), "")


def _named_zone(floor, apartment) -> bool:
    """Eigene Zone, nicht nur die Standardzone eines Stockwerks (FA-107)."""
    return (apartment.name or "") not in ("", floor.short_code or "", floor.name or "")


def all_rooms(project) -> list[tuple[str, object, object]]:
    """[(Anzeige, Stockwerk, Raum)] in der Reihenfolge der Gebäudestruktur.
    Die Zone steht dabei, sobald es benannte Zonen gibt (Innen/Aussen,
    Wohnungen), das Gebäude bei mehreren Gebäuden."""
    buildings = project.areal.buildings
    zones = any(_named_zone(floor, apt) for b in buildings
                for floor in b.all_floors for apt in floor.apartments)
    result = []
    for building in buildings:
        for wing in building.wings:
            for floor in wing.floors:
                for apt in floor.apartments:
                    for room in apt.rooms:
                        label = " ".join(p for p in (floor.short_code or floor.name,
                                                     room.number, room.name) if p)
                        extra = [building.name] if len(buildings) > 1 and building.name \
                            else []
                        if len(building.wings) > 1 and wing.name:
                            extra.append(wing.name)
                        if zones and apt.name:
                            extra.append(apt.name)
                        if extra:
                            label += f" ({', '.join(extra)})"
                        result.append((label, floor, room))
    return result


def zone_names(project) -> list[str]:
    """Benannte Zonen des Projekts in der Reihenfolge der Gebäudestruktur."""
    names: list[str] = []
    for building in project.areal.buildings:
        for floor in building.all_floors:
            for apt in floor.apartments:
                if _named_zone(floor, apt) and apt.name not in names:
                    names.append(apt.name)
    return names


def room_place(project, room_id: str) -> tuple[str, str]:
    """(Stockwerk-Kürzel, benannte Zone oder "") eines Raums, sonst ("", "")."""
    for building in project.areal.buildings:
        for floor in building.all_floors:
            for apt in floor.apartments:
                if any(r.id == room_id for r in apt.rooms):
                    return (floor.short_code or floor.name or "",
                            apt.name if _named_zone(floor, apt) else "")
    return "", ""


def find_floor(building, floor_name: str, wing=None):
    """Stockwerk nach Kürzel oder Name (ohne Gross-/Kleinschreibung), mit
    `wing` nur in diesem Gebäudeteil."""
    wanted = (floor_name or "").strip().lower()
    floors = wing.floors if wing is not None else building.all_floors
    return next((f for f in floors
                 if wanted and wanted in ((f.short_code or "").lower(),
                                          (f.name or "").lower())), None)


def suggest_number(project, floor, zone: str = "", wing=None) -> str:
    """Nächste freie Raumnummer nach dem Schema von Schritt 3 (im ganzen
    Projekt eindeutig, damit die GA-Namen eindeutig bleiben)."""
    from .room_numbering import suggest_room_number
    from ..models.building import Apartment
    if floor is None:
        return ""
    if wing is None:
        wing = next((w for b in project.areal.buildings for w in b.wings
                     if floor in w.floors), None)
    if wing is None:
        return ""
    apartment = next((a for a in floor.apartments
                      if zone and (a.name or "").lower() == zone.lower()), None)
    if apartment is None:
        apartment = floor.apartments[0] if not zone and floor.apartments else             Apartment(name=zone or floor.short_code or floor.name)
    return suggest_room_number(project.areal, wing, apartment, floor)


def duplicate_number(project, number: str) -> str:
    """Bezeichnung des Raums, der die Nummer schon trägt, sonst ""."""
    number = (number or "").strip()
    if not number:
        return ""
    return next((label for label, _f, room in all_rooms(project)
                 if room.number == number), "")


def channel_room(project, channel: Channel) -> str:
    """Raum-ID eines Kanals: der Raum, den alle seine GAs tragen, sonst ""."""
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    rooms = {by_address[a].room_id for a in channel.addresses if a in by_address}
    return rooms.pop() if len(rooms) == 1 else ""


def add_room(project, floor_name: str, number: str, name: str, zone: str = "",
             building=None, wing=None):
    """Raum anlegen; fehlt das Stockwerk (Name oder Kürzel), wird es angelegt.
    `zone`: Zone (Wohnung, Innen/Aussen); gleicher Name auf mehreren
    Stockwerken = eine Zone. Fehlt sie auf dem Stockwerk, wird sie dort
    angelegt. Leer = die erste Zone des Stockwerks. `wing`: Gebäudeteil,
    in dem das Stockwerk gesucht bzw. angelegt wird (sonst der erste)."""
    from .building_service import BuildingService
    areal = project.areal
    if not areal.buildings:
        fresh = BuildingService.create_default_areal(project.name or "")
        areal.buildings.extend(fresh.buildings)
    if building is None or building not in areal.buildings:
        building = areal.buildings[0]
    if not building.wings:
        from ..models.building import Wing
        building.wings.append(Wing(name="Hauptgebäude"))
    if wing is not None and wing not in building.wings:
        wing = None
    wanted = floor_name.strip()
    zone = (zone or "").strip()
    # Schreibweise einer bestehenden Zone, damit «innen» nicht eine zweite wird
    zone = next((n for n in zone_names(project) if n.lower() == zone.lower()), zone)
    floor = find_floor(building, wanted, wing)
    if floor is None:
        code = re.sub(r"[^A-Za-z0-9]", "", wanted)[:4].upper() or "EG"
        floor = BuildingService.add_floor(wing or building.wings[0], wanted or code, code,
                                          areal=areal)
        if zone and len(floor.apartments) == 1 and not floor.apartments[0].rooms:
            floor.apartments[0].name = zone          # keine leere Standardzone
    apartment = None
    if zone:
        apartment = next((a for a in floor.apartments
                          if (a.name or "").lower() == zone.lower()), None)
        if apartment is None:
            # die leere Standardzone eines Stockwerks übernimmt den Namen
            default = next((a for a in floor.apartments if not a.rooms
                            and not _named_zone(floor, a)), None)
            if default is not None:
                default.name = zone
                apartment = default
            else:
                apartment = BuildingService.add_apartment(floor, zone)
    elif floor.apartments:
        apartment = floor.apartments[0]
    else:
        apartment = BuildingService.add_apartment(floor, floor.short_code or floor.name)
    room = BuildingService.add_room(apartment, number.strip(), name.strip())
    room.floor_id = floor.id
    return room


def _floor_of(project, room_id: str):
    for building in project.areal.buildings:
        for floor in building.all_floors:
            if any(r.id == room_id for r in floor.all_rooms):
                return floor
    return None


# ── Zuordnen ─────────────────────────────────────────────────────────────

@dataclass
class AssignResult:
    device_moved: bool = False
    channels: int = 0
    renamed: int = 0

    def text(self) -> str:
        parts = []
        if self.device_moved:
            parts.append("Gerät zugeordnet")
        if self.channels:
            parts.append(f"{self.channels} Aktorkanäle")
        if self.renamed:
            parts.append(f"{self.renamed} GAs umbenannt")
        return ", ".join(parts) or "nichts geändert"


def assign(project, plan: RoomPlan, room, operator_address: str = "",
           channel_keys=()) -> AssignResult:
    """Taster/Sensor (Gerät und seine eigenen GAs) und die gewählten
    Aktorkanäle dem Raum zuordnen; GA-Namen mit Raum statt Geräteadresse."""
    from .ets_corrections import set_device_room
    result = AssignResult()
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    numbers = _used_numbers(project, room.id)
    # zuerst die Aktorkanäle: sie sind die Elemente des Raums (tiefe Nummern),
    # die eigenen GAs eines Tasters gehen oft nur an einen Logikserver
    for key in channel_keys:
        channel = plan.channels.get(key)
        if channel is None:
            continue
        gas = [by_address[a] for a in channel.addresses if a in by_address]
        if not gas or all(ga.room_id == room.id for ga in gas):
            continue
        result.renamed += _move_gas(project, gas, room, numbers)
        result.channels += 1
    operator = plan.operators.get(operator_address) if operator_address else None
    if operator is not None:
        # False auch, wenn der Raum aus der Planung folgt: dann bleibt er
        result.device_moved = set_device_room(project, operator.device, room)
        groups: dict[tuple[str, str], list] = {}
        for address in operator.addresses:
            ga = by_address.get(address)
            if ga is not None:
                groups.setdefault((ga.gewerk_code or "SF", _element_of(ga)), []).append(ga)
        for gas in groups.values():
            result.renamed += _move_gas(project, gas, room, numbers)
    return result


def _element_of(ga) -> str:
    """Element einer GA aus ihrem Namen («J_1.1.4_01 …» -> «J_1.1.4_01»)."""
    return (ga.designation or "").split(" ", 1)[0]


def _used_numbers(project, room_id: str) -> dict[str, set[int]]:
    used: dict[str, set[int]] = {}
    for ga in project.group_addresses.all_addresses():
        if ga.room_id == room_id and ga.element_number:
            used.setdefault(ga.gewerk_code or "SF", set()).add(ga.element_number)
    return used


# Element am Anfang des Namens: Gewerk, Ort (Geräteadresse oder Stockwerk/
# Raum), Nummer; danach Funktion und Klartext
_ELEMENT = re.compile(r"^(?P<code>[A-Za-z0-9]+(?:_[^\s_]+)*?)_(?P<n>\d{2,})(?P<rest>(?: .*)?)$")


def _move_gas(project, gas: list, room, numbers: dict[str, set[int]]) -> int:
    """GAs eines Elements in den Raum: Raum an der GA, nächste freie
    Elementnummer je Gewerk im Raum, Name nach dem Schema. Gibt die Anzahl
    umbenannter GAs zurück."""
    from .ets_corrections import set_ga_field
    from .naming_engine import element_code, label_floor_code
    floor = _floor_of(project, room.id)
    floor_code = label_floor_code(floor.short_code or "", room.number) if floor else ""
    gewerk = next((ga.gewerk_code for ga in gas if ga.gewerk_code), "") or "SF"
    used = numbers.setdefault(gewerk, set())
    current = {ga.element_number for ga in gas if ga.room_id == room.id and ga.element_number}
    if len(current) == 1:
        number = current.pop()
    else:
        number = 1
        while number in used:
            number += 1
    used.add(number)
    renamed = 0
    for ga in gas:
        old_room_name = _room_name(project, ga.room_id)
        ga.room_id = room.id
        ga.room_number = room.number
        ga.element_number = number
        match = _ELEMENT.match(ga.designation or "")
        code = (ga.gewerk_code or gewerk)
        if match is None or not match.group("code").upper().startswith(code.upper() + "_"):
            continue          # eigener Name: nur der Raum ändert
        rest = match.group("rest")
        rest = _with_room_name(rest, room.name, old_room_name)
        new = element_code(code, floor_code, room.number, number) + rest
        if new != ga.designation:
            set_ga_field(project, ga, "designation", new)
            renamed += 1
    return renamed


def _room_name(project, room_id: str) -> str:
    if not room_id:
        return ""
    for _label, _floor, room in all_rooms(project):
        if room.id == room_id:
            return room.name
    return ""


def _with_room_name(rest: str, room_name: str, old_room_name: str) -> str:
    """« AUF/AB (Motor C)» -> « AUF/AB (Wohnen Motor C)»; ein früherer
    Raumname im Klartext wird ersetzt."""
    match = re.match(r"^(?P<head>.*?) \((?P<text>.*)\)$", rest)
    if match is None:
        if not room_name:
            return rest
        return f"{rest} ({room_name})" if rest else f" ({room_name})"
    text = match.group("text")
    if old_room_name and (text == old_room_name or text.startswith(old_room_name + " ")):
        text = text[len(old_room_name):].lstrip()
    if room_name and not (text == room_name or text.startswith(room_name + " ")):
        text = f"{room_name} {text}".strip()
    return f"{match.group('head')} ({text})"
