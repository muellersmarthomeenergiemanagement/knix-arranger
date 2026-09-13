"""
Tests fuer ComObjectSelectDialog (GA-Vorauswahl bei Produktverknuepfung).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from knix_arranger.ui.dialogs.com_object_select_dialog import ComObjectSelectDialog


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _com_objects() -> list[dict]:
    return [
        {
            "number": 1, "name": "Helligkeit Ost", "function_text": "Helligkeit Ost",
            "datapoint_type": "DPST-9-4",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": True, "update_flag": False,
        },
        {
            "number": 2, "name": "Wind Geschwindigkeit", "function_text": "Wind Geschwindigkeit",
            "datapoint_type": "DPST-9-5",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": True, "update_flag": False,
        },
        {
            "number": 3, "name": "Regen", "function_text": "Regen",
            "datapoint_type": "DPST-1-2",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": True, "update_flag": False,
        },
        {
            "number": 4, "name": "Sperren Wind", "function_text": "Sperren Wind",
            "datapoint_type": "DPST-1-1",
            "communication_flag": True, "read_flag": False,
            "write_flag": True, "transmit_flag": False, "update_flag": False,
        },
        {
            # Kein needs_ga (kein Flag gesetzt) - darf nicht gelistet werden
            "number": 5, "name": "Reserve", "function_text": "Reserve",
            "datapoint_type": "DPST-1-1",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": False, "update_flag": False,
        },
    ]


class TestComObjectSelectDialog:
    def test_only_needs_ga_objects_are_listed(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        assert dlg._table.rowCount() == 4  # Nr. 5 (kein needs_ga) fehlt

    def test_default_all_selected_no_exclusions(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        assert dlg.excluded_numbers() == set()

    def test_preexisting_exclusions_respected(self):
        dlg = ComObjectSelectDialog(
            "Testprodukt", _com_objects(), excluded_numbers={2, 4},
        )
        assert dlg.excluded_numbers() == {2, 4}

    def test_unchecking_a_row_adds_it_to_excluded(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        dlg._checkboxes[1].setChecked(False)  # Nr. 2
        assert dlg.excluded_numbers() == {2}

    def test_select_none_then_select_all(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        dlg._set_visible(False)
        assert dlg.excluded_numbers() == {1, 2, 3, 4}
        dlg._set_visible(True)
        assert dlg.excluded_numbers() == set()

    def test_search_filter_hides_non_matching_rows(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        dlg._search_edit.setText("wind")
        hidden = [dlg._table.isRowHidden(r) for r in range(dlg._table.rowCount())]
        # "Wind Geschwindigkeit" (Nr. 2) und "Sperren Wind" (Nr. 4) bleiben sichtbar
        visible_numbers = {
            dlg._relevant[r].number for r in range(dlg._table.rowCount())
            if not dlg._table.isRowHidden(r)
        }
        assert visible_numbers == {2, 4}

    def test_choose_different_product_rejects_with_flag(self):
        dlg = ComObjectSelectDialog("Testprodukt", _com_objects())
        assert dlg.wants_different_product() is False
        dlg._choose_different_product()
        assert dlg.wants_different_product() is True
        assert dlg.result() == QDialog.Rejected

    def test_default_all_selected_false_starts_with_none_checked(self):
        """Opt-in-Modus (Taster-Zusatzsensorik): ohne explizite excluded_numbers
        startet nichts ausgewählt, statt wie im Standardfall alles."""
        dlg = ComObjectSelectDialog(
            "Testprodukt", _com_objects(), default_all_selected=False,
        )
        assert dlg.excluded_numbers() == {1, 2, 3, 4}

    def test_explicit_excluded_numbers_overrides_default_all_selected(self):
        """Beim Wiederöffnen mit einer gespeicherten Auswahl gewinnt die
        explizite excluded_numbers-Angabe gegenüber default_all_selected."""
        dlg = ComObjectSelectDialog(
            "Testprodukt", _com_objects(),
            excluded_numbers={1, 3, 4}, default_all_selected=False,
        )
        assert dlg.excluded_numbers() == {1, 3, 4}

    def test_header_note_override(self):
        from PySide6.QtWidgets import QLabel
        dlg = ComObjectSelectDialog(
            "Testprodukt", _com_objects(), header_note="Eigener Hinweistext",
        )
        labels = [w.text() for w in dlg.findChildren(QLabel)]
        assert any("Eigener Hinweistext" in t for t in labels)
