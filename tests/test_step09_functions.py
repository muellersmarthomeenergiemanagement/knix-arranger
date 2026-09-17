"""
Tests fuer Schritt 9 (Funktionsdefinition): der Funktionsbaum muss FunctionAssignments
derselben SensorFunktion (sf_id) unter einem gemeinsamen Tasten-/Kanal-Knoten
buendeln statt als flache Geschwister-Zeilen -- sonst wirkt eine physische Taste
mit mehreren GAs (Befehl + Rueckmeldung) wie mehrere "Tasten" (siehe Chalet
Franziska 2005, Taster 1.1.28/1.1.35). Ausserdem muss eine geraeteinterne
Fremdsteuerungs-GA (role="fremdsteuerung", z.B. LED-Nachtabsenkung) als eigener
"Fremdsteuerung"-Knoten erscheinen, nicht als nummerierte Taste.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, Bedienelement, FunctionAssignment,
)
from knix_arranger.ui.wizard.step09_functions import Step09Functions


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _project_with_taster_1_1_28() -> KnxProject:
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")
    floor = Floor(name="UG", short_code="UG")
    apt = Apartment(name="UG")
    room = Room(number="02", name="Waschkeller")

    be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.28", channels=4)
    be.function_assignments = [
        FunctionAssignment(button_channel="Taste 1, links", function_ga="1/0/0",
                            description="Taste 1, links", role="befehl", sf_id="sf1"),
        FunctionAssignment(button_channel="Taste 1, links", function_ga="1/7/0",
                            description="Taste 1, links", role="rueckmeldung", sf_id="sf1"),
        FunctionAssignment(button_channel="Taste 1, rechts", function_ga="1/0/0",
                            description="Taste 1, rechts", role="befehl", sf_id="sf2"),
        FunctionAssignment(button_channel="Taste 1, rechts", function_ga="1/7/0",
                            description="Taste 1, rechts", role="rueckmeldung", sf_id="sf2"),
        FunctionAssignment(button_channel="Nachtabsenkung LED's", function_ga="0/4/250",
                            description="Nachtabsenkung LED's", role="fremdsteuerung", sf_id="sf3"),
    ]
    room.bedienelemente.append(be)
    apt.rooms.append(room)
    floor.apartments.append(apt)
    wing.floors.append(floor)
    building.wings.append(wing)
    areal.buildings.append(building)

    project = KnxProject(name="Test")
    project.areal = areal
    return project


class TestStep09FunctionsTree:
    def setup_method(self):
        self.project = _project_with_taster_1_1_28()
        self.widget = Step09Functions(self.project)
        self.widget._refresh()

    def _room_item(self):
        return self.widget._tree.topLevelItem(0)

    def _sensor_item(self):
        return self._room_item().child(0)

    def test_channel_nodes_bundle_by_sensorfunktion(self):
        """3 physische Kanaele (2 Tasten + 1 Fremdsteuerung), nicht 5 flache Zeilen."""
        sensor_item = self._sensor_item()
        assert sensor_item.childCount() == 3

    def test_taste_channel_shows_both_fa_rows_as_children(self):
        """'Taste 1, links' (Befehl+Rueckmeldung) ist EIN Knoten mit 2 Kind-Zeilen."""
        sensor_item = self._sensor_item()
        taste1 = next(
            sensor_item.child(i) for i in range(sensor_item.childCount())
            if sensor_item.child(i).text(1) == "Taste 1, links"
        )
        assert taste1.childCount() == 2
        actions = {taste1.child(0).text(3), taste1.child(1).text(3)}
        assert actions == {"Befehl", "Rückmeld."}

    def test_fremdsteuerung_is_separate_node_not_a_taste(self):
        """Nachtabsenkung erscheint als 'Fremdsteuerung'-Knoten, nicht als 'Taste'."""
        sensor_item = self._sensor_item()
        fremd = next(
            sensor_item.child(i) for i in range(sensor_item.childCount())
            if sensor_item.child(i).text(1) == "Fremdsteuerung"
        )
        assert fremd.text(2) == "Nachtabsenkung LED's"
        assert fremd.childCount() == 1
        assert fremd.child(0).text(3) == "Fremdsteuerung"
        assert fremd.child(0).text(5) == "0/4/250"
