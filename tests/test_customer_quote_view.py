"""
Tests fuer CustomerQuoteView (Kundenofferte).

Deckt ab: Positionen aus Materialliste/Lieferantenofferten muessen den
Endpreis fuer den Kunden inkl. Material-Aufschlag zeigen (nicht den
Einkaufspreis), gerundet auf 5-Rappen-Schritte.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from unittest.mock import patch

from knix_arranger.models.project import KnxProject
from knix_arranger.models.material_list import MaterialEntry
from knix_arranger.models.quotation import QuotationItem, QuotationRequest
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.services.project_service import ProjectService
from knix_arranger.ui.views.customer_quote_view import CustomerQuoteView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_view_with_quote(project: KnxProject) -> CustomerQuoteView:
    view = CustomerQuoteView()
    view.set_project(project)
    view._add_quote()
    return view


class TestImportFromMaterialList:
    """Positionen aus der Materialliste muessen den Endpreis (inkl. Aufschlag,
    5-Rappen gerundet) zeigen, nicht den Einkaufspreis."""

    def test_item_price_includes_markup_and_is_rounded(self):
        project = KnxProject(name="Test")
        project.material_list.entries.append(MaterialEntry(
            quantity=2, manufacturer="ABB", order_number="X1",
            product_name="Schaltaktor", unit_price=99.99,
        ))
        view = _make_view_with_quote(project)
        view._material_markup.setValue(15.0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()

        cq = view._get_selected_quote()
        assert len(cq.items) == 1
        item = cq.items[0]

        # 99.99 * 1.15 = 114.9885 -> auf 5 Rappen gerundet: 115.00 (nicht 114.99)
        assert item.unit_price == pytest.approx(115.0)
        assert item.total_price == pytest.approx(230.0)
        # Sicherstellen, dass es sich nicht um den rohen Einkaufspreis handelt
        assert item.unit_price != 99.99

    def test_rounding_is_multiple_of_five_rappen(self):
        project = KnxProject(name="Test")
        project.material_list.entries.append(MaterialEntry(
            quantity=1, manufacturer="MDT", order_number="Y2",
            product_name="Dimmaktor", unit_price=37.13,
        ))
        view = _make_view_with_quote(project)
        view._material_markup.setValue(8.0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()

        cq = view._get_selected_quote()
        cents = round(cq.items[0].unit_price * 100)
        assert cents % 5 == 0, f"Preis {cq.items[0].unit_price} ist kein 5-Rappen-Schritt"

    def test_material_markup_percent_synced_from_spinbox(self):
        project = KnxProject(name="Test")
        project.material_list.entries.append(MaterialEntry(
            quantity=1, manufacturer="ABB", order_number="X1",
            product_name="Schaltaktor", unit_price=100.0,
        ))
        view = _make_view_with_quote(project)
        view._material_markup.setValue(25.0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()

        cq = view._get_selected_quote()
        assert cq.material_markup_percent == 25.0
        assert cq.items[0].unit_price == pytest.approx(125.0)

    def test_priced_entry_without_manufacturer_still_becomes_a_position(self):
        """Regression: ein bepreister Eintrag ohne zugewiesenen Hersteller
        durfte bisher im Material-Betrag stecken, ohne als Position sichtbar
        zu sein -- fuer den Kunden nicht nachvollziehbar."""
        project = KnxProject(name="Test")
        project.material_list.entries.append(MaterialEntry(
            quantity=1, manufacturer="ABB", order_number="X1",
            product_name="Schaltaktor", unit_price=100.0,
        ))
        project.material_list.entries.append(MaterialEntry(
            quantity=1, manufacturer="", order_number="",
            device_type="Reserve-Material", unit_price=50.0,
        ))
        view = _make_view_with_quote(project)
        view._material_markup.setValue(10.0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()

        cq = view._get_selected_quote()
        assert len(cq.items) == 2
        names = [item.product_name for item in cq.items]
        assert any("Reserve-Material" in n for n in names)

    def test_material_total_reconciles_with_position_sum(self):
        """Die Summe der GP-Spalte muss immer exakt dem angezeigten
        Material-Betrag entsprechen -- auch bei mehreren Positionen und
        auch wenn ein Eintrag keinen Hersteller hat."""
        project = KnxProject(name="Test")
        project.material_list.entries.append(MaterialEntry(
            quantity=2, manufacturer="ABB", order_number="X1",
            product_name="Schaltaktor", unit_price=99.99,
        ))
        project.material_list.entries.append(MaterialEntry(
            quantity=1, manufacturer="", order_number="",
            device_type="Kleinmaterial", unit_price=37.13,
        ))
        view = _make_view_with_quote(project)
        view._material_markup.setValue(15.0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()

        cq = view._get_selected_quote()
        assert cq.material_with_markup == pytest.approx(
            sum(item.total_price for item in cq.items)
        )


class TestStaleWarning:
    """Kundenofferte muss erkennen, wenn sich die Materialliste nach dem
    letzten Positionsimport veraendert hat (Offerte entspricht dann nicht
    mehr dem aktuellen Planungsstand)."""

    @staticmethod
    def _project_with_priced_entry(quantity=1, unit_price=100.0) -> KnxProject:
        project = KnxProject(name="Test")
        project.material_list.entries.append(MaterialEntry(
            quantity=quantity, manufacturer="ABB", order_number="X1",
            product_name="Schaltaktor", unit_price=unit_price,
        ))
        return project

    def test_snapshot_set_after_import_and_not_stale(self):
        project = self._project_with_priced_entry()
        view = _make_view_with_quote(project)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()

        cq = view._get_selected_quote()
        assert cq.material_snapshot != ""
        assert view._is_stale(cq) is False

    def test_unchanged_material_list_shows_no_warning(self):
        project = self._project_with_priced_entry()
        view = _make_view_with_quote(project)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()
        view._on_quote_selected(0, 0, -1, -1)

        assert view._stale_warning.text() == ""

    def test_changed_quantity_marks_stale_and_shows_warning(self):
        project = self._project_with_priced_entry(quantity=1)
        view = _make_view_with_quote(project)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()
        cq = view._get_selected_quote()

        project.material_list.entries[0].quantity = 5
        assert view._is_stale(cq) is True

        view._on_quote_selected(0, 0, -1, -1)
        assert view._stale_warning.text() != ""
        assert "Materialliste" in view._stale_warning.text()

    def test_stale_warning_wording_differs_once_sent(self):
        project = self._project_with_priced_entry()
        view = _make_view_with_quote(project)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()
        cq = view._get_selected_quote()
        cq.status = "Versendet"
        project.material_list.entries[0].quantity = 9

        view._on_quote_selected(0, 0, -1, -1)
        assert "bereits versendete" in view._stale_warning.text()

    def test_table_shows_marker_for_stale_quote(self):
        project = self._project_with_priced_entry()
        view = _make_view_with_quote(project)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()
        project.material_list.entries[0].quantity = 9
        view._refresh_quotes()

        assert "⚠" in view._quote_table.item(0, 6).text()

    def test_reimport_clears_stale_state(self):
        project = self._project_with_priced_entry(quantity=1)
        view = _make_view_with_quote(project)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()
        cq = view._get_selected_quote()

        project.material_list.entries[0].quantity = 5
        assert view._is_stale(cq) is True

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_material_list()
        assert view._is_stale(cq) is False


class TestImportFromAwardedRequests:
    """Positionen aus zugeschlagenen Lieferantenofferten muessen ebenfalls
    den Endpreis inkl. Aufschlag zeigen, nicht den Einkaufspreis."""

    def test_item_price_includes_markup_and_is_rounded(self):
        project = KnxProject(name="Test")
        qr = QuotationRequest(request_number="OA-001", status="Zugeschlagen")
        qr.items.append(QuotationItem(
            position=1, manufacturer="Gira", order_number="Z9",
            product_name="Taster", quantity=3, unit_price=49.93,
        ))
        project.quotation_requests.append(qr)

        view = _make_view_with_quote(project)
        view._material_markup.setValue(20.0)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._import_from_awarded_requests()

        cq = view._get_selected_quote()
        assert len(cq.items) == 1
        item = cq.items[0]

        # 49.93 * 1.20 = 59.916 -> auf 5 Rappen gerundet: 59.90
        assert item.unit_price == pytest.approx(59.90)
        assert item.unit_price != 49.93
        assert item.total_price == pytest.approx(59.90 * 3)


def _project_with_devices(device_types: list[str]) -> KnxProject:
    project = KnxProject(name="Test")
    line = Line(name="Linie 1", line_number=1)
    line.devices = [Device(device_type=dt, product=dt) for dt in device_types]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    topology = Topology()
    topology.areas = [area]
    project.topology = topology
    return project


class TestCountProgrammableDevices:
    """Geraetezaehlung fuer die Aufwandsschaetzung (FA-1707): Koppler und
    Spannungsversorgungen zaehlen nicht mit."""

    def test_excludes_coupler_and_power_supply(self):
        project = _project_with_devices([
            "actor", "actor", "actor", "sensor", "sensor", "gateway",
            "coupler", "power_supply",
        ])
        view = CustomerQuoteView()
        view.set_project(project)
        assert view._count_programmable_devices() == 6

    def test_no_project_returns_zero(self):
        view = CustomerQuoteView()
        assert view._count_programmable_devices() == 0

    def test_empty_topology_returns_zero(self):
        view = CustomerQuoteView()
        view.set_project(KnxProject(name="Leer"))
        assert view._count_programmable_devices() == 0


class TestEstimateEffort:
    """Automatische Aufwandsschaetzung aus der Geraeteanzahl (FA-1707)."""

    def test_applies_default_factors_to_quote(self):
        project = _project_with_devices(["actor"] * 5 + ["sensor"] * 5)
        view = _make_view_with_quote(project)

        profile = CompanyProfile(
            minutes_programming_per_device=20.0,
            minutes_commissioning_per_device=10.0,
            commissioning_base_hours=2.0,
            minutes_documentation_per_device=6.0,
            documentation_base_hours=0.5,
        )
        with patch.object(ProjectService, "load_company_profile", return_value=profile), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            view._estimate_effort()

        cq = view._get_selected_quote()
        # 10 Geraete * 20 Min. / 60 = 3.33... -> gerundet 3.3 h
        assert cq.labor_programming_hours == pytest.approx(round(10 * 20 / 60, 1))
        # 2.0 h Sockel + 10 * 10 Min. / 60 = 3.67 h -> gerundet 3.7 h
        assert cq.labor_commissioning_hours == pytest.approx(
            round(2.0 + 10 * 10 / 60, 1)
        )
        # 0.5 h Sockel + 10 * 6 Min. / 60 = 1.5 h
        assert cq.labor_documentation_hours == pytest.approx(
            round(0.5 + 10 * 6 / 60, 1)
        )

    def test_no_devices_shows_info_and_leaves_hours_unchanged(self):
        project = KnxProject(name="Leer")
        view = _make_view_with_quote(project)
        cq = view._get_selected_quote()
        cq.labor_programming_hours = 7.0

        with patch.object(QMessageBox, "information") as mock_info, \
             patch.object(QMessageBox, "question") as mock_question:
            view._estimate_effort()

        mock_info.assert_called_once()
        mock_question.assert_not_called()
        assert cq.labor_programming_hours == 7.0

    def test_declined_confirmation_leaves_quote_unchanged(self):
        project = _project_with_devices(["actor"] * 3)
        view = _make_view_with_quote(project)
        cq = view._get_selected_quote()
        cq.labor_programming_hours = 1.5

        with patch.object(ProjectService, "load_company_profile",
                           return_value=CompanyProfile()), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            view._estimate_effort()

        assert cq.labor_programming_hours == 1.5
