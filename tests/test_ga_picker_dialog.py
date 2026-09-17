"""
Tests fuer GaPickerDialog._on_accept (FA-2503).

Vorher schloss sich der Dialog beim Klick auf OK ohne vorherige Zeilen-
Auswahl lautlos per reject() -- von aussen ununterscheidbar von "Abbrechen"
gedrueckt. Ein Aufrufer wie BauherrFormView._SlotWidget._resolve_gewerk_via_picker
interpretiert das korrekt als Abbruch und verwirft die Auswahl, aber fuer den
Nutzer sah es so aus, als waere "einfach nichts passiert" -- Regression:
eine Gewerk-Auswahl im Bauherr-Formular wirkte dadurch, als wuerde die GA
kommentarlos geloescht, wenn man vergessen hatte, zuerst eine Zeile
anzuklicken (bei >1000 Zeilen in einem grossen importierten Projekt leicht
uebersehen).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import Room
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.ui.dialogs.ga_picker_dialog import GaPickerDialog


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_with_gas():
    gas = GroupAddressStructure()
    hg = MainGroup(number=1, name="Test")
    mg = MiddleGroup(number=0, name="Test")
    hg.middle_groups.append(mg)
    gas.main_groups.append(hg)
    mg.group_addresses.append(GroupAddress(
        main_group=1, middle_group=0, sub_group=1, designation="1/0/1 Licht",
    ))
    project = KnxProject(name="T")
    project.group_addresses = gas
    return project


class TestGaPickerNoSelection:
    def test_accepting_without_selection_warns_instead_of_silently_closing(self, monkeypatch):
        warned = []
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: warned.append(True))

        project = _project_with_gas()
        room = Room(number="01", name="Test")
        dlg = GaPickerDialog(project, room)

        dlg._on_accept()

        assert warned == [True]
        assert dlg.selected_ga is None

    def test_accepting_with_selection_still_works(self):
        project = _project_with_gas()
        room = Room(number="01", name="Test")
        dlg = GaPickerDialog(project, room)
        dlg._table.selectRow(0)

        dlg._on_accept()

        assert dlg.selected_ga is not None
        assert dlg.selected_ga.designation == "1/0/1 Licht"
