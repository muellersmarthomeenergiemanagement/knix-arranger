"""
Tests fuer den Klartext je Gewerk-Element (FA-403): "LDA x2" mit
"Decke" / "Wand" muss in jeder GA-Bezeichnung des Elements nach dem
Raumnamen stehen, die Neuberechnung ueberstehen und in
Schritt 5 bearbeitbar sein.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.address_generator import (
    AddressGenerator, regenerate_addresses,
)


def _areal(assignment: GewerkAssignment) -> Areal:
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    apt = Apartment(name="EG")
    room = Room(number="E01", name="Wohnen")
    room.gewerk_assignments.append(assignment)
    apt.rooms.append(room)
    floor.apartments.append(apt)
    wing.floors.append(floor)
    building.wings.append(wing)
    areal.buildings.append(building)
    return areal


def _gas(structure, code: str):
    return [ga for ga in structure.all_addresses()
            if ga.gewerk_code == code and ga.room_number and not ga.is_placeholder]


class TestModel:
    def test_roundtrip(self):
        ga = GewerkAssignment(gewerk_code="LDA", count=2)
        ga.set_element_labels(["Decke", "Wand"])
        restored = GewerkAssignment.from_dict(ga.to_dict())
        assert restored.element_labels == ["Decke", "Wand"]
        assert restored.element_label(2) == "Wand"
        assert restored.element_label(3) == ""

    def test_old_file_without_labels(self):
        restored = GewerkAssignment.from_dict({"gewerk_code": "L"})
        assert restored.element_labels == []
        assert restored.element_label(1) == ""

    def test_set_labels_cleans_input(self):
        ga = GewerkAssignment(gewerk_code="L", count=3)
        ga.set_element_labels([" Decke ", "", "Wand (links)", " ", ""])
        # Klammern begrenzen den Klartext in der Bezeichnung -> entfernt
        assert ga.element_labels == ["Decke", "", "Wand links"]

    def test_room_suffix(self):
        assignment = GewerkAssignment(gewerk_code="LDA", count=2)
        assignment.set_element_labels(["Decke"])
        room = Room(number="E01", name="Wohnen", gewerk_assignments=[assignment])
        assert room.gewerk_element_suffix("LDA", 1, True) == " (Decke)"
        assert room.gewerk_element_suffix("LDA", 2, True) == " #2"
        assert room.gewerk_element_suffix("LDA", 2, False) == ""


class TestDesignation:
    @pytest.mark.parametrize("variant", ["A", "B"])
    def test_label_in_every_ga_of_element(self, gewerk_catalog, variant):
        assignment = GewerkAssignment(gewerk_code="LD", count=2)
        assignment.set_element_labels(["Decke", "Wand"])
        structure = AddressGenerator(gewerk_catalog, variant=variant).generate(
            _areal(assignment))

        gas = _gas(structure, "LD")
        assert gas
        for ga in gas:
            expected = "(Wohnen Decke)" if ga.element_number == 1 else "(Wohnen Wand)"
            assert ga.designation.endswith(expected), ga.designation
        assert any(g.designation == "LD_E01_01 E/A (Wohnen Decke)" for g in gas)

    def test_without_label_room_name_in_every_ga(self, gewerk_catalog):
        assignment = GewerkAssignment(gewerk_code="J", count=1)
        structure = AddressGenerator(gewerk_catalog).generate(_areal(assignment))
        gas = _gas(structure, "J")
        assert len(gas) > 1
        assert all(ga.designation.endswith("(Wohnen)") for ga in gas)

    def test_label_change_renames_in_place(self, gewerk_catalog):
        assignment = GewerkAssignment(gewerk_code="LD", count=1)
        project = KnxProject(name="Test")
        project.areal = _areal(assignment)
        regenerate_addresses(project)
        before = {ga.id: ga.address for ga in _gas(project.group_addresses, "LD")}

        assignment.set_element_labels(["Decke"])
        regenerate_addresses(project)

        after = _gas(project.group_addresses, "LD")
        # Adressen bleiben, nur die Bezeichnung ändert sich
        assert {ga.id: ga.address for ga in after} == before
        assert all(ga.designation.endswith("(Wohnen Decke)") for ga in after)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestStep05Column:
    def test_edit_labels_in_table(self, qapp):
        from knix_arranger.ui.wizard.step05_gewerke import Step05Gewerke, _COL_LABEL

        assignment = GewerkAssignment(gewerk_code="LDA", count=2)
        project = KnxProject(name="Test")
        project.areal = _areal(assignment)
        step = Step05Gewerke(project)
        step._refresh_table()

        item = step._table.item(0, _COL_LABEL)
        assert item.text() == ""
        item.setText("Decke;Wand ")
        assert assignment.element_labels == ["Decke", "Wand"]
        assert step._table.item(0, _COL_LABEL).text() == "Decke; Wand"

    def test_tooltip_mapping_warning_and_width(self, qapp):
        from knix_arranger.ui.styles import COLOR_WARNING
        from knix_arranger.ui.wizard.step05_gewerke import (
            Step05Gewerke, _COL_COUNT, _COL_LABEL, _LABEL_MIN_WIDTH,
        )

        assignment = GewerkAssignment(gewerk_code="J", count=3)
        project = KnxProject(name="Test")
        project.areal = _areal(assignment)
        step = Step05Gewerke(project)
        step._refresh_table()
        assert step._table.columnWidth(_COL_LABEL) >= _LABEL_MIN_WIDTH

        step._table.item(0, _COL_LABEL).setText("; Süd; West; Ost")
        item = step._table.item(0, _COL_LABEL)
        tip = item.toolTip()
        assert "01  – (nur Raumname)" in tip and "02  Süd" in tip and "03  West" in tip
        assert "J_E01_02 … (Wohnen Süd)" in tip
        assert "«Ost» wird nicht verwendet" in tip
        assert item.foreground().color().name().upper() == COLOR_WARNING.upper()

        # Anzahl erhöhen: Ost wird Element 04, Warnung verschwindet
        step._table.item(0, _COL_COUNT).setText("4")
        item = step._table.item(0, _COL_LABEL)
        assert "04  Ost" in item.toolTip()
        assert "nicht verwendet" not in item.toolTip()
        assert item.foreground().color().name().upper() != COLOR_WARNING.upper()


class TestProduktJeElementSchritt5:
    """Schritt 5: «Produkt…» fragt bei mehreren Elementen, wofür es gilt."""

    @pytest.fixture(autouse=True)
    def _app(self):
        yield QApplication.instance() or QApplication([])

    def _step(self, assignment):
        from knix_arranger.ui.wizard.step05_gewerke import Step05Gewerke
        project = KnxProject(name="Test")
        project.areal = _areal(assignment)
        return Step05Gewerke(project)

    def test_auswahl_element_und_entfernen(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QInputDialog
        lp = {"manufacturer": "Elsner", "order_number": "70316",
              "product_name": "Leak KNX 2.0", "com_objects": []}
        assignment = GewerkAssignment(gewerk_code="A", count=2, element_products={2: lp})
        assignment.set_element_labels(["Rauchmelder", "Wassermelder"])
        step = self._step(assignment)
        captured = {}

        def pick(_parent, _title, _label, items, *_args):
            captured["items"] = items
            return items[2], True              # Element 2
        with patch.object(QInputDialog, "getItem", side_effect=pick):
            assert step._choose_product_target(assignment) == (2, "")
        assert captured["items"][0] == "Alle Elemente"
        assert captured["items"][1] == "Element 1 Rauchmelder  ·  wie alle Elemente"
        assert captured["items"][2] == \
            "Element 2 Wassermelder  ·  eigenes: Elsner 70316 – Leak KNX 2.0"
        assert captured["items"][3] == "Element 2 Wassermelder: eigenes Produkt entfernen"

        with patch.object(QInputDialog, "getItem",
                          return_value=(captured["items"][3], True)), \
                patch.object(step, "_regenerate_gas"):
            step._select_product(None, assignment)
        assert assignment.element_products == {}

    def test_produkt_fuer_alle_entfernen(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog, QInputDialog
        from knix_arranger.ui.dialogs.com_object_select_dialog import ComObjectSelectDialog
        co = {"number": 2, "name": "Leckage Alarm", "function_text": "Leckage Alarm",
              "datapoint_type": "DPST-1-1", "communication_flag": True,
              "transmit_flag": True}
        lp = {"manufacturer": "Elsner", "order_number": "70316",
              "product_name": "Leak KNX 2.0", "com_objects": [co]}
        # mehrere Elemente: Eintrag in der Auswahl
        assignment = GewerkAssignment(gewerk_code="A", count=2, linked_product=dict(lp))
        step = self._step(assignment)
        with patch.object(QInputDialog, "getItem",
                          return_value=("Alle Elemente: Produkt entfernen", True)), \
                patch.object(step, "_regenerate_gas"):
            step._select_product(None, assignment)
        assert assignment.linked_product is None
        # ein Element: Knopf im Dialog der Kommunikationsobjekte
        single = GewerkAssignment(gewerk_code="A", count=1, linked_product=dict(lp))
        step = self._step(single)

        def click_remove(dlg):
            assert dlg._btn_remove is not None
            dlg._btn_remove.click()
            return QDialog.Rejected
        with patch.object(ComObjectSelectDialog, "exec", click_remove), \
                patch.object(step, "_regenerate_gas"):
            step._select_product(None, single)
        assert single.linked_product is None


class TestGeraeteproduktInSchritt5:
    """FA-621: Schritt 5 bietet das Produkt des Sensor-Geräts zuoberst an."""

    @pytest.fixture(autouse=True)
    def _app(self):
        yield QApplication.instance() or QApplication([])

    def test_uebernehmen_zuoberst(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QInputDialog
        from tests.test_product_sync import _project
        from knix_arranger.ui.wizard.step05_gewerke import Step05Gewerke
        project, _room, assignment, _wasser = _project()
        step = Step05Gewerke(project)
        captured = {}

        def pick(_parent, _title, _label, items, *_args):
            captured["items"] = items
            return items[0], True
        with patch.object(QInputDialog, "getItem", side_effect=pick), \
                patch("knix_arranger.ui.dialogs.product_sync_dialog.take_over_device_product",
                      return_value=True) as take, \
                patch.object(step, "_regenerate_gas"):
            step._select_product(None, assignment)
        assert captured["items"][0].startswith(
            "Element 2 Wassermelder: Produkt von Gerät 1.2.113 übernehmen (Elsner 70316")
        assert take.call_args[0][1][0].element_nr == 2


def test_label_hint_example_with_floor():
    """Tooltip-Beispiel im Format der Bezeichnung: Stockwerk bei reinen Nummern."""
    from knix_arranger.models.building import GewerkAssignment
    from knix_arranger.ui.wizard.step05_gewerke import label_hint
    ga = GewerkAssignment(gewerk_code="J", count=2, element_labels=["", "Süd"])
    assert "J_DG_04_02 … (Schlafen Süd)" in label_hint(ga, "04", "Schlafen", "DG")[0]
    assert "J_E01_02 … (Schlafen Süd)" in label_hint(ga, "E01", "Schlafen", "EG")[0]
