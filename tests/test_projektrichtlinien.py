"""Abgleich mit den KNX-Swiss-Projektrichtlinien 2024: Variante B (MG 6/7 nur
Rückmeldungen, 13.2), parallele Spannungsversorgungen (8.2.1), IP-Topologie
(4.1, 4.2)."""
from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.gewerk import GewerkCatalog
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.services.report_service import VALIDATION_RULES
from knix_arranger.services.secure_checks import check_secure
from knix_arranger.services.topology_validation import check_topology
from knix_arranger.services.validation_engine import ValidationEngine


def _catalog():
    catalog = GewerkCatalog()
    catalog.load_defaults()
    return catalog


def _areal(*codes):
    room = Room(number="E01", name="Wohnen")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code=c, count=1) for c in codes]
    floor = Floor(name="EG", short_code="EG", main_group_number=2,
                  apartments=[Apartment(name="EG", rooms=[room])])
    return Areal(name="T", buildings=[Building(name="H", wings=[Wing(name="W", floors=[floor])])])


def _mgs(structure, code):
    return {ga.middle_group for ga in structure.all_addresses()
            if ga.gewerk_code == code and not ga.is_placeholder}


def test_variante_b_mg6_und_7_nur_rueckmeldungen():
    structure = AddressGenerator(_catalog(), variant="B").generate(
        _areal("LD", "J", "PV", "EV", "SP"))
    for code in ("PV", "EV", "SP"):
        assert _mgs(structure, code) == {5}
    assert _mgs(structure, "LD") == {0, 6} and _mgs(structure, "J") == {1, 7}


def test_variante_a_unveraendert():
    structure = AddressGenerator(_catalog(), variant="A").generate(_areal("LD", "PV"))
    assert _mgs(structure, "PV") == {6} and _mgs(structure, "LD") == {0}


def _structure(variant, *gas):
    by_mg = {}
    for mg, code in gas:
        by_mg.setdefault(mg, []).append(GroupAddress(
            main_group=2, middle_group=mg, sub_group=len(by_mg[mg]) if mg in by_mg else 0,
            gewerk_code=code, designation=f"{code}_E01_01"))
    return GroupAddressStructure(variant=variant, main_groups=[MainGroup(
        number=2, middle_groups=[MiddleGroup(number=mg, group_addresses=g)
                                 for mg, g in by_mg.items()])])


def test_fa607_fremdes_gewerk_in_rueckmeldungs_mg_bei_variante_b():
    engine = ValidationEngine(_catalog())
    issues = engine._check_middle_group_assignment(
        _structure("B", (6, "PV"), (6, "LD"), (7, "LD")).all_addresses(), "B")
    assert [(i.address, i.details["expected"]) for i in issues] == [("2/6/0", 5)]
    # Variante A: PV in MG 6 ist richtig
    assert engine._check_middle_group_assignment(
        _structure("A", (6, "PV")).all_addresses(), "A") == []


def _supply(address, product):
    return Device(physical_address=address, device_type="power_supply", product=product)


def test_parallele_spannungsversorgungen_ueber_1280_ma():
    project = KnxProject(name="SV")
    project.topology.areas = [Area(area_number=1, lines=[
        Line(line_number=1, devices=[_supply("1.1.-", "Spannungsversorgung 1280mA"),
                                     _supply("1.1.-", "Spannungsversorgung 1280mA"),
                                     Device(physical_address="1.1.1", device_type="actor")]),
        Line(line_number=2, devices=[_supply("1.2.-", "Spannungsversorgung 640mA"),
                                     _supply("1.2.-", "Spannungsversorgung 640mA"),
                                     Device(physical_address="1.2.1", device_type="actor")]),
    ])]
    issues = [i for i in check_topology(project) if i.rule_id == "FA-613c"]
    assert [(i.address, i.details["supply_ma"]) for i in issues] == [("1.1", 2560)]


def _coupler(address, product, secure=False):
    return Device(physical_address=address, device_type="coupler", product=product,
                  secure_supported=secure)


def test_ip_router_ohne_secure_hinweis():
    project = KnxProject(name="IP")
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1, devices=[
        _coupler("1.1.0", "KNX IP Router"), _coupler("1.2.0", "LK/S4.2.1")])])]
    issues = check_secure(project)
    assert [(i.rule_id, i.level, i.address) for i in issues] == [("FA-645d", "info", "1.1.0")]
    project.topology.areas[0].lines[0].devices[0].secure_supported = True
    assert check_secure(project) == []


def test_ip_linienkoppler_unter_ip_bereichskoppler():
    project = KnxProject(name="IP")
    project.topology.areas = [Area(area_number=1, lines=[
        Line(line_number=0, devices=[_coupler("1.0.0", "KNX IP Router", True)]),
        Line(line_number=1, devices=[_coupler("1.1.0", "KNX IP Router", True)]),
        Line(line_number=2, devices=[_coupler("1.2.0", "LK/S4.2.1")]),
    ])]
    issues = [i for i in check_topology(project) if i.rule_id == "FA-646"]
    assert [i.address for i in issues] == ["1.1.0"]


def test_regeln_beschrieben():
    assert {"FA-613c", "FA-645d", "FA-646"} <= set(VALIDATION_RULES)
