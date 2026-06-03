"""
Tests fuer Eingabe-Effizienz und Workflow-Optimierung (FA-3201 bis FA-3211).

Die Tests pruefen die Geschaeftslogik der Wizard-Schritte, ohne Qt zu
benoetigen: Datenmodell-Operationen werden direkt an Building-Objekten
getestet; UI-unabhaengige Algorithmen werden inline repliziert.
"""
import copy
import re
import sys
import os
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
    STANDARD_FLOOR_NAMES, FLOOR_TO_MAIN_GROUP,
)
from knix_arranger.services.building_service import BuildingService


# ---------------------------------------------------------------------------
# Hilfs-Algorithmen (aus den Wizard-Steps extrahiert, ohne Qt-Import)
# ---------------------------------------------------------------------------

def quick_add_floors(wing: Wing, codes_text: str) -> int:
    """Repliziert die Logik von Step01Building._quick_add_floors (FA-3201)."""
    existing_codes = {f.short_code for f in wing.floors}
    codes = [c.strip() for c in codes_text.split(",") if c.strip()]
    added = 0
    for code in codes:
        if code in existing_codes:
            continue
        name = STANDARD_FLOOR_NAMES.get(code, f"Stockwerk {code}")
        hg = FLOOR_TO_MAIN_GROUP.get(code, len(wing.floors) + 1)
        wing.floors.append(Floor(name=name, short_code=code, main_group_number=hg))
        existing_codes.add(code)
        added += 1
    return added


def auto_zones(floors: list[Floor]) -> int:
    """Repliziert die Logik von Step02Apartments._auto_zones (FA-3202)."""
    added = 0
    for floor in floors:
        if not floor.apartments:
            floor.apartments.append(Apartment(name=floor.name))
            added += 1
    return added


def increment_room_number(number: str) -> str:
    """Repliziert Step03Rooms._increment_room_number (FA-3203)."""
    m = re.match(r'^(.*?)(\d+)$', number)
    if m:
        prefix, digits = m.group(1), m.group(2)
        new_num = int(digits) + 1
        return f"{prefix}{new_num:0{len(digits)}d}"
    return number + "_2"


def parse_bulk_rooms(text: str) -> list[tuple[str, str]]:
    """Repliziert die Parsing-Logik von Step03Rooms._bulk_add_rooms (FA-3205)."""
    results = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        number = parts[0]
        name = parts[1] if len(parts) > 1 else parts[0]
        results.append((number, name))
    return results


def quick_add_gewerk(rooms: list[Room], code: str) -> int:
    """Repliziert Step05Gewerke._quick_add_gewerk (FA-3209)."""
    added = 0
    for room in rooms:
        if not any(ga.gewerk_code == code for ga in room.gewerk_assignments):
            room.gewerk_assignments.append(GewerkAssignment(gewerk_code=code, count=1))
            added += 1
    return added


def apply_to_same_rooms(src_rooms: list[Room], all_rooms: list[Room]) -> int:
    """Repliziert Step05Gewerke._apply_to_same_rooms (FA-3208)."""
    affected = 0
    for src in src_rooms:
        for target in all_rooms:
            if target is src:
                continue
            if target.name == src.name:
                new_assignments = []
                for ga in src.gewerk_assignments:
                    d = copy.deepcopy(ga.to_dict())
                    d["id"] = str(uuid.uuid4())
                    new_assignments.append(GewerkAssignment.from_dict(d))
                target.gewerk_assignments = new_assignments
                affected += 1
    return affected


def step_tooltip(project, step_index: int) -> str:
    """Repliziert WizardController._step_tooltip (FA-3211)."""
    p = project
    try:
        if step_index == 0:
            n = len(p.all_floors)
            return f"{n} Stockwerk{'e' if n != 1 else ''}"
        elif step_index == 1:
            zones = sum(len(f.apartments) for f in p.all_floors)
            return f"{zones} Zone{'n' if zones != 1 else ''}"
        elif step_index == 2:
            n = len(p.all_rooms)
            return f"{n} Raum/Räume"
        elif step_index == 4:
            n = sum(len(r.gewerk_assignments) for r in p.all_rooms)
            return f"{n} Gewerk-Zuweisung{'en' if n != 1 else ''}"
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# FA-3201: Schnelleingabe Stockwerke
# ---------------------------------------------------------------------------

class TestFA3201QuickFloors:
    """Schnelleingabe: mehrere Stockwerke auf einmal anlegen."""

    def _wing(self):
        wing = Wing(name="Haupt")
        return wing

    def test_known_code_maps_to_standard_name(self):
        wing = self._wing()
        quick_add_floors(wing, "EG")
        assert wing.floors[0].name == "Erdgeschoss"

    def test_known_code_maps_to_standard_hg(self):
        wing = self._wing()
        quick_add_floors(wing, "EG")
        assert wing.floors[0].main_group_number == 2

    def test_unknown_code_gets_generic_name(self):
        wing = self._wing()
        quick_add_floors(wing, "X1")
        assert "X1" in wing.floors[0].name

    def test_multiple_codes_parsed(self):
        wing = self._wing()
        added = quick_add_floors(wing, "UG, EG, OG")
        assert added == 3
        codes = [f.short_code for f in wing.floors]
        assert codes == ["UG", "EG", "OG"]

    def test_skips_existing_code(self):
        wing = self._wing()
        wing.floors.append(Floor(name="Erdgeschoss", short_code="EG", main_group_number=2))
        added = quick_add_floors(wing, "EG, OG")
        assert added == 1
        assert len(wing.floors) == 2
        assert wing.floors[1].short_code == "OG"

    def test_existing_floors_remain(self):
        wing = self._wing()
        wing.floors.append(Floor(name="UG", short_code="UG", main_group_number=1))
        quick_add_floors(wing, "EG")
        assert wing.floors[0].short_code == "UG"
        assert wing.floors[1].short_code == "EG"

    def test_empty_input_adds_nothing(self):
        wing = self._wing()
        added = quick_add_floors(wing, "   ")
        assert added == 0
        assert len(wing.floors) == 0

    def test_duplicate_codes_in_input_added_once(self):
        wing = self._wing()
        added = quick_add_floors(wing, "EG, EG, EG")
        assert added == 1
        assert len(wing.floors) == 1

    def test_standard_floor_names_dict_has_expected_keys(self):
        for code in ("UG", "EG", "OG", "1.OG", "2.OG", "3.OG", "DG"):
            assert code in STANDARD_FLOOR_NAMES

    def test_floor_to_main_group_dict_has_expected_keys(self):
        for code in ("UG", "EG", "OG", "1.OG", "2.OG", "3.OG", "DG"):
            assert code in FLOOR_TO_MAIN_GROUP

    def test_all_standard_hg_numbers_unique(self):
        values = list(FLOOR_TO_MAIN_GROUP.values())
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# FA-3202: Auto-Zone pro Stockwerk
# ---------------------------------------------------------------------------

class TestFA3202AutoZone:
    """Legt automatisch eine Zone pro Stockwerk ohne Zone an."""

    def test_adds_zone_to_empty_floor(self):
        floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
        added = auto_zones([floor])
        assert added == 1
        assert len(floor.apartments) == 1

    def test_zone_name_equals_floor_name(self):
        floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
        auto_zones([floor])
        assert floor.apartments[0].name == "Erdgeschoss"

    def test_skips_floor_with_existing_zone(self):
        floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
        floor.apartments.append(Apartment(name="Wohnung 1"))
        added = auto_zones([floor])
        assert added == 0
        assert len(floor.apartments) == 1

    def test_mixed_floors(self):
        f1 = Floor(name="UG", short_code="UG", main_group_number=1)
        f1.apartments.append(Apartment(name="UG"))  # hat schon Zone
        f2 = Floor(name="EG", short_code="EG", main_group_number=2)  # leer
        f3 = Floor(name="OG", short_code="OG", main_group_number=3)  # leer

        added = auto_zones([f1, f2, f3])
        assert added == 2
        assert len(f1.apartments) == 1  # unveraendert
        assert len(f2.apartments) == 1
        assert len(f3.apartments) == 1

    def test_no_floors_returns_zero(self):
        assert auto_zones([]) == 0


# ---------------------------------------------------------------------------
# FA-3203: Raum klonen – Raumnummer inkrementieren
# ---------------------------------------------------------------------------

class TestFA3203IncrementRoomNumber:
    """Automatisches Inkrementieren der Raumnummer beim Klonen."""

    def test_simple_increment(self):
        assert increment_room_number("E01") == "E02"

    def test_zero_padding_preserved(self):
        assert increment_room_number("E09") == "E10"

    def test_three_digit_number(self):
        assert increment_room_number("E001") == "E002"

    def test_no_prefix(self):
        assert increment_room_number("1") == "2"

    def test_large_number(self):
        assert increment_room_number("O99") == "O100"

    def test_multichar_prefix(self):
        assert increment_room_number("OG01") == "OG02"

    def test_unknown_format_appends_suffix(self):
        result = increment_room_number("Raum")
        assert result == "Raum_2"

    def test_number_only_no_padding(self):
        assert increment_room_number("5") == "6"

    def test_preserves_leading_zeros(self):
        # 01 -> 02 (both 2 digits)
        result = increment_room_number("A01")
        assert result == "A02"
        assert len(result.lstrip("A")) == 2


# ---------------------------------------------------------------------------
# FA-3205: Massenerfassung Raeume aus Textblock
# ---------------------------------------------------------------------------

class TestFA3205BulkRoomParsing:
    """Mehrere Raeume auf einmal aus einem Textblock anlegen."""

    def test_parses_number_and_name(self):
        result = parse_bulk_rooms("E01 Wohnzimmer")
        assert result == [("E01", "Wohnzimmer")]

    def test_ignores_empty_lines(self):
        text = "E01 Wohnzimmer\n\nE02 Schlafzimmer\n\n"
        result = parse_bulk_rooms(text)
        assert len(result) == 2

    def test_number_only_line(self):
        result = parse_bulk_rooms("E01")
        assert result == [("E01", "E01")]

    def test_multiple_rooms(self):
        text = "E01 Wohnzimmer\nE02 Kueche\nE03 Bad"
        result = parse_bulk_rooms(text)
        assert len(result) == 3
        assert result[0] == ("E01", "Wohnzimmer")
        assert result[1] == ("E02", "Kueche")
        assert result[2] == ("E03", "Bad")

    def test_name_with_spaces(self):
        result = parse_bulk_rooms("E01 Kinder zimmer Sued")
        assert result[0] == ("E01", "Kinder zimmer Sued")

    def test_whitespace_only_lines_ignored(self):
        text = "E01 Wohnzimmer\n   \nE02 Bad"
        result = parse_bulk_rooms(text)
        assert len(result) == 2

    def test_empty_input(self):
        assert parse_bulk_rooms("") == []


# ---------------------------------------------------------------------------
# FA-3208: Gewerk-Zuweisung auf alle gleichen Raeume uebertragen
# ---------------------------------------------------------------------------

class TestFA3208ApplyToSameRooms:
    """Gewerke auf alle Raeume mit demselben Namen uebertragen."""

    def _room(self, name: str, codes: list[str] = None) -> Room:
        r = Room(number="X00", name=name)
        for code in (codes or []):
            r.gewerk_assignments.append(GewerkAssignment(gewerk_code=code, count=1))
        return r

    def test_copies_to_same_named_room(self):
        src = self._room("Wohnzimmer", ["L", "J"])
        target = self._room("Wohnzimmer")
        apply_to_same_rooms([src], [src, target])
        assert len(target.gewerk_assignments) == 2
        codes = {ga.gewerk_code for ga in target.gewerk_assignments}
        assert codes == {"L", "J"}

    def test_does_not_affect_different_room(self):
        src = self._room("Wohnzimmer", ["L"])
        other = self._room("Schlafzimmer")
        apply_to_same_rooms([src], [src, other])
        assert len(other.gewerk_assignments) == 0

    def test_does_not_modify_source_room(self):
        src = self._room("Wohnzimmer", ["LD"])
        target = self._room("Wohnzimmer")
        apply_to_same_rooms([src], [src, target])
        # Quelle bleibt unveraendert
        assert len(src.gewerk_assignments) == 1
        assert src.gewerk_assignments[0].gewerk_code == "LD"

    def test_new_assignment_ids_created(self):
        src = self._room("Wohnzimmer", ["L"])
        target = self._room("Wohnzimmer")
        apply_to_same_rooms([src], [src, target])
        assert target.gewerk_assignments[0].id != src.gewerk_assignments[0].id

    def test_multiple_targets_with_same_name(self):
        src = self._room("Buero", ["L", "H"])
        t1 = self._room("Buero")
        t2 = self._room("Buero")
        affected = apply_to_same_rooms([src], [src, t1, t2])
        assert affected == 2
        assert len(t1.gewerk_assignments) == 2
        assert len(t2.gewerk_assignments) == 2

    def test_no_same_named_rooms_returns_zero(self):
        src = self._room("Kueche", ["L"])
        other = self._room("Bad")
        affected = apply_to_same_rooms([src], [src, other])
        assert affected == 0


# ---------------------------------------------------------------------------
# FA-3209: Schnell-Buttons fuer haeufige Gewerke
# ---------------------------------------------------------------------------

class TestFA3209QuickAddGewerk:
    """Gewerk per Schnell-Button zu selektierten Raeumen hinzufuegen."""

    def _room(self, codes: list[str] = None) -> Room:
        r = Room(number="X00", name="Test")
        for code in (codes or []):
            r.gewerk_assignments.append(GewerkAssignment(gewerk_code=code, count=1))
        return r

    def test_adds_gewerk_to_room(self):
        room = self._room()
        quick_add_gewerk([room], "L")
        assert len(room.gewerk_assignments) == 1
        assert room.gewerk_assignments[0].gewerk_code == "L"

    def test_does_not_duplicate_existing_gewerk(self):
        room = self._room(["L"])
        quick_add_gewerk([room], "L")
        assert len(room.gewerk_assignments) == 1

    def test_adds_to_multiple_rooms(self):
        r1 = self._room()
        r2 = self._room()
        added = quick_add_gewerk([r1, r2], "J")
        assert added == 2
        assert r1.gewerk_assignments[0].gewerk_code == "J"
        assert r2.gewerk_assignments[0].gewerk_code == "J"

    def test_skips_room_that_already_has_gewerk(self):
        r1 = self._room(["LD"])
        r2 = self._room()
        added = quick_add_gewerk([r1, r2], "LD")
        assert added == 1
        assert len(r1.gewerk_assignments) == 1

    def test_added_gewerk_has_count_one(self):
        room = self._room()
        quick_add_gewerk([room], "H")
        assert room.gewerk_assignments[0].count == 1

    def test_no_rooms_adds_nothing(self):
        added = quick_add_gewerk([], "L")
        assert added == 0

    def test_quick_gewerk_codes(self):
        """Alle Schnell-Button-Codes (L, LD, J, H, S, V) funktionieren."""
        for code in ("L", "LD", "J", "H", "S", "V"):
            room = Room(number="X00", name="Test")
            quick_add_gewerk([room], code)
            assert room.gewerk_assignments[0].gewerk_code == code


# ---------------------------------------------------------------------------
# FA-3210: Erweiterte Gebaeudevorlagen
# ---------------------------------------------------------------------------

class TestFA3210BuildingTemplates:
    """Erweiterte Vorlagen: EFH Klein, Chalet, Hotel klein."""

    def test_efh_klein_template_exists(self):
        areal = BuildingService.load_template("efh_klein")
        assert areal is not None

    def test_chalet_template_exists(self):
        areal = BuildingService.load_template("chalet")
        assert areal is not None

    def test_hotel_klein_template_exists(self):
        areal = BuildingService.load_template("hotel_klein")
        assert areal is not None

    def test_efh_klein_has_floors(self):
        areal = BuildingService.load_template("efh_klein")
        assert len(areal.all_floors) >= 2

    def test_chalet_has_floors(self):
        areal = BuildingService.load_template("chalet")
        assert len(areal.all_floors) >= 2

    def test_hotel_klein_has_floors(self):
        areal = BuildingService.load_template("hotel_klein")
        assert len(areal.all_floors) >= 1

    def test_efh_klein_has_rooms(self):
        areal = BuildingService.load_template("efh_klein")
        assert len(areal.all_rooms) >= 1

    def test_chalet_has_rooms(self):
        areal = BuildingService.load_template("chalet")
        assert len(areal.all_rooms) >= 1

    def test_all_templates_have_unique_floor_codes(self):
        for tmpl_id in ("efh_klein", "chalet", "hotel_klein"):
            areal = BuildingService.load_template(tmpl_id)
            codes = [f.short_code for f in areal.all_floors]
            assert len(codes) == len(set(codes)), \
                f"Vorlage '{tmpl_id}' hat doppelte Stockwerk-Codes: {codes}"


# ---------------------------------------------------------------------------
# FA-3211: Wizard-Schritt-Statusanzeige (Tooltip-Logik)
# ---------------------------------------------------------------------------

class TestFA3211StepTooltips:
    """Dynamische Tooltips der Wizard-Schritt-Buttons."""

    def _project_with(self, n_floors=1, n_zones=1, n_rooms=2):
        from knix_arranger.models.project import KnxProject
        project = KnxProject(name="Tooltip Test")
        areal = project.areal
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        for i in range(n_floors):
            floor = Floor(name=f"Stockwerk {i}", short_code=f"S{i}", main_group_number=i + 1)
            for j in range(n_zones):
                apt = Apartment(name=f"Zone {j}")
                for k in range(n_rooms):
                    apt.rooms.append(Room(number=f"R{k:02d}", name=f"Raum {k}"))
                floor.apartments.append(apt)
            wing.floors.append(floor)
        building.wings.append(wing)
        areal.buildings.append(building)
        return project

    def test_step0_single_floor(self):
        p = self._project_with(n_floors=1)
        tooltip = step_tooltip(p, 0)
        assert "1 Stockwerk" in tooltip
        assert "Stockwerke" not in tooltip

    def test_step0_multiple_floors(self):
        p = self._project_with(n_floors=3)
        tooltip = step_tooltip(p, 0)
        assert "3 Stockwerke" in tooltip

    def test_step1_zones_count(self):
        # 2 Stockwerke x 2 Zonen = 4 Zonen
        p = self._project_with(n_floors=2, n_zones=2)
        tooltip = step_tooltip(p, 1)
        assert "4 Zonen" in tooltip

    def test_step1_single_zone(self):
        p = self._project_with(n_floors=1, n_zones=1)
        tooltip = step_tooltip(p, 1)
        assert "1 Zone" in tooltip
        assert "Zonen" not in tooltip

    def test_step2_rooms_count(self):
        # 1 Stockwerk, 1 Zone, 5 Raeume
        p = self._project_with(n_floors=1, n_zones=1, n_rooms=5)
        tooltip = step_tooltip(p, 2)
        assert "5" in tooltip

    def test_step4_gewerk_assignments(self):
        p = self._project_with(n_floors=1, n_zones=1, n_rooms=2)
        rooms = p.all_rooms
        rooms[0].gewerk_assignments.append(GewerkAssignment(gewerk_code="L", count=1))
        rooms[0].gewerk_assignments.append(GewerkAssignment(gewerk_code="J", count=1))
        tooltip = step_tooltip(p, 4)
        assert "2 Gewerk-Zuweisungen" in tooltip

    def test_step4_single_gewerk_assignment(self):
        p = self._project_with(n_floors=1, n_zones=1, n_rooms=1)
        rooms = p.all_rooms
        rooms[0].gewerk_assignments.append(GewerkAssignment(gewerk_code="L", count=1))
        tooltip = step_tooltip(p, 4)
        assert "1 Gewerk-Zuweisung" in tooltip
        assert "Zuweisungen" not in tooltip

    def test_step0_empty_project(self):
        from knix_arranger.models.project import KnxProject
        p = KnxProject(name="Leer")
        tooltip = step_tooltip(p, 0)
        assert "0" in tooltip
