"""
ETS-Belegungsplan: Daten-Aufbereitung für Sensor/Taster- und Aktor-Funktionstabelle.

Generiert aus dem Projekt eine strukturierte Übersicht, welche GAs
an welche Sensortasten und Aktorkanäle gebunden werden sollen –
als Vorlage für die ETS-Programmierung.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import logging
import re

logger = logging.getLogger("knix_arranger.belegungsplan")

# Aktortyp-Bezeichnung (device.product prefix) → zugehörige Gewerk-Codes
# Spiegelt GEWERK_TO_ACTOR_TYPE aus models/device.py
# Enthält deutsche UND englische Keywords für ETS6-Importe.
_ACTOR_TYPE_GEWERKE: dict[str, set[str]] = {
    # Deutsch – spezifische Einträge VOR allgemeinen (Substring-Matching, first-match-wins)
    "Schaltaktor":          {"L", "S", "V", "G", "DF", "BW", "BL", "P"},
    "DALI-Gateway":         {"LDA"},
    "RGB-Dimmaktor":        {"LC"},   # vor "Dimmaktor" – "Dimmaktor" ist Teilstring
    "Tunable-White-Aktor":  {"LCT"},
    "RGBW-Dimmaktor":       {"LCW"},  # vor "Dimmaktor" – "Dimmaktor" ist Teilstring
    "Dimmaktor":            {"LD", "SD"},
    "DMX-KNX-Gateway":      {"DMX"},
    "Jalousieaktor":        {"J", "R", "M", "T"},
    "Heizungsaktor":        {"H"},
    "Modbus-KNX-Gateway":   {"WP"},
    "KWL-KNX-Gateway":      {"LU"},
    "Klima-KNX-Gateway":    {"KL"},
    "Wallbox-KNX-Gateway":  {"EV"},
    "PV-KNX-Gateway":       {"PV"},
    "Speicher-KNX-Gateway": {"SP"},
    # Englisch (ETS6-Import) – spezifische Einträge zuerst
    "switch act":    {"L", "S", "V", "G", "DF", "BW", "BL", "P"},
    "dimming act":   {"LD", "SD"},
    "dali":          {"LDA"},
    "rgbw":          {"LCW"},  # vor "rgb" – "rgb" ist Teilstring von "rgbw"
    "rgb":           {"LC"},
    "tunable":       {"LCT"},
    "dmx":           {"DMX"},
    "blind act":     {"J", "R", "M", "T"},
    "shutter act":   {"J", "R", "M", "T"},
    "heating act":   {"H"},
    "heating ctrl":  {"H"},
    "ventilation":   {"LU"},
    "hvac":          {"KL"},
    "wallbox":       {"EV"},
    "inverter":      {"PV"},
    "battery":       {"SP"},
}

# Alle Gewerk-Codes, die Aktorseite darstellen
_ALL_ACTOR_GEWERKE: set[str] = {
    code for codes in _ACTOR_TYPE_GEWERKE.values() for code in codes
}


@dataclass
class SensorRow:
    """Eine Zeile im Sensor/Taster-Belegungsplan."""
    floor_name: str
    zone_name: str          # Wohnung / Zone, z.B. "Wohnung 1"
    room_number: str
    room_name: str
    sensor_type: str
    physical_address: str   # physikalische Adresse des Bedienelements
    taste_label: str        # z.B. "Taste 1", "Taste 2", "Status", "Sollwert"
    function: str           # z.B. "Licht schalten"
    ga_designation: str     # z.B. "L_E01_01 E/A"
    ga_address: str         # z.B. "2/0/0"
    dpt: str                # z.B. "DPST-1-1"
    # Aktionstyp: "kurz" = kurz drücken, "lang" = lang drücken, "" = unspezifisch
    action_type: str = ""
    # True = LED-Rückmeldung (nur empfangen), False = Steuer-GA (Taster sendet)
    is_feedback: bool = False


@dataclass
class ActorRow:
    """Eine Zeile im Aktor-Belegungsplan."""
    line_name: str
    area_number: int
    line_number: int
    uv_location: str            # Einbauort des Aktors, z.B. "UV2 (Steigzone)"
    actor_type: str             # Gerätetyp, z.B. "Dimmaktor 2-fach"
    physical_address: str       # Physikalische Adresse des Aktors, z.B. "1.1.5"
    channel_number: str         # Ausgangskanal des Aktors, z.B. "1", "2" oder ""
    element_number: int         # GA-Elementnummer innerhalb Raum+Gewerk, z.B. 1, 2
    room_number: str
    zone_name: str              # Wohnung / Zone, z.B. "Wohnung 1"
    room_name: str
    gewerk_code: str            # z.B. "LD"
    function_name: str          # z.B. "E/A", "DIM", "WERT", "RM"
    ga_designation: str         # z.B. "LD_E01_01 E/A (Wohnen)"
    ga_address: str             # z.B. "2/0/4"
    dpt: str                    # z.B. "DPST-1-1"


@dataclass
class BelegungsplanData:
    """Vollständiger Belegungsplan (Sensoren/Taster + Aktoren)."""
    project_name: str
    sensor_rows: list[SensorRow] = field(default_factory=list)
    actor_rows: list[ActorRow] = field(default_factory=list)


def _split_button_channel(button_channel: str) -> tuple[str, str]:
    """Trennt "Taste 1" → ("Taste", "1"); "Taste" → ("Taste", "1"); "Sollwert" → ("Sollwert", "").

    Einzeltaster ohne Nummernsuffix ("Taste") erhalten Kanal "1", da es genau
    einen Kanal gibt. Nicht-Taster-Typen (Status, Sollwert, …) bleiben ohne Kanal.
    """
    parts = button_channel.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], parts[1]
    # Einzeltaster: kein Suffix, aber physisch Kanal 1
    if button_channel == "Taste":
        return "Taste", "1"
    return button_channel, ""


def _parse_phys_addr(addr: str) -> tuple[int, ...]:
    """Parst "1.1.5" → (1, 1, 5) für numerische Sortierung."""
    try:
        return tuple(int(p) for p in addr.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _parse_ga_addr(addr: str) -> tuple[int, ...]:
    """Parst "2/0/4" → (2, 0, 4) für numerische Sortierung."""
    try:
        return tuple(int(p) for p in addr.split("/"))
    except (ValueError, AttributeError):
        return (0, 0, 0)


class BelegungsplanService:
    """Erstellt den ETS-Belegungsplan aus einem KnxProject."""

    def generate(self, project) -> BelegungsplanData:
        """Haupteinstieg: generiert BelegungsplanData aus dem Projekt.

        Stellt sicher, dass function_assignments aller Bedienelemente aktuell
        sind (d.h. zur aktuellen GA-Struktur passen), bevor Berichte/Matrix
        gelesen werden.
        """
        from .sensor_service import SensorService
        from .knxproj_import_service import KnxprojImportService
        try:
            KnxprojImportService._create_bedienelemente_from_topology(
                project.topology, project.areal
            )
        except Exception:
            pass
        SensorService().auto_assign_functions(
            project.all_rooms, project.group_addresses
        )

        ga_index = self._build_ga_index(project)
        floor_index = self._build_floor_index(project)
        zone_index = self._build_zone_index(project)

        data = BelegungsplanData(project_name=project.name)
        data.sensor_rows = self._collect_sensor_rows(project, ga_index, floor_index, zone_index)
        data.actor_rows = self._collect_actor_rows(project, floor_index, zone_index)
        return data

    # ── Hilfsmethoden ──

    def _build_ga_index(self, project) -> dict:
        """Erstellt dict: GA-Bezeichnung → GroupAddress."""
        index = {}
        for ga in project.group_addresses.all_addresses():
            if ga.designation:
                index[ga.designation] = ga
        return index

    def _build_floor_index(self, project) -> dict:
        """Erstellt dict: room_id → Stockwerk-Name."""
        index = {}
        for building in project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            index[room.id] = floor.name
        return index

    def _build_zone_index(self, project) -> dict:
        """Erstellt dict: room_id → Zonen-/Wohnungsname (Apartment.name)."""
        index = {}
        for building in project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            index[room.id] = apt.name
        return index

    def _collect_sensor_rows(
        self, project, ga_index: dict, floor_index: dict, zone_index: dict
    ) -> list[SensorRow]:
        """
        Iteriert Topologie → Linien → Räume → Bedienelemente → FunctionAssignments
        und baut die Sensor-Zeilen auf.

        Fallback für ETS6-Importe (keine function_assignments): COs des Topology-
        Devices werden über be.participant_number aufgelöst und pro CO×GA eine Zeile
        erzeugt – analog zum Aktor-CO-Fallback.
        """
        room_index = {r.id: r for r in project.all_rooms}
        # Lookup: phys. Adresse → Device (für CO-Fallback)
        device_by_addr = {
            d.physical_address: d
            for area in project.topology.areas
            for line in area.lines
            for d in line.devices
        }
        # Lookup: GA-Adresse → GroupAddress (für CO-Fallback)
        ga_by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}

        seen_room_ids: set[str] = set()
        rows: list[SensorRow] = []

        for area in project.topology.areas:
            for line in area.lines:
                for room_id in line.assigned_room_ids:
                    if room_id in seen_room_ids:
                        continue
                    seen_room_ids.add(room_id)
                    room = room_index.get(room_id)
                    if not room:
                        continue
                    floor_name = floor_index.get(room_id, "")
                    zone_name = zone_index.get(room_id, "")
                    for be in room.bedienelemente:
                        if be.function_assignments:
                            for fa in be.function_assignments:
                                ga = ga_index.get(fa.function_ga)
                                rows.append(SensorRow(
                                    floor_name=floor_name,
                                    zone_name=zone_name,
                                    room_number=room.number,
                                    room_name=room.name,
                                    sensor_type=be.element_type,
                                    physical_address=be.participant_number or "",
                                    taste_label=fa.button_channel,
                                    action_type=fa.action_type,
                                    is_feedback=fa.is_feedback,
                                    function=fa.description,
                                    ga_designation=fa.function_ga,
                                    ga_address=ga.address if ga else "",
                                    dpt=ga.datapoint_type if ga else "",
                                ))
                        else:
                            rows.extend(self._sensor_rows_from_cos(
                                be, floor_name, zone_name, room,
                                device_by_addr, ga_by_address,
                            ))

        # Räume ohne Topologie-Linienzuordnung anhängen (z.B. reine Sensor-Räume)
        for room in project.all_rooms:
            if room.id in seen_room_ids:
                continue
            if not room.bedienelemente:
                continue
            floor_name = floor_index.get(room.id, "")
            zone_name = zone_index.get(room.id, "")
            for be in room.bedienelemente:
                if be.function_assignments:
                    for fa in be.function_assignments:
                        ga = ga_index.get(fa.function_ga)
                        rows.append(SensorRow(
                            floor_name=floor_name,
                            zone_name=zone_name,
                            room_number=room.number,
                            room_name=room.name,
                            sensor_type=be.element_type,
                            physical_address=be.participant_number or "",
                            taste_label=fa.button_channel,
                            function=fa.description,
                            ga_designation=fa.function_ga,
                            ga_address=ga.address if ga else "",
                            dpt=ga.datapoint_type if ga else "",
                        ))
                else:
                    rows.extend(self._sensor_rows_from_cos(
                        be, floor_name, zone_name, room,
                        device_by_addr, ga_by_address,
                    ))

        # Fallback für ETS6-Importe: Sensor-Devices ohne Bedienelement-Eintrag
        # direkt über ihre COs und connected_gas ausgeben (analog zum Aktor-Fallback).
        covered_phys: set[str] = {r.physical_address for r in rows if r.physical_address}
        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.device_type != "sensor":
                        continue
                    if device.physical_address in covered_phys:
                        continue
                    room_id = device.room_id or (line.assigned_room_ids[0] if line.assigned_room_ids else "")
                    room = room_index.get(room_id)
                    zone_name = zone_index.get(room_id, "") if room_id else ""
                    floor_name = floor_index.get(room_id, "") if room_id else ""
                    has_cos_with_gas = any(co.connected_gas for co in device.communication_objects)
                    if has_cos_with_gas:
                        for co in device.communication_objects:
                            for ga_addr in co.connected_gas:
                                ga_obj = ga_by_address.get(ga_addr)
                                rows.append(SensorRow(
                                    floor_name=floor_name,
                                    zone_name=zone_name,
                                    room_number=room.number if room else "",
                                    room_name=room.name if room else "",
                                    sensor_type=device.product or "Sensor",
                                    physical_address=device.physical_address,
                                    taste_label=co.name or f"KO {co.object_number}",
                                    action_type="",
                                    is_feedback=False,
                                    function=co.object_function,
                                    ga_designation=ga_obj.designation if ga_obj else ga_addr,
                                    ga_address=ga_addr,
                                    dpt=co.data_type,
                                ))
                    else:
                        # Sensor bekannt aber keine GAs → Platzhalter-Zeile
                        rows.append(SensorRow(
                            floor_name=floor_name,
                            zone_name=zone_name,
                            room_number=room.number if room else "",
                            room_name=room.name if room else "",
                            sensor_type=device.product or "Sensor",
                            physical_address=device.physical_address,
                            taste_label="-",
                            action_type="",
                            is_feedback=False,
                            function="",
                            ga_designation="",
                            ga_address="",
                            dpt="",
                        ))
                    covered_phys.add(device.physical_address)

        # Anzeigesortierung: Phys. Adresse ↑ → Taste-Nr. ↑ → GA-Adresse ↑
        # Taste-Nr. wird aus dem trailing digit von taste_label extrahiert ("Taste 2" → 2).
        def _taste_sort_key(label: str) -> int:
            suffix = label.rsplit(" ", 1)[-1]
            return int(suffix) if suffix.isdigit() else 0

        rows.sort(key=lambda r: (
            _parse_phys_addr(r.physical_address),
            _taste_sort_key(r.taste_label),
            _parse_ga_addr(r.ga_address),
        ))
        logger.info(f"Belegungsplan: {len(rows)} Sensor-Zeilen generiert.")
        return rows

    @staticmethod
    def _sensor_rows_from_cos(
        be, floor_name: str, zone_name: str, room,
        device_by_addr: dict, ga_by_address: dict,
    ) -> list[SensorRow]:
        """
        Fallback für ETS6-importierte Bedienelemente ohne function_assignments.
        Expandiert die COs des Topology-Devices (Lookup via be.participant_number)
        in einzelne SensorRows – eine Zeile pro CO×GA-Kombination.
        Ohne Treffer: eine Platzhalter-Zeile.
        """
        result: list[SensorRow] = []
        device = device_by_addr.get(be.participant_number or "")
        if device:
            for co in device.communication_objects:
                for ga_addr in co.connected_gas:
                    ga_obj = ga_by_address.get(ga_addr)
                    result.append(SensorRow(
                        floor_name=floor_name,
                        zone_name=zone_name,
                        room_number=room.number,
                        room_name=room.name,
                        sensor_type=be.element_type,
                        physical_address=be.participant_number or "",
                        taste_label=co.name or f"KO {co.object_number}",
                        action_type="",
                        is_feedback=False,
                        function=co.object_function,
                        ga_designation=ga_obj.designation if ga_obj else ga_addr,
                        ga_address=ga_addr,
                        dpt=co.data_type,
                    ))
        if not result:
            # Kein Device oder keine COs mit GAs → Platzhalter-Zeile
            result.append(SensorRow(
                floor_name=floor_name,
                zone_name=zone_name,
                room_number=room.number,
                room_name=room.name,
                sensor_type=be.element_type,
                physical_address=be.participant_number or "",
                taste_label="-",
                action_type="",
                is_feedback=False,
                function="",
                ga_designation="",
                ga_address="",
                dpt="",
            ))
        return result

    def _collect_actor_rows(self, project, floor_index: dict, zone_index: dict) -> list[ActorRow]:
        """
        Baut Aktor-Zeilen aus der Topologie.

        Primär: GA-basierte Zuordnung über Gewerk-Codes (Wizard-Projekte).
        Fallback: CO-basierte Zuordnung aus connected_gas (ETS6-Importe).
        Pro (Linie, Aktortyp-Gruppe) werden die passenden GAs einmalig aufgelistet.
        """
        room_index = {r.id: r for r in project.all_rooms}

        # GA-Index: (room_id, gewerk_code) → list[GroupAddress]
        # Fallback: (room_number, gewerk_code) für ältere Projekte ohne room_id
        ga_by_room_gewerk: dict[tuple, list] = {}
        ga_by_roomnr_gewerk: dict[tuple, list] = {}
        for ga in project.group_addresses.all_addresses():
            if ga.is_placeholder:
                continue
            if not ga.gewerk_code or ga.gewerk_code not in _ALL_ACTOR_GEWERKE:
                continue
            if ga.room_id:
                ga_by_room_gewerk.setdefault((ga.room_id, ga.gewerk_code), []).append(ga)
            elif ga.room_number:
                ga_by_roomnr_gewerk.setdefault((ga.room_number, ga.gewerk_code), []).append(ga)

        rows: list[ActorRow] = []
        covered_device_addrs: set[str] = set()  # Adressen mit GA-Treffer (kein CO-Fallback nötig)

        for area in project.topology.areas:
            for line in area.lines:
                actor_devices = [d for d in line.devices if d.device_type == "actor"]
                if not actor_devices:
                    continue

                # Geräte nach Gewerk-Gruppe (frozenset der Gewerk-Codes) clustern.
                # Mehrere Aktoren desselben Typs (z.B. 2× Schaltaktor) landen in
                # derselben Gruppe und erhalten jeweils ihre eigene Kapazität.
                groups: dict[frozenset, list[tuple]] = {}
                for device in actor_devices:
                    gewerke = self._gewerke_for_device(device.product)
                    if not gewerke:
                        continue
                    cap = self._parse_channel_count(device.product)
                    groups.setdefault(frozenset(gewerke), []).append((device, cap))

                for gewerke_set, device_cap_list in groups.items():
                    # Alle Stromkreise (room, gewerk, element_nr) für diese Gruppe
                    # in deterministischer Reihenfolge sammeln.
                    circuits: list[tuple] = []  # (room_id, room, gewerk_code, elem_nr, list[GA])
                    seen_circuits: set[tuple] = set()
                    for room_id in line.assigned_room_ids:
                        room = room_index.get(room_id)
                        if not room:
                            continue
                        for gewerk_code in sorted(gewerke_set):
                            gas = ga_by_room_gewerk.get((room_id, gewerk_code))
                            if not gas:
                                gas = ga_by_roomnr_gewerk.get((room.number, gewerk_code), [])
                            if not gas:
                                continue
                            by_elem: dict[int, list] = {}
                            for ga in gas:
                                by_elem.setdefault(ga.element_number, []).append(ga)
                            for elem_nr, elem_gas in sorted(by_elem.items()):
                                circ_key = (room.number, gewerk_code, elem_nr)
                                if circ_key not in seen_circuits:
                                    seen_circuits.add(circ_key)
                                    circuits.append((room_id, room, gewerk_code, elem_nr, elem_gas))

                    if not circuits:
                        continue

                    # Stromkreise sortieren (Raum-Nr → Gewerk → Element),
                    # damit die Kanalnummern konsistent mit der Vorsortierung sind.
                    circuits.sort(key=lambda c: (c[1].number, c[2], c[3]))

                    # Stromkreise sequenziell auf Geräte verteilen (nach Kapazität).
                    # Ist ein Gerät voll, wechselt der Zähler zum nächsten.
                    dev_idx = 0
                    ch_in_dev = 0
                    for room_id, room, gewerk_code, elem_nr, elem_gas in circuits:
                        # Nächstes Gerät wenn Kapazität erschöpft (letztes Gerät immer behalten)
                        if dev_idx < len(device_cap_list) - 1:
                            _, cap = device_cap_list[dev_idx]
                            if ch_in_dev >= cap:
                                dev_idx += 1
                                ch_in_dev = 0
                        device, _ = device_cap_list[dev_idx]

                        zone_name = zone_index.get(room_id, "")
                        for ga in sorted(elem_gas, key=lambda g: g.function_name):
                            covered_device_addrs.add(device.physical_address)
                            rows.append(ActorRow(
                                line_name=line.name,
                                area_number=area.area_number,
                                line_number=line.line_number,
                                uv_location=device.installation_location or line.uv_location or "",
                                actor_type=device.product,
                                physical_address=device.physical_address,
                                channel_number="",  # wird unten nachgetragen
                                element_number=elem_nr,
                                room_number=room.number,
                                zone_name=zone_name,
                                room_name=room.name,
                                gewerk_code=gewerk_code,
                                function_name=ga.function_name,
                                ga_designation=ga.designation,
                                ga_address=ga.address,
                                dpt=ga.datapoint_type,
                            ))
                        ch_in_dev += 1

        # Vorsortierung für konsistente Kanalnummern-Vergabe:
        # Reihenfolge Linie → Phys. Adresse → Raum-Nr. → Gewerk → Element-Nr. bestimmt,
        # welcher Stromkreis/Jalousie Kanal 1, 2, 3 … erhält.
        rows.sort(key=lambda r: (
            r.area_number, r.line_number,
            _parse_phys_addr(r.physical_address),
            r.room_number, r.gewerk_code, r.element_number,
        ))

        # Kanalnummern pro Aktor nachträglich vergeben:
        # Jede eindeutige (Raum-Nr, Gewerk, Element-Nr.) Kombination innerhalb eines Aktors
        # bekommt eine fortlaufende Kanalnummer (1, 2, 3, ...).
        actor_channel_counters: dict[str, dict[tuple, str]] = {}
        for row in rows:
            addr = row.physical_address
            if addr not in actor_channel_counters:
                actor_channel_counters[addr] = {}
            key = (row.room_number, row.gewerk_code, row.element_number)
            if key not in actor_channel_counters[addr]:
                actor_channel_counters[addr][key] = str(len(actor_channel_counters[addr]) + 1)
            row.channel_number = actor_channel_counters[addr][key]

        # Fallback für ETS6-Importe: Aktoren ohne GA-Treffer über connected_gas der COs anzeigen
        ga_by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
        fallback_rows: list[ActorRow] = []
        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.device_type != "actor":
                        continue
                    if device.physical_address in covered_device_addrs:
                        continue
                    room_id = device.room_id or (line.assigned_room_ids[0] if line.assigned_room_ids else "")
                    room = room_index.get(room_id)
                    zone_name = zone_index.get(room_id, "") if room_id else ""
                    uv = device.installation_location or getattr(line, "uv_location", "") or ""
                    # Eine Zeile pro CO×GA aus dem ETS6-Import
                    for co in device.communication_objects:
                        for ga_addr in co.connected_gas:
                            ga_obj = ga_by_address.get(ga_addr)
                            fallback_rows.append(ActorRow(
                                line_name=line.name,
                                area_number=area.area_number,
                                line_number=line.line_number,
                                uv_location=uv,
                                actor_type=device.product,
                                physical_address=device.physical_address,
                                channel_number="",
                                element_number=0,
                                room_number=room.number if room else "",
                                zone_name=zone_name,
                                room_name=room.name if room else "",
                                gewerk_code="",
                                function_name=co.name or co.object_function,
                                ga_designation=ga_obj.designation if ga_obj else ga_addr,
                                ga_address=ga_addr,
                                dpt=co.data_type,
                            ))

        if fallback_rows:
            # Kanalnummern für Fallback-Zeilen vergeben.
            # Schlüssel: function_name (entspricht co.name), da element_number und gewerk_code
            # für ETS6-Importe nicht bekannt sind. Mehrere GAs desselben COs teilen
            # damit die gleiche Kanalnummer.
            for row in fallback_rows:
                addr = row.physical_address
                if addr not in actor_channel_counters:
                    actor_channel_counters[addr] = {}
                key = row.function_name
                if key not in actor_channel_counters[addr]:
                    actor_channel_counters[addr][key] = str(len(actor_channel_counters[addr]) + 1)
                row.channel_number = actor_channel_counters[addr][key]
            rows.extend(fallback_rows)
            logger.debug(f"CO-Fallback: {len(fallback_rows)} Aktor-Zeilen aus ETS6-COs ergänzt.")

        # Anzeigesortierung: Phys. Adresse ↑ → Kanal ↑ → GA-Adresse ↑
        rows.sort(key=lambda r: (
            _parse_phys_addr(r.physical_address),
            int(r.channel_number) if r.channel_number.isdigit() else 0,
            _parse_ga_addr(r.ga_address),
        ))

        logger.info(f"Belegungsplan: {len(rows)} Aktor-Zeilen generiert.")
        return rows

    @staticmethod
    def _gewerke_for_device(product: str) -> set[str]:
        """Leitet die zugehörigen Gewerk-Codes aus dem Gerätetyp-String ab."""
        p = product.lower()
        for actor_type_prefix, codes in _ACTOR_TYPE_GEWERKE.items():
            if actor_type_prefix.lower() in p:
                return codes
        return set()

    @staticmethod
    def _parse_channel_count(product: str) -> int:
        """Liest die Kanalzahl aus dem Produktnamen.

        Erkennt u.a.: "12-fach", "12 fach", "12-fold", "12 CH", "12-channel".
        Fallback: 8.
        """
        patterns = [
            r'(\d+)\s*[-–]?\s*fach',     # Deutsch
            r'(\d+)\s*[-–]?\s*fold',     # Englisch
            r'(\d+)\s*[-–]?\s*ch(?:annel)?(?!\w)',  # Englisch (ch / channel)
            r'(\d+)\s*[-–]?\s*gang',     # Englisch
        ]
        for pat in patterns:
            m = re.search(pat, product, re.IGNORECASE)
            if m:
                n = int(m.group(1))
                if 1 <= n <= 64:   # plausibler Bereich
                    return n
        return 8  # vernünftiger Fallback
