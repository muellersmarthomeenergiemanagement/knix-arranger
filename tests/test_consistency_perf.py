"""
Zusammenhänge und Leistung (Release nach 1.4.0): KO-Varianten zentral,
Flags beim Laden vereinheitlicht, KNX-Secure-Spalte als Delegate,
Sofortprüfung gesammelt.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.topology import CommunicationObject, normalize_flags
from knix_arranger.services.ko_links import co_by_number, co_holding, parse_flags


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _variants():
    return [
        CommunicationObject(object_number=2, name="GO0002", object_function="{{0:GO}}",
                            flags="KLSÜA-", connected_gas=["1/1/0"]),
        CommunicationObject(object_number=2, name="GO0002",
                            object_function="Operation of Blinds (M1), End position",
                            flags="K-S---"),
    ]


def test_co_by_number_prefers_real_variant():
    cos = _variants()
    assert co_by_number(cos, 2) is cos[1]
    assert co_by_number(cos, 99) is None


def test_co_holding_finds_variant_with_ga():
    cos = _variants()
    assert co_holding(cos, 2, "1/1/0") is cos[0]      # dort hängt die GA
    assert co_holding(cos, 2, "9/9/9") is cos[1]      # sonst die echte


@pytest.mark.parametrize("old, new", [
    ("K-Ü--", "K-S---"), ("KL-S-", "KL-Ü--"), ("K-ÜSU", "K-SÜA-"),
    ("K-S---", "K-S---"), ("KSUA", "KSUA"), ("", ""),
])
def test_old_product_flags_normalized(old, new):
    assert normalize_flags(old) == new
    assert parse_flags(old) == parse_flags(new)


def test_flags_normalized_on_load():
    co = CommunicationObject.from_dict({"object_number": 1, "flags": "K-Ü--"})
    assert co.flags == "K-S---"


def test_secure_view_security_column_without_cell_widgets():
    from knix_arranger.models.group_address import (
        GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
    )
    from knix_arranger.models.project import KnxProject
    from knix_arranger.ui.views.knx_secure_view import KnxSecureView, _COL_GA_SEC
    project = KnxProject(name="Secure")
    ga = GroupAddress(main_group=1, middle_group=0, sub_group=0, designation="L E/A")
    project.group_addresses = GroupAddressStructure(main_groups=[
        MainGroup(number=1, middle_groups=[MiddleGroup(number=0, group_addresses=[ga])])])
    view = KnxSecureView(project)
    view.set_project(project)
    table = view._ga_table
    assert table.cellWidget(0, _COL_GA_SEC) is None
    item = table.item(0, _COL_GA_SEC)
    assert item.text() == ga.security
    item.setText("Ein")
    assert ga.security == "Ein"



def _planned(gewerk_catalog):
    from knix_arranger.models.building import (
        Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
    )
    from knix_arranger.models.project import KnxProject
    from knix_arranger.services.address_generator import regenerate_addresses
    from knix_arranger.services.recalc_service import RecalcService
    from knix_arranger.services.sensor_service import refresh_bedienelemente
    from knix_arranger.services.topology_engine import TopologyEngine
    room = Room(number="CDG02", name="Schlafzimmer",
                gewerk_assignments=[GewerkAssignment(gewerk_code="J", count=2),
                                    GewerkAssignment(gewerk_code="H", count=1)])
    other = Room(number="CDG03", name="Ankleide",
                 gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)])
    project = KnxProject(name="Konsistenz")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[Floor(
        name="DG", short_code="DG", main_group_number=1,
        apartments=[Apartment(name="Wohnung", rooms=[room, other])])])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    regenerate_addresses(project)

    def recompute():
        # wie das Hauptfenster (_on_functions_changed)
        RecalcService().recalc_actors_and_addresses(project)
        refresh_bedienelemente(project)
    recompute()
    return project, room, recompute


def _rule(project, rule):
    from knix_arranger.services.validation_engine import ValidationEngine
    return [i for i in ValidationEngine(project.gewerk_catalog).validate(
        project.group_addresses, project) if i.rule_id == rule]


def test_leftover_device_and_double_operation(gewerk_catalog):
    from knix_arranger.models.building import SensorFunktion
    from knix_arranger.services.button_move import add_bedienelement
    project, room, recompute = _planned(gewerk_catalog)
    assert _rule(project, "FA-631") == [] and _rule(project, "FA-632") == []
    second = add_bedienelement(room, "Tastereinheit", 2)
    recompute()
    assert [i.address for i in _rule(project, "FA-631")] == [second.participant_number]
    second.funktionen.append(SensorFunktion(gewerk_code="J", element_number=1))
    recompute()
    double = _rule(project, "FA-632")
    assert len(double) == 1 and second.participant_number in double[0].message
    assert _rule(project, "FA-631") == []


def test_melder_without_ga(gewerk_catalog):
    """FA-633: Melder mit Gerät, aber ohne GA -- Hinweis; eine GA am KO
    genügt. Rauch- und Wassermelder bekommen seit 2026-10-18 ein Element im
    Gewerk A (test_detector_adoption), daher hier ein Präsenzmelder."""
    from knix_arranger.models.topology import CommunicationObject
    from knix_arranger.services.button_move import add_bedienelement
    project, room, recompute = _planned(gewerk_catalog)
    melder = add_bedienelement(room, "Präsenzmelder", 1)
    recompute()
    assert [i.address for i in _rule(project, "FA-633")] == [melder.participant_number]
    assert _rule(project, "FA-631") == []
    device = next(d for a in project.topology.areas for l in a.lines for d in l.devices
                  if d.physical_address == melder.participant_number)
    device.communication_objects = [CommunicationObject(
        object_number=0, name="Alarm", connected_gas=["1/0/0"])]
    assert _rule(project, "FA-633") == []


def test_rauchmelder_bekommt_ga(gewerk_catalog):
    """Projekt_23 CUG02: ein in der Bauherrenberatung hinzugefügter
    Rauchmelder bekommt sein Element im Gewerk A und damit GAs."""
    from knix_arranger.services.button_move import add_bedienelement
    project, room, recompute = _planned(gewerk_catalog)
    melder = add_bedienelement(room, "Rauchmelder", 1)
    recompute()
    found = _rule(project, "FA-633")
    assert all("Schritt 10" in i.suggestion for i in found)
    recompute()                                    # GA-Generierung
    assert _rule(project, "FA-633") == []
    assert any(a.gewerk_code == "A" for a in room.gewerk_assignments)
    assert melder.function_assignments


def test_new_device_goes_to_end_and_others_keep_address(gewerk_catalog):
    from knix_arranger.services.button_move import add_bedienelement
    project, room, recompute = _planned(gewerk_catalog)

    def addresses():
        return {d.id: d.physical_address for a in project.topology.areas
                for l in a.lines for d in l.devices}
    before = addresses()
    add_bedienelement(project.all_rooms[0], "Tastereinheit", 2)
    recompute()
    after = addresses()
    assert all(after[k] == v for k, v in before.items() if k in after)
    new = [v for k, v in after.items() if k not in before]
    assert len(new) == 1
    sensors = [int(v.split(".")[2]) for v in after.values() if v.split(".")[2].isdigit()
               and int(v.split(".")[2]) > 100]
    assert int(new[0].split(".")[2]) == max(sensors)
