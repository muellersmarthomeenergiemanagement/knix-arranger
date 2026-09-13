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


def find_reusable_assignment(room: Room, gewerk_code: str) -> GewerkAssignment | None:
    """Eine bereits vorhandene, aber noch unverknüpfte GewerkAssignment
    desselben Codes in diesem Raum -- typischerweise von der
    Bezeichnungs-basierten Gewerk-Ableitung beim Import angelegt
    (FA-519b, `GewerkService.derive_gewerk_assignments`, laeuft
    automatisch bei jedem GA-Import und kennt nur den aus der
    GA-Bezeichnung geratenen Gewerk-Code, keinen echten Aktor-Kanal).
    Ohne diese Wiederverwendung würde ein Vorschlag hier eine zweite,
    für den Nutzer verwirrende Zuweisung desselben Gewerks im selben Raum
    anlegen, statt die bereits vorhandene mit dem echten Kanal zu
    vervollständigen."""
    for assignment in room.gewerk_assignments:
        if (
            assignment.gewerk_code == gewerk_code
            and assignment.count == 1
            and not assignment.linked_ga_ids
        ):
            return assignment
    return None


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

    skipped_no_room = 0
    for device in all_devices:
        if not device.communication_objects:
            continue
        if not device.room_id:
            skipped_no_room += 1
            continue
        room = rooms_by_id.get(device.room_id)
        if not room:
            skipped_no_room += 1
            continue

        for channel_name, cos in group_channels_by_name(device).items():
            if _channel_already_linked(cos, ga_by_address, already_linked):
                continue

            best_code, best_matched = _best_match(cos, schema_cache, ga_by_address)
            if not best_code:
                continue

            suggestions.append(GewerkSuggestion(
                device=device, channel_name=channel_name, room=room,
                gewerk_code=best_code, matched=best_matched,
                schema_function_count=_non_reserve_function_count(schema_cache[best_code]),
                existing_assignment=find_reusable_assignment(room, best_code),
            ))

    if skipped_no_room:
        warnings.append(
            f"{skipped_no_room} Gerät(e) ohne erkannten Raum wurden übersprungen."
        )
    return suggestions, warnings


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
