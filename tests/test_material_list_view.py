"""
Tests fuer MaterialListView – Produktvorschlag aus Schritt-5-Verknuepfung
und Regressionsschutz gegen verwaiste Materialliste-Eintraege aus Schritt 5.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.ui.views.material_list_view import MaterialListView
from knix_arranger.ui.wizard.step05_gewerke import Step05Gewerke
from knix_arranger.services.product_search_service import ProductSuggestion


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_with_weather_station(linked_product: dict | None) -> tuple[KnxProject, Room, Device]:
    """Projekt mit einem Raum (Gewerk 'W', optional mit linked_product) und
    einem passenden, unbestueckten Sensor-Platzhalter-Device in der Topologie."""
    project = KnxProject(name="Test")

    room = Room(number="E01", name="Garten")
    room.gewerk_assignments = [
        GewerkAssignment(gewerk_code="W", count=1, linked_product=linked_product),
    ]
    apt = Apartment(name="EG")
    apt.rooms = [room]
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    floor.apartments = [apt]
    wing = Wing(name="Haupt")
    wing.floors = [floor]
    building = Building(name="Haus")
    building.wings = [wing]
    project.areal = Areal(name="Test", buildings=[building])

    device = Device(
        device_type="sensor", product="Wetterstation", room_id=room.id,
    )
    line = Line(name="Linie 1", line_number=1)
    line.devices = [device]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    project.topology = Topology()
    project.topology.areas = [area]

    return project, room, device


class TestSuggestedSearchText:
    def test_suggests_order_number_from_linked_gewerk_assignment(self):
        project, room, device = _project_with_weather_station({
            "manufacturer": "Theben", "order_number": "1409208",
            "product_name": "Meteodata 140 S GPS", "com_objects": [],
        })
        view = MaterialListView()
        view.set_project(project)

        entry = next(e for e in view._material_list.entries if e.device_id == device.id)
        assert view._suggested_search_text(entry) == "1409208"

    def test_no_suggestion_without_linked_product(self):
        project, room, device = _project_with_weather_station(None)
        view = MaterialListView()
        view.set_project(project)

        entry = next(e for e in view._material_list.entries if e.device_id == device.id)
        assert view._suggested_search_text(entry) == ""

    def test_no_suggestion_for_unknown_device_id(self):
        project, _room, _device = _project_with_weather_station(None)
        view = MaterialListView()
        view.set_project(project)

        from knix_arranger.models.material_list import MaterialEntry
        orphan = MaterialEntry(device_id="does-not-exist")
        assert view._suggested_search_text(orphan) == ""


class TestStep05DoesNotCreateMaterialEntry:
    """Regression: Produktverknuepfung in Schritt 5 dient nur der
    GA-Generierung und darf keinen (nie mit der Topologie verknuepfbaren)
    Materialliste-Eintrag mehr anlegen."""

    def test_pick_new_product_leaves_material_list_untouched(self):
        project = KnxProject(name="Test")
        room = Room(number="E01", name="Garten")
        ga = GewerkAssignment(gewerk_code="W", count=1)
        room.gewerk_assignments = [ga]

        prod = ProductSuggestion(
            manufacturer="Theben", order_number="1409208",
            product_name="Meteodata 140 S GPS", category="sensor",
            com_objects=[],
        )

        fake_product_dialog = type("FakeDlg", (), {
            "exec": lambda self: QDialog.Accepted,
            "selected_product": prod,
        })()

        step = Step05Gewerke(project)
        with patch(
            "knix_arranger.ui.wizard.step05_gewerke.ProductSelectDialog",
            return_value=fake_product_dialog,
        ), patch(
            "knix_arranger.ui.wizard.step05_gewerke.QMessageBox.information",
        ), patch.object(step, "_regenerate_gas"), patch.object(step, "_refresh_table"):
            step._pick_new_product(room, ga)

        assert ga.linked_product is not None
        assert ga.linked_product["order_number"] == "1409208"
        assert "material_entry_id" not in ga.linked_product
        assert len(project.material_list.entries) == 0
