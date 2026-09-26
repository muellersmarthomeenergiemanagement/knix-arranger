"""Tests fuer die Gewerk-Zaehlung aus gesteuerten Elementen der Topologie."""
from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.channel_count_service import (
    count_controlled_elements, apply_element_counts,
)
from knix_arranger.services.gewerk_service import GewerkService


def _project(gas, devices, rooms):
    project = KnxProject(name="Import")
    floor = Floor(name="EG", short_code="EG", main_group_number=2)
    floor.apartments = [Apartment(name="", rooms=rooms)]
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    structure = GroupAddressStructure()
    hg = MainGroup(number=2, name="EG")
    mg = MiddleGroup(number=2, name="Heizung")
    mg.group_addresses.extend(gas)
    hg.middle_groups.append(mg)
    structure.main_groups.append(hg)
    project.group_addresses = structure
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1, devices=devices)])]
    return project


def _ga(sub, designation):
    return GroupAddress(main_group=2, middle_group=2, sub_group=sub, designation=designation)


def _device(addr, device_type, *ga_addresses):
    return Device(physical_address=addr, device_type=device_type, communication_objects=[
        CommunicationObject(object_number=i, name=f"Kanal {i + 1}", connected_gas=[a])
        for i, a in enumerate(ga_addresses)
    ])


def test_nur_von_aktoren_gesteuerte_elemente_zaehlen():
    halle = Room(number="00", name="Halle")
    garage = Room(number="02", name="Garage")
    gas = [
        _ga(0, "H.EG.00.1_ea ( Halle )"),
        _ga(1, "H.EG.00.1_status Ventil ( Halle )"),
        _ga(2, "H.EG.00.1_ist Temp ( Halle )"),        # nur Fuehler
        _ga(10, "H.EG.02.1_ea ( Garage )"),             # ohne Aktor
        _ga(20, "H.EG.02.01+H.EG.03.01_ea ( Garage / Werkstatt )"),
    ]
    devices = [
        _device("1.1.1", "actor", "2/2/0", "2/2/1", "2/2/20"),
        _device("1.1.2", "sensor", "2/2/2", "2/2/10"),
    ]
    counts = count_controlled_elements(_project(gas, devices, [halle, garage]))

    assert counts.by_room[halle.id]["H"] == 1
    assert counts.by_room[garage.id]["H"] == 1          # kombinierte GA = ein Element
    assert counts.totals()["H"] == 2


def test_fehlender_raum_wird_gemeldet():
    gas = [_ga(0, "H.EG.04.1_ea ( Eingang )")]
    counts = count_controlled_elements(
        _project(gas, [_device("1.1.1", "actor", "2/2/0")], [Room(number="00")]))
    assert counts.unassigned["H"] == 1
    assert counts.missing_rooms == {"EG 04": {"H": 1}}


def test_anzahl_uebernehmen_behaelt_zuweisung():
    halle = Room(number="00", name="Halle")
    studio = Room(number="06", name="Studio")
    kept = GewerkAssignment(gewerk_code="H", count=3, taster_indices=[2])
    halle.gewerk_assignments = [kept]
    studio.gewerk_assignments = [GewerkAssignment(gewerk_code="H", count=1)]
    gas = [_ga(0, "H.EG.00.1_ea"), _ga(1, "H.EG.00.2_ea")]
    project = _project(gas, [_device("1.1.1", "actor", "2/2/0", "2/2/1")], [halle, studio])

    counts = count_controlled_elements(project)
    preview = apply_element_counts(project.areal, counts, dry_run=True)
    assert preview == ["EG 00 Halle: H 3 → 2", "EG 06 Studio: H 1 → 0"]
    assert kept.count == 3                               # dry_run aendert nichts

    apply_element_counts(project.areal, counts)
    assert halle.gewerk_assignments == [kept]
    assert kept.count == 2 and kept.taster_indices == [2]
    assert studio.gewerk_assignments == []


def test_kombinierte_adressierung_mit_vollem_namen():
    matched = GewerkService._match_ga_designation("H.EG.02.01+H.EG.03.01_ea")
    assert matched is not None and matched[4] is True
