"""
Tests fuer LinkingMatrixView Zell-Bearbeitung (FA-2503).

Deckt die Editierbarkeits-Regeln ab: direkte GA-Zuordnungen (Variante 2) und
leere Zellen sind editierbar, gewerk-basierte (Variante 1) und mehrdeutige
Zellen sind gesperrt. Sowie: eine Bearbeitung uebersteht den Refresh-Zyklus.
Die Ansicht selbst berechnet nichts; wie beim Oeffnen eines Projekts wird
vorher refresh_bedienelemente() aufgerufen (_open).
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
from knix_arranger.services.sensor_service import refresh_bedienelemente
from knix_arranger.ui.views.linking_matrix_view import LinkingMatrixView, _S_COL


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


def _open(project: KnxProject) -> LinkingMatrixView:
    """Wie MainWindow.open_file: erst Tastenbelegung ableiten, dann anzeigen."""
    refresh_bedienelemente(project)
    view = LinkingMatrixView()
    view.set_project(project)
    return view


def _ga(sub: int, gewerk: str, desig: str) -> GroupAddress:
    return GroupAddress(
        main_group=1, middle_group=0, sub_group=sub,
        designation=desig, gewerk_code=gewerk,
        room_number="E01", datapoint_type="DPST-1-1",
    )


class TestDoppelklickOeffnetBauherrenberatung:
    """Die Matrix ist die Übersicht -- Doppelklick springt zum Taster in der
    Bauherrenberatung, dort wird bearbeitet."""

    def test_doppelklick_meldet_bedienelement(self):
        ga1 = _ga(0, "L", "L_E01_01 E/A")
        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2",
                           is_auto=False, funktionen=[
                               SensorFunktion(label="Taste 1", ga_designation=ga1.designation)])
        project, _ = _make_project(be, [ga1])
        view = _open(project)
        opened = []
        view.open_in_bauherr.connect(opened.append)

        view._on_sensor_cell_double_clicked(0, 0)

        assert opened == [be.id]
        assert be.funktionen[0].ga_designation == ga1.designation   # nichts geändert

    def test_ohne_bedienelement_hinweis_statt_sprung(self):
        from knix_arranger.services.belegungsplan_service import BelegungsplanData, SensorRow
        view = LinkingMatrixView()
        view._belegungsplan = BelegungsplanData(project_name="T", sensor_rows=[SensorRow(
            floor_name="EG", zone_name="", room_number="01", room_name="Flur",
            sensor_type="Sensor", physical_address="1.1.9", taste_label="-",
            function="", ga_designation="", ga_address="", dpt="",
        )], actor_rows=[])
        view._fill_sensor_tab()
        opened = []
        view.open_in_bauherr.connect(opened.append)

        with patch("knix_arranger.ui.views.linking_matrix_view.QMessageBox.information") as msg:
            view._on_sensor_cell_double_clicked(0, 0)

        assert opened == []
        msg.assert_called_once()


class TestLangerTastendruck:
    """Langer Tastendruck gehört zu seiner Taste (SensorFunktion.press_of)."""

    def test_eigene_zeile_mit_etsname_ohne_nummernverschiebung(self):
        gas = [_ga(i, "L", f"L_E01_0{i} E/A") for i in range(3)]
        t1 = SensorFunktion(ga_designation=gas[0].designation)
        t2 = SensorFunktion(ga_designation=gas[1].designation)
        lang = SensorFunktion(ga_designation=gas[2].designation, press_of=t1.id,
                              action_type="lang")
        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2",
                           is_auto=False, funktionen=[t1, lang, t2])
        project, _ = _make_project(be, gas)

        view = _open(project)

        assert [rk[1] for rk in view._sensor_row_order] == [
            "Taste 1", "Taste 1 (langer Tastendruck)", "Taste 2"]
        fa = next(f for f in be.function_assignments if f.sf_id == lang.id)
        assert fa.action_type == "lang"

    def test_offener_langer_tastendruck_erscheint_unter_seiner_taste(self):
        """Regression "Test Musik": ein langer Tastendruck mit freiem Wunsch
        (noch ohne GA) fehlte in der Matrix."""
        ga1 = _ga(0, "L", "L_E01_01 E/A")
        t1 = SensorFunktion(ga_designation=ga1.designation)
        t2 = SensorFunktion(label="Taste 2")
        wunsch = SensorFunktion(label="DALI Licht", press_of=t1.id, action_type="lang")
        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2",
                           is_auto=False, funktionen=[t1, t2, wunsch])
        project, _ = _make_project(be, [ga1])

        view = _open(project)

        assert [rk[1] for rk in view._sensor_row_order] == [
            "Taste 1", "Taste 1 (langer Tastendruck)", "Taste 2"]

    def test_importierter_langer_tastendruck_wird_erkannt(self):
        from knix_arranger.models.building import is_long_press, long_press_of
        kurz = SensorFunktion(label="Taste 2, links", ga_designation="a")
        lang = SensorFunktion(label="Taste 2, links (langer Tastendruck)", ga_designation="b")
        andere = SensorFunktion(label="Taste 3 (langer Tastendruck)", ga_designation="c")
        funktionen = [kurz, lang, andere]

        assert long_press_of(funktionen, kurz) is lang
        assert is_long_press(funktionen, lang)
        assert not is_long_press(funktionen, andere)   # ohne passende Taste: eigene Taste

    def test_bauherr_formular_zaehlt_langen_tastendruck_nicht_als_taste(self):
        from knix_arranger.services.bauherr_form_service import button_funktionen
        t1 = SensorFunktion(label="Taste 1")
        lang = SensorFunktion(press_of=t1.id, action_type="lang")
        t2 = SensorFunktion(label="Taste 2")
        be = Bedienelement(element_type="Tastereinheit", funktionen=[t1, lang, t2])

        assert button_funktionen(be) == [t1, t2]

    def test_press_of_wird_gespeichert(self):
        lang = SensorFunktion(press_of="abc", action_type="lang")
        assert SensorFunktion.from_dict(lang.to_dict()).press_of == "abc"
        assert "press_of" not in SensorFunktion().to_dict()


# ---------------------------------------------------------------------------
# Raum-Filter -- Regression: Raumnummern wiederholen sich pro Stockwerk (z.B.
# "01" auf UG UND EG, siehe project_reconcile_service). Ein Filter, der nur
# nach der Raumnummer vergleicht, zeigt beim Auswählen eines Raums faelschlich
# auch die Zeilen des gleichnummerigen Raums auf einem anderen Stockwerk.
# ---------------------------------------------------------------------------

class TestRoomFilterDisambiguatesSameNumberAcrossFloors:
    def _view_with_two_same_numbered_rooms(self) -> LinkingMatrixView:
        from knix_arranger.services.belegungsplan_service import (
            BelegungsplanData, SensorRow, ActorRow,
        )

        sensor_rows = [
            SensorRow(
                floor_name="UG", zone_name="Haus", room_number="01", room_name="Technikraum",
                sensor_type="Sensor", physical_address="1.1.24", taste_label="Alarm",
                function="Leckage Alarm", ga_designation="", ga_address="0/0/1", dpt="1 bit",
                gewerk_code="AK",
            ),
            SensorRow(
                floor_name="EG", zone_name="Haus", room_number="01", room_name="Carnotzet",
                sensor_type="Tastereinheit", physical_address="1.1.41", taste_label="Taste 1",
                function="Licht schalten", ga_designation="", ga_address="0/0/2", dpt="1 bit",
                gewerk_code="L",
            ),
        ]
        data = BelegungsplanData(project_name="Test", sensor_rows=sensor_rows, actor_rows=[])

        view = LinkingMatrixView()
        view._belegungsplan = data
        view._fill_sensor_tab()
        view._fill_actor_tab()
        view._populate_room_filter()
        return view

    def test_room_filter_entries_carry_number_and_name(self):
        view = self._view_with_two_same_numbered_rooms()
        entries = [
            (view._room_filter.itemText(i), view._room_filter.itemData(i))
            for i in range(view._room_filter.count())
        ]
        assert ("01  Technikraum", ("01", "Technikraum")) in entries
        assert ("01  Carnotzet", ("01", "Carnotzet")) in entries

    def test_selecting_one_room_hides_the_other_same_numbered_room(self):
        view = self._view_with_two_same_numbered_rooms()
        idx = view._room_filter.findText("01  Carnotzet")
        assert idx >= 0
        view._room_filter.setCurrentIndex(idx)
        view._apply_filter()

        tbl = view._sensor_table
        visible_rooms = [
            tbl.item(r, _S_COL["Raumname"]).text()
            for r in range(tbl.rowCount())
            if not tbl.isRowHidden(r)
        ]
        assert visible_rooms == ["Carnotzet"]
