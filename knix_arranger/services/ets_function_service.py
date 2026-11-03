"""
ETS6-Funktionen (FA-529, FA-636): Katalog der Funktionstypen, Übersicht und
Prüfungen der in der ETS angelegten Funktionen.

Funktionstypen und Funktionspunkte stammen aus knx_master.xml der ETS 6.4
(FunctionTypes, deutsche Texte, Schweizer Schreibweise). Im Projekt stehen
die Rollen mit Namen ("SwitchOnOff"), in knx_master mit Nummer ("DR-1") --
die Zuordnung ist aus Probeprojekten der ETS 6.4 ermittelt (2026-10-21).

Die ETS legt die GAs einer neuen Funktion in die Mittelgruppe ihres Raums
(je Raum eine MG, Untergruppen fortlaufend über alle Funktionen des Raums).
Die MG eines Raums ist die erste freie der HÖCHSTEN Hauptgruppe, ist sie
voll, eine neue HG dahinter (Tests ETS 6.4.1, 2026-10-22: 12/4…12/7, 13/0;
ohne HG 12/13 landete eine EG-Funktion in 4/3, der Lücke des DG). Sie benennt
die GAs nur mit dem Text des Funktionspunkts ("Schalten", "Status") und
vergibt den DPT richtig. Geplante Projekte führen deshalb HG 13 «ETS-
Funktionen» als leere höchste HG (FA-411b).
"""
from __future__ import annotations
from dataclasses import dataclass

from ..models.building import ETS_FUNCTION_MAIN_GROUP, ETS_FUNCTION_MAIN_GROUP_NAME


@dataclass(frozen=True)
class FunctionPoint:
    role: str        # Rolle im Projekt, z.B. "SwitchOnOff"; "" = unbekannt
    label: str       # Text der ETS (de), z.B. "Schalten"
    dpt: str         # Standard-DPT der ETS, z.B. "DPST-1-1"


_SWITCH = FunctionPoint("SwitchOnOff", "Schalten", "DPST-1-1")
_STATUS = FunctionPoint("InfoOnOff", "Status", "DPST-1-1")
_DIM = FunctionPoint("DimmingControl", "Dimmen", "DPST-3-7")
_HEATING_COMMON = (
    FunctionPoint("TempRoom", "Isttemperatur", "DPST-9-1"),
    FunctionPoint("TempRoomSetpoint", "Solltemperatur", "DPST-9-1"),
)
_HEATING_TAIL = (
    FunctionPoint("HVACMode", "Betriebsart", "DPST-20-102"),
    FunctionPoint("WindowStatus", "Fensterkontakt", "DPST-1-19"),
)
_VALVE = FunctionPoint("ValvePosition", "Stellgrösse", "DPST-5-1")
_BLINDS = (
    FunctionPoint("MoveUpDown", "Bewegen", "DPST-1-8"),
    FunctionPoint("StopStepUpDown", "Schritt/Stop", "DPST-1-7"),
    FunctionPoint("WindAlarm", "Windalarm", "DPST-1-5"),
    FunctionPoint("RainAlarm", "Regenalarm", "DPST-1-5"),
)

#: Funktionstyp -> (Bezeichnung, Funktionspunkte). FT-2 bis FT-5 sind in
#: der ETS 6.4 veraltet, kommen in älteren Projekten aber noch vor.
FUNCTION_TYPES: dict[str, tuple[str, tuple[FunctionPoint, ...]]] = {
    "FT-0": ("Benutzerdefiniert", ()),
    "FT-1": ("Licht schalten", (_SWITCH, _STATUS)),
    "FT-2": ("Licht dimmen (alt)", (
        _SWITCH, _DIM, FunctionPoint("DimmingValue", "Wert", "DPST-5-1"), _STATUS)),
    "FT-3": ("Sonnenschutz (alt)", _BLINDS),
    "FT-4": ("Heizkörper (alt)", (*_HEATING_COMMON, _VALVE, *_HEATING_TAIL)),
    "FT-5": ("Fussbodenheizung (alt)", (*_HEATING_COMMON, _VALVE, *_HEATING_TAIL)),
    "FT-6": ("Licht dimmen", (
        _SWITCH, _DIM,
        FunctionPoint("DimmingValue", "Wert", "DPST-5-1"),
        _STATUS,
        FunctionPoint("InfoDimmingValue", "Dimmwert", "DPST-5-1"),
    )),
    "FT-7": ("Sonnenschutz", (
        *_BLINDS,
        FunctionPoint("CurrentAbsolutePositionBlindsPercentage", "Position", "DPST-5-1"),
        FunctionPoint("CurrentAbsolutePositionSlatPercentage", "Lamellenstellung", "DPST-5-1"),
    )),
    # Rollenname der schaltenden Stellgrösse noch nicht gesehen: Zuordnung
    # über den DPT (siehe function_point)
    "FT-8": ("Heizung (schaltende Stellgrösse)", (
        *_HEATING_COMMON, FunctionPoint("", "schaltende Stellgrösse", "DPST-1-1"),
        *_HEATING_TAIL)),
    "FT-9": ("Heizung (stetige Stellgrösse)", (
        *_HEATING_COMMON, FunctionPoint("ValvePosition", "stetige Stellgrösse", "DPST-5-1"),
        *_HEATING_TAIL)),
    "FT-10": ("Steckdose schalten", (_SWITCH, FunctionPoint("InfoOnOff", "Schalten Status", "DPST-1-1"))),
}

#: Namen, die die ETS automatisch angelegten GAs gibt (mit ß und ss)
ETS_STANDARD_NAMES = frozenset(
    name
    for _label, points in FUNCTION_TYPES.values() for p in points
    for name in (p.label, p.label.replace("ss", "ß"))
) | {"Stellgröße", "stetige Stellgröße", "schaltende Stellgröße"}


def type_label(function_type: str) -> str:
    entry = FUNCTION_TYPES.get(function_type)
    return entry[0] if entry else f"Funktionstyp {function_type}"


def function_point(function_type: str, ref) -> FunctionPoint | None:
    """Funktionspunkt einer GA: über die Rolle, sonst -- Rolle unbekannt --
    über den DPT, wenn er im Funktionstyp eindeutig ist."""
    points = FUNCTION_TYPES.get(function_type, ("", ()))[1]
    if ref.role:
        for p in points:
            if p.role == ref.role:
                return p
        return None
    if ref.datapoint_type:
        matches = [p for p in points if p.dpt == ref.datapoint_type]
        if len(matches) == 1:
            return matches[0]
    return None


def role_label(function_type: str, ref) -> str:
    """Bezeichnung der Rolle für Übersicht und Berichte."""
    point = function_point(function_type, ref)
    if point:
        return point.label
    if function_type == "FT-0":
        return ""
    # Ohne Rolle: vom Integrator zusätzlich zugeordnete GA (in der ETS mit GUID)
    return ref.role or "zusätzliche GA"


def is_ets_generated(ref) -> bool:
    """GA, die die ETS beim Anlegen der Funktion erzeugt hat: nur mit dem
    Text des Funktionspunkts benannt -- in welcher HG, hängt von der Struktur
    ab (erste freie MG der höchsten HG)."""
    return bool(ref.address) and ref.ga_name.strip() in ETS_STANDARD_NAMES


def _main_group(address: str) -> int:
    try:
        return int(address.split("/")[0])
    except ValueError:
        return -1


def _middle_group(address: str) -> int:
    try:
        return int(address.split("/")[1])
    except (ValueError, IndexError):
        return -1


def _home_groups(project):
    """Funktion -> (HG des Stockwerks, MG des Funktionstyps oder None)."""
    from .ets_function_plan import TYPE_MIDDLE_GROUP, floor_main_groups
    main_of = floor_main_groups(project)

    def home(floor, function) -> tuple[int | None, int | None]:
        return main_of.get(floor.id), TYPE_MIDDLE_GROUP.get(function.function_type)
    return home


#: Rückmeldungen der Funktion: die ETS legt je Funktion eine Status-GA an,
#: senden muss das Status-KO des Aktors (verknüpft die ETS nicht selbst).
#: Position/Lamellen (FT-7) gelten wie in der Planung als Befehl.
STATUS_ROLES = frozenset({"InfoOnOff", "InfoDimmingValue"})
#: MGs für Rückmeldungen (Variante B; Chalet: 6 Jalousie, 7 Licht)
STATUS_MIDDLE_GROUPS = (6, 7)


def _misplaced(ref, home: tuple[int | None, int | None]) -> str:
    """Wohin eine GA gehört, wenn sie nicht in HG des Stockwerks und MG des
    Funktionstyps liegt ("HG 3", "MG 3/0"); "" = Ort stimmt. Status-GAs
    dürfen auch in den Rückmelde-MGs liegen."""
    main, middle = home
    if main is not None and _main_group(ref.address) != main:
        return f"HG {main}" if middle is None else f"MG {main}/{middle}"
    mg = _middle_group(ref.address)
    if (middle is not None and mg != middle
            and not (ref.role in STATUS_ROLES and mg in STATUS_MIDDLE_GROUPS)):
        return f"MG {_main_group(ref.address)}/{middle}"
    return ""


def _status_finding(ref, linked: set[str], status_links: dict | None):
    """(Stufe, Kurzhinweis, Meldung, Massnahme) zur Status-GA einer Funktion,
    None = in Ordnung oder nicht prüfbar. Ein Status-KO sendet nur auf seine
    erste GA; mehrere Status-KOs auf einer GA: der Wert springt je nach dem
    zuletzt sendenden Kanal."""
    if status_links is None or ref.role not in STATUS_ROLES or ref.address not in linked:
        return None
    links = status_links.get(ref.address, [])
    if not links:
        return ("info", "Status: an keinem Status-KO",
                "an keinem Status-KO eines Aktors",
                "Status-KO des Aktors verknüpfen und den Status im Aktor aktivieren")
    if len(links) > 1:
        return ("warning", f"Status: an {len(links)} Status-KOs – Wert springt",
                f"an {len(links)} Status-KOs ("
                + ", ".join(s.text for s, _ in links[:3]) + ")",
                "Status-GA nur an ein Status-KO hängen: jeder Kanal meldet auf seine "
                "eigene Status-GA, gemeinsamer Status nur über Logik (ODER-Gatter, "
                "Sammelstatus)")
    sender, sent = links[0]
    if sent != ref.address:
        return ("info", f"Status: KO sendet auf {sent}",
                f"{sender.text} sendet auf {sent}, nicht auf diese GA",
                f"Der Funktion die Status-GA {sent} zuordnen oder diese GA als "
                f"sendende GA des KOs setzen")
    return None


def _generated_hint(ref, home) -> str:
    target = _misplaced(ref, home)
    if target:
        return f"von der ETS angelegt: in {target} verschieben und benennen"
    return "von der ETS benannt: nach den Richtlinien benennen"


@dataclass
class FunctionRow:
    """Eine Zeile der Übersicht (Raum > Funktion > GA)."""
    floor: str
    room: str
    function: str
    type_label: str
    role: str
    address: str
    ga_name: str
    datapoint_type: str
    hints: list[str]


def _linked_addresses(project) -> set[str]:
    linked: set[str] = set()
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                for co in device.communication_objects:
                    linked.update(co.connected_gas)
    return linked


def _room_label(floor, room) -> str:
    return " ".join(p for p in (room.number, room.name) if p) or "Raum"


def iter_functions(project):
    """(Stockwerk, Raum, Funktion) aller ETS-Funktionen."""
    for floor in project.areal.all_floors:
        for apartment in floor.apartments:
            for room in apartment.rooms:
                for function in room.ets_functions:
                    yield floor, room, function


def functions_by_address(project) -> dict[str, list[str]]:
    """GA -> ETS-Funktionen, zu denen sie gehört, als "Name (Funktionstyp)"
    (Topologie: Funktion statt Raum am Aktorkanal)."""
    result: dict[str, list[str]] = {}
    for _floor, _room, function in iter_functions(project):
        label = f"{function.name} ({type_label(function.function_type)})"
        for ref in function.refs:
            if ref.address and label not in result.setdefault(ref.address, []):
                result[ref.address].append(label)
    return result


def function_key(floor, room, function) -> tuple[str, str, str]:
    """(Stockwerk, Raum, Funktion) wie in FunctionRow, Schlüssel der Ansicht."""
    return floor.name or floor.short_code, _room_label(floor, room), function.name


def function_text(room, function) -> str:
    """«Jalousien Balkon» (01 Fitness)"""
    return f"«{function.name}» ({_room_label(None, room)})"


# Gemeinsame Eingänge vieler Funktionen, z.B. eine Wetterstation für alle
# Jalousien: in mehreren Funktionen richtig (die ETS legt sie so an)
SHARED_OK_ROLES = frozenset({"WindAlarm", "RainAlarm"})


def shared_function_gas(project) -> dict[str, list[tuple]]:
    """GAs, die in der ETS mehreren Funktionen zugeordnet sind (FA-636b):
    GA -> [(Stockwerk, Raum, Funktion)]. Jede dieser Funktionen bedient
    dann auch alle Elemente der anderen. Wind- und Regenalarm zählen nicht."""
    by_address: dict[str, list[tuple]] = {}
    for floor, room, function in iter_functions(project):
        for ref in function.refs:
            if ref.address and ref.role not in SHARED_OK_ROLES:
                entries = by_address.setdefault(ref.address, [])
                if not any(f is function for _fl, _r, f in entries):
                    entries.append((floor, room, function))
    return {a: e for a, e in by_address.items() if len(e) > 1}


def _check_shared_gas(project) -> list:
    """Eine Warnung je Gruppe von Funktionen mit gemeinsamen GAs (FA-636b)."""
    from .validation_engine import ValidationIssue
    groups: dict[tuple, tuple[list, list[str]]] = {}
    for address, entries in shared_function_gas(project).items():
        key = tuple(id(f) for _fl, _r, f in entries)
        groups.setdefault(key, (entries, []))[1].append(address)
    issues = []
    for entries, addresses in groups.values():
        names = ", ".join(function_text(room, f) for _fl, room, f in entries)
        issues.append(ValidationIssue(
            "warning", "FA-636",
            f"GA {', '.join(addresses)} in {len(entries)} Funktionen zugeordnet: {names} – "
            f"jede bedient auch die Elemente der anderen",
            addresses[0],
            "In der ETS jeder Funktion eigene GAs geben oder die doppelten Funktionen "
            "zu einer zusammenfassen",
            details={"kind": "shared", "addresses": addresses}))
    return issues


@dataclass
class MemberLink:
    """Ein von einer eingelesenen Funktion bedientes Element: Aktorkanal mit
    einer Funktions-GA und der Element-GA des Gewerks am selben KO."""
    code: str              # Gewerk
    place: str             # "02 Bibliothek, Element 2 Fenster gross"
    address: str           # Element-GA
    designation: str
    channel: str           # "1.1.5 Bedienung Storen (M1)"


class EtsFunctionMembers:
    """Bediente Elemente der eingelesenen Funktionen, abgeleitet aus den
    KO-Verknüpfungen der Aktoren (FA-529b): die Funktion hat in der ETS keine
    Mitglieder, nur GAs."""

    def __init__(self, project):
        from .ets_corrections import effective_gewerk
        from .report_service import ReportService
        self._project = project
        self._gas = {ga.address: ga for ga in project.group_addresses.all_addresses()}
        self._index = ReportService(project).gewerk_index()
        self._rooms = {r.id: r for r in project.all_rooms}
        self._function_gas = {ref.address for _fl, _r, f in iter_functions(project)
                              for ref in f.refs if ref.address}
        self._gewerk = lambda ga: effective_gewerk(project, ga)
        self._actor_cos = [(d, co) for area in project.topology.areas
                           for line in area.lines for d in line.devices
                           if d.device_type in ("actor", "gateway")
                           for co in d.communication_objects if co.connected_gas]

    def _place(self, address: str, code: str) -> str:
        for room_id, short, element in self._index.get(address, []):
            room = self._rooms.get(room_id)
            if room is None or short != code:
                continue
            text = _room_label(None, room)
            assignment = next((a for a in room.gewerk_assignments
                               if a.gewerk_code == code), None)
            if element and assignment is not None and assignment.count > 1:
                text += f", Element {element} {assignment.element_label(element)}".rstrip()
            return text
        return ""

    def members(self, function) -> list[MemberLink]:
        addresses = {ref.address for ref in function.refs if ref.address}
        found: dict[tuple, MemberLink] = {}
        for device, co in self._actor_cos:
            if not addresses & set(co.connected_gas):
                continue
            element = next((a for a in sorted(co.connected_gas, key=_address_key)
                            if a not in self._function_gas and a in self._gas
                            and _main_group(a) != 0
                            and self._gewerk(self._gas[a])), None)
            if element is None:
                continue
            ga = self._gas[element]
            code = self._gewerk(ga)
            place = self._place(element, code)
            # KO-Name ohne Funktion: "Bedienung Storen (M2), Endlage" -> Kanal
            channel = (co.name or "").split(",")[0].strip()
            # Ein Eintrag je Aktorkanal, nicht je KO (Bewegen, Beschattung …):
            # das Element mit Raum, sonst die kleinste Element-GA (Chalet M5:
            # 3/1/0 «Halle» statt 3/1/4 «_beschattung» ohne Raum)
            key = (device.physical_address, channel or element.rsplit("/", 1)[0], code)
            link = MemberLink(code, place, element, ga.designation,
                              f"{device.physical_address} {channel}".strip())
            known = found.get(key)
            if known is None or (bool(place), _neg_key(element)) > (
                    bool(known.place), _neg_key(known.address)):
                found[key] = link
        return sorted(found.values(), key=lambda m: (m.code, m.place, _address_key(m.address)))


@dataclass
class OperatorLink:
    """Bedienendes Element einer Funktion: sendendes KO eines Tasters oder
    Sensors auf eine Funktions-GA."""
    place: str             # "Studio, Taste 2"
    address: str           # Funktions-GA
    text: str              # Objektfunktion, z.B. "AUF/AB, Jalousie"
    device: str            # "Sensor 1.1.68 KO 6"
    physical_address: str = ""


def function_operators(project, addresses) -> list[OperatorLink]:
    """Sendende KOs von Tastern, Sensoren, Visualisierungen … (nicht Aktoren
    und Gateways) auf die GAs; die sendende GA eines KOs ist die erste."""
    from .ko_links import parse_flags
    from .topology_diagram import device_type_label
    addresses = set(addresses)
    rooms = {r.id: r for r in project.all_rooms}
    result = []
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                if device.device_type in ("actor", "gateway"):
                    continue
                room = rooms.get(device.room_id)
                where = _room_label(None, room) if room else device.installation_location
                for co in device.communication_objects:
                    flags = parse_flags(co.flags)
                    if (not co.connected_gas or co.connected_gas[0] not in addresses
                            or (flags and "Ü" not in flags)):
                        continue
                    place = ", ".join(p for p in (where, (co.name or "").strip()) if p)
                    result.append(OperatorLink(
                        place, co.connected_gas[0], (co.object_function or "").strip(),
                        f"{device_type_label(device)} {device.physical_address} "
                        f"KO {co.object_number}", device.physical_address))
    return sorted(result, key=lambda o: (o.place, _address_key(o.address)))


def _neg_key(address: str) -> tuple:
    """Kleinere Adresse = grösserer Schlüssel (für max-Vergleiche)."""
    return tuple(-p for p in _address_key(address))


def _address_key(address: str) -> tuple:
    try:
        return tuple(int(p) for p in address.split("/"))
    except ValueError:
        return (999,)


#: Rolle der ETS -> Funktion nach dem Aktor-KO (ets_function_plan.ko_functions)
_ROLE_FUNCTION = {
    "MoveUpDown": "AUF/AB", "StopStepUpDown": "STOPP",
    "WindAlarm": "STOERUNG", "RainAlarm": "STOERUNG",
    "CurrentAbsolutePositionBlindsPercentage": "POSITION HOEHE",
    "CurrentAbsolutePositionSlatPercentage": "POSITION LAMELLEN",
    "SwitchOnOff": "E/A", "DimmingControl": "DIM", "DimmingValue": "WERT",
    "HVACMode": "UMSCHALTEN BETRIEBSART",
}
_KO_FUNCTION_LABEL = {
    "AUF/AB": "Bewegen", "STOPP": "Schritt/Stop", "POSITION HOEHE": "Position",
    "POSITION LAMELLEN": "Lamellenstellung", "BESCHATTUNG": "Beschattung",
    "SPERREN": "Sperren", "E/A": "Schalten", "DIM": "Dimmen", "WERT": "Wert",
    "STOERUNG": "Alarm", "UMSCHALTEN BETRIEBSART": "Betriebsart",
}


def role_mismatch(function_type: str, ref, by_ko: dict[str, str] | None) -> tuple[str, str] | None:
    """(Hinweis, Massnahme), wenn das Aktor-KO der GA etwas anderes tut, als
    die Rolle in der Funktion sagt (FA-531a: Bedeutung vom Gerät), z.B. die
    Beschattung auf dem Platz «Windalarm» -- die ETS erzeugt die GAs je
    Rolle, umbenannt bleibt die Rolle."""
    if not by_ko or not ref.role or not ref.address:
        return None
    point = function_point(function_type, ref)
    expected = _ROLE_FUNCTION.get(ref.role)
    actual = by_ko.get(ref.address)
    if point is None or not expected or not actual or actual == expected:
        return None
    label = _KO_FUNCTION_LABEL.get(actual, actual)
    other = next((p for p in FUNCTION_TYPES.get(function_type, ("", ()))[1]
                  if _ROLE_FUNCTION.get(p.role) == actual), None)
    measure = (f"In der ETS der Rolle «{other.label}» zuordnen" if other else
               f"In der ETS als zusätzliche GA ohne Rolle führen; die Funktion "
               f"«{type_label(function_type)}» hat keinen Platz für {label}")
    return f"Rolle {point.label}, KO sagt {label}", measure


def ref_hints(function_type: str, ref, linked: set[str],
              home: tuple[int | None, int | None] = (None, None),
              status_links: dict | None = None,
              by_ko: dict[str, str] | None = None) -> list[str]:
    """Hinweise zu einer GA einer Funktion (gleich wie in der Validierung);
    home = HG des Stockwerks und MG des Funktionstyps (siehe _home_groups),
    status_links = multi_ga_check.build_status_link_index (None = Status
    nicht prüfen), by_ko = ets_function_plan.ko_functions."""
    if not ref.address:
        return ["GA nicht gefunden"]
    hints = []
    mismatch = role_mismatch(function_type, ref, by_ko)
    if is_ets_generated(ref):
        hints.append(_generated_hint(ref, home))
    elif mismatch:
        # die falsche Rolle erklärt auch einen abweichenden DPT
        hints.append(mismatch[0])
    elif function_type != "FT-0":
        point = function_point(function_type, ref)
        if point and not _dpt_matches(ref.datapoint_type, point.dpt):
            hints.append(f"DPT {_dpt_text(ref.datapoint_type)} statt "
                         f"{_dpt_text(point.dpt)}")
    if ref.address not in linked:
        hints.append("auf kein KO verknüpft")
    status = _status_finding(ref, linked, status_links)
    if status:
        hints.append(status[1])
    return hints


def overview_rows(project) -> list[FunctionRow]:
    from .multi_ga_check import build_status_link_index
    linked = _linked_addresses(project)
    home_of = _home_groups(project)
    status_links = build_status_link_index(project)
    from .ets_function_plan import ko_functions
    by_ko = ko_functions(project)
    shared = shared_function_gas(project)
    rows = []
    for floor, room, function in iter_functions(project):
        floor_text = floor.name or floor.short_code
        if not function.refs:
            rows.append(FunctionRow(
                floor_text, _room_label(floor, room), function.name,
                type_label(function.function_type), "", "", "", "",
                [] if function.function_type == "FT-0" else ["keine GA"]))
            continue
        for ref in function.refs:
            hints = ref_hints(function.function_type, ref, linked, home_of(floor, function),
                              status_links, by_ko)
            others = [function_text(r, f) for _fl, r, f in shared.get(ref.address, [])
                      if f is not function]
            if others:
                hints.append(f"auch in {', '.join(others)}")
            rows.append(FunctionRow(
                floor_text, _room_label(floor, room), function.name,
                type_label(function.function_type),
                role_label(function.function_type, ref),
                ref.address, ref.ga_name, _dpt_text(ref.datapoint_type), hints))
    return rows


def _dpt_matches(actual: str, expected: str) -> bool:
    """Ohne DPT oder nur mit Haupttyp ("DPT-1") wird nur verglichen, was da ist."""
    if not actual:
        return True
    a = actual.upper().replace("DPST-", "").replace("DPT-", "").split("-")
    e = expected.upper().replace("DPST-", "").replace("DPT-", "").split("-")
    return a == e[:len(a)]


def _dpt_text(dpt: str) -> str:
    """"DPST-1-8" -> "1.008"."""
    parts = (dpt or "").upper().replace("DPST-", "").replace("DPT-", "").split("-")
    if not parts or not parts[0]:
        return ""
    if len(parts) == 1:
        return parts[0]
    try:
        return f"{int(parts[0])}.{int(parts[1]):03d}"
    except ValueError:
        return dpt


def check_functions(project) -> list:
    """FA-636: Prüfung der ETS-Funktionen und der höchsten HG."""
    from .validation_engine import ValidationIssue
    issues = []
    linked = _linked_addresses(project)
    function_addresses: set[str] = set()
    generated = 0
    planned_names = {f.name.strip().lower() for f in getattr(project, "functions", [])}
    home_of = _home_groups(project)
    from .multi_ga_check import build_status_link_index
    status_links = build_status_link_index(project)
    from .ets_function_plan import ko_functions
    by_ko = ko_functions(project)
    for floor, room, function in iter_functions(project):
        where = f"{_room_label(floor, room)}, Funktion «{function.name}»"
        home = home_of(floor, function)
        if not function.refs and function.function_type != "FT-0":
            issues.append(ValidationIssue(
                "info", "FA-636", f"{where}: keine Gruppenadresse",
                "", "In der ETS die GAs der Funktion zuordnen oder die Funktion entfernen"))
        for ref in function.refs:
            label = role_label(function.function_type, ref)
            prefix = f"{where}, {label}" if label else where
            if not ref.address:
                issues.append(ValidationIssue(
                    "warning", "FA-636", f"{prefix}: GA nicht gefunden", "",
                    "In der ETS die GA der Funktion neu zuordnen"))
                continue
            function_addresses.add(ref.address)
            if is_ets_generated(ref):
                generated += 1
                target = _misplaced(ref, home)
                # In KNiX geplant: die Funktions-GAs gibt es schon, die der ETS
                # sind überflüssig (verschieben brächte zwei GAs je Punkt)
                if function.name.strip().lower() in planned_names:
                    measure = ("In der ETS löschen und der Funktion die KNiX-GA zuordnen "
                               "(ETS-Arbeitsliste)")
                elif target:
                    measure = (f"In der ETS in {target} verschieben und nach den "
                               f"Richtlinien benennen")
                else:
                    measure = "In der ETS nach den Richtlinien benennen"
                message = (f"{prefix}: GA von der ETS angelegt (HG {_main_group(ref.address)}, "
                           f"Name «{ref.ga_name}»)" if target else
                           f"{prefix}: GA mit dem Namen der ETS «{ref.ga_name}»")
                issues.append(ValidationIssue(
                    "info", "FA-636", message, ref.address, measure,
                    designation=ref.ga_name))
            elif mismatch := role_mismatch(function.function_type, ref, by_ko):
                issues.append(ValidationIssue(
                    "warning", "FA-636", f"{prefix}: {mismatch[0]}", ref.address,
                    mismatch[1], designation=ref.ga_name,
                    details={"kind": "role", "role": ref.role}))
            elif function.function_type != "FT-0":
                point = function_point(function.function_type, ref)
                if point and not _dpt_matches(ref.datapoint_type, point.dpt):
                    issues.append(ValidationIssue(
                        "warning", "FA-636",
                        f"{prefix}: DPT {_dpt_text(ref.datapoint_type)}, die Funktion "
                        f"erwartet {_dpt_text(point.dpt)}",
                        ref.address, "Andere GA zuordnen oder den DPT der GA prüfen",
                        designation=ref.ga_name,
                        details={"expected": _dpt_text(point.dpt),
                                 "actual": _dpt_text(ref.datapoint_type)}))
            if ref.address not in linked:
                issues.append(ValidationIssue(
                    "info", "FA-636", f"{prefix}: GA auf kein KO verknüpft",
                    ref.address,
                    "In der ETS mit den KOs von Aktor und Taster verknüpfen",
                    designation=ref.ga_name))
            status = _status_finding(ref, linked, status_links)
            if status:
                level, _hint, text, measure = status
                issues.append(ValidationIssue(
                    level, "FA-636", f"{prefix}: {text}", ref.address, measure,
                    designation=ref.ga_name))
    issues.extend(_check_shared_gas(project))
    issues.extend(_check_catch_main_group(project, function_addresses, generated))
    return issues


def _check_catch_main_group(project, function_addresses: set[str], generated: int) -> list:
    """Die ETS legt die GAs neuer Funktionen in die erste freie MG der
    höchsten HG. Geplant: das soll die leere HG 13 sein; importiert: Hinweis,
    wenn dort eigene GAs liegen."""
    from .validation_engine import ValidationIssue
    structure = project.group_addresses
    if not structure.main_groups:
        return []
    top = max(hg.number for hg in structure.main_groups)
    own = [ga for ga in structure.all_addresses()
           if ga.main_group == top and ga.address not in function_addresses
           and not ga.function_id]
    details = {"hg": top, "count": len(own), "generated": generated}
    if not project.topology.is_imported and top != ETS_FUNCTION_MAIN_GROUP:
        return [ValidationIssue(
            "warning", "FA-636",
            f"Neue ETS-Funktionen landen in HG {top}: die ETS legt ihre GAs in die "
            f"erste freie Mittelgruppe der höchsten Hauptgruppe",
            f"HG {top}",
            f"Adressen neu erzeugen – KNiX legt HG {ETS_FUNCTION_MAIN_GROUP} "
            f"«{ETS_FUNCTION_MAIN_GROUP_NAME}» als höchste Hauptgruppe an",
            details=details)]
    if not own:
        return []
    level = "info" if project.topology.is_imported else "warning"
    return [ValidationIssue(
        level, "FA-636",
        f"HG {top} enthält {len(own)} eigene GA(s): die ETS legt die GAs neuer "
        f"Funktionen in die erste freie Mittelgruppe der höchsten Hauptgruppe",
        f"HG {top}",
        f"Eigene GAs in eine andere Hauptgruppe verschieben bzw. eine leere HG "
        f"{ETS_FUNCTION_MAIN_GROUP} «{ETS_FUNCTION_MAIN_GROUP_NAME}» anlegen",
        details=details)]


def ensure_ets_function_main_group(project, structure) -> None:
    """Geplante Projekte: leere HG 13 «ETS-Funktionen» als höchste HG, damit
    die ETS die GAs neuer Funktionen dort ablegt statt in den Lücken des
    obersten Stockwerks (FA-411b). Der CSV-Export schreibt auch leere HGs."""
    topology = getattr(project, "topology", None)
    if topology is not None and topology.is_imported:
        return
    from ..models.group_address import MainGroup
    if any(hg.number == ETS_FUNCTION_MAIN_GROUP for hg in structure.main_groups):
        return
    structure.main_groups.append(
        MainGroup(number=ETS_FUNCTION_MAIN_GROUP, name=ETS_FUNCTION_MAIN_GROUP_NAME))
    structure.main_groups.sort(key=lambda hg: hg.number)
