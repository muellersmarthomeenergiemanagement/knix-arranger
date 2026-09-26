"""Tests fuer den Topologie-Bericht (Schema, Geraete nach Linie und nach Einbauort)."""
import pytest
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Line, Device
from knix_arranger.services.report_service import (
    ReportService, _clean_location, _location_sort_key, _device_type_label, _device_cell,
)


def test_einbauort_bereinigt():
    assert _clean_location("UV2   ( Steigzone )") == "UV2 (Steigzone)"
    assert _clean_location("") == ""


def test_verteiler_zuerst_ohne_angabe_zuletzt():
    locations = ["02 Garage", "", "UV1 (Steigzone)", "HzV Garage", "00 Halle"]
    assert sorted(locations, key=_location_sort_key) == [
        "HzV Garage", "UV1 (Steigzone)", "00 Halle", "02 Garage", "",
    ]


def test_spannungsversorgung_trotz_koppler_typ():
    sv = Device(device_type="coupler", product="SV/S30.640.3.1 Power Supply,640mA,MDRC")
    assert _device_type_label(sv) == "Spannungsversorgung"
    assert _device_type_label(Device(device_type="actor")) == "Aktor"


def test_koppler_nur_wenn_als_geraet_vorhanden():
    from knix_arranger.services.report_service import _line_coupler
    area = Area(area_number=1)
    ohne = Line(line_number=1, coupler_address="1.1.0",
                devices=[Device(physical_address="1.1.2", device_type="actor")])
    mit = Line(line_number=2, coupler_address="1.2.0",
               devices=[Device(physical_address="1.2.0", device_type="coupler")])
    assert _line_coupler(area, ohne) == ""
    assert _line_coupler(area, mit) == "1.2.0"


def test_geraetezelle_mit_zweiter_zeile():
    dev = Device(product="JAX-9", manufacturer="Griesser", order_number="JAX-9",
                 serial_number="00EE:000845CC")
    assert _device_cell(dev) == ("JAX-9", "Griesser · JAX-9 · SN 00EE:000845CC")
    assert _device_cell(Device(product="X")) == ("X", "")


def test_bericht_abschnitte(tmp_path):
    fitz = pytest.importorskip("fitz")
    project = KnxProject(name="Topo")
    devices = [
        Device(physical_address="1.1.1", device_type="actor", product="Schaltaktor",
               manufacturer="ABB", serial_number="0001:0002",
               installation_location="UV1   ( Steigzone )"),
        Device(physical_address="1.1.2", device_type="sensor", product="Taster",
               installation_location="00 Halle"),
    ]
    project.topology.areas = [Area(area_number=1, name="Bereich 1", lines=[
        Line(line_number=1, name="Linie 1", coupler_address="1.1.0", devices=devices),
        Line(line_number=2, name="Leer"),
    ])]
    path = str(tmp_path / "topo.pdf")
    ReportService(project).generate_topology_report(path)

    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    assert "Geräte nach Linie" in text
    assert "Geräte nach Einbauort" in text
    assert "UV1 (Steigzone)  (1 Gerät)" in text
    assert "ABB · SN 0001:0002" in text
    assert "2 / 256 Geräte" in text
    assert "Leer" not in text                       # Linien ohne Geraete entfallen
