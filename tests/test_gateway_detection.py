"""
Gateways am Produktnamen (Chalet: Viessmann «Vitogate 200, type KNX» wurde
als Sensor und im Raum als «Wassermelder» eingelesen).
"""
from __future__ import annotations

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.knxproj_import_service import KnxprojImportService
from knix_arranger.services.project_service import correct_gateway_types
from knix_arranger.services.room_sheet import _strip_common_prefix


def test_compound_gate_is_a_gateway():
    infer = KnxprojImportService._infer_device_type
    assert infer("Vitogate 200, type KNX", []) == "gateway"
    assert infer("KNX-Gateway", []) == "gateway"
    # Tor-Aktor bleibt Aktor
    assert infer("Garage gate actuator", []) == "actor"


def test_warm_water_is_no_water_detector():
    cos = [CommunicationObject(name="1_1_CU401B_G__ / Warmwassertemperatur oben")]
    assert not KnxprojImportService._has_ko_hint(cos, KnxprojImportService._WASSERMELDER_KO_HINTS)
    leak = [CommunicationObject(name="Leckage Alarm")]
    assert KnxprojImportService._has_ko_hint(leak, KnxprojImportService._WASSERMELDER_KO_HINTS)


def _project(imported=True):
    gate = Device(device_type="sensor", physical_address="1.1.32",
                  product="Vitogate 200, type KNX",
                  communication_objects=[CommunicationObject(name="1_1_CU401B_G__ / Verdichter")])
    taster = Device(device_type="sensor", physical_address="1.1.50", product="Taster EDIZIOdue",
                    communication_objects=[CommunicationObject(name="Taste 1")])
    technik = Room(name="Technik", bedienelemente=[
        Bedienelement(element_type="Wassermelder", participant_number="1.1.32", is_auto=False),
        Bedienelement(element_type="Tastereinheit", participant_number="1.1.50")])
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="UG", apartments=[Apartment(rooms=[technik])])])])])
    project.topology = Topology(is_imported=imported, areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[gate, taster])])])
    return project, gate, taster, technik


def test_saved_project_corrected_on_load():
    project, gate, taster, technik = _project()
    assert correct_gateway_types(project) == ["1.1.32"]
    assert (gate.device_type, taster.device_type) == ("gateway", "sensor")
    assert [be.participant_number for be in technik.bedienelemente] == ["1.1.50"]
    assert correct_gateway_types(project) == []          # einmal genügt


def test_planned_project_untouched():
    project, gate, _taster, _technik = _project(imported=False)
    assert correct_gateway_types(project) == [] and gate.device_type == "sensor"


def test_technical_prefix_only_for_codes():
    assert _strip_common_prefix(["1_1_CU401B_G__ / (2000) Raumtemperatur Soll",
                                 "Auf / Beschattung"]) == [
        "(2000) Raumtemperatur Soll", "Auf / Beschattung"]
