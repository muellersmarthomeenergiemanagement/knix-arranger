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
    return ref.role or "unbekannt"


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


def ref_hints(function_type: str, ref, linked: set[str]) -> list[str]:
    """Hinweise zu einer GA einer Funktion (gleich wie in der Validierung)."""
    if not ref.address:
        return ["GA nicht gefunden"]
    hints = []
    if is_ets_generated(ref):
        hints.append("von der ETS angelegt: in die passende Hauptgruppe "
                     "verschieben und benennen")
    elif function_type != "FT-0":
        point = function_point(function_type, ref)
        if point and not _dpt_matches(ref.datapoint_type, point.dpt):
            hints.append(f"DPT {_dpt_text(ref.datapoint_type)} statt "
                         f"{_dpt_text(point.dpt)}")
    if ref.address not in linked:
        hints.append("auf kein KO verknüpft")
    return hints


def overview_rows(project) -> list[FunctionRow]:
    linked = _linked_addresses(project)
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
            rows.append(FunctionRow(
                floor_text, _room_label(floor, room), function.name,
                type_label(function.function_type),
                role_label(function.function_type, ref),
                ref.address, ref.ga_name, _dpt_text(ref.datapoint_type),
                ref_hints(function.function_type, ref, linked)))
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
    for floor, room, function in iter_functions(project):
        where = f"{_room_label(floor, room)}, Funktion «{function.name}»"
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
                # In KNiX geplant: die Funktions-GAs gibt es schon, die der ETS
                # sind überflüssig (verschieben brächte zwei GAs je Punkt)
                measure = ("In der ETS löschen und der Funktion die KNiX-GA zuordnen "
                           "(ETS-Arbeitsliste)"
                           if function.name.strip().lower() in planned_names else
                           "In der ETS in die Hauptgruppe des Stockwerks verschieben und "
                           "nach den Richtlinien benennen")
                issues.append(ValidationIssue(
                    "info", "FA-636",
                    f"{prefix}: GA von der ETS angelegt (HG {_main_group(ref.address)}, "
                    f"Name «{ref.ga_name}»)",
                    ref.address, measure,
                    designation=ref.ga_name))
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
