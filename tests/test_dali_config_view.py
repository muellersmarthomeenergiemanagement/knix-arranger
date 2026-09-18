"""
Tests fuer DaliConfigView Inline-Bearbeitung (FA-2801-Folgefehler).

Regression: Die Gruppen-/Szenen-Tabellen liessen sich per Doppelklick
anklicken und Text eintippen -- ohne itemChanged-Handler landete die
Eingabe aber nie im DaliGroup-/DaliScene-Modell, sondern ging beim
naechsten Refresh (Reiterwechsel, Gateway-Wechsel, Speichern) verloren.
Das EVG-Grid war ebenso inline "editierbar", ohne dass etwas gespeichert
wurde -- dort ist der "Bearbeiten..."-Dialog der einzige echte Editierweg.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QAbstractItemView

from knix_arranger.models.project import KnxProject
from knix_arranger.models.dali_config import DaliGateway, DaliGroup, DaliScene
from knix_arranger.ui.views.dali_config_view import (
    DaliConfigView, _CG_NAME, _CG_SWITCH, _CG_NR, _CG_DEVS,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_view_with_gateway():
    project = KnxProject(name="Test")
    view = DaliConfigView(project)
    gw = DaliGateway(gateway_device_id="dev-1", name="GW")
    gw.groups = [DaliGroup(number=0, name="Alt", ga_switch="2/0/5")]
    gw.scenes = [DaliScene(number=0, name="Alt")]
    view._current_gw = gw
    view._populate_groups_table(gw)
    view._populate_scenes_table(gw)
    return view, gw


class TestGroupsTableInlineEdit:

    def test_name_edit_persists_to_model(self):
        view, gw = _make_view_with_gateway()
        view._groups_table.item(0, _CG_NAME).setText("Galerie")
        assert gw.groups[0].name == "Galerie"

    def test_ga_switch_edit_persists_to_model(self):
        view, gw = _make_view_with_gateway()
        view._groups_table.item(0, _CG_SWITCH).setText("2/0/3")
        assert gw.groups[0].ga_switch == "2/0/3"

    def test_invalid_ga_is_rejected_and_reverted(self):
        view, gw = _make_view_with_gateway()
        with patch("knix_arranger.ui.views.dali_config_view.QMessageBox.warning") as mock_warn:
            view._groups_table.item(0, _CG_SWITCH).setText("keine-ga")
        mock_warn.assert_called_once()
        assert gw.groups[0].ga_switch == "2/0/5"
        assert view._groups_table.item(0, _CG_SWITCH).text() == "2/0/5"

    def test_edit_on_newly_added_group_persists(self):
        """Der urspruengliche Bug-Report: eine neu per '+ Gruppe' angelegte
        Gruppe editieren und die Eingabe muss im Modell landen."""
        view, gw = _make_view_with_gateway()
        view._add_group()
        assert len(gw.groups) == 2
        new_grp = next(g for g in gw.groups if g.number == 1)
        row = next(
            r for r in range(view._groups_table.rowCount())
            if view._groups_table.item(r, _CG_NR).data(Qt.UserRole) is new_grp
        )
        view._groups_table.item(row, _CG_NAME).setText("Spots Haupteingang")
        view._groups_table.item(row, _CG_SWITCH).setText("2/0/3")
        assert new_grp.name == "Spots Haupteingang"
        assert new_grp.ga_switch == "2/0/3"

    def test_nr_and_devices_columns_not_editable(self):
        view, gw = _make_view_with_gateway()
        assert not (view._groups_table.item(0, _CG_NR).flags() & Qt.ItemIsEditable)
        assert not (view._groups_table.item(0, _CG_DEVS).flags() & Qt.ItemIsEditable)

    def test_repopulate_does_not_trigger_spurious_writes(self):
        """Neu-Befuellen (z.B. Gateway-Wechsel) darf keine itemChanged-
        Handler-Schreibvorgaenge ausloesen (Rueckkopplungsschutz)."""
        view, gw = _make_view_with_gateway()
        gw.groups.append(DaliGroup(number=1, name="Zweite"))
        view._populate_groups_table(gw)  # darf nicht crashen/nichts kaputt machen
        assert {g.name for g in gw.groups} == {"Alt", "Zweite"}


class TestScenesTableInlineEdit:

    def test_name_edit_persists_to_model(self):
        view, gw = _make_view_with_gateway()
        view._scenes_table.item(0, 1).setText("Praesenz")
        assert gw.scenes[0].name == "Praesenz"


class TestEvgTableEditGuard:

    def test_evg_table_disables_inline_editing(self):
        """EVG-Zellen duerfen nicht inline editierbar sein -- Bearbeitung nur
        ueber den Dialog (_edit_evg), der korrekt zurueckschreibt."""
        view, _gw = _make_view_with_gateway()
        assert view._evg_table.editTriggers() == QAbstractItemView.NoEditTriggers
