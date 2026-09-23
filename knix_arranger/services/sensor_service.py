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
                is_overridden = bool(assignment.sensor_type_override)

                # taster_indices: viele-zu-viele – pro taster_index ein eigenes Gerät.
                # Bei Override jede Zuweisung einzeln zeigen (eigener Schlüssel via id).
                for taster_idx in assignment.taster_indices:
                    effective_type = self._effective_sensor_type(
                        room, assignment, taster_idx, auto_type
                    )
                    if effective_type in suppressed_types:
                        continue
                    agg_key = (
                        room.id, effective_type, taster_idx,
                        assignment.id if is_overridden else "",
                    )
                    if agg_key in aggregated:
                        aggregated[agg_key].count += assignment.count
                    else:
                        aggregated[agg_key] = SensorRequirement(
                            sensor_type=effective_type,
                            room_id=room.id,
                            room_name=f"{room.number} {room.name}",
                            gewerk_code=assignment.gewerk_code,
                            count=assignment.count,
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
    ) -> int:
        """
        Ordnet Sensoren automatisch die passenden Gruppenadressen zu (FA-1410).

        Für gewerk-basierte Sensorfunktionen werden alle Primär- und
        Rückmelde-GAs automatisch expandiert.  Direkte GA-Referenzen werden
        unverändert als FunctionAssignment übernommen.

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
                    effective_type = self._effective_sensor_type(
                        room, assignment, taster_idx, auto_type
                    )
                    grp_key = (
                        effective_type,
                        taster_idx,
                        assignment.id if assignment.sensor_type_override else "",
                    )
                    if grp_key not in element_groups:
                        element_groups[grp_key] = []
                    element_groups[grp_key].append((assignment, code, effective_type))

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
                    tombstone = next(
                        (b for b in room.bedienelemente
                         if b.element_type == element_type and b.suppressed),
                        None,
                    )
                    if tombstone is None:
                        tombstone = Bedienelement(
                            element_type=element_type,
                            is_auto=False,
                            suppressed=True,
                        )
                    room.bedienelemente.append(tombstone)
                    handled_suppressed_types.add(element_type)
                    continue

                total_channels = sum(a.count for a, _, _et in assignments)
                be = Bedienelement(element_type=element_type, channels=total_channels,
                                   taster_index=taster_idx)

                existing_be = pre_matched.get((element_type, taster_idx, _asgn_id))
                if existing_be and existing_be.id not in consumed_manual_ids:
                    consumed_manual_ids.add(existing_be.id)
                elif existing_be:
                    existing_be = None  # wurde schon von anderer Gruppe konsumiert
                if existing_be:
                    be.element_type = existing_be.element_type  # Typ aus Step 5c
                    be.funktionen = existing_be.funktionen
                    be.channels = existing_be.channels
                    be.participant_number = existing_be.participant_number
                    be.product_name = existing_be.product_name
                    be.manufacturer = existing_be.manufacturer
                    be.order_number = existing_be.order_number
                    be.datasheets = existing_be.datasheets
                    be.bauherr_annotation = existing_be.bauherr_annotation
                    be.is_auto = False
                    consumed_manual_ids.add(existing_be.id)
                else:
                    # Auto: SensorFunktionen aus Gewerken ableiten (FA-1410b)
                    be.is_auto = True
                    be.funktionen = []
                    for assignment, gewerk_code, _eff in assignments:
                        for elem_nr in range(1, assignment.count + 1):
                            be.funktionen.append(SensorFunktion(
                                gewerk_code=gewerk_code,
                                element_number=elem_nr,
                                source_room_id="",
                            ))
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
                    be.funktionen, room, ga_lookup,
                )
                total += added

                if be.function_assignments or be.funktionen or not be.is_auto:
                    room.bedienelemente.append(be)

            # Manuell konfigurierte BEs ohne Gewerk-Entsprechung beibehalten
            for mbe in manual_bes:
                if mbe.id not in consumed_manual_ids:
                    mbe.function_assignments, added = self._expand_funktionen(
                        mbe.funktionen, room, ga_lookup,
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

            # Keine Gewerke → import-erzeugte Bedienelemente wiederherstellen
            if not room.bedienelemente and saved_import_bes:
                room.bedienelemente.extend(saved_import_bes)
                continue

            # Physikalische Adressen wiederherstellen
            pn_iter: dict[str, int] = {}
            for be in room.bedienelemente:
                key = be.element_type
                idx = pn_iter.get(key, 0)
                saved = saved_pn.get(key, [])
                if idx < len(saved) and saved[idx]:
                    be.participant_number = saved[idx]
                pn_iter[key] = idx + 1

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

    def _expand_funktionen(
        self,
        funktionen: list[SensorFunktion],
        room,
        ga_lookup: dict,
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
        total_sf_count = sum(1 for sf in funktionen if sf.gewerk_code or sf.ga_designation)
        use_numbers = total_sf_count > 1
        global_channel = 0  # globaler Zähler über alle Gewerke

        for sf in funktionen:
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
                button_ch = sf.label or (
                    f"Taste {global_channel}" if use_numbers else "GA"
                )
                new_fas = self._expand_direct_ga(sf, button_ch)
                fas.extend(new_fas)
                total += len(new_fas)
                continue

            if not sf.gewerk_code:
                continue

            src_room_id = sf.source_room_id or room.id

            # Globaler Zähler: jede SensorFunktion bekommt eine eindeutige Kanalnummer.
            global_channel += 1

            primary_fns = GEWERK_PRIMARY_FUNCTIONS.get(sf.gewerk_code, [])
            feedback_fns = GEWERK_FEEDBACK_FUNCTIONS.get(sf.gewerk_code, [])

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


def project_for_export(project):
    """Kopie des Projekts mit aktuellen Bedienelement-Adressen (FA-1404) und
    Funktionszuordnungen – für Berichte/Exporte, die das Projekt selbst
    nicht verändern dürfen (ein Export soll nur lesen)."""
    import copy
    from .knxproj_import_service import KnxprojImportService

    snapshot = copy.deepcopy(project)
    try:
        KnxprojImportService._create_bedienelemente_from_topology(
            snapshot.topology, snapshot.areal
        )
    except Exception:
        logger.exception("Bedienelement-Adressen für Export nicht ermittelbar")
    SensorService().auto_assign_functions(snapshot.all_rooms, snapshot.group_addresses)
    return snapshot
