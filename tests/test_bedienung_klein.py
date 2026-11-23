"""Kleinere Bedienpunkte: direkte Dateiauswahl beim Import, Wizard nach
«Neues Projekt», Erklärung der MG-Variante, Schrittstatus im Wizard."""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel  # noqa: E402

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing  # noqa: E402
from knix_arranger.models.group_address import (  # noqa: E402
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    return QApplication.instance() or QApplication([])


# ── Import: direkt die Dateiauswahl ──────────────────────────────────────

def test_dateityp_nach_endung():
    from knix_arranger.ui.dialogs.import_dialog import file_type
    assert file_type("C:/x/Chalet.KNXPROJ") == "knxproj"
    assert file_type("report.xlsx") == "xlsx"
    assert file_type("ga.csv") == "csv"


def test_dateiauswahl_liefert_pfad_und_typ(monkeypatch):
    from knix_arranger.ui.dialogs import import_dialog
    calls = []

    def fake(parent, title, start, filters):
        calls.append((start, filters))
        return ("C:/Projekte/Chalet.knxproj", "")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake))
    assert import_dialog.choose_import_file(None, "C:/Projekte/Chalet/Import") == \
        ("C:/Projekte/Chalet.knxproj", "knxproj")
    assert calls[0][0] == "C:/Projekte/Chalet/Import"
    assert calls[0][1].index("*.knxproj") < calls[0][1].index("*.csv")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a: ("", "")))
    assert import_dialog.choose_import_file(None) == ("", "")


# ── Neues Projekt ────────────────────────────────────────────────────────

def test_neues_projekt_erklaert_variante_und_bietet_wizard():
    from knix_arranger.ui.dialogs.new_project_dialog import NewProjectDialog
    dialog = NewProjectDialog()
    assert dialog.start_wizard is True
    texts = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Mittelgruppen 6/7" in texts and "Schritt 9" in texts
    dialog._start_wizard.setChecked(False)
    assert dialog.start_wizard is False


def test_wizard_knopf_ohne_projekt_startet_wizard_nur_einmal(monkeypatch):
    """Knopf «Wizard» ohne offenes Projekt: _new_project darf den Wizard nicht
    selbst starten, sonst liefe er zweimal."""
    from knix_arranger.ui.main_window import MainWindow
    calls = []

    def new_project(offer_wizard=True):
        calls.append(offer_wizard)

    fake = SimpleNamespace(_project=None, _new_project=new_project)
    MainWindow._start_wizard(fake)
    assert calls == [False]


# ── Schrittstatus im Wizard ──────────────────────────────────────────────

def _project(rooms_per_zone=(1, 1), with_gas=0) -> KnxProject:
    zones = [Apartment(name=f"Z{i}", rooms=[Room(name=f"R{i}{j}", number=f"{i}{j}")
                                          for j in range(n)])
             for i, n in enumerate(rooms_per_zone)]
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="EG", short_code="EG", apartments=zones)])])])
    mg = MiddleGroup(number=1, name="L", group_addresses=[
        GroupAddress(main_group=1, middle_group=1, sub_group=i) for i in range(with_gas)])
    project.group_addresses = GroupAddressStructure(
        main_groups=[MainGroup(number=1, name="EG", middle_groups=[mg])] if with_gas else [])
    return project


def _status(project, step):
    from knix_arranger.ui.wizard.wizard_controller import WizardController
    return WizardController(project)._step_status(step)


def test_raeume_vollstaendig_wenn_jede_zone_einen_raum_hat():
    assert _status(_project((1,)), 2) == "complete"          # ein Raum genügt (vorher ab 2)
    assert _status(_project((2, 0)), 2) == "partial"         # Zone ohne Raum
    assert _status(_project((0,)), 2) == "empty"


def test_gruppenadressen_vollstaendig_sobald_erzeugt():
    assert _status(_project(with_gas=3), 8) == "complete"    # vorher erst ab 10
    assert _status(_project(), 8) == "empty"
