"""
Tests fuer die Vollstaendigkeitspruefung der Revisionsunterlagen (FA-2104).
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Bedienelement, SensorFunktion,
)
from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.models.documentation import (
    AcceptanceProtocol, CommissioningChecklist, ChecklistItem, Defect,
)
from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.material_list import MaterialEntry
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Line, Device
from knix_arranger.services.address_generator import insert_ga
from knix_arranger.services.documentation_service import DocumentationService
from knix_arranger.services.revision_check import check_revision_completeness


def _complete_project() -> tuple[KnxProject, CompanyProfile]:
    project = KnxProject(name="Test")
    areal = Areal(name="A")
    building, wing = Building(name="B"), Wing(name="W")
    floor = Floor(name="EG", short_code="EG", main_group_number=2)
    apt = Apartment(name="EG")
    room = Room(number="E01", name="Wohnen")
    be = Bedienelement(element_type="Tastereinheit")
    be.funktionen.append(SensorFunktion(gewerk_code="L"))
    room.bedienelemente.append(be)
    apt.rooms.append(room)
    floor.apartments.append(apt)
    wing.floors.append(floor)
    building.wings.append(wing)
    areal.buildings.append(building)
    project.areal = areal

    insert_ga(project.group_addresses,
              GroupAddress(main_group=2, middle_group=0, sub_group=0,
                           designation="L_E01_01 E/A (Wohnen)"))
    actor = Device(physical_address="1.1.1", device_type="actor",
                   manufacturer="MDT", order_number="AKS-0816.03",
                   product_name="Schaltaktor 8-fach", datasheets=["aks.pdf"])
    project.topology.areas.append(Area(lines=[Line(devices=[actor])]))

    project.acceptance_protocol = AcceptanceProtocol(result="Abnahme erfolgt")
    project.checklists.append(CommissioningChecklist(items=[ChecklistItem(result="OK")]))
    project.material_list.entries.append(MaterialEntry(order_number="AKS-0816.03"))
    return project, CompanyProfile(company_name="Müller SmartHome")


def _parts(findings) -> list[str]:
    return [f.part for f in findings]


class TestCompleteness:
    def test_complete_project_has_no_findings(self):
        project, company = _complete_project()
        assert check_revision_completeness(project, company) == []

    def test_empty_project_lists_all_parts(self):
        parts = _parts(check_revision_completeness(KnxProject(name="Leer")))
        for part in ("Deckblatt", "Topologie", "Gruppenadressen", "Geräteliste",
                     "Abnahmeprotokoll", "Inbetriebnahme-Checkliste", "Materialliste"):
            assert part in parts

    def test_missing_datasheet_named_per_product(self):
        project, company = _complete_project()
        project.topology.areas[0].lines[0].devices[0].datasheets = []
        findings = check_revision_completeness(project, company)
        assert [f.message for f in findings] == [
            "Produktdatenblatt für Schaltaktor 8-fach (MDT AKS-0816.03) fehlt."]

    def test_device_without_product(self):
        project, company = _complete_project()
        project.topology.areas[0].lines[0].devices.append(
            Device(physical_address="1.1.2", device_type="sensor", product="Taster"))
        msg = check_revision_completeness(project, company)[0].message
        assert msg == "1 Gerät(e) ohne Produkt (Bestellnummer): 1.1.2 Taster."

    def test_open_points_of_acceptance(self):
        project, company = _complete_project()
        project.acceptance_protocol.defects.append(Defect(status="offen"))
        project.checklists[0].items.append(ChecklistItem())
        messages = [f.message for f in check_revision_completeness(project, company)]
        assert "1 Mangel/Mängel noch nicht behoben." in messages
        assert "1 von 2 Prüfpunkten noch offen." in messages

    def test_operable_element_without_function(self):
        project, company = _complete_project()
        project.all_rooms[0].bedienelemente[0].funktionen.clear()
        findings = check_revision_completeness(project, company)
        assert _parts(findings) == ["Funktionszuordnung"]


class TestPackage:
    def test_index_lists_open_points_and_material_list(self, tmp_path):
        project, company = _complete_project()
        project.acceptance_protocol = None
        DocumentationService(project, company_profile=company).generate_revision_package(
            str(tmp_path))
        assert (tmp_path / "Test_Materialliste.xlsx").exists()
        with fitz.open(tmp_path / "Test_Inhaltsverzeichnis.pdf") as doc:
            text = "".join(page.get_text() for page in doc)
        assert "Offene Punkte" in text
        assert "Abnahmeprotokoll fehlt noch" in text
        assert "Materialliste" in text
