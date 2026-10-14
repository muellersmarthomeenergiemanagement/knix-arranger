"""GA-Übersicht: Gewerke, Aktoren und Bedienung je Gruppenadresse.

Projekt_23: L «Deckenlicht» am Schaltaktor, bedient von einem Taster;
Gewerk A gehört dem Bewegungsmelder (kein Aktor); Szenen-GA 0/4/1 wirkt auf
die Gewerke der Stromkreise ihrer Aktoren; das Revox-Gateway (MM, gemeinsam)
bedient auch Räume anderer Linien.
"""
import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, FunctionAssignment,
    GewerkAssignment, Room, SensorFunktion, Wing,
)
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line
from knix_arranger.services.belegungsplan_service import BelegungsplanService
from knix_arranger.services.ga_links import ga_links
from knix_arranger.services.report_service import ReportService


def _ga(main, middle, sub, designation, gewerk="", room=None, element=0,
        function="", assignment=None, central="", placeholder=False):
    return GroupAddress(
        main_group=main, middle_group=middle, sub_group=sub, designation=designation,
        gewerk_code=gewerk, room_id=room.id if room else "",
        room_number=room.number if room else "", element_number=element,
        function_name=function, assignment_id=assignment.id if assignment else "",
        central=central, datapoint_type="DPST-1-1", is_placeholder=placeholder)


def _project():
    waschen = Room(number="CUG01", name="Waschen")
    licht = GewerkAssignment(gewerk_code="L", count=1)
    alarm = GewerkAssignment(gewerk_code="A", count=1)
    waschen.gewerk_assignments = [licht, alarm]
    waschen.bedienelemente = [
        Bedienelement(element_type="Tastereinheit", participant_number="1.2.101",
                      is_auto=False, funktionen=[SensorFunktion(gewerk_code="L",
                                                                element_number=1)],
                      function_assignments=[FunctionAssignment(
                          button_channel="Taste 1",
                          function_ga="L_CUG01_01 E/A (Waschen Deckenlicht)")]),
        Bedienelement(element_type="Bewegungsmelder", participant_number="1.2.105",
                      is_auto=False, funktionen=[SensorFunktion(gewerk_code="A",
                                                                element_number=1)]),
    ]
    wohnen = Room(number="COG04", name="Wohnen")
    multimedia = GewerkAssignment(gewerk_code="MM", count=1)
    wohnen.gewerk_assignments = [multimedia]

    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="UG", short_code="UG", main_group_number=4,
              apartments=[Apartment(name="Wohnung", rooms=[waschen])]),
        Floor(name="OG", short_code="OG", main_group_number=2,
              apartments=[Apartment(name="Wohnung", rooms=[wohnen])]),
    ])])])
    project.topology.areas = [Area(area_number=1, lines=[
        Line(line_number=2, assigned_room_ids=[waschen.id], devices=[
            Device(physical_address="1.2.13", device_type="actor",
                   product="Schaltaktor 4-fach"),
            Device(physical_address="1.2.9", device_type="gateway",
                   product="KNX-Schnittstelle"),
            Device(physical_address="1.2.101", device_type="sensor",
                   product="Tastereinheit", room_id=waschen.id),
            Device(physical_address="1.2.105", device_type="sensor",
                   product="Bewegungsmelder", room_id=waschen.id,
                   manufacturer="Busch-Jaeger", order_number="6131/40",
                   product_name="Busch-Watchdog Sky"),
        ]),
        Line(line_number=3, assigned_room_ids=[wohnen.id]),
    ])]

    gas = [
        _ga(4, 0, 1, "L_CUG01_01 E/A (Waschen Deckenlicht)", "L", waschen, 1, "E/A", licht),
        _ga(4, 0, 2, "L_CUG01_01 RM (Waschen Deckenlicht)", "L", waschen, 1, "RM", licht),
        _ga(4, 0, 3, "", placeholder=True),
        _ga(4, 5, 1, "A_CUG01_01 P1: Bewegung", "A", waschen, 1, "P1: Bewegung", alarm),
        _ga(2, 4, 0, "MM_COG04_01 System Off", "MM", wohnen, 1, "System Off", multimedia),
        _ga(0, 4, 1, "ZENTRAL Anwesenheit Komplex", function="SZENE", central="true"),
    ]
    structure = GroupAddressStructure()
    for number, name in ((0, "Zentraladressen"), (2, "Obergeschoss"), (4, "Untergeschoss")):
        hg = MainGroup(number=number, name=name)
        for middle in sorted({g.middle_group for g in gas if g.main_group == number}):
            hg.middle_groups.append(MiddleGroup(number=middle, name="Szenen" if number == 0 else "",
                group_addresses=[g for g in gas if (g.main_group, g.middle_group)
                                 == (number, middle)]))
        structure.main_groups.append(hg)
    project.group_addresses = structure
    return project


def test_gemeinsames_gateway_bedient_alle_linien():
    """Revox: das Gateway 1.2.9 auf Linie 2 bedient auch COG04 auf Linie 3."""
    rows = BelegungsplanService().generate(_project()).actor_rows
    assert ("1.2.9", "2/4/0") in {(r.physical_address, r.ga_address) for r in rows}


def test_aktor_und_bedienung():
    links = ga_links(_project())
    link = links["4/0/1"]
    assert link.gewerke == ["L"]
    assert link.room == ("CUG01", "Waschen")
    assert link.actor_addresses == ["1.2.13"]
    assert link.outputs[0].startswith("Schaltaktor 4-fach 1.2.13")
    assert link.operators and link.operators[0].startswith("1.2.101")
    assert "4/0/3" not in links    # Reserve


def test_gewerk_des_sensors():
    """Gewerk A hat keinen Aktor: das Gerät ist der Bewegungsmelder."""
    link = ga_links(_project())["4/5/1"]
    assert link.outputs == ["Busch-Watchdog Sky 1.2.105"]


def test_szene_wirkt_auf_gewerke_der_aktoren():
    link = ga_links(_project())["0/4/1"]
    assert set(link.actor_addresses) == {"1.2.13", "1.2.9"}
    assert link.gewerke == ["L", "MM"]


def test_bericht(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = str(tmp_path / "ga.pdf")
    ReportService(_project()).generate_ga_report(path)
    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    assert "Gruppenadressen je Gewerk und Hauptgruppe" in text
    assert "Aktor / Gerät" in text and "Bedient von" in text
    assert "Schaltaktor 4-fach 1.2.13" in text
    assert "2 Aktoren" in text and "L, MM" in text
    assert "MG 0:" in text and "1 Reserve" in text
    assert "Alle Gruppenadressen sind mit einem Aktor" in text
