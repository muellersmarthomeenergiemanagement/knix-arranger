"""
Sensor-Ermittlung (FA-1400)
Bestimmt benötigte Sensortypen pro Raum basierend auf Gewerken.
"""
from __future__ import annotations
import json
import os
import logging
from dataclasses import dataclass, field
from ..models.building import Room, Bedienelement, FunctionAssignment, SensorFunktion, SensorFunktionGa
from ..models.topology import Topology
from ..models.device import Sensor, ProductInfo, GEWERK_TO_SENSOR_TYPE
from ..models.group_address import GroupAddressStructure
from ..models.gewerk import GewerkCatalog

logger = logging.getLogger("knix_arranger.sensor_service")

# FA-1408: Gewerke mit interface_type="system_sensor" werden NICHT raumweise geplant,
# sondern einmalig pro Projekt (→ determine_system_sensors).
SYSTEM_SENSOR_GEWERKE: frozenset[str] = frozenset({"W"})

# Melder, die selbst schalten: Kanäle statt Tasten, nur der Befehl (Schalten
# bzw. Fahren) -- kein langer Druck, kein Dimmen, keine Rückmeldung
PRESENCE_SENSOR_TYPES: frozenset[str] = frozenset({"Präsenzmelder", "Bewegungsmelder"})
PRESENCE_BEDIENART = "Schaltet bei Anwesenheit"

# Primaere GA-Funktionen die einem Sensor automatisch zugeordnet werden.
# Format: list[(Button-Label, GA-Funktionsname, Beschreibung, Aktionstyp, Bedienart)]
# Aktionstyp: "kurz" = kurz druecken, "lang" = lang druecken,
#             "loslassen" = beim Loslassen, "" = unspezifisch (Kontakt/Sensor)
# Bedienart (FA-1502b): was der Tastendruck/Dreher konkret sendet, fuer die
# Bauherrenberatung (Bauherr-Formular, Bedienungsanleitung). "" = kein
# manueller Taster (Kontakt/Sensor), daher keine Bedienart-Angabe.
_UMSCHALTEN = "Umschalten (Ein/Aus wechselnd)"
_DIMMEN = "Dimmen (Richtung wechselnd)"
_FAHREN = "Fahren (Richtung wechselnd)"
_STOPP = "Stopp / Lamellenverstellung"

GEWERK_PRIMARY_FUNCTIONS: dict[str, list[tuple[str, str, str, str, str]]] = {
    # Licht
    "L":   [("Taste", "E/A",  "Licht schalten",    "kurz", _UMSCHALTEN)],
    "LD":  [("Taste", "E/A",  "Licht schalten",    "kurz", _UMSCHALTEN),
            ("Taste", "DIM",  "Licht dimmen",       "lang", _DIMMEN)],
    "LDA": [("Taste", "E/A",  "Licht schalten",    "kurz", _UMSCHALTEN),
            ("Taste", "DIM",  "Licht dimmen",       "lang", _DIMMEN)],
    "LC":  [("Taste", "E/A",  "Licht schalten",    "kurz", _UMSCHALTEN),
            ("Taste", "DIM",  "Licht dimmen",       "lang", _DIMMEN)],
    "LCT": [("Taste", "E/A",  "Licht schalten",    "kurz", _UMSCHALTEN),
            ("Taste", "DIM",  "Licht dimmen",       "lang", _DIMMEN)],
    "LCW": [("Taste", "E/A",  "Licht schalten",    "kurz", _UMSCHALTEN),
            ("Taste", "DIM",  "Licht dimmen",       "lang", _DIMMEN)],
    "DMX": [("Taste", "E/A",  "DMX schalten",      "kurz", _UMSCHALTEN),
            ("Taste", "DIM",  "DMX dimmen",         "lang", _DIMMEN)],
    "S":   [("Taste", "E/A",  "Steckdose schalten", "kurz", _UMSCHALTEN)],
    "SD":  [("Taste", "E/A",  "Steckdose schalten", "kurz", _UMSCHALTEN),
            ("Taste", "DIM",  "Steckdose dimmen",   "lang", _DIMMEN)],
    # Jalousie: lang druecken = fahren, kurz druecken = stoppen
    "J":   [("Taste", "AUF/AB", "Jalousie fahren", "lang", _FAHREN),
            ("Taste", "STOPP",  "Jalousie stopp",   "kurz", _STOPP)],
    "R":   [("Taste", "AUF/AB", "Rollladen fahren", "lang", _FAHREN),
            ("Taste", "STOPP",  "Rollladen stopp",  "kurz", _STOPP)],
    "M":   [("Taste", "AUF/AB", "Markise fahren",  "lang", _FAHREN),
            ("Taste", "STOPP",  "Markise stopp",    "kurz", _STOPP)],
    "T":   [("Taste", "AUF/AB", "Vorhang fahren",  "lang", _FAHREN),
            ("Taste", "STOPP",  "Vorhang stopp",    "kurz", _STOPP)],
    # Heizung/Klima: Sollwert = Drehregler (kein Tastendruck), Betriebsart = Kurzbefehl
    "H":   [("Sollwert",   "BASIS-SOLL",             "Heizung Sollwert",   "",
             "Wert senden (Temperatur-Sollwert)"),
            ("Betriebsart", "UMSCHALTEN BETRIEBSART", "Heizung Betriebsart", "kurz",
             "Umschalten (Betriebsart wechselnd)")],
    "KL":  [("Sollwert",   "SOLLWERT",               "Klima Sollwert",     "",
             "Wert senden (Temperatur-Sollwert)"),
            ("Betriebsart", "BETRIEBSART",            "Klima Betriebsart",  "kurz",
             "Umschalten (Betriebsart wechselnd)")],
    # Lueftung
    "LU":  [("Taste", "STUFE", "Lueftung Stufe", "kurz", "Wert senden (Lüftungsstufe)")],
    # Allgemein
    "V":   [("Taste", "E/A",  "Ventilator schalten", "kurz", _UMSCHALTEN)],
    # Alarm/Kontakte: kein manueller Tastendruck
    "FK":  [("Kontakt", "E/A", "Fenster offen/geschlossen", "", "")],
    "TK":  [("Kontakt", "E/A", "Tuer offen/geschlossen",    "", "")],
    "RK":  [("Kontakt", "E/A", "Riegel offen/geschlossen",  "", "")],
    "A":   [("Ausgang", "E/A", "Bewegung erkannt",          "", "")],
}

# Rueckmelde-GAs die dem Sensor zusaetzlich zugeordnet werden, damit er den
# Schaltzustand des Aktorkanals kennt (z.B. LED-Rueckmeldung am Taster).
# Format: list[(Kanal-Label, GA-Funktionsname, Beschreibung)]
# Element mit Funktionsumfang Schalten (FA-1003d), z.B. Spiegelheizung als H
_SWITCH_PRIMARY = [("Taste", "E/A", "Ein/Aus schalten", "kurz", _UMSCHALTEN)]
_SWITCH_FEEDBACK = [("Status", "RM", "Schaltzustand Rueckmeldung")]

GEWERK_FEEDBACK_FUNCTIONS: dict[str, list[tuple[str, str, str]]] = {
    # Licht
    "L":   [("Status", "RM", "Schaltzustand Rueckmeldung")],
    "LD":  [("Status", "RM", "Schaltzustand Rueckmeldung"),
            ("Status", "RM WERT", "Dimmwert Rueckmeldung")],
    "LDA": [("Status", "RM", "Schaltzustand Rueckmeldung"),
            ("Status", "RM WERT", "Dimmwert Rueckmeldung")],
    "LC":  [("Status", "RM", "Schaltzustand Rueckmeldung"),
            ("Status", "RM WERT", "Dimmwert Rueckmeldung"),
            ("Status", "RM FARBE", "Farbwert Rueckmeldung")],
    "LCT": [("Status", "RM", "Schaltzustand Rueckmeldung"),
            ("Status", "RM HELL", "Helligkeit Rueckmeldung"),
            ("Status", "RM CCT", "Farbtemperatur Rueckmeldung")],
    "LCW": [("Status", "RM", "Schaltzustand Rueckmeldung"),
            ("Status", "RM WERT", "Dimmwert Rueckmeldung"),
            ("Status", "RM FARBE", "Farbwert RGBW Rueckmeldung")],
    "DMX": [("Status", "RM", "Schaltzustand Rueckmeldung"),
            ("Status", "RM WERT", "Dimmwert Rueckmeldung")],
    "S":   [("Status", "RM", "Schaltzustand Rueckmeldung")],
    "SD":  [("Status", "RM", "Schaltzustand Rueckmeldung"),
            ("Status", "RM WERT", "Dimmwert Rueckmeldung")],
    # Jalousie
    "J":   [("Status", "STATUS POSITION HOEHE", "Jalousiehoehe"),
            ("Status", "STATUS POSITION LAMELLEN", "Lamellenposition")],
    "R":   [("Status", "STATUS POSITION HOEHE", "Rollladenposition"),
            ("Status", "STATUS POSITION LAMELLEN", "Lamellenposition")],
    "M":   [("Status", "STATUS POSITION HOEHE", "Markisenposition"),
            ("Status", "STATUS POSITION LAMELLEN", "Lamellenposition")],
    "T":   [("Status", "STATUS POSITION HOEHE", "Vorhangposition"),
            ("Status", "STATUS POSITION LAMELLEN", "Lamellenposition")],
    # Heizung/Klima
    "H":   [("Status", "RM AKTUELLER SOLLWERT", "Aktueller Sollwert"),
            ("Status", "STATUS BETRIEBSART", "Betriebsart Status")],
    "KL":  [("Status", "IST", "Isttemperatur"),
            ("Status", "STATUS BETRIEB", "Betriebsstatus")],
    # Lueftung
    "LU":  [("Status", "STATUS STUFE", "Lueftungsstufe aktiv"),
            ("Status", "STATUS BETRIEBSART", "Betriebsart aktiv")],
    # Allgemein
    "V":   [("Status", "RM", "Schaltzustand Rueckmeldung")],
}


class SensorRequirement:
    """Benötigter Sensor-Typ."""

    def __init__(self, sensor_type: str, room_id: str, room_name: str,
                 gewerk_code: str, count: int = 1, taster_index: int = 1,
                 assignment_id: str = "", is_overridden: bool = False):
        self.sensor_type = sensor_type
        self.room_id = room_id
        self.room_name = room_name
        self.gewerk_code = gewerk_code
        self.count = count
        self.taster_index = taster_index
        # FA-1407: Referenz auf die GewerkAssignment-ID für Override-Änderungen
        self.assignment_id = assignment_id
        # FA-1407: True wenn sensor_type manuell überschrieben wurde
        self.is_overridden = is_overridden


@dataclass
class LineSensorResult:
    """Ergebnis der Sensor-Ermittlung für eine einzelne Linie."""
    line_name: str = ""
    coupler_address: str = ""
    area_number: int = 0
    line_number: int = 0
    device_count: int = 0
    requirements: list[SensorRequirement] = field(default_factory=list)
    sensors: list[Sensor] = field(default_factory=list)


class SensorService:
    """Ermittelt benötigte Sensoren basierend auf Gewerken (FA-1401)."""

    @staticmethod
    def _effective_sensor_type(
        room: Room,
        assignment,
        taster_idx: int,
        auto_type: str,
    ) -> str:
        """Bestimmt den effektiven Sensortyp nach Priorität:
        sensor_type_override > TE-Typ (Step 5b) > Gewerk-Standard (auto_type).

        Der TE-Typ "Präsenzmelder" ersetzt nur "Tastereinheit", nicht
        andere Gerätetypen wie "Raumthermostat" (Gewerk H) – diese
        bleiben unverändert, da ein Präsenzmelder-TE den Thermostat
        nicht ersetzen kann.
        """
        if assignment.sensor_type_override:
            return assignment.sensor_type_override
        te_type = room.get_te_type(taster_idx)
        if te_type == "Präsenzmelder" and auto_type == "Tastereinheit":
            return "Präsenzmelder"
        return auto_type

    def determine_sensors(self, rooms: list[Room],
                          catalog: GewerkCatalog) -> list[SensorRequirement]:
        """
        Ermittelt benötigte Sensortypen pro Raum.

        Mehrere Gewerke die zum selben Sensortyp (element_type) gehören,
        werden zu EINEM SensorRequirement zusammengefasst und ihre Counts
        addiert — damit stimmt die Anzahl Sensor-Devices in der Topologie
        mit der Anzahl Bedienelemente pro Raum überein.

        Beispiel: L×2 + LD×1 → beide "Taste" → 1 × SensorRequirement
        mit count=3 → 1 Device in der Linie → 1 Bedienelement im Raum.
        """
        # (room_id, sensor_type, taster_index, assignment_id) -> SensorRequirement
        aggregated: dict[tuple, SensorRequirement] = {}

        for room in rooms:
            # In der Gerätekonfiguration (Wizard-Schritt 6) gelöschte Auto-Geräte
            # hinterlassen ein suppressed=True-Tombstone-BE. Diese Typen dürfen
            # hier nicht neu ermittelt werden, sonst erscheint das gelöschte
            # Gerät wieder in der Topologie.
            suppressed_types = {
                be.element_type for be in room.bedienelemente if be.suppressed
            }
            for assignment in room.gewerk_assignments:
                # FA-1408: Systemsensoren (W) werden projektweise geplant – hier überspringen.
                if assignment.gewerk_code in SYSTEM_SENSOR_GEWERKE:
                    continue
                auto_type = GEWERK_TO_SENSOR_TYPE.get(assignment.gewerk_code)
                if not auto_type:
                    continue

                # FA-1407: Override hat Vorrang vor automatisch ermitteltem Typ
                own_key = _own_type_key(assignment)
                is_overridden = bool(own_key)

                # taster_indices: viele-zu-viele – pro taster_index ein eigenes Gerät.
                # Bei Override jede Zuweisung einzeln zeigen (eigener Schlüssel via id).
                # Elemente verschiedenen Typs (Gewerk A) ergeben eigene Geräte.
                for taster_idx in assignment.taster_indices:
                    for effective_type, elements in element_sensor_types(
                            room, assignment, taster_idx, auto_type).items():
                        if effective_type in suppressed_types:
                            continue
                        agg_key = (room.id, effective_type, taster_idx, own_key)
                        if agg_key in aggregated:
                            aggregated[agg_key].count += len(elements)
                        else:
                            aggregated[agg_key] = SensorRequirement(
                                sensor_type=effective_type,
                                room_id=room.id,
                                room_name=f"{room.number} {room.name}",
                                gewerk_code=assignment.gewerk_code,
                                count=len(elements),
                                taster_index=taster_idx,
                                assignment_id=assignment.id,
                                is_overridden=is_overridden,
                            )

        return list(aggregated.values())

    def suggest_sensors(self, requirements: list[SensorRequirement]) -> list[Sensor]:
        """Schlägt passende Sensoren vor."""
        sensors = []

        for req in requirements:
            sensor = Sensor(
                sensor_type=req.sensor_type,
                room_id=req.room_id,
                buttons_channels=req.count,
                taster_index=req.taster_index,
            )
            sensors.append(sensor)

        return sensors

    def determine_sensors_per_line(
        self, topology: Topology, all_rooms: list[Room],
        catalog: GewerkCatalog,
    ) -> list[LineSensorResult]:
        """
        Ermittelt Sensoren pro Linie (liniengerecht).

        Sensoren sitzen im Raum und gehoeren zur selben Linie
        wie die zugehoerigen Aktoren.
        """
        room_by_id = {r.id: r for r in all_rooms}

        results: list[LineSensorResult] = []
        for area in topology.areas:
            for line in area.lines:
                line_rooms = [
                    room_by_id[rid]
                    for rid in line.assigned_room_ids
                    if rid in room_by_id
                ]
                if not line_rooms:
                    continue

                requirements = self.determine_sensors(line_rooms, catalog)
                sensors = self.suggest_sensors(requirements)

                results.append(LineSensorResult(
                    line_name=line.name,
                    coupler_address=line.coupler_address,
                    area_number=area.area_number,
                    line_number=line.line_number,
                    device_count=line.device_count,
                    requirements=requirements,
                    sensors=sensors,
                ))

        return results

    def auto_assign_functions(
        self, rooms: list[Room],
        group_addresses: GroupAddressStructure,
        topology=None,
    ) -> int:
        """
        Ordnet Sensoren automatisch die passenden Gruppenadressen zu (FA-1410).

        Für gewerk-basierte Sensorfunktionen werden alle Primär- und
        Rückmelde-GAs automatisch expandiert.  Direkte GA-Referenzen werden
        unverändert als FunctionAssignment übernommen.

        Automatische Bedienelemente, die in einem Raum mit Gewerken keiner
        Gewerk-Gruppe entsprechen, bleiben nur, wenn ihr Gerät real vorhanden
        ist. Mit topology eines geplanten Projekts heisst das: ein Sensor im
        Raum mit dieser Adresse und ohne anderen Typ (_has_own_device) --
        sonst blieb ein früherer Sensor ohne auflösbare GA mit seiner alten
        Adresse stehen (Projekt_23 Technik: «Wassermelder 1.2.113», die
        Adresse hatte inzwischen der Raumthermostat). Ohne topology oder bei
        importierten Projekten bleiben alle (Chalet Bibliothek 1.1.52).

        Gibt die Anzahl erstellter FunctionAssignment-Einträge zurück.
        """
        # Lookup: (gewerk_code, room_key, element_number, function_name) -> designation
        ga_lookup: dict[tuple[str, str, int, str], str] = {}
        for ga in group_addresses.all_addresses():
            if ga.is_placeholder or not ga.function_name:
                continue
            room_key = ga.room_id if ga.room_id else ga.room_number
            key = (ga.gewerk_code, room_key, ga.element_number, ga.function_name)
            ga_lookup[key] = ga.designation

        total = 0
        for room in rooms:
            saved_pn: dict[str, list[str]] = {}
            saved_import_bes: list = []
            manual_bes: list = []        # is_auto=False, nicht suppressed
            suppressed_types: set[str] = set()  # element_types die unterdrückt sind
            suppressed_bes: list = []    # Tombstones, für Wiederherstellung ohne Gewerk-Match
            consumed_manual_ids: set[str] = set()
            for be in room.bedienelemente:
                saved_pn.setdefault(be.element_type, []).append(be.participant_number)
                if not be.function_assignments and not be.suppressed:
                    saved_import_bes.append(be)
                if not be.is_auto:
                    if be.suppressed:
                        suppressed_types.add(be.element_type)
                        suppressed_bes.append(be)
                    else:
                        manual_bes.append(be)

            # Lookup für Import-BEs (is_auto=True, keine function_assignments):
            # Stellt participant_number + Produktdaten für Auto-BEs wieder her.
            _import_queue: dict[str, list] = {}
            for _ibe in saved_import_bes:
                if _ibe.is_auto:
                    _import_queue.setdefault(_ibe.element_type, []).append(_ibe)

            # Bisherige automatische Bedienelemente: das neu abgeleitete
            # übernimmt ID, Tasten-IDs und Anmerkung (_inherit) -- sonst
            # verwiesen Checklisten und Matrix-Sprünge nach jeder Neuberechnung
            # ins Leere, und die Anmerkung des Bauherrn ging verloren
            previous_auto: dict[tuple, list] = {}
            for be in room.bedienelemente:
                if be.is_auto and not be.suppressed:
                    previous_auto.setdefault((be.element_type, be.taster_index), []).append(be)

            room.bedienelemente.clear()

            # Gewerk-Zuweisungen nach (effektiver Element-Typ, Taster-Index) gruppieren.
            # taster_indices: viele-zu-viele → jedes Gewerk erscheint auf jeder TE als eigene Gruppe.
            element_groups: dict[tuple, list[tuple]] = {}
            for assignment in room.gewerk_assignments:
                code = assignment.gewerk_code
                if code in SYSTEM_SENSOR_GEWERKE:
                    continue
                auto_type = GEWERK_TO_SENSOR_TYPE.get(code)
                if not auto_type:
                    continue
                if code not in GEWERK_PRIMARY_FUNCTIONS:
                    continue
                for taster_idx in assignment.taster_indices:
                    for effective_type, elements in element_sensor_types(
                            room, assignment, taster_idx, auto_type).items():
                        grp_key = (effective_type, taster_idx, _own_type_key(assignment))
                        element_groups.setdefault(grp_key, []).append(
                            (assignment, code, effective_type, elements))

            sorted_groups = sorted(element_groups.items())

            # ── Zweistufiges Matching manueller BEs (FA-1410c) ────────────────
            # Stufe 1: Exaktes Matching nach (element_type, taster_index).
            #          Verhindert, dass Gruppe A einen manuellen BE von Gruppe B
            #          konsumiert, wenn beide dieselbe taster_index haben
            #          (z.B. Raumthermostat-1 und Tastereinheit-1 im selben Raum).
            # Stufe 2: Fallback auf taster_index allein – erlaubt Gerätetyp-
            #          Überschreibung aus Step 6 (z.B. Tastereinheit→Präsenzmelder),
            #          aber nur für Gruppen, die in Stufe 1 kein Match fanden.
            pre_matched: dict[tuple, object] = {}   # grp_key → manual_be
            pre_claimed: set[str] = set()
            # Pass 1: exaktes Matching
            for (element_type, taster_idx, asgn_id), _ in sorted_groups:
                for b in manual_bes:
                    if (b.taster_index == taster_idx
                            and b.element_type == element_type
                            and b.id not in pre_claimed):
                        pre_matched[(element_type, taster_idx, asgn_id)] = b
                        pre_claimed.add(b.id)
                        break
            # Pass 2: Fallback nur für noch ungematchte Gruppen
            for (element_type, taster_idx, asgn_id), _ in sorted_groups:
                if (element_type, taster_idx, asgn_id) in pre_matched:
                    continue
                for b in manual_bes:
                    if b.taster_index == taster_idx and b.id not in pre_claimed:
                        pre_matched[(element_type, taster_idx, asgn_id)] = b
                        pre_claimed.add(b.id)
                        break

            handled_suppressed_types: set[str] = set()
            for (element_type, taster_idx, _asgn_id), assignments in sorted_groups:
                # Unterdrücktes BE: Tombstone wiederherstellen, auto-BE NICHT neu erstellen
                if element_type in suppressed_types:
                    # Die bisherige Markierung (gesichert vor dem Leeren der
                    # Liste) weiterverwenden, je Typ nur einmal
                    if element_type not in handled_suppressed_types:
                        tombstone = next(
                            (b for b in suppressed_bes if b.element_type == element_type),
                            None,
                        ) or Bedienelement(
                            element_type=element_type,
                            is_auto=False,
                            suppressed=True,
                        )
                        room.bedienelemente.append(tombstone)
                        handled_suppressed_types.add(element_type)
                    continue

                total_channels = sum(len(elements) for _a, _c, _et, elements in assignments)
                be = Bedienelement(element_type=element_type, channels=total_channels,
                                   taster_index=taster_idx)

                existing_be = pre_matched.get((element_type, taster_idx, _asgn_id))
                if existing_be and existing_be.id not in consumed_manual_ids:
                    consumed_manual_ids.add(existing_be.id)
                elif existing_be:
                    existing_be = None  # wurde schon von anderer Gruppe konsumiert
                if existing_be:
                    # Dasselbe Objekt weiterverwenden (Typ aus Step 5c, Funktionen,
                    # Produkt, Anmerkung bleiben): vorher entstand bei jeder
                    # Neuberechnung eine Kopie mit neuer ID -- die Bauherren-
                    # beratung bearbeitete danach ein nicht mehr verwendetes
                    # Objekt, und der Sprung aus der Verknüpfungsmatrix fand
                    # den Taster nicht mehr.
                    be = existing_be
                    be.taster_index = taster_idx
                    be.is_auto = False
                    consumed_manual_ids.add(existing_be.id)
                else:
                    # Auto: SensorFunktionen aus Gewerken ableiten (FA-1410b)
                    be.is_auto = True
                    be.funktionen = []
                    for _assignment, gewerk_code, _eff, elements in assignments:
                        for elem_nr in elements:
                            be.funktionen.append(SensorFunktion(
                                gewerk_code=gewerk_code,
                                element_number=elem_nr,
                                source_room_id="",
                            ))
                    olds = previous_auto.get((element_type, taster_idx))
                    if olds:
                        _inherit(be, olds.pop(0))
                    # Physikalische Adresse + Produktdaten aus Import wiederherstellen
                    _ibes = _import_queue.get(element_type, [])
                    if _ibes:
                        _ibe = _ibes.pop(0)
                        be.participant_number = _ibe.participant_number
                        be.product_name = _ibe.product_name or be.product_name
                        be.manufacturer = _ibe.manufacturer or be.manufacturer
                        be.order_number = _ibe.order_number or be.order_number

                # function_assignments aus funktionen ableiten
                be.function_assignments = []
                be.function_assignments, added = self._expand_funktionen(
                    be.funktionen, room, ga_lookup, be.element_type,
                )
                total += added

                if be.function_assignments or be.funktionen or not be.is_auto:
                    room.bedienelemente.append(be)

            # Manuell konfigurierte BEs ohne Gewerk-Entsprechung beibehalten
            for mbe in manual_bes:
                if mbe.id not in consumed_manual_ids:
                    mbe.function_assignments, added = self._expand_funktionen(
                        mbe.funktionen, room, ga_lookup, mbe.element_type,
                    )
                    total += added
                    room.bedienelemente.append(mbe)

            # Gelöschte (suppressed) BEs ohne Gewerk-Entsprechung beibehalten
            # (z.B. ETS6-Importe ohne Gewerk-Zuweisung) -- sonst geht die
            # Löschmarkierung bei der nächsten Neuberechnung verloren und das
            # Gerät taucht andernorts (Verknüpfungsmatrix-Fallback etc.) wieder auf.
            for sbe in suppressed_bes:
                if sbe.element_type not in handled_suppressed_types:
                    room.bedienelemente.append(sbe)

            # Importierte Geräte, die keiner Gewerk-Gruppe zugeordnet wurden,
            # sind trotzdem real vorhanden -- nicht verwerfen (Chalet
            # Bibliothek: zwei Taster, eine Gewerk-Gruppe -> 1.1.52 fehlte)
            for leftover in _import_queue.values():
                room.bedienelemente.extend(
                    be for be in leftover if be.participant_number
                    and _has_own_device(topology, room, be))

            # Keine Gewerke → import-erzeugte Bedienelemente wiederherstellen
            if not room.bedienelemente and saved_import_bes:
                room.bedienelemente.extend(saved_import_bes)
                continue

            # Physikalische Adressen wiederherstellen -- nur fehlende, sonst
            # tauschen Bedienelemente mit eigener Adresse ihr Gerät, sobald
            # sich die Reihenfolge ändert. Bereits vergebene überspringen.
            used = {be.participant_number for be in room.bedienelemente if be.participant_number}
            free: dict[str, list[str]] = {
                key: [pn for pn in pns if pn and pn not in used]
                for key, pns in saved_pn.items()
            }
            for be in room.bedienelemente:
                if not be.participant_number and free.get(be.element_type):
                    be.participant_number = free[be.element_type].pop(0)

        if topology is not None:
            link_bedienelemente_to_devices(topology, rooms)
        return total

    @staticmethod
    def _expand_direct_ga(sf: SensorFunktion, button_channel: str) -> list[FunctionAssignment]:
        """Expandiert eine Direkte-GA-SensorFunktion zu FunctionAssignment-
        Einträgen -- die primäre GA (sf.ga_designation, Rolle sf.primary_role)
        plus alle sf.extra_gas (FA-1410d), alle mit derselben sf_id (teilen
        sich dieselbe Taste).

        Gemeinsam genutzt von _expand_funktionen (Wizard-/Matrix-Flow, hier
        IMMER die massgebliche Quelle -- jeder Aufruf von
        SensorService.auto_assign_functions, u.a. via BelegungsplanService.generate()
        für Topologie/Verknüpfungsmatrix/Belegungsplan, leitet function_assignments
        aus funktionen neu ab) und XlsxImportService.backfill_function_assignments
        (Import-Flow). Ohne extra_gas identisch zum bisherigen Verhalten (ein
        einzelner FunctionAssignment) -- stellt aber sicher, dass zusätzliche
        GAs (z.B. Rückmeldung, Dimmen-Befehl) UND die Rolle der primären GA
        (z.B. "fremdsteuerung" statt "befehl") eine Neuableitung aus funktionen
        überleben, statt beim nächsten Refresh verloren zu gehen.
        """
        fas = [FunctionAssignment(
            button_channel=button_channel,
            function_ga=sf.ga_designation,
            description=sf.label or sf.ga_designation,
            action_type=sf.action_type,   # z.B. "kurz" für Szene-Aufruf
            role=sf.primary_role,
            sf_id=sf.id,
            bedienart=sf.bedienart,
        )]
        for extra in sf.extra_gas:
            fas.append(FunctionAssignment(
                button_channel=button_channel,
                function_ga=extra.ga_designation,
                description=extra.description or sf.label or extra.ga_designation,
                role=extra.role,
                sf_id=sf.id,
            ))
        return fas

    @staticmethod
    def _is_switched(ga_lookup: dict, sf, src_room_id: str, room, primary_fns) -> bool:
        """Element ohne die Befehls-GAs seines Gewerks, aber mit E/A."""
        def has(fn: str) -> bool:
            return bool(ga_lookup.get((sf.gewerk_code, src_room_id, sf.element_number, fn))
                        or ga_lookup.get((sf.gewerk_code, room.number, sf.element_number, fn)))
        if any(fn == "E/A" for _l, fn, *_r in primary_fns):
            return False
        return has("E/A") and not any(has(fn) for _l, fn, *_r in primary_fns)

    def _expand_funktionen(
        self,
        funktionen: list[SensorFunktion],
        room,
        ga_lookup: dict,
        element_type: str = "",
    ) -> tuple[list[FunctionAssignment], int]:
        """Expandiert Sensorfunktionen zu FunctionAssignment-Einträgen.

        Gewerk-basierte SFs liefern alle Primär- und Rückmelde-GAs automatisch.
        Direkte GA-SFs werden als Einzeleintrag übernommen.

        Der Kanal-Zähler läuft global über alle Gewerke einer Bedienelement-Einheit,
        damit bei mehreren Gewerken auf derselben TE keine Kanalnummern doppelt
        vergeben werden (z.B. L×3 + S×2 + J×1 → Taste 1…6, nicht 1…3, 1…2, 1).
        """
        fas: list[FunctionAssignment] = []
        total = 0

        gewerk_sf_total = sum(
            1 for sf in funktionen if sf.gewerk_code and not sf.ga_designation
        )
        # Nummerierung aktiv wenn mehr als eine Funktion insgesamt vorhanden ist
        # (gewerk-basierte + direkte GAs zählen zusammen). So erhalten gewerk-
        # basierte Kanäle auch dann Nummern, wenn nur eine gewerk-SF vorhanden ist,
        # aber weitere direkte GAs auf derselben BE liegen (z.B. TE mit V + 2 Szenen).
        # Offene Tasten (benannt, ohne GA -- in der Verknüpfungsmatrix geleert)
        # zählen mit, damit die übrigen Tasten ihre Nummer behalten
        # Lange Tastendrücke (press_of) sind keine eigene Taste -- sie folgen
        # unten nach ihrer Taste und zählen nicht mit
        total_sf_count = sum(
            1 for sf in funktionen
            if not sf.press_of and (sf.gewerk_code or sf.ga_designation or sf.label)
        )
        use_numbers = total_sf_count > 1
        global_channel = 0  # globaler Zähler über alle Gewerke
        base_by_id: dict[str, str] = {}   # Tastenname je SensorFunktion

        for sf in funktionen:
            if sf.press_of:
                continue
            if sf.ga_designation:
                # Direkte GA (FA-1410a, inkl. Szenen)
                global_channel += 1
                # sf.label hat Vorrang vor der Zaehl-Nummer, wenn vorhanden:
                # bei importierten Projekten traegt es haeufig bereits die
                # echte, aussagekraeftige Tastenbezeichnung aus der ETS
                # (z.B. "Taste 2, rechts"), waehrend "Taste {global_channel}"
                # nur eine bedeutungslose fortlaufende Position ueber ALLE
                # SensorFunktionen der Bedienstelle ist. Vorher wurde das
                # Label sobald use_numbers aktiv war (>1 Funktion auf der
                # Bedienstelle -- der Regelfall) komplett verworfen, wodurch
                # z.B. Primaer- und Status-GA DERSELBEN echten Taste ("Taste
                # 2, rechts") als zwei verschiedene, falsch benannte Zeilen
                # ("Taste 5"/"Taste 6") in der Verknuepfungsmatrix auftauchten
                # (Chalet Franziska 2005, Formular K Verknuepfungsmatrix).
                # Die Nummer bleibt nur noch Fallback fuer Funktionen ohne
                # eigenes Label (z.B. Wizard-Direktzuordnung ohne Taste-Text).
                # Ausnahme Szenenaufruf (Schritt 8 / Bauherrenberatung): dort
                # ist das Label der Szenenname ("Komponieren"), keine Taste --
                # als Tastenname ergab das keinen Kanal im Topologiereport.
                # Der Name bleibt als Beschreibung (description) erhalten.
                if sf.bedienart == "Szene abrufen":
                    button_ch = f"Taste {global_channel}" if use_numbers else "Taste"
                else:
                    # Label gleich GA-Bezeichnung = keine echte Tasten-
                    # bezeichnung (ältere Direkte-GA-Zuweisungen aus Schritt 8
                    # setzten die GA als Label, wenn keine Bezeichnung
                    # eingegeben war) -- wie "ohne Label" behandeln.
                    own_label = sf.label if sf.label != sf.ga_designation else ""
                    button_ch = own_label or (
                        f"Taste {global_channel}" if use_numbers else "GA"
                    )
                new_fas = self._expand_direct_ga(sf, button_ch)
                fas.extend(new_fas)
                total += len(new_fas)
                base_by_id[sf.id] = button_ch
                continue

            if not sf.gewerk_code:
                if sf.label:
                    global_channel += 1   # offene Taste behält ihre Position
                    base_by_id[sf.id] = sf.label
                continue

            src_room_id = sf.source_room_id or room.id

            # Globaler Zähler: jede SensorFunktion bekommt eine eindeutige Kanalnummer.
            global_channel += 1
            primary_fns = GEWERK_PRIMARY_FUNCTIONS.get(sf.gewerk_code, [])
            feedback_fns = GEWERK_FEEDBACK_FUNCTIONS.get(sf.gewerk_code, [])
            if self._is_switched(ga_lookup, sf, src_room_id, room, primary_fns):
                # Element nur Ein/Aus (Funktionsumfang Schalten, FA-1003d),
                # z.B. Spiegelheizung als Gewerk H: die Taste schaltet statt
                # Sollwert/Betriebsart
                primary_fns, feedback_fns = _SWITCH_PRIMARY, _SWITCH_FEEDBACK
            word = "Taste"
            if element_type in PRESENCE_SENSOR_TYPES:
                # Präsenz-/Bewegungsmelder: Kanal statt Taste (in der
                # Topologie hiess der Melder sonst "Taste 1 ... kurz")
                word = "Kanal"
                primary_fns = [("Kanal", fn, desc, "", PRESENCE_BEDIENART)
                               for _label, fn, desc, _action, _art in primary_fns[:1]]
                feedback_fns = []
            base_by_id[sf.id] = f"{word} {global_channel}" if use_numbers else word

            found_primary = False
            for btn_label, fn_name, desc, action_type, bedienart in primary_fns:
                key = (sf.gewerk_code, src_room_id, sf.element_number, fn_name)
                ga_designation = ga_lookup.get(key)
                if ga_designation is None:
                    key = (sf.gewerk_code, room.number, sf.element_number, fn_name)
                    ga_designation = ga_lookup.get(key)
                if not ga_designation:
                    continue
                channel_name = f"{btn_label} {global_channel}" if use_numbers else btn_label
                fas.append(FunctionAssignment(
                    button_channel=channel_name,
                    function_ga=ga_designation,
                    description=desc,
                    action_type=action_type,
                    role="befehl",
                    sf_id=sf.id,
                    bedienart=bedienart,
                ))
                total += 1
                found_primary = True

            if not found_primary:
                label = primary_fns[0][0] if primary_fns else word
                channel_name = f"{label} {global_channel}" if use_numbers else label
                product_fas = _product_element_fas(
                    sf, room, src_room_id, ga_lookup, channel_name)
                fas.extend(product_fas)
                total += len(product_fas)
                if product_fas:
                    continue

            for fb_label, fb_fn_name, fb_desc in feedback_fns:
                key = (sf.gewerk_code, src_room_id, sf.element_number, fb_fn_name)
                ga_designation = ga_lookup.get(key)
                if ga_designation is None:
                    key = (sf.gewerk_code, room.number, sf.element_number, fb_fn_name)
                    ga_designation = ga_lookup.get(key)
                if not ga_designation:
                    continue
                channel_name = f"{fb_label} {global_channel}" if use_numbers else fb_label
                fas.append(FunctionAssignment(
                    button_channel=channel_name,
                    function_ga=ga_designation,
                    description=fb_desc,
                    action_type="",
                    role="rueckmeldung",
                    sf_id=sf.id,
                ))
                total += 1

        # Lange Tastendrücke nach ihrer Taste benennen, wie die ETS:
        # "Taste 2, links (langer Tastendruck)" (siehe bedienelement_layout)
        for sf in funktionen:
            if not sf.press_of or not sf.ga_designation:
                continue
            base = base_by_id.get(sf.press_of)
            if base is None:
                continue   # Taste gibt es nicht mehr
            new_fas = self._expand_direct_ga(sf, f"{base}{SensorFunktion.LONG_PRESS_SUFFIX}")
            for fa in new_fas:
                fa.action_type = "lang"
            fas.extend(new_fas)
            total += len(new_fas)

        return fas, total

    def determine_system_sensors(self, all_rooms: list[Room]) -> list[dict]:
        """
        Ermittelt projektweite Systemsensoren (FA-1408).

        Gewerke mit interface_type="system_sensor" (z.B. W = Wetterstation) werden
        nicht raumweise, sondern einmalig pro Projekt geplant. Pro Gewerk-Code wird
        genau ein Eintrag erzeugt, sofern das Gewerk in irgendeinem Raum vorkommt.

        Gibt eine Liste von Dicts zurueck:
          {"gewerk_code": str, "sensor_type": str, "count": 1}
        """
        found_codes: set[str] = set()
        for room in all_rooms:
            for assignment in room.gewerk_assignments:
                if assignment.gewerk_code in SYSTEM_SENSOR_GEWERKE:
                    found_codes.add(assignment.gewerk_code)

        result = []
        for code in sorted(found_codes):
            sensor_type = GEWERK_TO_SENSOR_TYPE.get(code, code)
            result.append({
                "gewerk_code": code,
                "sensor_type": sensor_type,
                "count": 1,
            })
        return result

    def create_material_list(self, sensors: list[Sensor]) -> list[dict]:
        """Erstellt eine Materialliste der Sensoren (FA-1405)."""
        summary: dict[str, dict] = {}

        for sensor in sensors:
            key = f"{sensor.sensor_type}|{sensor.product.manufacturer}|{sensor.product.order_number}"
            if key not in summary:
                summary[key] = {
                    "sensor_type": sensor.sensor_type,
                    "manufacturer": sensor.product.manufacturer,
                    "order_number": sensor.product.order_number,
                    "product_name": sensor.product.product_name,
                    "quantity": 0,
                    "unit_price": sensor.product.price,
                }
            summary[key]["quantity"] += 1

        return list(summary.values())


# Wählbare Typen für Sensoren aus Gewerken (FA-1407), z.B. Gewerk A: der
# Standard "Bewegungsmelder" lässt sich durch einen Wassermelder ersetzen.
SENSOR_TYPE_CHOICES = [
    "Bewegungsmelder", "Präsenzmelder", "Wassermelder", "Rauchmelder",
    "Magnetkontakt", "Fensterkontakt", "Türkontakt", "Riegelkontakt",
    "Temperaturfuehler", "Sensor",
]


# Gewerk A (Alarm-Magnetkontakte): Typ je Element aus seiner Bezeichnung.
# Vorher war jedes A-Element ein «Bewegungsmelder» -- ein Typ-Batch in der
# Materialliste gab so Rauchmeldern und Türkontakten ein Bewegungsmelder-
# Produkt (Projekt_23 Technik, Garage, Haupteingang, Eingang). Reihenfolge
# zählt: «Schlüsselkontakt Türe» ist ein Türkontakt, «Fensterkontakt» ein
# Fensterkontakt, erst danach «…kontakt» allgemein.
_LABEL_SENSOR_TYPES = (
    (("rauch",), "Rauchmelder"),
    (("wasser", "leck", "leak", "überflut", "ueberflut"), "Wassermelder"),
    (("präsenz", "praesenz"), "Präsenzmelder"),
    (("bewegung",), "Bewegungsmelder"),
    (("fenster",), "Fensterkontakt"),
    (("riegel",), "Riegelkontakt"),
    (("tür", "tuer"), "Türkontakt"),
    (("kontakt", "magnet"), "Magnetkontakt"),
    (("temperatur",), "Temperaturfuehler"),
)
NEUTRAL_SENSOR_TYPE = "Sensor"


def label_sensor_type(label: str) -> str | None:
    """Sensortyp aus der Bezeichnung eines Elements, None wenn nicht erkennbar."""
    text = (label or "").lower()
    for words, sensor_type in _LABEL_SENSOR_TYPES:
        if any(w in text for w in words):
            return sensor_type
    return None


def element_sensor_types(room: Room, assignment, taster_idx: int,
                         auto_type: str) -> dict[str, list[int]]:
    """Elemente eines Gewerks je wirksamem Sensortyp. Vorrang: Typ des
    Elements (Gebäude › Sensortyp) > bei Gewerk A aus der Bezeichnung > Typ
    des Gewerks (sensor_type_override) > bei A neutral «Sensor» > TE-Typ /
    Gewerk-Standard. Die Bezeichnung geht bei A dem Gewerk-Typ vor: der gilt
    für alle Elemente (früher setzte ihn auch Gebäude › Sensortyp, Projekt_23
    Technik: «Rauchmelder» auch für das Element «Wassermelder»). Elemente
    verschiedenen Typs ergeben eigene Geräte."""
    groups: dict[str, list[int]] = {}
    for nr in range(1, assignment.count + 1):
        sensor_type = assignment.element_sensor_types.get(nr)
        if not sensor_type and assignment.gewerk_code == "A":
            sensor_type = label_sensor_type(assignment.element_label(nr))
        if not sensor_type and assignment.sensor_type_override:
            sensor_type = assignment.sensor_type_override
        if not sensor_type and assignment.gewerk_code == "A":
            sensor_type = NEUTRAL_SENSOR_TYPE
        if not sensor_type:
            sensor_type = SensorService._effective_sensor_type(
                room, assignment, taster_idx, auto_type)
        groups.setdefault(sensor_type, []).append(nr)
    return groups


def _own_type_key(assignment) -> str:
    """Eigenes Gerät je Gewerk, wenn sein Typ von Hand gesetzt ist (FA-1407)."""
    return assignment.id if (assignment.sensor_type_override
                             or assignment.element_sensor_types) else ""


def _product_element_fas(sf: SensorFunktion, room: Room, src_room_id: str,
                         ga_lookup: dict, channel_name: str) -> list[FunctionAssignment]:
    """Kanal eines Sensors an einem Gewerk ohne Aktor (A, FK …), dessen GAs
    aus dem Melder-Produkt entstanden (product_sync): die GAs seines Elements
    heissen nach den KOs («P1: Bewegung»), nicht «E/A» -- vorher fand der
    Kanal keine GA (Projekt_23: Bewegungsmelder Haupteingang, Garage,
    Eingang ohne GA). Richtung aus den KO-Flags: sendet der Sensor, ist es
    ein Befehl, empfängt er (Freigabe, Nachlaufzeit …), eine Rückmeldung."""
    from .product_sync import sensor_owns_gewerk
    # Ein Melder meldet aus seinem eigenen Raum
    if src_room_id != room.id or not sensor_owns_gewerk(sf.gewerk_code):
        return []
    assignment = next((a for a in room.gewerk_assignments
                       if a.gewerk_code == sf.gewerk_code), None)
    product = assignment.product_for_element(sf.element_number) if assignment else None
    if not product or not product.get("com_objects"):
        return []
    from .address_generator import _com_object_function_name
    receives = {_com_object_function_name(co) for co in product["com_objects"]
                if co.get("write_flag") and not co.get("transmit_flag")}
    room_keys = {src_room_id, room.number}
    return [FunctionAssignment(
        button_channel=channel_name,
        function_ga=designation,
        description=fn_name,
        role="rueckmeldung" if fn_name in receives else "befehl",
        sf_id=sf.id,
    ) for (code, room_key, element, fn_name), designation in ga_lookup.items()
        if code == sf.gewerk_code and room_key in room_keys
        and element == sf.element_number]


def _inherit(be: Bedienelement, old: Bedienelement) -> None:
    """Neu abgeleitetes automatisches Bedienelement übernimmt vom bisherigen
    die ID, die Anmerkung und je Taste (gleiches Gewerk-Element) die ID."""
    be.id = old.id
    be.bauherr_annotation = be.bauherr_annotation or old.bauherr_annotation
    old_ids = {(sf.gewerk_code, sf.element_number, sf.source_room_id): sf.id
               for sf in old.funktionen if sf.gewerk_code and not sf.press_of}
    for sf in be.funktionen:
        sf.id = old_ids.pop((sf.gewerk_code, sf.element_number, sf.source_room_id), sf.id)


def link_bedienelemente_to_devices(topology, rooms) -> None:
    """Geplantes Projekt: jedes Bedienelement trägt die Adresse des Sensors,
    der aus ihm entstand -- gleicher Raum, Typ und Index (Device.taster_index,
    siehe TopologyEngine.populate_devices). Vorher behielt es seine alte
    Adresse, auch wenn das Gerät inzwischen eine andere hatte, und der
    Abgleich mit der Topologie legte fürs Gerät ein zweites an (Projekt_23
    Technik: «Wassermelder 1.2.113», die Adresse gehörte dem Raumthermostat).
    Importierte Projekte und Geräte älterer Dateien ohne Index: unverändert."""
    if topology is None or topology.is_imported:
        return
    by_key: dict[tuple, list] = {}
    indexed_rooms: set[str] = set()
    without_index: set[str] = set()   # z.B. von Hand in der Topologie eingefügt
    for area in topology.areas:
        for line in area.lines:
            for d in line.devices:
                if d.device_type != "sensor" or not d.room_id:
                    continue
                if d.taster_index:
                    by_key.setdefault((d.room_id, d.product, d.taster_index), []).append(d)
                    indexed_rooms.add(d.room_id)
                elif d.physical_address:
                    without_index.add(d.physical_address)
    for room in rooms:
        if room.id not in indexed_rooms:
            continue
        for be in room.bedienelemente:
            if be.suppressed or be.participant_number in without_index:
                continue
            devices = by_key.get((room.id, be.element_type, be.taster_index))
            be.participant_number = devices.pop(0).physical_address if devices else ""


def _has_own_device(topology, room: Room, be: Bedienelement) -> bool:
    """Steht hinter dem Bedienelement ein Sensor der Topologie? Siehe
    SensorService.auto_assign_functions. Ein Gerät ohne Typ (z.B. aus der
    ETS) zählt, eines mit anderem Typ gehört einem anderen Bedienelement."""
    if topology is None or topology.is_imported:
        return True
    return any(d.device_type == "sensor" and d.room_id == room.id
               and d.physical_address == be.participant_number
               and d.product in ("", be.element_type)
               for area in topology.areas for line in area.lines for d in line.devices)


def sensor_elements(room: Room, be: Bedienelement) -> list[tuple]:
    """(Gewerk-Zuweisung, Element-Nummern), aus denen der Sensor be abgeleitet
    ist -- bei Gewerk A ggf. nur ein Teil der Elemente."""
    result = []
    for assignment in room.gewerk_assignments:
        auto_type = GEWERK_TO_SENSOR_TYPE.get(assignment.gewerk_code)
        if not auto_type or assignment.gewerk_code in SYSTEM_SENSOR_GEWERKE:
            continue
        if be.taster_index not in assignment.taster_indices:
            continue
        elements = element_sensor_types(
            room, assignment, be.taster_index, auto_type).get(be.element_type)
        if elements:
            result.append((assignment, elements))
    return result


def sensor_assignments(room: Room, be: Bedienelement) -> list:
    """Gewerk-Zuweisungen, aus denen der Sensor be abgeleitet ist."""
    return [assignment for assignment, _elements in sensor_elements(room, be)]


def set_sensor_type(room: Room, be: Bedienelement, sensor_type: str) -> bool:
    """Sensortyp der Elemente setzen, aus denen der Sensor be besteht
    (GewerkAssignment.element_sensor_types) -- nur dieses Gerät, nicht das
    ganze Gewerk (Technik: Rauchmelder und Wassermelder im selben Gewerk A).
    Der abgeleitete Typ hebt die Angabe wieder auf. Die Neuberechnung legt
    den Sensor danach mit dem neuen Typ an. False, wenn be nicht aus Gewerken
    stammt oder schon diesen Typ hat."""
    found = sensor_elements(room, be)
    if not found or be.element_type == sensor_type:
        return False
    for assignment, elements in found:
        auto_type = GEWERK_TO_SENSOR_TYPE[assignment.gewerk_code]
        for nr in elements:
            assignment.element_sensor_types.pop(nr, None)
        derived = element_sensor_types(room, assignment, be.taster_index, auto_type)
        for nr in elements:
            if nr not in derived.get(sensor_type, []):
                assignment.element_sensor_types[nr] = sensor_type
    # Manuell bearbeitete Sensoren werden nach Typ wiedergefunden
    be.element_type = sensor_type
    return True


# Melder, die zum Gewerk A (Alarm-Magnetkontakte) gehören -- Präsenz- und
# Bewegungsmelder schalten Licht und gehören zu ihrem eigenen Gewerk
ALARM_SENSOR_TYPES = frozenset({
    "Rauchmelder", "Wassermelder", "Magnetkontakt", "Fensterkontakt",
    "Türkontakt", "Riegelkontakt",
})


def adopt_manual_detectors(project) -> int:
    """Melder, die ausserhalb der Gewerke angelegt wurden (Bauherrenberatung
    «Sonstige», Gebäude), bekommen ein Element im Gewerk A ihres Raums, mit
    dem Meldertyp als Bezeichnung -- sonst erzeugt die GA-Generierung
    (Wizard Schritt 10) keine Adressen für sie (Projekt_23 Technik:
    Rauchmelder 1.2.109, Wassermelder 1.2.113 ohne GA).

    Das bestehende Bedienelement und sein Gerät werden mit dem Element
    verbunden, nicht verdoppelt: Sensorfunktion für das Element, Taster-Index
    der Gewerk-Gruppe (auch am Gerät), und eine Löschmarkierung desselben
    Typs im Raum entfällt (sie hätte das Element blockiert). Nur geplante
    Projekte; wiederholt aufrufbar. Gibt die Anzahl übernommener Melder zurück.
    """
    if project.topology is None or project.topology.is_imported:
        return 0
    from ..models.building import GewerkAssignment
    devices = {d.physical_address: d for a in project.topology.areas
               for line in a.lines for d in line.devices
               if d.device_type == "sensor" and d.physical_address}
    adopted = 0
    for room in project.all_rooms:
        for be in list(room.bedienelemente):
            if (be.is_auto or be.suppressed or be.element_type not in ALARM_SENSOR_TYPES
                    or any(sf.gewerk_code for sf in be.funktionen)):
                continue
            assignment = next((a for a in room.gewerk_assignments
                               if a.gewerk_code == "A"), None)
            if assignment is None:
                assignment = GewerkAssignment(gewerk_code="A", count=0)
                room.gewerk_assignments.append(assignment)
            nr = assignment.count + 1
            assignment.count = nr
            labels = list(assignment.element_labels)
            labels += [""] * (nr - 1 - len(labels))
            assignment.element_labels = labels[:nr - 1] + [be.element_type]
            assignment.element_sensor_types[nr] = be.element_type
            taster_idx = assignment.taster_indices[0] if assignment.taster_indices else 1
            device = devices.get(be.participant_number)
            if device is not None and device.room_id == room.id:
                device.taster_index = taster_idx
            be.taster_index = taster_idx
            be.funktionen.append(SensorFunktion(gewerk_code="A", element_number=nr,
                                                source_room_id=""))
            room.bedienelemente = [
                b for b in room.bedienelemente
                if not (b.suppressed and b.element_type == be.element_type)]
            adopted += 1
    return adopted


def refresh_bedienelemente(project) -> None:
    """Bedienelemente mit der Topologie abgleichen (FA-1404: je Sensor-Gerät
    eines, im Raum des Geräts) und die Tastenbelegung aus den Funktionen neu
    ableiten (FA-1410).

    Nach Änderungen aufrufen (Öffnen, Import, Assistent, Gebäude/Gewerke/
    GAs/Topologie geändert, Verknüpfungsmatrix), NIE beim Anzeigen: früher
    lief das bei jedem Öffnen von Topologie, Verknüpfungsmatrix und
    Belegungsplan (BelegungsplanService.generate) -- Anzeigen veränderte so
    Daten, und Fehler darin waren kaum nachvollziehbar (Chalet 1.1.40/1.1.52).
    """
    from .knxproj_import_service import KnxprojImportService
    from .ets_corrections import apply_ets_corrections
    # Korrekturen zur ETS nach Öffnen/Import/Neuaufbau wieder anwenden
    apply_ets_corrections(project)
    # Melder ohne Gewerk: Element im Gewerk A, damit sie GAs bekommen
    adopt_manual_detectors(project)
    # Geplant: zuerst Bedienelement <-> Gerät über Raum/Typ/Index, sonst legt
    # der Abgleich für jedes Gerät mit neuer Adresse ein zweites an
    link_bedienelemente_to_devices(project.topology, project.all_rooms)
    try:
        KnxprojImportService._create_bedienelemente_from_topology(
            project.topology, project.areal
        )
    except Exception:
        logger.exception("Bedienelement-Adressen aus Topologie nicht ermittelbar")
    # Weitere GAs an sendenden Tasten-KOs: Rückmeldung oder "Mithören – prüfen"
    from .multi_ga_check import apply_listen_roles
    try:
        apply_listen_roles(project)
    except Exception:
        logger.exception("Mehrfach verknüpfte Tasten-KOs nicht prüfbar")
    SensorService().auto_assign_functions(project.all_rooms, project.group_addresses,
                                          topology=project.topology)


def project_for_export(project):
    """Kopie des Projekts mit aktuellen Bedienelement-Adressen (FA-1404) und
    Funktionszuordnungen – für Berichte/Exporte, die das Projekt selbst
    nicht verändern dürfen (ein Export soll nur lesen)."""
    import copy

    snapshot = copy.deepcopy(project)
    refresh_bedienelemente(snapshot)
    return snapshot
