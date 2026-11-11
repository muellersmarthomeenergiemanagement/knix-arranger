"""
Positionsnummern der Bedienelemente «E05-01» (Projektrichtlinien 10.7, FA-1404b).
"""
from __future__ import annotations

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.position_numbers import (
    PositionLabels, assign_position_numbers, room_part,
)
from knix_arranger.services.sensor_service import _inherit


def _project(imported=False):
    korridor = Room(number="E05", name="Korridor", bedienelemente=[
        Bedienelement(element_type="Tastereinheit"),
        Bedienelement(element_type="Tastereinheit", participant_number="1.1.12"),
        Bedienelement(element_type="Präsenzmelder", participant_number="1.1.13")])
    schlafen = Room(number="04", name="Schlafen", bedienelemente=[
        Bedienelement(element_type="Tastereinheit", participant_number="1.1.20"),
        Bedienelement(element_type="Tastereinheit", participant_number="1.1.20")])
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="Erdgeschoss", short_code="EG", apartments=[Apartment(rooms=[korridor])]),
        Floor(name="Dachgeschoss", short_code="DG", apartments=[Apartment(rooms=[schlafen])]),
    ])])])
    project.topology = Topology(is_imported=imported, areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[
            Device(device_type="sensor", physical_address="1.1.12",
                   product="Tasterschnittstelle 4-fach"),
            Device(device_type="sensor", physical_address="1.1.13", product="Präsenzmelder"),
            Device(device_type="sensor", physical_address="1.1.20", product="Taster 2-fach"),
        ])])])
    return project, korridor, schlafen


def test_room_part_like_ga_label():
    project, korridor, schlafen = _project()
    eg, dg = project.all_floors
    assert room_part(eg, korridor) == "E05"          # Buchstaben: ohne Stockwerk
    assert room_part(dg, schlafen) == "DG_04"        # Nummer je Stockwerk


def test_assigned_once_per_room_and_stable():
    project, korridor, schlafen = _project()
    assert assign_position_numbers(project) == 5
    assert [be.position_index for be in korridor.bedienelemente] == [1, 2, 3]
    assert [be.position_index for be in schlafen.bedienelemente] == [1, 2]
    assert assign_position_numbers(project) == 0

    # gelöscht: nichts rückt nach, neues Element erhält die nächste Nummer
    del korridor.bedienelemente[0]
    korridor.bedienelemente.append(Bedienelement(element_type="Tastereinheit"))
    assign_position_numbers(project)
    assert [be.position_index for be in korridor.bedienelemente] == [2, 3, 4]


def test_moved_element_with_same_number_gets_new_one():
    project, korridor, schlafen = _project()
    assign_position_numbers(project)
    moved = schlafen.bedienelemente.pop(0)           # Nummer 1 in Schlafen
    korridor.bedienelemente.append(moved)            # Korridor hat 1 schon
    assign_position_numbers(project)
    assert [be.position_index for be in korridor.bedienelemente] == [1, 2, 3, 4]


def test_imported_project_gets_none():
    project, korridor, _schlafen = _project(imported=True)
    assert assign_position_numbers(project) == 0
    assert all(not be.position_index for be in korridor.bedienelemente)
    assert PositionLabels(project).reference(korridor, korridor.bedienelemente[1]) == "1.1.12"


def test_shown_where_the_address_does_not_identify_the_button():
    project, korridor, schlafen = _project()
    assign_position_numbers(project)
    labels = PositionLabels(project)
    ohne, schnittstelle, melder = korridor.bedienelemente
    assert labels.reference(korridor, ohne) == "E05-01"
    assert labels.reference(korridor, schnittstelle) == "1.1.12 · E05-02"
    assert labels.reference(korridor, melder) == "1.1.13"         # eigene Adresse
    assert labels.reference(schlafen, schlafen.bedienelemente[1]) == "1.1.20 · DG_04-02"


def test_saved_and_inherited():
    be = Bedienelement(element_type="Tastereinheit", position_index=3)
    assert Bedienelement.from_dict(be.to_dict()).position_index == 3
    fresh = Bedienelement(element_type="Tastereinheit")
    _inherit(fresh, be)
    assert fresh.position_index == 3


def test_views_always_show_the_position():
    """Gebäudeansicht und Bauherrenberatung: Positionsnummer auch neben einer
    eindeutigen Adresse (zum Beschriften der Pläne); aus Areal + Topologie."""
    project, korridor, _schlafen = _project()
    assign_position_numbers(project)
    labels = PositionLabels(areal=project.areal, topology=project.topology)
    melder = korridor.bedienelemente[2]
    assert labels.reference(korridor, melder) == "1.1.13"
    assert labels.reference(korridor, melder, always=True) == "1.1.13 · E05-03"
    imported, korridor, _ = _project(imported=True)
    assert PositionLabels(imported).reference(
        korridor, korridor.bedienelemente[2], always=True) == "1.1.13"


def test_numbered_when_added_by_hand():
    from knix_arranger.services.button_move import add_bedienelement
    _project_, korridor, _ = _project()
    assign_position_numbers(_project_)
    be = add_bedienelement(korridor, "Tastereinheit", 4)
    assert be.position_index == 4
