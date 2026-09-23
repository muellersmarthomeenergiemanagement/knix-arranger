"""
Gewerke-Verwaltung und Vorlagen (FA-300, FA-306)
"""
from __future__ import annotations
import logging
import re
from collections import defaultdict
from ..models.building import Room, GewerkAssignment, Areal
from ..models.gewerk import GewerkCatalog, Gewerk
from ..models.group_address import GroupAddressStructure
from ..models.topology import Topology
from .naming_engine import NamingEngine

logger = logging.getLogger("knix_arranger.gewerk_service")

# GA-Bezeichnungsmuster: GEWERK.STOCKWERK.RAUM_NR.ELEM_NR[_suffix]
# Beispiele: "LDA.OG.00.01_ea", "J.EG.06.1_move", "H.DG.01.01_ea"
# ELEM_NR ist 1- oder 2-stellig -- nicht jeder Installateur zaehlt zweistellig durch.
_GA_DESIGNATOR_RE = re.compile(
    r"^([A-Z]{1,4})\.([A-Z0-9]{2,5})\.(\d{2})\.(\d{1,2})"
)
# Ziffern-Konvention ohne Stockwerk-Buchstaben: GEWERK.{Stockwerk}{RAUM_NR}.ELEM_NR
# Beispiel: "L.004.1_ea" -> Stockwerk 0, Raum 04, Element 1.
# Floor-Key muss zu Floor.short_code aus xlsx_import_service passen ("D" + Ziffer).
_GA_DIGIT_DESIGNATOR_RE = re.compile(
    r"^([A-Z]{1,4})\.(\d)(\d{2})\.(\d{1,2})"
)
# Kombinierte/Bereichs-Adressierung direkt nach der Element-Nr., z.B.
# "L.OG.05.02+04_ea" (zwei Elemente auf einer GA) oder "J.DG.01.01-03_move"
# (Bereich). Solche GAs steuern mehrere Elemente gleichzeitig -- als
# Einzelelement gezaehlt wuerden sie die Kanalzahl verfaelschen.
_COMBINED_TAIL_RE = re.compile(r"^[+-]\d")


def _com_object_needs_ga(co: dict) -> bool:
    """Repliziert ComObjectInfo.needs_ga auf einem serialisierten ComObject-Dict."""
    return co.get("communication_flag", True) and (
        co.get("write_flag", False)
        or co.get("transmit_flag", False)
        or co.get("read_flag", False)
        or co.get("update_flag", False)
    )


def linked_product_ga_count(assignment: GewerkAssignment) -> int | None:
    """Anzahl GAs pro Element aus verknüpftem Produkt (None = kein Produkt verknüpft)."""
    lp = assignment.linked_product
    if not lp or not lp.get("com_objects"):
        return None
    count = sum(1 for co in lp["com_objects"] if _com_object_needs_ga(co))
    if count == 0:
        return None
    return count + len(assignment.extra_entries)


# System-Gewerke-Vorlagen (FA-306) -- schreibgeschuetzt
GEWERK_TEMPLATES = {
    "wohnzimmer": {
        "name": "Standardraum Wohnen",
        "gewerke": [
            ("LD", 2),   # 2x Licht dimmbar
            ("J", 2),    # 2x Jalousie
            ("H", 1),    # 1x Heizung
            ("TF", 1),   # 1x Temperaturfuehler
        ],
    },
    "schlafzimmer": {
        "name": "Schlafzimmer",
        "gewerke": [
            ("LD", 1),
            ("J", 2),
            ("H", 1),
            ("TF", 1),
        ],
    },
    "kueche": {
        "name": "Kueche",
        "gewerke": [
            ("L", 3),    # 3x Licht
            ("S", 2),    # 2x Steckdose
            ("J", 1),
            ("H", 1),
            ("V", 1),    # 1x Ventilator
        ],
    },
    "badezimmer": {
        "name": "Badezimmer",
        "gewerke": [
            ("L", 2),
            ("V", 1),
            ("H", 1),
            ("TF", 1),
        ],
    },
    "buero": {
        "name": "Büro",
        "gewerke": [
            ("LD", 2),
            ("J", 1),
            ("S", 2),
            ("H", 1),
        ],
    },
    "flur": {
        "name": "Flur/Eingang",
        "gewerke": [
            ("L", 2),
            ("A", 1),    # 1x Alarm
        ],
    },
    "technik": {
        "name": "Technikraum",
        "gewerke": [
            ("L", 1),
            ("E", 1),    # 1x Energiezähler
            ("WP", 1),   # 1x Waermepumpe
        ],
    },
}


class GewerkService:
    """Service für Gewerke-Verwaltung."""

    def __init__(self, catalog: GewerkCatalog):
        self.catalog = catalog

    # ── Vorlagen anwenden ──

    def apply_template(self, room: Room, template_id: str,
                       custom_templates: dict[str, dict] | None = None):
        """Wendet eine Gewerke-Vorlage auf einen Raum an (FA-306).

        Sucht zuerst in System-Vorlagen, dann in benutzerdefinierten.
        """
        template = GEWERK_TEMPLATES.get(template_id)
        if not template and custom_templates:
            template = custom_templates.get(template_id)
        if not template:
            return

        room.gewerk_assignments.clear()
        for code, count in template["gewerke"]:
            if self.catalog.get(code):
                room.gewerk_assignments.append(
                    GewerkAssignment(gewerk_code=code, count=count)
                )

    def get_template_names(self) -> list[tuple[str, str]]:
        """Gibt System-Vorlagen zurück."""
        return [(k, v["name"]) for k, v in GEWERK_TEMPLATES.items()]

    def get_all_template_names(
        self, custom_templates: dict[str, dict] | None = None,
    ) -> list[tuple[str, str, bool]]:
        """Gibt alle Vorlagen zurück: (key, name, is_system).

        System-Vorlagen zuerst, dann benutzerdefinierte.
        """
        result: list[tuple[str, str, bool]] = []
        for k, v in GEWERK_TEMPLATES.items():
            result.append((k, v["name"], True))
        if custom_templates:
            for k, v in custom_templates.items():
                result.append((k, v["name"], False))
        return result

    def get_template(self, template_id: str,
                     custom_templates: dict[str, dict] | None = None,
                     ) -> dict | None:
        """Gibt eine einzelne Vorlage zurück (System oder benutzerdefiniert)."""
        template = GEWERK_TEMPLATES.get(template_id)
        if not template and custom_templates:
            template = custom_templates.get(template_id)
        return template

    def is_system_template(self, template_id: str) -> bool:
        """Prüft ob eine Vorlage eine System-Vorlage ist."""
        return template_id in GEWERK_TEMPLATES

    # ── Benutzerdefinierte Vorlagen CRUD ──

    @staticmethod
    def add_custom_template(
        custom_templates: dict[str, dict],
        key: str, name: str, gewerke: list[tuple[str, int]],
    ):
        """Fügt eine benutzerdefinierte Vorlage hinzu."""
        custom_templates[key] = {"name": name, "gewerke": gewerke}

    @staticmethod
    def update_custom_template(
        custom_templates: dict[str, dict],
        key: str, name: str, gewerke: list[tuple[str, int]],
    ):
        """Aktualisiert eine benutzerdefinierte Vorlage."""
        if key in custom_templates:
            custom_templates[key] = {"name": name, "gewerke": gewerke}

    @staticmethod
    def remove_custom_template(
        custom_templates: dict[str, dict], key: str,
    ):
        """Entfernt eine benutzerdefinierte Vorlage."""
        custom_templates.pop(key, None)

    @staticmethod
    def create_template_from_room(room: Room) -> tuple[str, list[tuple[str, int]]]:
        """Erstellt Vorlagen-Daten aus den Gewerken eines Raums.

        Returns:
            (vorgeschlagener Name, Liste von (code, count) Paaren)
        """
        name = f"Vorlage {room.name}" if room.name else "Neue Vorlage"
        gewerke = [
            (ga.gewerk_code, ga.count)
            for ga in room.gewerk_assignments
        ]
        return name, gewerke

    @staticmethod
    def generate_template_key(name: str, existing_keys: set[str]) -> str:
        """Generiert einen eindeutigen Schlüssel aus dem Vorlagennamen."""
        import re
        base = re.sub(r"[^a-z0-9]", "_", name.lower().strip())
        base = re.sub(r"_+", "_", base).strip("_")
        if not base:
            base = "vorlage"
        key = base
        counter = 2
        while key in existing_keys or key in GEWERK_TEMPLATES:
            key = f"{base}_{counter}"
            counter += 1
        return key

    # ── Berechnungen ──

    def calculate_ga_count(self, room: Room) -> int:
        """Berechnet die Gesamtzahl der GA für einen Raum."""
        total = 0
        for assignment in room.gewerk_assignments:
            gewerk = self.catalog.get(assignment.gewerk_code)
            if gewerk:
                ga_per_element = linked_product_ga_count(assignment)
                if ga_per_element is None:
                    ga_per_element = gewerk.ga_count
                total += ga_per_element * assignment.count
        return total

    def get_room_summary(self, room: Room) -> list[dict]:
        """Gibt eine Zusammenfassung der Gewerke eines Raums zurück."""
        summary = []
        for assignment in room.gewerk_assignments:
            gewerk = self.catalog.get(assignment.gewerk_code)
            if gewerk:
                ga_per_element = linked_product_ga_count(assignment)
                if ga_per_element is None:
                    ga_per_element = gewerk.ga_count
                summary.append({
                    "code": assignment.gewerk_code,
                    "name": gewerk.name,
                    "count": assignment.count,
                    "ga_per_element": ga_per_element,
                    "total_ga": ga_per_element * assignment.count,
                })
        return summary

    @staticmethod
    def _build_room_index(areal: Areal) -> dict[tuple[str, str], Room]:
        """Baut (floor_code, room_nr) -> Room über die gesamte Gebäudestruktur."""
        room_index: dict[tuple[str, str], Room] = {}
        for building in areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apartment in floor.apartments:
                        for room in apartment.rooms:
                            room_index[(floor.short_code, room.number)] = room
        return room_index

    @staticmethod
    def _match_ga_designation(
        designation: str,
    ) -> tuple[str, str, str, str, bool] | None:
        """Matched eine GA-Bezeichnung gegen die GEWERK.STOCKWERK.RAUM.ELEM[_suffix]-
        Konvention (beide Regex-Varianten, siehe _GA_DESIGNATOR_RE /
        _GA_DIGIT_DESIGNATOR_RE). Gibt (code, floor_code, room_nr, elem_nr,
        is_combined) zurück, oder None wenn kein Muster passt. is_combined=True
        bei kombinierter/Bereichs-Adressierung (z.B. "L.OG.05.02+04_ea") -- die
        Elem-Nr. ist dann nicht eindeutig einem einzelnen Element zuordenbar."""
        m = _GA_DESIGNATOR_RE.match(designation)
        if m:
            code, floor_code, room_nr, elem_nr = (
                m.group(1), m.group(2), m.group(3), m.group(4)
            )
        else:
            m = _GA_DIGIT_DESIGNATOR_RE.match(designation)
            if not m:
                return None
            code = m.group(1)
            floor_code = f"D{m.group(2)}"
            room_nr, elem_nr = m.group(3), m.group(4)
        is_combined = bool(_COMBINED_TAIL_RE.match(designation[m.end():]))
        return code, floor_code, room_nr, elem_nr, is_combined

    def _resolve_room_for_designation(
        self, designation: str,
        room_by_number: dict[str, Room],
        room_by_floor_room: dict[tuple[str, str], Room],
    ) -> tuple[Room, str] | None:
        """Löst eine GA-Bezeichnung zu (Room, gewerk_code) auf -- probiert erst
        die native KNiX-Konvention (NamingEngine: "GEWERK_RAUMNUMMER_NR ...",
        Raumnummer enthält bereits das Stockwerk, z.B. "E05"), dann als
        Fallback die externe/ETS-Punkt-Konvention ("GEWERK.STOCKWERK.RAUM.ELEM",
        siehe _match_ga_designation) für Bezeichnungen aus fremd-erzeugten
        ETS-Projekten. Gibt None wenn nichts passt oder der Gewerk-Code
        unbekannt/die Adressierung mehrdeutig ist."""
        parsed = NamingEngine.parse_designation(designation)
        code = parsed["gewerk_code"]
        room_nr = parsed["room_number"]
        if code and room_nr and room_nr in room_by_number:
            return room_by_number[room_nr], code

        matched = self._match_ga_designation(designation)
        if matched is None:
            return None
        code, floor_code, room_nr, _elem_nr, is_combined = matched
        if is_combined:
            return None
        room = room_by_floor_room.get((floor_code, room_nr))
        if room is None:
            return None
        return room, code

    def relink_assignment_ids(
        self, ga_structure: GroupAddressStructure, areal: Areal,
    ) -> int:
        """Verknüpft importierte GroupAddress-Objekte ohne assignment_id mit der
        passenden (ggf. per Reimport erhaltenen) GewerkAssignment, damit
        AddressGenerator._index_existing_hg sie bei der nächsten Neugenerierung
        wiedererkennt statt Duplikat-Blöcke zu erzeugen (FA-521e).

        Muss NACH project_reconcile_service.reconcile_reimport() aufgerufen
        werden, wenn room.gewerk_assignments den finalen (ggf. reimportierten)
        Stand hat. Erzeugt keine neuen Zuweisungen (siehe dazu
        derive_gewerk_assignments) -- nur Verknüpfung. Bereits gesetzte
        assignment_ids werden nie überschrieben.

        Returns:
            Anzahl der neu verknüpften GroupAddress-Objekte.
        """
        room_by_number = {r.number: r for r in areal.all_rooms if r.number}
        room_by_floor_room = self._build_room_index(areal)
        if not room_by_number and not room_by_floor_room:
            return 0
        relinked = 0
        for ga in ga_structure.all_addresses():
            if ga.assignment_id:
                continue
            designation = ga.designation or ""
            if not designation or ga.main_group == 0:
                continue
            resolved = self._resolve_room_for_designation(
                designation, room_by_number, room_by_floor_room,
            )
            if resolved is None:
                continue
            room, code = resolved
            if not self.catalog.get(code):
                continue
            assignment = next(
                (a for a in room.gewerk_assignments if a.gewerk_code == code), None
            )
            if assignment is None:
                continue
            ga.assignment_id = assignment.id
            relinked += 1

        # Reserve-/Platzhalter-Eintraege ("--") tragen keinen auswertbaren
        # Inhalt und werden von der Schleife oben nie erkannt, gehoeren aber
        # zum selben Block wie ihre Nachbarn -- ueber Position statt Inhalt
        # nachtraeglich verknuepfen.
        relinked += self._relink_sandwiched_gaps(ga_structure)

        if relinked:
            logger.info(f"relink_assignment_ids: {relinked} GAs verknüpft.")
        return relinked

    @staticmethod
    def _relink_sandwiched_gaps(ga_structure: GroupAddressStructure) -> int:
        """Verknüpft GAs ohne assignment_id (typischerweise Reserve-Platzhalter
        ohne eigenen Inhalt), die innerhalb einer Mittelgruppe direkt zwischen
        zwei bereits verknüpften Einträgen mit identischer assignment_id
        liegen -- diese lassen sich nicht aus ihrer eigenen Bezeichnung
        ableiten, sind aber eindeutig demselben Block zugehörig, wenn sie auf
        beiden Seiten von genau dieser einen Zuweisung eingerahmt werden.
        Randlücken ohne beidseitigen Nachbarn bleiben bewusst unverknüpft."""
        relinked = 0
        for hg in ga_structure.main_groups:
            for mg in hg.middle_groups:
                gas = sorted(mg.group_addresses, key=lambda g: g.sub_group)
                n = len(gas)
                i = 0
                while i < n:
                    if gas[i].assignment_id:
                        i += 1
                        continue
                    start = i
                    while i < n and not gas[i].assignment_id:
                        i += 1
                    if start == 0 or i == n:
                        continue
                    before_id = gas[start - 1].assignment_id
                    after_id = gas[i].assignment_id
                    if before_id and before_id == after_id:
                        for j in range(start, i):
                            gas[j].assignment_id = before_id
                            relinked += 1
        return relinked

    def derive_gewerk_assignments(
        self,
        ga_structure: GroupAddressStructure,
        areal: Areal,
        overwrite: bool = False,
    ) -> int:
        """
        Leitet Gewerk-Zuweisungen aus GA-Bezeichnungen ab und trägt sie in Räume ein.

        Scannt alle GA-Bezeichnungen nach dem Muster
        'GEWERK.STOCKWERK.RAUM_NR.ELEMENT_NR[_suffix]' (z.B. 'LDA.OG.00.01_ea')
        und erzeugt pro Raum je einen GewerkAssignment-Eintrag pro erkanntem
        Gewerk-Code mit der Anzahl eindeutiger Elemente.

        Nur Gewerk-Codes, die im Katalog bekannt sind, werden übernommen.
        Unbekannte Codes (z.B. 'RAUM1', 'AK', 'HS') werden protokolliert und
        übersprungen.

        Zwei Arten von Adressen lassen sich nicht zuverlässig einem einzelnen
        Raum-Element zuordnen und werden daher NICHT gezählt, sondern nur in
        `self.last_central_addresses` / `self.last_ambiguous_designations`
        gesammelt (für eine Warnmeldung des Aufrufers):

        - Zentraladressen (Hauptgruppe 0, verbreitete ETS6-Konvention "0 = Zentral")
          steuern typischerweise mehrere Räume/Gewerke gleichzeitig.
        - Kombinierte/Bereichs-Adressierung in der Bezeichnung selbst, z.B.
          "L.OG.05.02+04_ea" oder "J.DG.01.01-03_move" -- eine GA für mehrere
          Elemente auf einmal.

        Args:
            ga_structure:  Gruppenadress-Struktur (aus GA-Report oder Topologie-Import)
            areal:         Gebäudestruktur mit Floor.short_code und Room.number
            overwrite:     Wenn True, werden bestehende Zuweisungen ersetzt;
                           sonst nur leere Räume befüllt.

        Returns:
            Anzahl der erstellten GewerkAssignment-Einträge.
        """
        self.last_central_addresses: list[str] = []
        self.last_ambiguous_designations: list[str] = []

        room_index = self._build_room_index(areal)
        if not room_index:
            logger.warning("derive_gewerk_assignments: Keine Räume in Gebäudestruktur.")
            return 0

        # GA-Bezeichnungen auswerten: (floor, room_nr) -> {code -> set(elem_nr)}
        room_gewerke: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for ga in ga_structure.all_addresses():
            designation = ga.designation or ""
            if not designation:
                continue

            if ga.main_group == 0:
                self.last_central_addresses.append(f"{ga.address}  {designation}")
                continue

            matched = self._match_ga_designation(designation)
            if matched is None:
                continue
            code, floor_code, room_nr, elem_nr, is_combined = matched

            if is_combined:
                self.last_ambiguous_designations.append(f"{ga.address}  {designation}")
                continue

            if (floor_code, room_nr) in room_index:
                room_gewerke[(floor_code, room_nr)][code].add(elem_nr)

        if not room_gewerke:
            logger.warning(
                "derive_gewerk_assignments: Keine passenden GA-Bezeichnungen gefunden."
            )
            return 0

        unknown_codes: set[str] = set()
        total_assignments = 0

        for (floor_code, room_nr), gewerke in room_gewerke.items():
            room = room_index[(floor_code, room_nr)]

            if room.gewerk_assignments and not overwrite:
                continue

            new_assignments: list[GewerkAssignment] = []
            for code, elem_nrs in sorted(gewerke.items()):
                if not self.catalog.get(code):
                    unknown_codes.add(code)
                    continue
                new_assignments.append(
                    GewerkAssignment(gewerk_code=code, count=len(elem_nrs))
                )
                total_assignments += 1

            if new_assignments:
                if overwrite:
                    room.gewerk_assignments = new_assignments
                else:
                    room.gewerk_assignments.extend(new_assignments)

        if unknown_codes:
            logger.info(
                f"derive_gewerk_assignments: Unbekannte Gewerk-Codes übersprungen: "
                f"{sorted(unknown_codes)}"
            )

        if self.last_central_addresses:
            logger.info(
                f"derive_gewerk_assignments: {len(self.last_central_addresses)} "
                f"Zentraladressen (Hauptgruppe 0) von der Zählung ausgeschlossen."
            )
        if self.last_ambiguous_designations:
            logger.info(
                f"derive_gewerk_assignments: {len(self.last_ambiguous_designations)} "
                f"kombinierte/Bereichs-Adressierungen von der Zählung ausgeschlossen."
            )

        logger.info(
            f"derive_gewerk_assignments: {total_assignments} Zuweisungen in "
            f"{len(room_gewerke)} Räumen erstellt."
        )
        return total_assignments

    def detect_channel_gewerk_conflicts(
        self,
        topology: Topology,
        ga_structure: GroupAddressStructure,
    ) -> list[str]:
        """Erkennt Kommunikationsobjekte, deren verbundene GAs zu UNTERSCHIEDLICHEN
        Gewerk-Codes gehören (FA-521d) -- z.B. ein Aktorkanal, auf den zwei GAs
        für zwei verschiedene Gewerke programmiert wurden.

        Solche Kanäle lassen sich nicht automatisch korrekt einem einzelnen
        Gewerk zuordnen (die Kanal-/Gewerkezählung nimmt implizit 1 Kanal =
        1 Gewerk-Element an). Statt still ein Gewerk zu wählen, werden sie hier
        nur zur manuellen Prüfung aufgelistet.

        Nur im Gewerk-Katalog bekannte Codes zählen -- freie GA-Namensteile wie
        Szenen-Helfer ("Raum5_Szene...") werden sonst faelschlich als eigenes
        "Gewerk" erkannt, obwohl sie regulaer denselben Kanal wie die primaere
        Schalt-GA verwenden (kein echter Konflikt).

        Gibt eine Liste menschenlesbarer Warnungen zurück (Gerät, Kanal, Gewerke).
        """
        ga_gewerk: dict[str, str] = {
            ga.address: ga.gewerk_code
            for ga in ga_structure.all_addresses()
            if ga.gewerk_code and self.catalog.get(ga.gewerk_code)
        }

        conflicts: list[str] = []
        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    for ko in device.communication_objects:
                        codes = {
                            ga_gewerk[addr] for addr in ko.connected_gas
                            if addr in ga_gewerk
                        }
                        if len(codes) > 1:
                            label = device.product_name or device.product or device.physical_address
                            conflicts.append(
                                f"{device.physical_address}  {label}  –  "
                                f"{ko.name or 'Kanal'}: Gewerke {', '.join(sorted(codes))}"
                            )

        if conflicts:
            logger.warning(
                f"detect_channel_gewerk_conflicts: {len(conflicts)} Kanäle mit "
                f"mehreren Gewerken auf derselben GA-Verbindung gefunden."
            )
        return conflicts
