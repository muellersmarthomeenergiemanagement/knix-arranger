"""
Sensortyp je Element bei Gewerk A und Warnung bei unpassendem Produkt
(FA-1407g, FA-626). Auslöser Projekt_23: jedes A-Element war ein
«Bewegungsmelder»; ein Typ-Batch gab Rauchmeldern und Türkontakten einen
Busch-Watchdog.
"""
from __future__ import annotations
import os
import sys
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from knix_arranger.models.building import GewerkAssignment, Room
from knix_arranger.models.group_address import GroupAddressStructure
from knix_arranger.services.sensor_service import (
    SensorService, element_sensor_types, label_sensor_type, set_sensor_type,
)

WATCHDOG = {"manufacturer": "ABB", "order_number": "6131/40-500",
            "product_name": "6131/40-500 Busch-Watchdog Sky", "com_objects": []}
LEAK = {"manufacturer": "Elsner", "order_number": "70316",
        "product_name": "Leak KNX 2.0", "com_objects": []}


@pytest.mark.parametrize("label, expected", [
    ("Rauchmelder", "Rauchmelder"),
    ("Wassermelder", "Wassermelder"),
    ("Leckage Keller", "Wassermelder"),
    ("Schlüsselkontakt Türe", "Türkontakt"),
    ("Fensterkontakt Bad", "Fensterkontakt"),
    ("Riegelkontakt", "Riegelkontakt"),
    ("Magnetkontakt Tor", "Magnetkontakt"),
    ("Bewegung Eingang", "Bewegungsmelder"),
    ("Sirene", None),
    ("", None),
])
def test_label_sensor_type(label, expected):
    assert label_sensor_type(label) == expected


def _technik() -> Room:
    room = Room(number="CUG02", name="Technik")
    a = GewerkAssignment(gewerk_code="A", count=2)
    a.set_element_labels(["Rauchmelder", "Wassermelder"])
    room.gewerk_assignments = [a]
    return room


def test_elements_of_different_type_become_own_devices():
    room = _technik()
    reqs = SensorService().determine_sensors([room], None)
    assert sorted((r.sensor_type, r.count) for r in reqs) == [
        ("Rauchmelder", 1), ("Wassermelder", 1)]

    SensorService().auto_assign_functions([room], GroupAddressStructure())
    found = {be.element_type: [sf.element_number for sf in be.funktionen]
             for be in room.bedienelemente}
    assert found == {"Rauchmelder": [1], "Wassermelder": [2]}


def test_label_beats_gewerk_type_neutral_without_label():
    """Der Typ des Gewerks (früher von Gebäude › Sensortyp für alle Elemente
    gesetzt) gilt nur für Elemente ohne erkennbare Bezeichnung."""
    room = _technik()
    a = room.gewerk_assignments[0]
    a.sensor_type_override = "Rauchmelder"
    a.count = 3
    assert element_sensor_types(room, a, 1, "Sensor") == {
        "Rauchmelder": [1, 3], "Wassermelder": [2]}
    a.sensor_type_override = None
    assert element_sensor_types(room, a, 1, "Sensor")["Sensor"] == [3]


def test_sensor_type_applies_to_its_elements_only():
    room = _technik()
    SensorService().auto_assign_functions([room], GroupAddressStructure())
    water = next(be for be in room.bedienelemente if be.element_type == "Wassermelder")

    assert set_sensor_type(room, water, "Sensor")

    a = room.gewerk_assignments[0]
    assert a.element_sensor_types == {2: "Sensor"} and a.sensor_type_override is None
    assert element_sensor_types(room, a, 1, "Sensor") == {"Rauchmelder": [1], "Sensor": [2]}


def test_element_sensor_types_saved():
    a = GewerkAssignment(gewerk_code="A", count=2, element_sensor_types={2: "Sensor"})
    assert GewerkAssignment.from_dict(a.to_dict()).element_sensor_types == {2: "Sensor"}


def test_validation_warns_on_unfitting_product(gewerk_catalog):
    from knix_arranger.models.project import KnxProject
    from knix_arranger.services.product_sync import product_kind_conflicts
    room = _technik()
    a = room.gewerk_assignments[0]
    a.element_products = {1: dict(WATCHDOG), 2: dict(LEAK)}
    project = KnxProject(name="Test")
    with patch.object(KnxProject, "all_rooms", new=property(lambda self: [room])):
        conflicts = product_kind_conflicts(project)
    assert [(c.sensor_type, c.product_name) for c in conflicts] == [
        ("Rauchmelder", WATCHDOG["product_name"])]


def test_takeover_asks_before_unfitting_elements():
    """Typ-Batch: der Watchdog geht auf den Bewegungsmelder, für den
    Rauchmelder nur nach Bestätigung (Standard Nein)."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    from knix_arranger.services.product_sync import ProductMismatch
    from knix_arranger.ui.dialogs.product_sync_dialog import _without_unfitting
    QApplication.instance() or QApplication([])
    room = Room(number="CEG05", name="Garage")
    a = GewerkAssignment(gewerk_code="A", count=2)
    a.set_element_labels(["Bewegung Einfahrt", "Rauchmelder"])
    room.gewerk_assignments = [a]
    mismatches = [ProductMismatch(None, room, a, 1), ProductMismatch(None, room, a, 2)]

    with patch.object(QMessageBox, "warning", return_value=QMessageBox.No) as ask:
        kept = _without_unfitting(None, mismatches, dict(WATCHDOG))

    assert ask.called
    assert [m.element_nr for m in kept] == [1]
