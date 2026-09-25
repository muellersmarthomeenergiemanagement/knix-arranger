"""
GewerkSuggestionService -- schlaegt aus einer importierten Topologie
Raum+Gewerk-Kombinationen fuer noch nicht zugewiesene Aktor-Kanaele vor.

Dreht die Richtung von gewerk_channel_matching.py um: statt dass der
Nutzer im GewerkChannelAssignDialog erst manuell ein Geraet/einen Kanal
suchen muss, werden hier ALLE Aktor-Kanaele der Topologie gescannt und
gegen jedes in _MATCHABLE_CODES gelistete Gewerk-Schema getestet. Nur bei
eindeutigem Treffer (genau ein Gewerk-Code mit mindestens einer
Kernfunktion erkannt) wird ein Vorschlag erzeugt -- mehrdeutige oder
schwache Treffer (nur RM/STOERUNG/SPERREN) werden bewusst verworfen statt
geraten, siehe _PRIMARY_FUNCTIONS.

Raum, Gewerk und Element kommen bevorzugt aus den Bezeichnungen der am
Kanal haengenden GAs ("J.OG.04.02_move" -> Raum OG.04, Jalousie, Element 2
-- dieselbe Zaehlung wie GewerkService.derive_gewerk_assignments, die aus
denselben Bezeichnungen "J ×2" ableitet). Nur ohne auswertbare Bezeichnung
gilt der Raum des Geraets -- bei Aktoren ist das meist der Verteiler, nicht
der Raum des Verbrauchers.

Wie bei scene_detection_service.py: reine Erkennungsfunktion, haengt
selbst nichts an `project` an, der Aufrufer (UI) committet nach Review.
"""
from __future__ import annotations
from dataclasses import dataclass

from ..models.topology import Device
from ..models.building import Room, GewerkAssignment
from ..models.group_address import GroupAddress
from .address_generator import AddressGenerator
from .gewerk_channel_matching import (
    group_channels_by_name, match_channel_to_schema, all_linked_ga_ids,
)
from .gewerk_service import GewerkService

# Gewerk-Codes, fuer die _FUNCTION_KEYWORDS (gewerk_channel_matching.py)
# tatsaechlich aussagekraeftige Stichworte enthaelt -- Licht-Familie,
# Jalousie-Familie, DALI. Fuer alle anderen 29 Katalog-Codes (Heizung,
# Farblicht, Lueftung, PV/Speicher, Multimedia, generische Bloecke, ...)
# wuerde die Erkennung bestenfalls "Stoerung"/"Sperren" finden, nie das
# eigentliche Gewerk -- daher hier bewusst nicht mitgetestet, um keine
# falschen Vorschlaege vorzutaeuschen. Erweiterbar, sobald weitere
# Stichworte in _FUNCTION_KEYWORDS ergaenzt werden. Wird von der
# Review-UI als Auswahl fuer die manuelle Korrektur angeboten.
_MATCHABLE_CODES = ("L", "LD", "S", "SD", "J", "DF", "F", "FG", "M", "R", "T", "LDA")

# Codes aus _MATCHABLE_CODES, die auf ein GENUIN unterschiedliches Schema
# aufloesen (L/LD/S/SD teilen sich alle dasselbe Licht-Schema, J/DF/F/FG/
# M/R/T alle dasselbe Jalousie-Schema -- category-basierter Fallback in
# AddressGenerator._get_block_schema). Nur diese Repraesentanten werden
# beim automatischen Erkennen gegeneinander getestet: wuerde man alle
# Codes einer Familie einzeln testen, waeren sie fuer denselben Kanal
# IMMER punktgleich (identisches Schema) -- das Ergebnis waere ein
# Dauer-Unentschieden statt eines Vorschlags. Der Nutzer kann den
# vorgeschlagenen Code in der Review-UI trotzdem auf jeden Code aus
# _MATCHABLE_CODES umstellen.
_REPRESENTATIVE_CODES = ("L", "J", "LDA")

# Funktionen, die tatsaechlich eine Gewerk-Identitaet belegen (schreibende
# Kernfunktion). Ein Treffer nur in RM/RM WERT/STOERUNG/SPERREN/STATUS ...
# reicht nicht aus, um ein Gewerk zu erkennen (z.B. traegt praktisch jeder
# Aktor ein Stoerungs-Objekt).
_PRIMARY_FUNCTIONS = {
    "E/A", "DIM", "WERT", "AUF/AB", "STOPP",
    "POSITION HOEHE", "POSITION LAMELLEN", "BESCHATTUNG", "SZENE",
}

# Mindestanzahl erkannter Funktionen, damit ein Treffer ueberhaupt als
# Vorschlag zaehlt. Am echten Chalet-Projekt beobachtet: ein einzelnes
# "E/A" (Stichwort "schalten") matcht auch auf voellig fachfremde
# 1-Bit-Objekte -- Leckage-Sensoren, Rauchmelder-Alarme, ein Audio-Gateway
# ("Lautstaerke relativ" -> matcht faelschlich "STOPP") wurden so als
# "Licht"/"Jalousie" vorgeschlagen. Jeder echte Aktor in diesem Datensatz
# lieferte dagegen mindestens 2 Funktionen (Licht: E/A+RM, Jalousie: bis
# zu 6). Ein einzelner Treffer ist damit kein verlaessliches Signal.
_MIN_MATCHED_FUNCTIONS = 2


@dataclass
class GewerkSuggestion:
    device: Device
    channel_name: str
    room: Room
    gewerk_code: str
    matched: dict[str, GroupAddress]
    schema_function_count: int
    # Bereits vorhandene, noch unverknuepfte GewerkAssignment desselben
    # Codes in diesem Raum (siehe find_reusable_assignment) -- wird beim
    # Uebernehmen befuellt statt eine zweite, doppelte Zeile anzulegen.
    existing_assignment: GewerkAssignment | None = None
    # Element innerhalb der Zuweisung (1-basiert), z.B. 2 fuer den zweiten
    # Storen bei "J ×2" -- aus der GA-Bezeichnung, sonst 1.
    element_nr: int = 1
    # Raum/Gewerk/Element stammen aus den GA-Bezeichnungen (sonst: Raum des
    # Geraets und bestes Schema)
    from_designation: bool = False


def find_reusable_assignment(
    room: Room, gewerk_code: str, element_nr: int = 1,
) -> GewerkAssignment | None:
    """Eine bereits vorhandene, aber noch unverknüpfte GewerkAssignment
    desselben Codes in diesem Raum -- typischerweise von der
    Bezeichnungs-basierten Gewerk-Ableitung beim Import angelegt
    (FA-519b, `GewerkService.derive_gewerk_assignments`, laeuft
    automatisch bei jedem GA-Import und kennt nur den aus der
    GA-Bezeichnung geratenen Gewerk-Code, keinen echten Aktor-Kanal).
    Ohne diese Wiederverwendung würde ein Vorschlag hier eine zweite,
    für den Nutzer verwirrende Zuweisung desselben Gewerks im selben Raum
    anlegen, statt die bereits vorhandene mit dem echten Kanal zu
    vervollständigen. Bei Mehrfach-Zuweisungen ("J ×2") muss das Element
    existieren und noch unverknüpft sein."""
    for assignment in room.gewerk_assignments:
        if (
            assignment.gewerk_code == gewerk_code
            and element_nr <= assignment.count
            and not assignment.all_element_links().get(element_nr)
        ):
            return assignment
    return None


def assignment_for_suggestion(
    room: Room, gewerk_code: str, element_nr: int = 1,
) -> tuple[GewerkAssignment, int]:
    """Zuweisung und Element, in die ein uebernommener Vorschlag geschrieben
    wird: eine passende unverknuepfte (find_reusable_assignment), sonst eine
    Zuweisung desselben Gewerks, die um das Element erweitert wird ("L ×2"
    -> "L ×3" fuer Element 3), sonst eine neue mit Anzahl = Element-Nr.
    Neue Zuweisungen werden dem Raum angehaengt."""
    assignment = find_reusable_assignment(room, gewerk_code, element_nr)
    if assignment:
        return assignment, element_nr
    for candidate in room.gewerk_assignments:
        if candidate.gewerk_code == gewerk_code and element_nr > candidate.count:
            candidate.count = element_nr
            return candidate, element_nr
    assignment = GewerkAssignment(gewerk_code=gewerk_code, count=element_nr)
    room.gewerk_assignments.append(assignment)
    return assignment, element_nr


def _designation_targets(project) -> dict[str, tuple[Room, str, int]]:
    """GA-id -> (Raum, Gewerk-Code, Element-Nr.) aus der Bezeichnung.

    Element-Nr. ist die Position der Element-Kennung unter allen Kennungen
    desselben Raums/Gewerks (".01", ".02" -> 1, 2), genau wie die Anzahl in
    GewerkService.derive_gewerk_assignments gezaehlt wird. Zentraladressen
    (HG 0) und kombinierte Adressierung ("L.OG.05.02+04") bleiben aussen vor."""
    room_index = GewerkService._build_room_index(project.areal)
    parsed: dict[str, tuple[tuple[str, str], str, str]] = {}
    elements: dict[tuple[tuple[str, str], str], set[str]] = {}
    for ga in project.group_addresses.all_addresses():
        if ga.main_group == 0 or not ga.designation:
            continue
        matched = GewerkService._match_ga_designation(ga.designation)
        if not matched:
            continue
        code, floor_code, room_nr, elem_nr, is_combined = matched
        if is_combined or (floor_code, room_nr) not in room_index:
            continue
        key = (floor_code, room_nr)
        parsed[ga.id] = (key, code, elem_nr)
        elements.setdefault((key, code), set()).add(elem_nr)

    order = {
        group: {nr: i + 1 for i, nr in enumerate(sorted(nrs, key=int))}
        for group, nrs in elements.items()
    }
    return {
        ga_id: (room_index[key], code, order[(key, code)][elem_nr])
        for ga_id, (key, code, elem_nr) in parsed.items()
    }


def suggest_gewerk_assignments(project) -> tuple[list[GewerkSuggestion], list[str]]:
    """Scannt alle Aktor-Kanaele der Topologie und schlaegt Raum+Gewerk
    fuer noch nicht verknuepfte Kanaele vor.

    Rueckgabe: (Vorschlaege, Warnungen). Aendert `project` nicht."""
    warnings: list[str] = []
    suggestions: list[GewerkSuggestion] = []

    rooms_by_id = {room.id: room for room in project.all_rooms}
    already_linked = all_linked_ga_ids(project)
    ga_by_address = {
        ga.address: ga for ga in project.group_addresses.all_addresses()
    }
    gen = AddressGenerator(project.gewerk_catalog, variant=project.config.mg_variant)

    schema_cache: dict[str, object] = {}
    for code in _REPRESENTATIVE_CODES:
        gewerk = project.gewerk_catalog.get(code)
        if not gewerk:
            continue
        schema = gen._get_block_schema(gewerk, assignment=None, is_feedback=False)
        if schema:
            schema_cache[code] = schema

    all_devices = [
        d
        for area in project.topology.areas
        for line in area.lines
        for d in line.devices
    ]
    targets = _designation_targets(project)

    skipped_no_room = 0
    for device in all_devices:
        # Taster senden auf dieselben GAs wie der Aktor -- ihr Vorschlag
        # wuerde dasselbe Element ein zweites Mal belegen.
        if not device.communication_objects or device.device_type == "sensor":
            continue
        device_room =rooms_by_id.get(device.room_id) if device.room_id else None
        missing_room = False

        for channel_name, cos in group_channels_by_name(device).items():
            if _channel_already_linked(cos, ga_by_address, already_linked):
                continue

            target = _channel_target(cos, ga_by_address, targets)
            if target:
                suggestion = _suggest_from_designation(
                    device, channel_name, cos, target, project, gen, ga_by_address,
                )
                if suggestion:
                    suggestions.append(suggestion)
                    continue

            if not device_room:
                missing_room = True
                continue

            best_code, best_matched = _best_match(cos, schema_cache, ga_by_address)
            if not best_code:
                continue

            suggestions.append(GewerkSuggestion(
                device=device, channel_name=channel_name, room=device_room,
                gewerk_code=best_code, matched=best_matched,
                schema_function_count=_non_reserve_function_count(schema_cache[best_code]),
                existing_assignment=find_reusable_assignment(device_room, best_code),
            ))
        if missing_room:
            skipped_no_room += 1

    if skipped_no_room:
        warnings.append(
            f"{skipped_no_room} Gerät(e) ohne erkannten Raum wurden übersprungen."
        )
    return _merge_same_target(suggestions), warnings


def _merge_same_target(suggestions: list[GewerkSuggestion]) -> list[GewerkSuggestion]:
    """Ein Vorschlag je (Raum, Gewerk, Element) aus der Bezeichnung.

    Manche Geraete teilen einen Kanal in mehrere ComObject-Namen auf (DALI-
    Gateway: "G7, Schalten," / "G7, Dimmen," ...) -- Vorschlaege desselben
    Geraets werden zu einem zusammengefasst. Zielen verschiedene Geraete
    auf dasselbe Element, bleibt der mit den meisten erkannten Funktionen.
    Vorschlaege ohne Bezeichnungs-Ziel (Raum des Geraets) bleiben
    unveraendert."""
    result: list[GewerkSuggestion] = []
    by_target: dict[tuple, GewerkSuggestion] = {}
    for s in suggestions:
        if not s.from_designation:
            result.append(s)
            continue
        key = (s.room.id, s.gewerk_code, s.element_nr)
        kept = by_target.get(key)
        if kept is None:
            by_target[key] = s
            result.append(s)
        elif kept.device is s.device:
            kept.matched = {**s.matched, **kept.matched}
            kept.channel_name = f"{kept.channel_name} / {s.channel_name}"
        elif len(s.matched) > len(kept.matched):
            result[result.index(kept)] = s
            by_target[key] = s
    return result


def _channel_target(
    cos, ga_by_address: dict[str, GroupAddress],
    targets: dict[str, tuple[Room, str, int]],
) -> tuple[Room, str, int] | None:
    """Eindeutiges (Raum, Gewerk, Element) des Kanals aus den Bezeichnungen
    seiner GAs -- None, wenn keine auswertbar ist oder sie sich
    widersprechen (z.B. Kanal steuert zwei Raeume)."""
    found = {
        (id(t[0]), t[1], t[2]): t
        for co in cos for addr in co.connected_gas
        if addr in ga_by_address and (t := targets.get(ga_by_address[addr].id))
    }
    if len(found) != 1:
        return None
    return next(iter(found.values()))


def _suggest_from_designation(
    device, channel_name, cos, target, project, gen, ga_by_address,
) -> GewerkSuggestion | None:
    """Vorschlag mit Raum/Gewerk/Element aus der Bezeichnung. Das Gewerk
    muss erkennbar sein (_MATCHABLE_CODES) und mindestens eine
    Kernfunktion des Kanals zu dessen Schema passen."""
    room, code, element_nr = target
    gewerk = project.gewerk_catalog.get(code)
    if code not in _MATCHABLE_CODES or not gewerk:
        return None
    schema = gen._get_block_schema(gewerk, assignment=None, is_feedback=False)
    if not schema:
        return None
    matched = {
        function: ga_by_address[co.connected_gas[0]]
        for function, co in match_channel_to_schema(cos, schema).items()
        if co.connected_gas and co.connected_gas[0] in ga_by_address
    }
    if not matched.keys() & _PRIMARY_FUNCTIONS:
        return None
    return GewerkSuggestion(
        device=device, channel_name=channel_name, room=room,
        gewerk_code=code, matched=matched,
        schema_function_count=_non_reserve_function_count(schema),
        existing_assignment=find_reusable_assignment(room, code, element_nr),
        element_nr=element_nr,
        from_designation=True,
    )


def _channel_already_linked(
    cos, ga_by_address: dict[str, GroupAddress],
    already_linked: dict[str, tuple[str, str]],
) -> bool:
    """True wenn der Kanal keine auswertbaren GAs hat, oder alle davon
    bereits über eine GewerkAssignment verknüpft sind."""
    gas = [
        ga_by_address[addr] for co in cos for addr in co.connected_gas
        if addr in ga_by_address
    ]
    if not gas:
        return True
    return all(ga.id in already_linked for ga in gas)


def _best_match(
    cos, schema_cache: dict[str, object], ga_by_address: dict[str, GroupAddress],
) -> tuple[str, dict[str, GroupAddress]]:
    """Testet den Kanal gegen jedes Kandidaten-Schema, gibt den eindeutig
    besten Treffer zurueck (oder ("", {}) wenn keiner/mehrdeutig).

    Manche Schemata teilen Funktionsnamen (z.B. hat LDA dieselben E/A,
    DIM, WERT, RM, RM WERT-Slots wie L, plus SZENE/STOERUNG/SPERREN) --
    ein reiner Schalt-/Dimm-Kanal ohne Szenen-Objekt matcht dann bei
    beiden gleich oft. Tie-Breaker: der Kandidat, dessen Schema durch die
    Treffer prozentual staerker "erklaert" wird (weniger unbesetzte
    Slots), gilt als der plausiblere -- bleibt es dabei gleichstehen,
    wird die Zuordnung als mehrdeutig verworfen statt geraten."""
    candidates: list[tuple[str, dict[str, GroupAddress], float]] = []
    for code, schema in schema_cache.items():
        matched_cos = match_channel_to_schema(cos, schema)
        matched_gas = {
            function: ga_by_address[co.connected_gas[0]]
            for function, co in matched_cos.items()
            if co.connected_gas and co.connected_gas[0] in ga_by_address
        }
        if len(matched_gas) >= _MIN_MATCHED_FUNCTIONS and matched_gas.keys() & _PRIMARY_FUNCTIONS:
            ratio = len(matched_gas) / _non_reserve_function_count(schema)
            candidates.append((code, matched_gas, ratio))

    if not candidates:
        return "", {}

    best_score = max(len(matched) for _, matched, _ in candidates)
    top = [c for c in candidates if len(c[1]) == best_score]
    if len(top) > 1:
        best_ratio = max(ratio for _, _, ratio in top)
        top = [c for c in top if c[2] == best_ratio]
    if len(top) != 1:
        return "", {}
    code, matched, _ = top[0]
    return code, matched


def _non_reserve_function_count(schema) -> int:
    return sum(1 for e in schema.entries if not e.is_reserve and e.function)
