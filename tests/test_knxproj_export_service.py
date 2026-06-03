"""
Tests fuer KnxprojExportService (FA-2401 bis FA-2406).
"""
import os
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.topology import Topology, Area, Line, Device, CommunicationObject
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.services.knxproj_export_service import (
    KnxprojExportService, ExportSummary, _encode_ga,
)
from knix_arranger.services.address_generator import AddressGenerator

_NS  = "http://knx.org/xml/project/23"
_NS5 = "http://knx.org/xml/project/20"


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _make_project(name: str = "Testprojekt") -> KnxProject:
    """Minimales Projekt mit Gebäude, GAs und Topologie."""
    project = KnxProject(name=name, project_number="T-001")

    # Gebäude
    room1 = Room(number="E01", name="Wohnzimmer")
    room1.gewerk_assignments = [
        GewerkAssignment(gewerk_code="L", count=1),
        GewerkAssignment(gewerk_code="J", count=1),
    ]
    room2 = Room(number="E02", name="Kueche")
    room2.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=2)]

    apt = Apartment(name="EG")
    apt.rooms = [room1, room2]
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    floor.apartments = [apt]
    wing = Wing(name="Hauptgebaeude")
    wing.floors = [floor]
    building = Building(name="EFH")
    building.wings = [wing]
    project.areal = Areal(name="Test", buildings=[building])

    # GAs generieren
    gen = AddressGenerator(project.gewerk_catalog, variant="A")
    project.group_addresses = gen.generate(project.areal)

    # Topologie
    line = Line(name="Linie 1", line_number=1)
    line.assigned_room_ids = [room1.id, room2.id]
    actor = Device(
        device_type="actor", product="Schaltaktor 4-fach",
        physical_address="1.1.1", room_id=room1.id,
    )
    sensor = Device(
        device_type="sensor", product="Taster 2-fach",
        physical_address="1.1.101",
    )
    line.devices = [actor, sensor]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    topology = Topology()
    topology.areas = [area]
    project.topology = topology

    return project


def _export(project, ets5: bool = False) -> tuple[str, KnxprojExportService]:
    """Exportiert ins Temp-Verzeichnis; gibt (pfad, service) zurück."""
    svc = KnxprojExportService()
    suffix = ".knxproj"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        path = f.name
    if ets5:
        svc.export_ets5_compat(project, path)
    else:
        svc.export(project, path)
    return path, svc


def _xml_from_zip(path: str, filename: str) -> ET.Element:
    """Liest eine XML-Datei aus dem ZIP und gibt das Root-Element zurück."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        match = next(n for n in names if n.endswith(f"/{filename}") or n == filename)
        return ET.fromstring(zf.read(match))


# ── GA-Kodierung ───────────────────────────────────────────────────────────────

class TestEncodeGa:

    def test_null_adresse(self):
        assert _encode_ga(0, 0, 0) == 0

    def test_standard_adresse(self):
        # 1/0/1 = (1 << 11) | (0 << 8) | 1 = 2048 + 1 = 2049
        assert _encode_ga(1, 0, 1) == 2049

    def test_maximalwert(self):
        # 31/7/255 = (31 << 11) | (7 << 8) | 255 = 63488 + 1792 + 255 = 65535
        assert _encode_ga(31, 7, 255) == 65535

    def test_hauptgruppe_2_mittel_3_sub_15(self):
        # 2/3/15 = (2 << 11) | (3 << 8) | 15 = 4096 + 768 + 15 = 4879
        assert _encode_ga(2, 3, 15) == 4879


# ── ZIP-Struktur (FA-2401) ─────────────────────────────────────────────────────

class TestZipStruktur:

    def test_zip_wird_erstellt(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            assert os.path.exists(path)
            assert zipfile.is_zipfile(path)
        finally:
            os.unlink(path)

    def test_zip_enthaelt_project_xml(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
            assert any(n.endswith("/project.xml") for n in names)
        finally:
            os.unlink(path)

    def test_zip_enthaelt_0_xml(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
            assert any(n.endswith("/0.xml") for n in names)
        finally:
            os.unlink(path)

    def test_projekt_id_als_verzeichnis(self):
        """Alle Dateien liegen in einem P-XXXX/-Verzeichnis."""
        project = _make_project()
        path, _ = _export(project)
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
            assert all("/" in n for n in names)
            dirs = {n.split("/")[0] for n in names}
            assert len(dirs) == 1
            assert list(dirs)[0].startswith("P-")
        finally:
            os.unlink(path)


# ── Projektmetadaten (FA-2401/2402) ──────────────────────────────────────────

class TestProjektmetadaten:

    def test_projektname_in_project_xml(self):
        project = _make_project("Mein Projekt")
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "project.xml")
            ns = f"{{{_NS}}}"
            proj_info = root.find(f".//{ns}ProjectInformation")
            assert proj_info is not None
            assert proj_info.get("Name") == "Mein Projekt"
        finally:
            os.unlink(path)

    def test_projektnummer_als_kommentar(self):
        project = _make_project("Test")
        project.project_number = "P-2026-001"
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "project.xml")
            ns = f"{{{_NS}}}"
            proj_info = root.find(f".//{ns}ProjectInformation")
            assert "P-2026-001" in (proj_info.get("Comment") or "")
        finally:
            os.unlink(path)

    def test_ga_style_three_level(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "project.xml")
            ns = f"{{{_NS}}}"
            proj_info = root.find(f".//{ns}ProjectInformation")
            assert proj_info.get("GroupAddressStyle") == "ThreeLevel"
        finally:
            os.unlink(path)


# ── Gruppenadressen (FA-2402) ─────────────────────────────────────────────────

class TestGruppenadressen:

    def test_gruppenadressen_in_0_xml(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            gas = root.findall(f".//{ns}GroupAddress")
            assert len(gas) > 0
        finally:
            os.unlink(path)

    def test_ga_anzahl_stimmt(self):
        project = _make_project()
        expected = len([ga for ga in project.group_addresses.all_addresses()
                        if not ga.is_placeholder])
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            gas = root.findall(f".//{ns}GroupAddress")
            assert len(gas) == expected
        finally:
            os.unlink(path)

    def test_ga_adresse_korrekt_kodiert(self):
        """GA 2/0/0 muss als 4096 kodiert sein."""
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            gas = root.findall(f".//{ns}GroupAddress")
            addresses = {int(ga.get("Address")) for ga in gas}
            assert _encode_ga(2, 0, 0) in addresses
        finally:
            os.unlink(path)

    def test_hauptgruppen_hierarchie(self):
        """Zwei Hierarchieebenen GroupRange vorhanden."""
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            ranges = root.findall(f".//{ns}GroupRange")
            assert len(ranges) >= 2
        finally:
            os.unlink(path)

    def test_ga_dpt_wird_exportiert(self):
        """DatapointType-Attribut muss für GAs mit DPT gesetzt sein."""
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            gas_with_dpt = [
                ga for ga in root.findall(f".//{ns}GroupAddress")
                if ga.get("DatapointType")
            ]
            assert len(gas_with_dpt) > 0
        finally:
            os.unlink(path)


# ── Topologie (FA-2402/2403) ──────────────────────────────────────────────────

class TestTopologie:

    def test_topology_element_in_0_xml(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            topo = root.find(f".//{ns}Topology")
            assert topo is not None
        finally:
            os.unlink(path)

    def test_bereich_in_topologie(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            areas = root.findall(f".//{ns}Area")
            # Bereichslinie (Adresse 0) + Bereich 1
            assert len(areas) >= 2
        finally:
            os.unlink(path)

    def test_gerät_in_topologie(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            devices = root.findall(f".//{ns}DeviceInstance")
            assert len(devices) > 0
        finally:
            os.unlink(path)

    def test_geraet_hat_physikalische_adresse(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            devices = root.findall(f".//{ns}DeviceInstance")
            assert all(d.get("Address") for d in devices)
        finally:
            os.unlink(path)

    def test_schaltaktor_adresse_1(self):
        """Schaltaktor 1.1.1 → Address='1' im XML."""
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            devices = root.findall(f".//{ns}DeviceInstance")
            addrs = {d.get("Address") for d in devices}
            assert "1" in addrs
        finally:
            os.unlink(path)


# ── Gebäudestruktur (FA-2402) ─────────────────────────────────────────────────

class TestGebaeudestruktur:

    def test_locations_element_vorhanden(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            assert root.find(f".//{ns}Locations") is not None
        finally:
            os.unlink(path)

    def test_gebaeude_als_space(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            spaces = root.findall(f".//{ns}Space")
            buildings = [s for s in spaces if s.get("Type") == "Building"]
            assert len(buildings) >= 1
        finally:
            os.unlink(path)

    def test_raum_als_space(self):
        project = _make_project()
        path, _ = _export(project)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            spaces = root.findall(f".//{ns}Space")
            rooms = [s for s in spaces if s.get("Type") == "Room"]
            assert len(rooms) >= 2
        finally:
            os.unlink(path)


# ── Validierung (FA-2406) ─────────────────────────────────────────────────────

class TestValidierung:

    def test_warnung_ohne_projektname(self):
        project = _make_project("")
        svc = KnxprojExportService()
        warnings = svc._validate(project)
        assert any("Projektname" in w for w in warnings)

    def test_warnung_ohne_gruppenadressen(self):
        project = _make_project()
        project.group_addresses = GroupAddressStructure()
        svc = KnxprojExportService()
        warnings = svc._validate(project)
        assert any("Gruppenadresse" in w or "GA" in w for w in warnings)

    def test_warnung_ohne_topologie(self):
        project = _make_project()
        project.topology = Topology()  # leere Topologie
        svc = KnxprojExportService()
        warnings = svc._validate(project)
        assert any("Topologie" in w for w in warnings)

    def test_applikationsprogramm_warnung_immer(self):
        """Applikationsprogramm-Warnung wird immer ausgegeben."""
        project = _make_project()
        svc = KnxprojExportService()
        warnings = svc._validate(project)
        assert any("Applikationsprogramm" in w for w in warnings)

    def test_vollstaendiges_projekt_nur_app_warnung(self):
        """Vollständiges Projekt hat nur die Applikationsprogramm-Warnung."""
        project = _make_project()
        svc = KnxprojExportService()
        warnings = svc._validate(project)
        non_app = [w for w in warnings if "Applikationsprogramm" not in w]
        assert non_app == []


# ── ExportSummary (FA-2405) ──────────────────────────────────────────────────

class TestExportSummary:

    def test_ga_anzahl_in_summary(self):
        project = _make_project()
        path, svc = _export(project)
        try:
            summary = KnxprojExportService().export(project, path)
            expected = len([ga for ga in project.group_addresses.all_addresses()
                            if not ga.is_placeholder])
            assert summary.ga_count == expected
        finally:
            os.unlink(path)

    def test_geraete_anzahl_in_summary(self):
        project = _make_project()
        path, svc = _export(project)
        try:
            summary = KnxprojExportService().export(project, path)
            assert summary.device_count == 2  # Schaltaktor + Taster
        finally:
            os.unlink(path)

    def test_summary_as_text_enthaelt_ga_count(self):
        summary = ExportSummary(ga_count=42, device_count=5, co_link_count=10)
        text = summary.as_text()
        assert "42" in text
        assert "5" in text

    def test_summary_as_text_zeigt_warnungen(self):
        summary = ExportSummary(warnings=["Test-Warnung"])
        text = summary.as_text()
        assert "Test-Warnung" in text


# ── ETS5-Compat-Export ────────────────────────────────────────────────────────

class TestEts5CompatExport:

    def test_ets5_zip_wird_erstellt(self):
        project = _make_project()
        path, _ = _export(project, ets5=True)
        try:
            assert os.path.exists(path)
            assert zipfile.is_zipfile(path)
        finally:
            os.unlink(path)

    def test_ets5_namespace(self):
        """ETS5 muss Namespace project/20 verwenden."""
        project = _make_project()
        path, _ = _export(project, ets5=True)
        try:
            root = _xml_from_zip(path, "0.xml")
            assert _NS5 in root.tag
        finally:
            os.unlink(path)

    def test_ets5_kein_segment_element(self):
        """ETS5: DeviceInstance direkt in Line, kein Segment-Element."""
        project = _make_project()
        path, _ = _export(project, ets5=True)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS5}}}"
            segments = root.findall(f".//{ns}Segment")
            assert len(segments) == 0
        finally:
            os.unlink(path)

    def test_ets5_enthaelt_gruppenadressen(self):
        project = _make_project()
        path, _ = _export(project, ets5=True)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS5}}}"
            gas = root.findall(f".//{ns}GroupAddress")
            assert len(gas) > 0
        finally:
            os.unlink(path)

    def test_ets6_hat_segment_element(self):
        """ETS6: DeviceInstance in Segment."""
        project = _make_project()
        path, _ = _export(project, ets5=False)
        try:
            root = _xml_from_zip(path, "0.xml")
            ns = f"{{{_NS}}}"
            segments = root.findall(f".//{ns}Segment")
            assert len(segments) >= 1
        finally:
            os.unlink(path)
