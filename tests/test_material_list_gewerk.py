"""
Tests fuer die Gewerk-/Raumzuordnung von Aktoren und Gateways in der
Materialliste (Spalte "Gewerk / Raum", Kategorie der Gateways, Titel des
Produktauswahl-Dialogs).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.gewerk import GewerkCatalog
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.services.device_gewerk_service import (
    describe_device_gewerke, gewerk_codes_for_device,
)
from knix_arranger.ui.views.material_list_view import MaterialListView, _COL_GEWERK


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _room(number: str, name: str, *codes: str) -> Room:
    return Room(number=number, name=name,
                gewerk_assignments=[GewerkAssignment(gewerk_code=c) for c in codes])


def _catalog() -> GewerkCatalog:
    catalog = GewerkCatalog()
    catalog.load_defaults()
    return catalog


def _music_project() -> KnxProject:
    """Nachbau von "Test Musik": Musikzimmer (DALI, Jalousie, Multimedia),
    Aussenfassade (Wetterstation), Technik (Wärmepumpe)."""
    musik = _room("M01", "Musikzimmer", "LDA", "J", "MM")
    fassade = _room("A01", "Aussenfassade", "W")
    technik = _room("U01", "Technik", "WP")
    rooms = [musik, fassade, technik]

    project = KnxProject(name="Test Musik")
    apt = Apartment(name="Haus")
    apt.rooms = rooms
    floor = Floor(name="EG", short_code="EG", main_group_number=1)
    floor.apartments = [apt]
    wing = Wing(name="Haupt")
    wing.floors = [floor]
    building = Building(name="Test")
    building.wings = [wing]
    project.areal = Areal(name="Test", buildings=[building])

    line = Line(name="Linie 1", line_number=1, coupler_address="1.1.0")
    line.assigned_room_ids = [r.id for r in rooms]
    line.devices = [
        Device(device_type="gateway", product="DALI-Gateway 16-fach", physical_address="1.1.1"),
        Device(device_type="actor", product="Jalousieaktor 2-fach", physical_address="1.1.9"),
        Device(device_type="gateway", product="KNX-Schnittstelle 1-fach", physical_address="1.1.13"),
        Device(device_type="gateway", product="Modbus-KNX-Gateway 1-fach", physical_address="1.1.17"),
        Device(device_type="sensor", product="Tastereinheit", physical_address="1.1.101"),
    ]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    project.topology = Topology()
    project.topology.areas = [area]
    return project


def _line(project: KnxProject) -> Line:
    return project.topology.areas[0].lines[0]


def _device(project: KnxProject, addr: str) -> Device:
    return next(d for d in _line(project).devices if d.physical_address == addr)


class TestDescribeDeviceGewerke:
    def _describe(self, project, addr):
        room_by_id = {r.id: r for r in project.all_rooms}
        return describe_device_gewerke(
            [(_device(project, addr), _line(project))], room_by_id, _catalog()
        )

    def test_gateways_show_their_gewerk_and_room(self):
        project = _music_project()
        text, _ = self._describe(project, "1.1.13")
        assert text == "MM Multimedia – M01 Musikzimmer"
        text, _ = self._describe(project, "1.1.17")
        assert text.startswith("WP ") and text.endswith("– U01 Technik")

    def test_actor_shows_only_codes_present_on_line(self):
        # Jalousieaktor deckt J/R/M/T ab -- angezeigt wird nur J (im Projekt vorhanden)
        text, _ = self._describe(_music_project(), "1.1.9")
        assert text == "J Jalousie – M01 Musikzimmer"

    def test_sensor_has_no_gewerk_text(self):
        assert self._describe(_music_project(), "1.1.101") == ("", "")

    def test_many_rooms_are_compressed_with_full_tooltip(self):
        rooms = [_room(f"E0{i}", f"Zimmer {i}", "J") for i in range(1, 5)]
        line = Line(name="L", line_number=1)
        line.assigned_room_ids = [r.id for r in rooms]
        dev = Device(device_type="actor", product="Jalousieaktor 8-fach")
        text, tooltip = describe_device_gewerke(
            [(dev, line)], {r.id: r for r in rooms}, _catalog()
        )
        assert text == "J Jalousie – 4 Räume"
        assert "E04 Zimmer 4" in tooltip

    def test_manual_functions_take_precedence(self):
        dev = Device(device_type="gateway", product="Irgendein Gateway",
                     manual_functions=["WP", "SZ"])
        assert gewerk_codes_for_device(dev) == {"WP"}


class TestMaterialListView:
    def _view(self):
        view = MaterialListView()
        view.set_project(_music_project())
        return view

    def _entry(self, view, addr):
        return next(e for e in view._material_list.entries if addr in e.physical_addresses)

    def _row_text(self, view, entry, col):
        for row in range(view._table.rowCount()):
            if view._table.item(row, 0).data(0x0100) == entry.id:  # Qt.UserRole
                return view._table.item(row, col).text()
        raise AssertionError("Zeile nicht gefunden")

    def test_gateways_get_gateway_category(self):
        view = self._view()
        for addr in ("1.1.1", "1.1.13", "1.1.17"):
            assert self._entry(view, addr).category == "Gateway / Schnittstellen"

    def test_gewerk_column(self):
        view = self._view()
        entry = self._entry(view, "1.1.13")
        assert self._row_text(view, entry, _COL_GEWERK) == "MM Multimedia – M01 Musikzimmer"
        entry = self._entry(view, "1.1.101")
        assert self._row_text(view, entry, _COL_GEWERK) == ""

    def test_product_dialog_title_names_gewerk(self):
        view = self._view()
        entry = self._entry(view, "1.1.13")
        title = view._product_dialog_title([entry], entry.device_type)
        assert title == ("Produkt für KNX-Schnittstelle 1-fach auswählen "
                         "(MM Multimedia – M01 Musikzimmer)")
