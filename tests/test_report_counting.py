"""
Berichte-Durchsicht 2026-11-10 (Chalet): eine Zählregel für Busteilnehmer in
allen Berichten, Präsenzmelder/Binäreingänge als Sensor, MG-Variante aus den
Projekteigenschaften, Kopfdaten mit Rückfall auf Projekt und Kundenprofil.
"""
from __future__ import annotations

import fitz

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.client_profile import ClientProfile
from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import (
    Area, Device, Line, Topology, count_bus_devices, is_bus_device,
)
from knix_arranger.services.documentation_service import DocumentationService
from knix_arranger.services.knxproj_import_service import KnxprojImportService
from knix_arranger.services.plant_check import run_check
from knix_arranger.services.project_service import correct_sensor_types
from knix_arranger.services.report_service import ReportService


def _project(imported: bool = True) -> KnxProject:
    room = Room(name="Wohnen", number="01")
    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="EG", apartments=[Apartment(rooms=[room])])])])])
    devices_1 = [
        Device(physical_address="1.1.-", device_type="power_supply",
               product="SV/S30.640.3.1 Power Supply,640mA,MDRC"),
        Device(physical_address="1.1.1", device_type="actor",
               product="SA/S8.16.1 Switch Actuator,8-fold", room_id=room.id),
        Device(physical_address="1.1.12", device_type="actor",
               product="BE/S8.20.1 Binary Input,8-fold,Cont.Sc.,MDRC", room_id=room.id),
        Device(physical_address="1.1.29", device_type="actor",
               product="compact office EIB", room_id=room.id),
        Device(physical_address="1.1.200", device_type="other", product="Z-Server",
               external=True),
    ]
    devices_2 = [
        Device(physical_address="1.2.-", device_type="power_supply",
               product="SV/S30.640.3.1 Power Supply,640mA,MDRC"),
        Device(physical_address="1.2.0", device_type="coupler", product="LK/S4.1 Line Coupler"),
        Device(physical_address="1.2.4", device_type="actor", product="pirios 360 KNX",
               room_id=room.id),
    ]
    project.topology = Topology(is_imported=imported, areas=[
        Area(area_number=1, lines=[Line(line_number=1, devices=devices_1),
                                   Line(line_number=2, devices=devices_2),
                                   Line(line_number=0, devices=[])]),
        Area(area_number=0, lines=[Line(line_number=0, devices=[])]),
    ])
    return project


def _devices(project):
    return [d for a in project.topology.areas for ln in a.lines for d in ln.devices]


def _pdf_text(path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def test_bus_count_rule():
    devices = _devices(_project())
    count = count_bus_devices(devices)
    # Koppler zählt, Spannungsversorgungen nicht, Z-Server getrennt
    assert (count.ets, count.external, count.total) == (5, 1, 6)
    assert count.label() == "5 + 1 nicht im ETS-Projekt"
    assert not is_bus_device(devices[0])
    assert count_bus_devices(devices[1:4]).label() == "3"


def test_sensors_corrected_on_load():
    project = _project()
    assert sorted(correct_sensor_types(project)) == ["1.1.12", "1.1.29", "1.2.4"]
    types = {d.physical_address: d.device_type for d in _devices(project)}
    assert types["1.1.1"] == "actor" and types["1.1.29"] == "sensor"
    assert correct_sensor_types(project) == []
    assert correct_sensor_types(_project(imported=False)) == []


def test_import_classifies_presence_and_binary_input_as_sensor():
    infer = KnxprojImportService._infer_device_type
    writable = [{"write_flag": True}] * 4
    assert infer("compact office EIB", writable) == "sensor"
    assert infer("BE/S4.20.1 Binary Input,4-fold,Contact Sc.,MDRC", writable) == "sensor"
    assert infer("SA/S8.16.1 Switch Actuator,8-fold", writable) == "actor"


def test_plant_check_and_protocol_use_same_count():
    project = _project()
    item = next(i for i in run_check(project, (0, 0)) if i.title == "Busteilnehmer")
    assert item.value.startswith("5 (") and "1 Koppler" in item.value
    scope = DocumentationService(project)._plant_scope()
    assert scope[0][:2] == ["Busteilnehmer", "5 + 1 nicht im ETS-Projekt"]


def test_summary_counts(tmp_path):
    project = _project()
    path = tmp_path / "summary.pdf"
    ReportService(project).generate_project_summary(str(path))
    text = _pdf_text(path)
    assert "Bereiche: 1" in text and "Linien: 2" in text
    assert "Busteilnehmer: 5 + 1 nicht im ETS-Projekt" in text
    assert "Spannungsversorgungen: 2 (keine Busteilnehmer)" in text


def test_ga_report_uses_project_variant(tmp_path):
    project = _project()
    project.config.mg_variant = "B"
    assert project.group_addresses.variant == "A"      # Import-Standard
    path = tmp_path / "ga.pdf"
    ReportService(project).generate_ga_report(str(path))
    assert "Variante: B" in _pdf_text(path)


def test_report_info_falls_back_to_project_and_client():
    project = _project()
    project.project_number = "2026-1"
    project.client_profile = ClientProfile(name="Familie Muster", object_address="Dorf 1")
    info = project.report_info()
    assert (info.project_name, info.project_number) == ("Chalet", "2026-1")
    assert (info.client_name, info.project_address) == ("Familie Muster", "Dorf 1")
    project.project_info.client_name = "Bauherr AG"
    assert project.report_info().client_name == "Bauherr AG"


def test_stored_protocol_gets_integrator_and_footer_title(tmp_path):
    from knix_arranger.models.documentation import AcceptanceProtocol
    project = _project()
    company = CompanyProfile(company_name="Muster AG", user_name="Max Muster",
                             role="Integrator")
    path = tmp_path / "abnahme.pdf"
    DocumentationService(project, company_profile=company).export_acceptance_protocol(
        str(path), AcceptanceProtocol())
    text = _pdf_text(path)
    assert "Max Muster, Muster AG (Integrator)" in text
    assert "Abnahmeprotokoll  ·  Max Muster" in text
