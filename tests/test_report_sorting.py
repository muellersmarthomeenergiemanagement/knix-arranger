"""Tests fuer die einheitliche Sortierung in Berichten."""
from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.scene import Scene
from knix_arranger.models.project import KnxProject
from knix_arranger.services.report_service import ReportService
from knix_arranger.services.report_sorting import (
    group_address_key, physical_address_key, sorted_rooms,
)


def _areal():
    """Stockwerke in Gebaeude-Reihenfolge, deren Namen alphabetisch anders
    sortieren wuerden (Dachgeschoss < Erdgeschoss < ... < Untergeschoss)."""
    def floor(name, code, rooms):
        return Floor(name=name, short_code=code, apartments=[Apartment(name=code, rooms=rooms)])
    floors = [
        floor("Untergeschoss", "UG", [Room(number="02", name="Keller"), Room(number="01", name="Technik")]),
        floor("Erdgeschoss", "EG", [Room(number="", name="Verteiler"), Room(number="10", name="Wohnen"),
                                    Room(number="9", name="Bad")]),
        floor("Dachgeschoss", "DG", [Room(number="01", name="Schlafen")]),
    ]
    return Areal(buildings=[Building(wings=[Wing(floors=floors)])])


def test_rooms_in_building_order():
    names = [r.name for r in sorted_rooms(_areal())]
    assert names == ["Technik", "Keller", "Bad", "Wohnen", "Verteiler", "Schlafen"]


def test_address_keys_numeric_and_invalid_last():
    addrs = ["1.1.10", "", "1.1.9", "1.2.1", "1.1.-"]
    assert sorted(addrs, key=physical_address_key) == ["1.1.9", "1.1.10", "1.2.1", "", "1.1.-"]
    gas = ["2/0/10", "2/0/9", "", "1/7/255"]
    assert sorted(gas, key=group_address_key) == ["1/7/255", "2/0/9", "2/0/10", ""]


def test_scenes_sorted_by_scope_then_building_order():
    project = KnxProject(name="Test")
    project.areal = _areal()
    rooms = {r.name: r for r in project.all_rooms}
    scenes = [
        Scene(name="Schlafen 1", scope="room", scope_id=rooms["Schlafen"].id, scene_number=1),
        Scene(name="Technik 2", scope="room", scope_id=rooms["Technik"].id, scene_number=2),
        Scene(name="Zentral", scope="central", scene_number=5),
        Scene(name="Technik 1", scope="room", scope_id=rooms["Technik"].id, scene_number=1),
    ]
    key = ReportService(project)._scene_sort_key()
    assert [s.name for s in sorted(scenes, key=key)] == ["Zentral", "Technik 1", "Technik 2", "Schlafen 1"]
