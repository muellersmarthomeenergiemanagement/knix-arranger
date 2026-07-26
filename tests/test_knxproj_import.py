"""
Tests fuer KnxprojImportService (FA-521 bis FA-526).
Nutzt die echte Referenzdatei 241114_Chalet.knxproj.
"""
from __future__ import annotations
import os
import xml.etree.ElementTree as ET
import pytest
from knix_arranger.services.knxproj_import_service import (
    KnxprojImportService,
    KnxprojImportError,
)

CHALET = os.path.join(os.path.dirname(__file__), "..", "241114_Chalet 64.knxproj")


@pytest.fixture
def project():
    svc = KnxprojImportService()
    return svc.import_knxproj(CHALET)


# ------------------------------------------------------------------
# FA-521: Datei oeffnen
# ------------------------------------------------------------------

def test_file_not_found():
    svc = KnxprojImportService()
    with pytest.raises(FileNotFoundError):
        svc.import_knxproj("nicht_vorhanden.knxproj")


def test_invalid_zip(tmp_path):
    bad = tmp_path / "bad.knxproj"
    bad.write_bytes(b"this is not a zip file")
    svc = KnxprojImportService()
    with pytest.raises(KnxprojImportError):
        svc.import_knxproj(str(bad))


# ------------------------------------------------------------------
# FA-522: Projektmetadaten
# ------------------------------------------------------------------

def test_project_name(project):
    assert "chalet" in project.name.lower() or len(project.name) > 0


# ------------------------------------------------------------------
# FA-522: Gruppenadressen
# ------------------------------------------------------------------

def test_ga_count(project):
    assert len(project.group_addresses.all_addresses()) == 1044


def test_main_group_count(project):
    assert len(project.group_addresses.main_groups) == 6


def test_main_group_names(project):
    names = {hg.name for hg in project.group_addresses.main_groups}
    assert "Zentral" in names
    assert "OG" in names


def test_ga_address_decoding(project):
    """Alle GAs muessen gueltige Adressen haben."""
    for ga in project.group_addresses.all_addresses():
        assert 0 <= ga.main_group <= 31
        assert 0 <= ga.middle_group <= 7
        assert 0 <= ga.sub_group <= 255


def test_ga_dpt_present(project):
    """Mindestens einige GAs sollen einen DPT haben."""
    dpts = [ga.datapoint_type for ga in project.group_addresses.all_addresses()
            if ga.datapoint_type]
    assert len(dpts) > 10


# ------------------------------------------------------------------
# FA-522b: Description-Fallback aus Klammer-Zusatz (Paritaet zum XLSX-Import)
# ------------------------------------------------------------------

def _installation_with_ga(name: str, description: str = "", comment: str = "") -> ET.Element:
    """Baut ein minimales <Installation>-Fragment mit einer einzigen GA (Adresse 0/0/1)."""
    ns = "http://knx.org/xml/project/23"
    ET.register_namespace("", ns)
    installation = ET.Element(f"{{{ns}}}Installation")
    gas = ET.SubElement(installation, f"{{{ns}}}GroupAddresses")
    ranges = ET.SubElement(gas, f"{{{ns}}}GroupRanges")
    hg = ET.SubElement(ranges, f"{{{ns}}}GroupRange", RangeStart="0", Name="HG")
    mg = ET.SubElement(hg, f"{{{ns}}}GroupRange", RangeStart="0", Name="MG")
    attribs = {"Address": "1", "Name": name}
    if description:
        attribs["Description"] = description
    if comment:
        attribs["Comment"] = comment
    ET.SubElement(mg, f"{{{ns}}}GroupAddress", **attribs)
    return installation


def test_description_fallback_from_parentheses():
    """Ist ETS-Description/Comment leer, wird der Klammer-Zusatz aus der
    Bezeichnung als Description uebernommen (Paritaet zum XLSX-Import)."""
    installation = _installation_with_ga("L.004.1_ea ( Dusche / WC )")
    structure = KnxprojImportService()._parse_group_addresses(installation)
    ga = structure.all_addresses()[0]
    assert ga.description == "Dusche / WC"


def test_description_fallback_does_not_override_real_description():
    """Eine echte, gepflegte ETS-Description hat Vorrang vor dem Klammer-Fallback."""
    installation = _installation_with_ga(
        "L.004.1_ea ( Dusche / WC )", description="Echte ETS-Beschreibung"
    )
    structure = KnxprojImportService()._parse_group_addresses(installation)
    ga = structure.all_addresses()[0]
    assert ga.description == "Echte ETS-Beschreibung"


def test_description_fallback_empty_without_parentheses():
    """Ohne Klammer-Zusatz und ohne ETS-Description bleibt description leer."""
    installation = _installation_with_ga("L.004.1_ea")
    structure = KnxprojImportService()._parse_group_addresses(installation)
    ga = structure.all_addresses()[0]
    assert ga.description == ""


# ------------------------------------------------------------------
# FA-523: Gebaeudestruktur
# ------------------------------------------------------------------

def test_building_count(project):
    assert len(project.areal.buildings) == 1


def test_floor_count(project):
    assert len(project.areal.all_floors) >= 2


def test_room_count(project):
    assert len(project.areal.all_rooms) > 5


# ------------------------------------------------------------------
# Topologie
# ------------------------------------------------------------------

def test_area_count(project):
    assert len(project.topology.areas) >= 1


def test_device_count(project):
    total = sum(
        len(line.devices)
        for area in project.topology.areas
        for line in area.lines
    )
    assert total > 0


def test_physical_address_format(project):
    """Physikalische Adressen muessen das Format B.L.T haben."""
    for area in project.topology.areas:
        for line in area.lines:
            for dev in line.devices:
                parts = dev.physical_address.split(".")
                assert len(parts) == 3, f"Ungueltige Adresse: {dev.physical_address}"
