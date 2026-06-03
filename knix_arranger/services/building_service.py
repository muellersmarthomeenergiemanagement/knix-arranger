"""
Gebäudestruktur erstellen und verwalten (FA-101 bis FA-107)
"""
from __future__ import annotations
import json
import os

from ..models.building import (
    Areal, Building, Wing, Floor, Apartment, Room,
    GewerkAssignment, STANDARD_FLOOR_NAMES, FLOOR_TO_MAIN_GROUP,
)


class BuildingService:
    """Service für Gebäudestruktur-Verwaltung."""

    @staticmethod
    def create_default_areal(name: str = "") -> Areal:
        """Erstellt ein leeres Areal mit einem Gebäude."""
        areal = Areal(name=name)
        building = Building(name=name or "Gebäude 1")
        wing = Wing(name="Hauptgebäude")
        building.wings.append(wing)
        areal.buildings.append(building)
        return areal

    @staticmethod
    def add_floor(wing: Wing, name: str, short_code: str,
                  main_group: int = -1) -> Floor:
        """Fügt ein Stockwerk hinzu."""
        if main_group == -1:
            main_group = FLOOR_TO_MAIN_GROUP.get(short_code, len(wing.floors) + 1)
        floor = Floor(name=name, short_code=short_code, main_group_number=main_group)
        # Fuer EFH: Standard-Wohnung/Zone erstellen (FA-107)
        default_apt = Apartment(name=short_code)
        floor.apartments.append(default_apt)
        wing.floors.append(floor)
        return floor

    @staticmethod
    def add_apartment(floor: Floor, name: str) -> Apartment:
        """Fügt eine Wohnung/Zone zu einem Stockwerk hinzu."""
        apt = Apartment(name=name)
        floor.apartments.append(apt)
        return apt

    @staticmethod
    def add_room(apartment: Apartment, number: str, name: str) -> Room:
        """Fügt einen Raum zu einer Wohnung/Zone hinzu."""
        room = Room(number=number, name=name)
        apartment.rooms.append(room)
        return room

    @staticmethod
    def add_gewerk(room: Room, gewerk_code: str, count: int = 1) -> GewerkAssignment:
        """Weist einem Raum ein Gewerk zu (FA-301, FA-304)."""
        assignment = GewerkAssignment(gewerk_code=gewerk_code, count=count)
        room.gewerk_assignments.append(assignment)
        return assignment

    @staticmethod
    def remove_floor(wing: Wing, floor_id: str):
        wing.floors = [f for f in wing.floors if f.id != floor_id]

    @staticmethod
    def remove_apartment(floor: Floor, apartment_id: str):
        floor.apartments = [a for a in floor.apartments if a.id != apartment_id]

    @staticmethod
    def remove_room(apartment: Apartment, room_id: str):
        apartment.rooms = [r for r in apartment.rooms if r.id != room_id]

    @staticmethod
    def assign_main_groups(areal: Areal):
        """Weist Hauptgruppen automatisch zu (FA-411).
        Stellt sicher, dass jedes Stockwerk eine eindeutige HG-Nummer bekommt.
        """
        used_numbers: set[int] = set()

        # Erst alle bereits vergebenen Nummern sammeln
        for floor in areal.all_floors:
            if floor.main_group_number > 0:
                used_numbers.add(floor.main_group_number)

        # Dann fehlende Nummern vergeben
        next_free = 1
        for building in areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    if floor.main_group_number <= 0:
                        while next_free in used_numbers:
                            next_free += 1
                        floor.main_group_number = next_free
                        used_numbers.add(next_free)
                        next_free += 1

        # Duplikate auflösen: Falls durch manuelle Zuweisung Duplikate
        # entstanden sind, werden diese korrigiert.
        seen: dict[int, bool] = {}
        for building in areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    if floor.main_group_number in seen:
                        while next_free in used_numbers:
                            next_free += 1
                        floor.main_group_number = next_free
                        used_numbers.add(next_free)
                        next_free += 1
                    else:
                        seen[floor.main_group_number] = True

    @staticmethod
    def list_templates() -> list[tuple[str, str, str]]:
        """Gibt alle verfügbaren Gebäudevorlagen zurück als [(id, name, description), ...]."""
        config_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
        )
        filepath = os.path.join(config_dir, "building_templates.json")
        if not os.path.exists(filepath):
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [
            (t["id"], t.get("name", t["id"]), t.get("description", ""))
            for t in data.get("templates", [])
        ]

    @staticmethod
    def load_template(template_id: str) -> Areal | None:
        """Lädt eine Gebäudestruktur-Vorlage (FA-104)."""
        config_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
        )
        filepath = os.path.join(config_dir, "building_templates.json")
        if not os.path.exists(filepath):
            return None

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        for tmpl in data.get("templates", []):
            if tmpl["id"] == template_id:
                return BuildingService._template_to_areal(tmpl)
        return None

    @staticmethod
    def _template_to_areal(tmpl: dict) -> Areal:
        areal = Areal(name=tmpl["name"])
        building = Building(name=tmpl["name"])
        wing = Wing(name="Hauptgebäude")

        for fl_data in tmpl.get("floors", []):
            floor = Floor(
                name=fl_data["name"],
                short_code=fl_data["short_code"],
                main_group_number=fl_data.get("main_group", -1),
            )
            for apt_data in fl_data.get("apartments", []):
                apt = Apartment(name=apt_data["name"])
                for rm_data in apt_data.get("rooms", []):
                    room = Room(
                        number=rm_data["number"],
                        name=rm_data["name"],
                    )
                    apt.rooms.append(room)
                floor.apartments.append(apt)
            wing.floors.append(floor)

        building.wings.append(wing)
        areal.buildings.append(building)
        return areal

    @staticmethod
    def get_all_rooms_by_floor(areal: Areal) -> dict[str, list[Room]]:
        """Gibt alle Räume gruppiert nach Stockwerk-ID zurück."""
        result: dict[str, list[Room]] = {}
        for floor in areal.all_floors:
            result[floor.id] = floor.all_rooms
        return result

    @staticmethod
    def find_room_by_id(areal: Areal, room_id: str) -> Room | None:
        for room in areal.all_rooms:
            if room.id == room_id:
                return room
        return None

    @staticmethod
    def find_floor_for_room(areal: Areal, room_id: str) -> Floor | None:
        for floor in areal.all_floors:
            for room in floor.all_rooms:
                if room.id == room_id:
                    return floor
        return None
