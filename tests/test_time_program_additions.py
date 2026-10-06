"""
Zeitsteuerung: Duplizieren, eigene Vorlagen, Wochenraster, Datumsbereich,
DPT-Pruefung, Einfaerbung, Kuerzel [T], Feiertage, Zeitsteuerungsplan und
Abschnitt in der Bedienungsanleitung (FA-3302 bis FA-3307).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment, Room
from knix_arranger.models.project import KnxProject
from knix_arranger.models.time_program import (
    DayProfile, SwitchPoint, TimeProgram, WEEKDAY_MON, WEEKDAY_SAT,
)
from knix_arranger.services import time_program_service as tps
from knix_arranger.services.validation_engine import ValidationEngine


def _project() -> KnxProject:
    project = KnxProject(name="Test")
    room = Room(number="01", name="Wohnen")
    floor = Floor(name="Erdgeschoss", short_code="EG")
    floor.apartments = [Apartment(name="EG", rooms=[room])]
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    light = GroupAddress(main_group=1, middle_group=0, sub_group=0, gewerk_code="L",
                         room_number="01", room_id=room.id, designation="L_01_01 E/A (Wohnen)",
                         datapoint_type="DPST-1-1")
    blind = GroupAddress(main_group=1, middle_group=1, sub_group=0, gewerk_code="J",
                         room_number="01", room_id=room.id,
                         designation="J_01_01 AUF/AB (Wohnen)", datapoint_type="DPST-1-8")
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=1, name="EG", middle_groups=[
            MiddleGroup(number=0, name="Licht", group_addresses=[light]),
            MiddleGroup(number=1, name="Storen", group_addresses=[blind])])])
    tp = TimeProgram(name="Morgen", day_profiles=[DayProfile(
        weekday_mask=WEEKDAY_MON | WEEKDAY_SAT, switch_points=[
            SwitchPoint(fixed_time="07:00", target_ga_id=blind.id, action_value="0",
                        date_range_start="2026-04-01", date_range_end="2026-09-30"),
            SwitchPoint(fixed_time="07:30", target_ga_id=light.id, action_value="1"),
        ])])
    project.time_programs = [tp]
    return project


class TestService:
    def test_value_fits_dpt(self):
        assert tps.value_fits_dpt("1", "DPST-1-1")
        assert tps.value_fits_dpt("Aus", "1.001")
        assert not tps.value_fits_dpt("50", "DPST-1-1")
        assert tps.value_fits_dpt("50", "DPST-5-1")
        assert not tps.value_fits_dpt("150", "DPST-5-1")
        assert tps.value_fits_dpt("200", "DPST-5-4")
        assert not tps.value_fits_dpt("70", "DPST-17-1")
        assert tps.value_fits_dpt("21.5", "DPST-9-1")
        assert not tps.value_fits_dpt("warm", "DPST-9-1")
        assert tps.value_fits_dpt("irgendwas", "")

    def test_validation_marks_switch_points(self):
        project = _project()
        sps = project.time_programs[0].day_profiles[0].switch_points
        sps[1].action_value = "50"
        sps[0].target_ga_id = "weg"
        errors = tps.validate_all_programs(project)
        assert {(e.severity, e.sp_id) for e in errors} == {
            ("error", sps[0].id), ("warning", sps[1].id)}
        assert any("inkompatibel mit DPT DPST-1-1 der GA '1/0/0'" in e.message for e in errors)

    def test_engine_reports_fa3306(self):
        project = _project()
        project.time_programs[0].day_profiles[0].switch_points[1].action_value = "50"
        issues = ValidationEngine().validate(project.group_addresses, project=project)
        fa = [i for i in issues if i.rule_id == "FA-3306"]
        assert [(i.level, i.address) for i in fa] == [("warning", "1/0/0")]

    def test_duplicate_has_new_ids(self):
        project = _project()
        original = project.time_programs[0]
        copy_tp = tps.duplicate_program(project, original)
        assert copy_tp.name == "Morgen (Kopie)"
        assert copy_tp.id != original.id
        assert {sp.id for _, sp in copy_tp.all_switch_points}.isdisjoint(
            {sp.id for _, sp in original.all_switch_points})
        assert [sp.fixed_time for _, sp in copy_tp.all_switch_points] == ["07:00", "07:30"]

    def test_user_template_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        project = _project()
        tps.save_user_template(project.time_programs[0], "Mein Morgen")
        tps.save_user_template(project.time_programs[0], "Mein Morgen")   # ersetzt
        user = [t for t in tps.load_templates() if t.get("user")]
        assert [t["name"] for t in user] == ["Mein Morgen"]
        tp = tps.create_program_from_template(user[0]["id"])
        sps = [sp for _, sp in tp.all_switch_points]
        assert [sp.target_ga_id for sp in sps] == ["", ""]      # Ziel-GAs leer
        assert sps[0].date_range_start == "2026-04-01"
        assert tps.missing_target_count(tp) == 2

    def test_timed_ga_programs_only_active(self):
        project = _project()
        second = tps.duplicate_program(project, project.time_programs[0])
        second.name = "Ferien"
        programs = tps.timed_ga_programs(project)
        assert len(programs) == 2
        assert all(names == ["Morgen", "Ferien"] for names in programs.values())
        assert tps.timed_label(["Morgen"]) == "Zeitprogramm: Morgen"
        assert tps.timed_label(["Morgen", "Ferien"]) == "Zeitprogramme: Morgen, Ferien"
        for tp in project.time_programs:
            tp.active = False
        assert tps.timed_ga_programs(project) == {}

    def test_holiday_count(self):
        assert tps.holiday_count("CH", 2026) > 5


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class TestView:
    def test_week_grid_banner_and_colors(self, qapp):
        from knix_arranger.ui.views.time_program_view import TimeProgramView, _ERROR_BG
        project = _project()
        sps = project.time_programs[0].day_profiles[0].switch_points
        sps[0].target_ga_id = "weg"
        view = TimeProgramView(project)
        view._prog_table.setCurrentCell(0, 0)
        assert view._current_tp is project.time_programs[0]

        # Wochenraster: 07:00 Montag und Samstag
        assert "07:30 → 1  L_01_01 E/A" in view._week_table.item(7, 0).text()
        assert view._week_table.item(7, 5) is not None
        assert view._week_table.item(7, 1) is None

        # Fehlerzeile rot, Hinweisbalken
        assert view._sp_table.item(0, 0).background().color().name().upper() == _ERROR_BG
        assert not view._banner.isHidden()
        assert "1 Fehler" in view._banner.text()
        assert "01.04.2026 – 30.09.2026" == view._sp_table.item(0, 5).text()

    def test_rename_and_deactivate(self, qapp):
        from PySide6.QtCore import Qt
        from knix_arranger.ui.views.time_program_view import TimeProgramView
        project = _project()
        view = TimeProgramView(project)
        item = view._prog_table.item(0, 0)
        item.setText("Werktags früh")
        item.setCheckState(Qt.CheckState.Unchecked)
        qapp.processEvents()        # Liste wird nach dem Signal neu aufgebaut
        tp = project.time_programs[0]
        assert tp.name == "Werktags früh" and tp.active is False
        assert view._prog_table.item(0, 0).foreground().color().name().upper() == "#9E9E9E"

    def test_dialog_date_range_and_filter(self, qapp):
        from knix_arranger.ui.views.time_program_view import _SwitchPointDialog
        project = _project()
        sp = SwitchPoint()
        dlg = _SwitchPointDialog(sp, project)
        dlg._le_filter.setText("J_01")
        labels = [dlg._cb_ga.itemText(i) for i in range(dlg._cb_ga.count())]
        assert any("J_01_01" in t for t in labels)
        assert not any("L_01_01" in t for t in labels)
        assert any(t.startswith("── HG 1") for t in labels)
        dlg._cb_ga.setCurrentIndex(labels.index(next(t for t in labels if "J_01_01" in t)))
        dlg._chk_range.setChecked(True)
        dlg.apply_to(sp)
        assert sp.target_ga_id == project.group_addresses.main_groups[0].middle_groups[1] \
            .group_addresses[0].id
        assert sp.date_range_start and sp.date_range_end

        dlg._cb_type.setCurrentIndex(1)       # Astro
        assert dlg._astro_preview.text().startswith("Heute: Sonnenaufgang")


class TestAddressViews:
    def test_timed_marker(self, qapp):
        from knix_arranger.ui.views.address_table_view import AddressTableView
        from knix_arranger.ui.views.address_tree_view import AddressTreeView
        project = _project()
        timed = tps.timed_ga_programs(project)
        table = AddressTableView()
        table.set_timed_gas(timed)
        table.set_structure(project.group_addresses)
        notes_col = table.COLUMNS.index("Notizen")
        assert {table._table.item(r, notes_col).text() for r in range(2)} == {
            "Zeitprogramm: Morgen"}

        tree = AddressTreeView()
        tree.set_timed_gas(timed)
        tree.set_structure(project.group_addresses)
        ga_item = tree._tree.topLevelItem(0).child(0).child(0)
        assert ga_item.text(2) == "⏱"
        assert ga_item.toolTip(2) == "Zeitprogramm: Morgen"


class TestDocuments:
    def test_time_plan_and_manual_section(self, tmp_path):
        from knix_arranger.services.documentation_service import DocumentationService
        project = _project()
        svc = DocumentationService(project)
        plan = tmp_path / "plan.pdf"
        svc.generate_time_programs_doc(str(plan))
        with fitz.open(plan) as doc:
            text = " ".join("".join(p.get_text() for p in doc).split())
        assert "Zeitsteuerungsplan" in text and "01.04.2026 – 30.09.2026" in text

        manual = tmp_path / "anleitung.pdf"
        svc.generate_user_manual(str(manual))
        with fitz.open(manual) as doc:
            text = " ".join("".join(p.get_text() for p in doc).split())
        assert "Automatische Zeitsteuerung" in text
        assert "07:00 Uhr" in text and "Auf" in text and "01.04. – 30.09." in text
        assert "1/1/0" not in text           # keine GA-Nummern für den Bauherrn

        project.manual_settings.hidden = ["zeitsteuerung"]
        svc.generate_user_manual(str(manual))
        with fitz.open(manual) as doc:
            assert "Automatische Zeitsteuerung" not in "".join(p.get_text() for p in doc)
