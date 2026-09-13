"""
Tests fuer WizardController - Schritt-Status-Farbkodierung (FA-3211).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import Verteiler
from knix_arranger.ui.wizard.wizard_controller import WizardController


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestVerteilerStepStatus:
    """Regression: Verteiler werden pro Raum gespeichert (Room.verteiler),
    nicht pro Wohnung/Zone -- Schritt 4 durfte deshalb nie 'grau' bleiben,
    wenn im Projekt bereits HV/UV eingetragen sind (bug meldung Projekt
    'Test Musik')."""

    def test_empty_project_is_empty(self, simple_efh):
        project = KnxProject(name="Test")
        project.areal = simple_efh
        wizard = WizardController(project)

        assert wizard._step_status(3) == "empty"
        assert wizard._step_tooltip(3) == "0 Verteilungen"

    def test_room_with_hv_and_uv_is_complete(self, simple_efh):
        project = KnxProject(name="Test")
        project.areal = simple_efh
        room = simple_efh.all_rooms[0]
        room.verteiler.append(Verteiler(name="HV", verteiler_type="HV"))
        room.verteiler.append(Verteiler(name="UV Keller", verteiler_type="UV"))
        wizard = WizardController(project)

        assert wizard._step_status(3) == "complete"
        assert wizard._step_tooltip(3) == "2 Verteilungen"

    def test_single_verteiler_uses_singular_tooltip(self, simple_efh):
        project = KnxProject(name="Test")
        project.areal = simple_efh
        simple_efh.all_rooms[0].verteiler.append(
            Verteiler(name="HV", verteiler_type="HV")
        )
        wizard = WizardController(project)

        assert wizard._step_tooltip(3) == "1 Verteilung"
