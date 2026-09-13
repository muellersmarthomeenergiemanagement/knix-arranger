"""
Tests fuer Schritt 5 (Gewerke): on_leave() darf bei importierten Projekten
nicht mehr automatisch/kommentarlos Gruppenadressen (neu) generieren
(FA-521f) -- vorher hier ein Bug: kein is_imported-Schutz, anders als
Schritt 7.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.ui.wizard.step05_gewerke import Step05Gewerke


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_with_assignment(is_imported: bool) -> KnxProject:
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")
    floor = Floor(name="EG", short_code="EG")
    apt = Apartment(name="EG")
    room = Room(number="01", name="Energiekeller")
    room.gewerk_assignments.append(GewerkAssignment(gewerk_code="L", count=1))
    apt.rooms.append(room)
    floor.apartments.append(apt)
    wing.floors.append(floor)
    building.wings.append(wing)
    areal.buildings.append(building)

    project = KnxProject(name="Test")
    project.areal = areal
    project.topology.is_imported = is_imported
    return project


class TestOnLeaveImportGuard:
    def test_does_not_regenerate_for_imported_project(self):
        project = _project_with_assignment(is_imported=True)
        step = Step05Gewerke(project)

        with patch.object(step, "_regenerate_gas") as mock_regen:
            step.on_leave()

        mock_regen.assert_not_called()

    def test_still_regenerates_for_non_imported_project(self):
        """Regressionsschutz: der Fix darf das normale (nicht importierte)
        Verhalten nicht versehentlich mit abschalten."""
        project = _project_with_assignment(is_imported=False)
        step = Step05Gewerke(project)

        with patch.object(step, "_regenerate_gas") as mock_regen:
            step.on_leave()

        mock_regen.assert_called_once()

    def test_does_not_regenerate_when_no_assignments_regardless_of_import(self):
        project = _project_with_assignment(is_imported=False)
        project.all_rooms[0].gewerk_assignments.clear()
        step = Step05Gewerke(project)

        with patch.object(step, "_regenerate_gas") as mock_regen:
            step.on_leave()

        mock_regen.assert_not_called()


class TestAutoDetectGroupVisibility:
    """Der 'Gewerke aus Topologie vorschlagen…'-Button (FA-521g) darf nur
    bei importierten Projekten sichtbar sein -- fuer neu geplante Projekte
    gibt es keine Topologie zum Scannen."""

    def test_visible_when_imported(self):
        # isVisible() waere hier immer False (Top-Level-Widget nie
        # .show()n), daher isHidden() -- reflektiert den expliziten
        # setVisible()-Aufruf unabhaengig von der Darstellung.
        project = _project_with_assignment(is_imported=True)
        step = Step05Gewerke(project)
        step.on_enter()
        assert not step._auto_detect_group.isHidden()

    def test_hidden_when_not_imported(self):
        project = _project_with_assignment(is_imported=False)
        step = Step05Gewerke(project)
        step.on_enter()
        assert step._auto_detect_group.isHidden()
