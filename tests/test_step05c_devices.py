"""
Tests fuer Schritt 5c (_DeviceConfigDialog) - Zusatzsensorik-Produktverknuepfung.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog

from knix_arranger.models.building import Bedienelement
from knix_arranger.ui.wizard.step05c_devices import _DeviceConfigDialog
from knix_arranger.services.product_search_service import ProductSuggestion


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _fake_dialog(**attrs):
    """Baut ein Objekt, das sich wie ein akzeptierter Dialog verhaelt."""
    obj = type("FakeDlg", (), {"exec": lambda self: QDialog.Accepted})()
    for k, v in attrs.items():
        setattr(obj, k, v)
    return obj


class TestExtraSensorProductLink:
    def test_pick_new_product_sets_linked_product(self):
        be = Bedienelement(element_type="Tastereinheit")
        dlg = _DeviceConfigDialog(be)

        prod = ProductSuggestion(
            manufacturer="Test", order_number="TA-1",
            product_name="Glastaster mit Temperaturfühler", category="sensor",
            com_objects=[{
                "number": 2, "name": "Temperatur", "function_text": "Temperatur",
                "datapoint_type": "DPST-9-1",
                "communication_flag": True, "write_flag": False,
                "transmit_flag": True, "read_flag": False, "update_flag": False,
            }],
        )
        fake_product_dlg = _fake_dialog(selected_product=prod)
        fake_co_dlg = _fake_dialog(excluded_numbers=lambda: set())

        with patch(
            "knix_arranger.ui.wizard.step05c_devices.ProductSelectDialog",
            return_value=fake_product_dlg,
        ), patch(
            "knix_arranger.ui.wizard.step05c_devices.ComObjectSelectDialog",
            return_value=fake_co_dlg,
        ):
            dlg._pick_new_extra_sensor_product()

        assert be.linked_product is not None
        assert be.linked_product["order_number"] == "TA-1"
        assert be.linked_product["excluded_co_numbers"] == []
        assert dlg._btn_extra_product.text() == "✓ Zusatzsensorik-Produkt"

    def test_no_com_objects_shows_hint_and_sets_nothing(self):
        be = Bedienelement(element_type="Tastereinheit")
        dlg = _DeviceConfigDialog(be)

        prod = ProductSuggestion(
            manufacturer="Test", order_number="TA-2",
            product_name="Taster ohne KNXPROD-Daten", category="sensor",
            com_objects=[],
        )
        fake_product_dlg = _fake_dialog(selected_product=prod)

        with patch(
            "knix_arranger.ui.wizard.step05c_devices.ProductSelectDialog",
            return_value=fake_product_dlg,
        ), patch(
            "knix_arranger.ui.wizard.step05c_devices.QMessageBox.information",
        ):
            dlg._pick_new_extra_sensor_product()

        assert be.linked_product is None

    def test_reopen_existing_link_goes_directly_to_co_dialog(self):
        be = Bedienelement(
            element_type="Tastereinheit",
            linked_product={
                "manufacturer": "Test", "order_number": "TA-1",
                "product_name": "Glastaster",
                "com_objects": [{
                    "number": 2, "name": "Temperatur", "function_text": "Temperatur",
                    "datapoint_type": "DPST-9-1",
                    "communication_flag": True, "write_flag": False,
                    "transmit_flag": True, "read_flag": False, "update_flag": False,
                }],
                "excluded_co_numbers": [],
            },
        )
        dlg = _DeviceConfigDialog(be)

        fake_co_dlg = _fake_dialog(
            excluded_numbers=lambda: {2}, wants_different_product=lambda: False,
        )

        with patch(
            "knix_arranger.ui.wizard.step05c_devices.ProductSelectDialog",
        ) as mock_product_dlg, patch(
            "knix_arranger.ui.wizard.step05c_devices.ComObjectSelectDialog",
            return_value=fake_co_dlg,
        ):
            dlg._select_extra_sensor_product()

        mock_product_dlg.assert_not_called()
        assert be.linked_product["excluded_co_numbers"] == [2]
