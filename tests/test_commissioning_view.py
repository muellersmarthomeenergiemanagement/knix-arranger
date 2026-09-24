"""
Tests fuer die Inbetriebnahme-Checkliste (CommissioningView): Ergebnis fuer
mehrere markierte Zeilen setzen -- ueber die Leiste "Markierte Zeilen" und
ueber die Ergebnis-Auswahl einer der markierten Zeilen (vorher wurde dort nur
die eine Zeile uebernommen).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from knix_arranger.models.documentation import (
    ChecklistItem, CommissioningChecklist, RESULT_OK, RESULT_DEFECT, RESULT_OPEN,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.ui.views.commissioning_view import CommissioningView, _COL_RES


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _view(n_items: int = 5):
    project = KnxProject(name="Test")
    cl = CommissioningChecklist(room_id="r1", room_name="M01 Musikzimmer", items=[
        ChecklistItem(check_type=f"Kanal {i + 1}", room_id="r1") for i in range(n_items)
    ])
    project.checklists = [cl]
    view = CommissioningView(project)
    view.set_project(project)
    view._tree.setCurrentItem(view._tree.topLevelItem(0))
    return view, cl


def _select(view, rows):
    view._table.clearSelection()
    for r in rows:
        view._table.selectionModel().select(
            view._table.model().index(r, 0),
            QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )


def _combo(view, row):
    return view._table.cellWidget(row, _COL_RES)


class TestMultiRowResult:
    def test_combo_in_marked_row_applies_to_all_marked_rows(self):
        view, cl = _view()
        _select(view, [1, 2, 3])
        _combo(view, 2).setCurrentIndex(_combo(view, 2).findData(RESULT_DEFECT))

        assert [i.result for i in cl.items] == [
            RESULT_OPEN, RESULT_DEFECT, RESULT_DEFECT, RESULT_DEFECT, RESULT_OPEN,
        ]
        # Anzeige der anderen markierten Zeilen ist nachgezogen
        assert _combo(view, 1).currentData() == RESULT_DEFECT
        assert _combo(view, 3).currentData() == RESULT_DEFECT

    def test_real_clicks_keep_marking_and_rate_all_rows(self):
        """Echter Ablauf mit Maus: Zeilen per Klick/Shift+Klick markieren,
        dann auf die Ergebnis-Auswahl einer markierten Zeile klicken. Vorher
        verwarf der Fokuswechsel auf die Auswahl die Mehrfachmarkierung."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from knix_arranger.ui.views.commissioning_view import _COL_CHECK

        view, cl = _view()
        view.resize(1200, 700)
        view.show()
        QTest.qWaitForWindowExposed(view)
        t = view._table

        def click(row, mod=Qt.NoModifier):
            rect = t.visualRect(t.model().index(row, _COL_CHECK))
            QTest.mouseClick(t.viewport(), Qt.LeftButton, mod, rect.center())

        click(1)
        click(3, Qt.ShiftModifier)
        combo = _combo(view, 2)
        QTest.mouseClick(combo, Qt.LeftButton)          # öffnet die Auswahl
        assert sorted({i.row() for i in t.selectedIndexes()}) == [1, 2, 3]
        combo.hidePopup()
        combo.setCurrentIndex(combo.findData(RESULT_DEFECT))

        assert [i.result for i in cl.items] == [
            RESULT_OPEN, RESULT_DEFECT, RESULT_DEFECT, RESULT_DEFECT, RESULT_OPEN,
        ]
        assert sorted({i.row() for i in t.selectedIndexes()}) == [1, 2, 3]
        view.close()

    def test_combo_outside_marking_changes_only_its_row(self):
        view, cl = _view()
        _select(view, [0, 1])
        _combo(view, 4).setCurrentIndex(_combo(view, 4).findData(RESULT_OK))

        assert [i.result for i in cl.items] == [RESULT_OPEN] * 4 + [RESULT_OK]

    def test_single_marked_row_changes_only_that_row(self):
        view, cl = _view()
        _select(view, [2])
        _combo(view, 2).setCurrentIndex(_combo(view, 2).findData(RESULT_OK))

        assert [i.result for i in cl.items] == [
            RESULT_OPEN, RESULT_OPEN, RESULT_OK, RESULT_OPEN, RESULT_OPEN,
        ]

    def test_bulk_bar_applies_to_marked_rows(self):
        view, cl = _view()
        _select(view, [0, 4])
        view._bulk_combo.setCurrentIndex(view._bulk_combo.findData(RESULT_OK))
        view._bulk_apply_selected()

        assert [i.result for i in cl.items] == [
            RESULT_OK, RESULT_OPEN, RESULT_OPEN, RESULT_OPEN, RESULT_OK,
        ]
