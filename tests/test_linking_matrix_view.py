"""
Tests fuer LinkingMatrixView Zell-Bearbeitung (FA-2503).

Deckt die Editierbarkeits-Regeln ab: direkte GA-Zuordnungen (Variante 2) und
leere Zellen sind editierbar, gewerk-basierte (Variante 1) und mehrdeutige
Zellen sind gesperrt. Sowie: eine Bearbeitung uebersteht den Refresh-Zyklus
(belegungsplan_service.generate() -> auto_assign_functions()).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from unittest.mock import patch

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room,
    Bedienelement, FunctionAssignment, SensorFunktion,
)
from knix_arranger.models.topology import Topology, Area, Line
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.ui.views.linking_matrix_view import LinkingMatrixView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_project(be: Bedienelement, gas: list[GroupAddress]) -> tuple[KnxProject, Room]:
    room = Room(number="E01", name="Wohnzimmer")
    room.bedienelemente = [be]

    mg = MiddleGroup(number=0, name="Test")
    mg.group_addresses = gas
    hg = MainGroup(number=1, name="EG")
    hg.middle_groups = [mg]
    structure = GroupAddressStructure()
    structure.main_groups = [hg]

    apt = Apartment(name="WG")
    apt.rooms = [room]
    floor = Floor(name="EG", short_code="EG", main_group_number=1)
    floor.apartments = [apt]
    wing = Wing(name="Haupt")
    wing.floors = [floor]
    building = Building(name="Test")
    building.wings = [wing]
    areal = Areal(name="Test", buildings=[building])

    topo = Topology()
    line = Line(name="Linie 1", line_number=1)
    line.assigned_room_ids = [room.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    topo.areas = [area]

    project = KnxProject(name="MatrixEditTest")
    project.areal = areal
    project.topology = topo
    project.group_addresses = structure
    return project, room


def _ga(sub: int, gewerk: str, desig: str) -> GroupAddress:
    return GroupAddress(
        main_group=1, middle_group=0, sub_group=sub,
        designation=desig, gewerk_code=gewerk,
        room_number="E01", datapoint_type="DPST-1-1",
    )


class TestEditableSfForCell:
    """FA-2503: welche Zellen sind per Doppelklick editierbar."""

    def test_direkte_ga_zelle_ist_editierbar(self):
        ga1 = _ga(0, "L", "L_E01_01 E/A")
        sf = SensorFunktion(ga_designation=ga1.designation)
        be = Bedienelement(element_type="Tastereinheit", is_auto=False, funktionen=[sf])
        project, room = _make_project(be, [ga1])

        view = LinkingMatrixView()
        view._project = project
        fa = FunctionAssignment(button_channel="Taste 1", function_ga=ga1.designation, sf_id=sf.id)

        class Meta:
            be_id = be.id
        resolved = view._editable_sf_for_cell(Meta(), [fa])
        assert resolved is not None
        assert resolved[2] is sf

    def test_leere_zelle_ist_editierbar(self):
        be = Bedienelement(element_type="Tastereinheit", is_auto=False)
        project, room = _make_project(be, [])
        view = LinkingMatrixView()
        view._project = project

        class Meta:
            be_id = be.id
        resolved = view._editable_sf_for_cell(Meta(), None)
        assert resolved is not None
        assert resolved[2] is None   # keine bestehende SensorFunktion

    def test_gewerk_basierte_zelle_ist_gesperrt(self):
        sf = SensorFunktion(gewerk_code="L", element_number=1)
        be = Bedienelement(element_type="Tastereinheit", is_auto=False, funktionen=[sf])
        project, room = _make_project(be, [])
        view = LinkingMatrixView()
        view._project = project
        fa = FunctionAssignment(button_channel="Taste 1", function_ga="X", sf_id=sf.id)

        class Meta:
            be_id = be.id
        assert view._editable_sf_for_cell(Meta(), [fa]) is None

    def test_mehrdeutige_zelle_ist_gesperrt(self):
        be = Bedienelement(element_type="Tastereinheit", is_auto=False)
        project, room = _make_project(be, [])
        view = LinkingMatrixView()
        view._project = project
        fa1 = FunctionAssignment(button_channel="Taste 1", function_ga="X", sf_id="a")
        fa2 = FunctionAssignment(button_channel="Taste 1", function_ga="Y", sf_id="b")

        class Meta:
            be_id = be.id
        assert view._editable_sf_for_cell(Meta(), [fa1, fa2]) is None

    def test_ohne_be_id_ist_gesperrt(self):
        view = LinkingMatrixView()
        view._project = KnxProject(name="Leer")

        class Meta:
            be_id = ""
        assert view._editable_sf_for_cell(Meta(), None) is None


class TestDoppelklickEditFlow:
    """FA-2503/2504: End-zu-End -- Edit ueberlebt den Refresh-Zyklus."""

    def test_reassign_ueberlebt_refresh(self):
        ga1 = _ga(0, "L", "L_E01_01 E/A")
        ga2 = _ga(1, "J", "J_E01_01 auf/ab")
        sf = SensorFunktion(ga_designation=ga1.designation)
        be = Bedienelement(
            element_type="Tastereinheit", participant_number="1.1.2",
            is_auto=False, funktionen=[sf],
        )
        project, room = _make_project(be, [ga1, ga2])

        view = LinkingMatrixView()
        view.set_project(project)
        n_fixed = 7
        col_l = n_fixed + view._sensor_col_keys.index("L")

        with patch("knix_arranger.ui.views.linking_matrix_view.GaPickerDialog") as MockDlg:
            instance = MockDlg.return_value
            instance.exec.return_value = QDialog.Accepted
            instance.clear_requested = False
            instance.selected_ga = ga2
            view._on_sensor_cell_double_clicked(0, col_l)

        assert sf.ga_designation == ga2.designation
        assert be.is_auto is False

        # Nochmal refreshen (simuliert erneutes Oeffnen der Ansicht) -- Edit
        # darf nicht durch auto_assign_functions() verworfen werden.
        view._refresh()
        rk = view._sensor_row_order[0]
        entries = view._sensor_groups[rk]["cells"].get("J")
        assert entries is not None
        assert entries[0].ga_designation == ga2.designation

    def test_neue_zuordnung_erzeugt_spalte_nach_refresh(self):
        ga1 = _ga(0, "L", "L_E01_01 E/A")
        ga2 = _ga(1, "J", "J_E01_01 auf/ab")
        sf = SensorFunktion(ga_designation=ga1.designation)
        be = Bedienelement(
            element_type="Tastereinheit", participant_number="1.1.2",
            is_auto=False, funktionen=[sf],
        )
        project, room = _make_project(be, [ga1, ga2])

        view = LinkingMatrixView()
        view.set_project(project)
        assert view._sensor_col_keys == ["L"]

        meta = view._sensor_groups[view._sensor_row_order[0]]["meta"]
        resolved = view._editable_sf_for_cell(meta, None)
        room_r, be_r, sf_r = resolved
        assert sf_r is None
        be_r.funktionen.append(SensorFunktion(ga_designation=ga2.designation))
        be_r.is_auto = False

        view._refresh()
        assert "J" in view._sensor_col_keys
        assert len(be.funktionen) == 2

    def test_gesperrte_zelle_wird_ohne_aenderung_abgelehnt(self):
        sf = SensorFunktion(gewerk_code="L", element_number=1)
        be = Bedienelement(
            element_type="Tastereinheit", participant_number="1.1.2",
            is_auto=False, funktionen=[sf],
        )
        ga1 = _ga(0, "L", "L_E01_01 E/A")
        project, room = _make_project(be, [ga1])

        view = LinkingMatrixView()
        view.set_project(project)

        with patch("knix_arranger.ui.views.linking_matrix_view.QMessageBox.information") as mock_msg:
            with patch("knix_arranger.ui.views.linking_matrix_view.GaPickerDialog") as MockDlg:
                view._on_sensor_cell_double_clicked(0, 7)  # erste dynamische Spalte
                MockDlg.assert_not_called()
                mock_msg.assert_called_once()
        # funktionen unveraendert
        assert be.funktionen == [sf]
