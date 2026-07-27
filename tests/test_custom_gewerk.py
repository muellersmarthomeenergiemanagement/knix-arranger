"""
Tests fuer benutzerdefinierte Gewerke (FA-303): Persistenz mit dem Projekt und
generische Gruppenadress-Erzeugung fuer Gewerke ausserhalb des Standard-
Katalogs (z.B. Fremdsystem-Gateways wie eine Musikanlage).
"""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.project import KnxProject
from knix_arranger.models.gewerk import Gewerk, GewerkCatalog
from knix_arranger.models.building import GewerkAssignment
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.ui.dialogs.custom_gewerk_dialog import CustomGewerkDialog


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _musikanlage_gewerk() -> Gewerk:
    return Gewerk(
        code="MU", name="Musikanlage",
        ga_count=5, block_size=5,
        middle_group=4, category="allgemein",
        interface_type="gateway",
    )


def test_add_custom_gewerk_available_in_catalog():
    project = KnxProject(name="Test")
    assert project.gewerk_catalog.get("MU") is None

    project.add_custom_gewerk(_musikanlage_gewerk())

    gewerk = project.gewerk_catalog.get("MU")
    assert gewerk is not None
    assert gewerk.name == "Musikanlage"
    assert gewerk.is_custom is True
    assert gewerk.interface_type == "gateway"


def test_custom_gewerk_survives_save_load_roundtrip():
    project = KnxProject(name="Test")
    project.add_custom_gewerk(_musikanlage_gewerk())

    data = project.to_dict()
    restored = KnxProject.from_dict(data)

    gewerk = restored.gewerk_catalog.get("MU")
    assert gewerk is not None
    assert gewerk.name == "Musikanlage"
    assert gewerk.is_custom is True
    # Standard-Katalog bleibt daneben vollstaendig vorhanden
    assert restored.gewerk_catalog.get("L") is not None


def test_custom_gewerk_generates_real_group_addresses(simple_efh):
    """Der eigentliche Nutzen: einmal angelegt, generiert ein eigenes Gewerk
    genau wie jedes Standard-Gewerk automatisch Gruppenadressen -- nur die
    automatische Aktor-/Produktvorschlags-Logik (separat, hartcodiert)
    funktioniert dafuer bewusst nicht."""
    project = KnxProject(name="Test")
    project.areal = simple_efh
    project.add_custom_gewerk(_musikanlage_gewerk())

    room = simple_efh.all_rooms[0]
    room.gewerk_assignments.append(GewerkAssignment(gewerk_code="MU", count=1))

    generator = AddressGenerator(project.gewerk_catalog, variant="A")
    structure = generator.generate(simple_efh)

    mu_gas = [ga for ga in structure.all_addresses() if ga.gewerk_code == "MU"]
    assert mu_gas, "Für das eigene Gewerk MU wurden keine Gruppenadressen erzeugt"
    assert all(ga.designation.startswith("MU_") for ga in mu_gas)
    assert all(ga.middle_group == 4 for ga in mu_gas)  # eigene Mittelgruppe übernommen


class TestCustomGewerkDialogValidation:
    """FA-303: Der Dialog darf kein Gewerk mit leerem/ungültigem/bereits
    vergebenem Kürzel erzeugen -- sonst würde ein Standard-Gewerk überschrieben."""

    def _catalog(self) -> GewerkCatalog:
        catalog = GewerkCatalog()
        catalog.load_defaults()
        return catalog

    @pytest.fixture(autouse=True)
    def _suppress_warning_popup(self, monkeypatch):
        # QMessageBox.warning() blockiert im echten Betrieb auf Nutzerklick --
        # ohne Unterdrueckung wuerde der Test beim erwarteten Validierungsfehler haengen.
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)

    def test_rejects_empty_code(self):
        dlg = CustomGewerkDialog(self._catalog())
        dlg._code_edit.setText("")
        dlg._name_edit.setText("Musikanlage")
        dlg._on_accept()
        assert dlg.get_gewerk() is None

    def test_rejects_non_alpha_code(self):
        dlg = CustomGewerkDialog(self._catalog())
        dlg._code_edit.setText("M1")
        dlg._name_edit.setText("Musikanlage")
        dlg._on_accept()
        assert dlg.get_gewerk() is None

    def test_rejects_existing_code(self):
        """'L' (Licht) existiert bereits im Standard-Katalog -- darf nicht
        überschrieben werden."""
        dlg = CustomGewerkDialog(self._catalog())
        dlg._code_edit.setText("L")
        dlg._name_edit.setText("Irgendwas")
        dlg._on_accept()
        assert dlg.get_gewerk() is None

    def test_accepts_valid_new_code(self):
        dlg = CustomGewerkDialog(self._catalog())
        dlg._code_edit.setText("mu")  # Kleinschreibung -- muss auf MU normalisiert werden
        dlg._name_edit.setText("Musikanlage")
        dlg._on_accept()
        gewerk = dlg.get_gewerk()
        assert gewerk is not None
        assert gewerk.code == "MU"
        assert gewerk.name == "Musikanlage"
