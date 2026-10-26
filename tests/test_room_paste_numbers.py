"""Schritt 3: eingefügte Räume erhalten Raumnummern im Schema der Ziel-Zone
und des Ziel-Stockwerks (Projekt «Test Siemens»: vorher überall EG01–EG06)."""
from __future__ import annotations
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.project import KnxProject
from knix_arranger.services.room_numbering import room_number_warnings

NAMES = ["Eingang", "Küche", "Wohnzimmer", "Bad", "Kinderzimmer", "Schlafzimmer"]


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _project() -> KnxProject:
    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=1)
    og = Floor(name="1. Obergeschoss", short_code="1.OG", main_group_number=2)
    eg.apartments = [
        Apartment(name="Zone 1", rooms=[
            Room(number=f"EG{i:02d}", name=n, floor_id=eg.id) for i, n in enumerate(NAMES, 1)]),
        Apartment(name="Zone 2"),
    ]
    og.apartments = [Apartment(name="Zone 3"), Apartment(name="Zone 4")]
    project = KnxProject(name="Test Siemens")
    project.areal = Areal(buildings=[Building(name="Test Siemens", wings=[Wing(floors=[eg, og])])])
    return project


def _step(project, monkeypatch):
    from knix_arranger.ui.wizard.step03_rooms import Step03Rooms
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    step = Step03Rooms(project)
    step.on_enter()
    return step, warnings


def _numbers(apt) -> list[str]:
    return [r.number for r in apt.rooms]


def test_zone_kopieren_und_einfuegen(monkeypatch):
    from knix_arranger.ui.wizard.step03_rooms import _KIND_ZONE
    project = _project()
    step, warnings = _step(project, monkeypatch)
    eg, og = project.areal.buildings[0].wings[0].floors
    zone1, zone2 = eg.apartments
    zone3, zone4 = og.apartments

    step._select_by_data(_KIND_ZONE, "Zone 1")
    step._copy_zone()
    for target in ("Zone 2", "Zone 3", "Zone 4"):
        step._select_by_data(_KIND_ZONE, target)
        step._paste_zone()

    assert _numbers(zone2) == [f"EG{i:02d}" for i in range(7, 13)]
    assert _numbers(zone3) == [f"1.OG{i:02d}" for i in range(1, 7)]
    assert _numbers(zone4) == [f"1.OG{i:02d}" for i in range(7, 13)]
    assert [r.name for r in zone4.rooms] == NAMES
    assert warnings == []
    assert not any(room_number_warnings(project.areal, r) for r in project.areal.all_rooms)


def test_stockwerk_einfuegen_mit_zonenpraefix(monkeypatch):
    from knix_arranger.ui.wizard.step03_rooms import _KIND_ZONE_FLOOR
    project = _project()
    eg, og = project.areal.buildings[0].wings[0].floors
    zone1, zone2 = eg.apartments
    for i, room in enumerate(zone1.rooms, 1):
        room.number = f"S-EG{i:02d}"                   # Zone 1 mit Präfix S
    step, warnings = _step(project, monkeypatch)

    step._select_by_data(_KIND_ZONE_FLOOR, zone1)
    step._copy_floor()
    step._select_by_data(_KIND_ZONE_FLOOR, zone2)
    step._paste_floor()
    # Neue Zone im Projekt mit Präfixen: erster freier Buchstabe des Namens
    assert _numbers(zone2) == [f"Z-EG{i:02d}" for i in range(1, 7)]
    assert warnings == []
