"""ETS-Funktionen planen (FA-530, FA-637)."""
import logging

import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.ets_function import EtsFunction, EtsFunctionRef
from knix_arranger.models.project import KnxProject, ProjectConfig
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.ets_function_plan import (
    planned_functions, compare_plan, check_plan,
)
from knix_arranger.services import ets_worklist


@pytest.fixture
def project():
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="Plan")
    project.config.mg_variant = "B"
    wohnen = Room(number="01", name="Wohnen", gewerk_assignments=[
        GewerkAssignment(gewerk_code="L", count=1),
        GewerkAssignment(gewerk_code="LD", count=2, element_labels=["Decke"]),
        GewerkAssignment(gewerk_code="J", count=1),
        GewerkAssignment(gewerk_code="H", count=1),
        GewerkAssignment(gewerk_code="S", count=1),
        GewerkAssignment(gewerk_code="A", count=1),   # ohne ETS-Funktion
    ])
    kueche = Room(number="02", name="Küche")
    floor = Floor(name="EG", short_code="EG", main_group_number=2,
                  apartments=[Apartment(name="W", rooms=[wohnen, kueche])])
    project.areal = Areal(buildings=[Building(name="H", wings=[Wing(floors=[floor])])])
    regenerate_addresses(project)
    yield project
    logging.disable(logging.NOTSET)


def _plan(project, name):
    return next(p for p in planned_functions(project) if p.name == name)


def _rooms(project):
    return {r.name: r for r in project.areal.all_rooms}


def test_planned_functions(project):
    plans = planned_functions(project)
    assert [(p.name, p.function_type) for p in plans] == [
        ("Licht Wohnen", "FT-1"), ("Licht Decke", "FT-6"), ("Licht Wohnen 2", "FT-6"),
        ("Jalousie Wohnen", "FT-7"), ("Heizung Wohnen", "FT-9"),
        ("Steckdose Wohnen", "FT-10")]
    light = _plan(project, "Licht Wohnen")
    assert [(r.role, r.address) for r in light.refs] == [
        ("SwitchOnOff", "2/0/0"), ("InfoOnOff", "2/6/0")]      # kein DIM bei FT-1
    dim = _plan(project, "Licht Decke")
    assert [r.role for r in dim.refs] == [
        "SwitchOnOff", "DimmingControl", "DimmingValue", "InfoOnOff", "InfoDimmingValue"]
    blinds = _plan(project, "Jalousie Wohnen")
    assert [r.role for r in blinds.refs] == [
        "MoveUpDown", "StopStepUpDown",
        "CurrentAbsolutePositionBlindsPercentage", "CurrentAbsolutePositionSlatPercentage"]
    heating = _plan(project, "Heizung Wohnen")
    assert [r.role for r in heating.refs] == [
        "TempRoom", "TempRoomSetpoint", "ValvePosition", "HVACMode"]


def test_switching_valve_is_ft8(project):
    ga = next(g for g in project.group_addresses.all_addresses()
              if g.gewerk_code == "H" and g.function_name == "STELLGROESSE")
    ga.datapoint_type = "DPST-1-1"
    assert _plan(project, "Heizung Wohnen").function_type == "FT-8"


def test_check_only_when_planning(project):
    assert check_plan(project) == []
    project.config.plan_ets_functions = True
    issues = check_plan(project)
    assert len(issues) == 6 and all(i.rule_id == "FA-637" for i in issues)
    light = next(i for i in issues if "«Licht Wohnen»" in i.message)
    assert light.details["task"] == (
        "Funktion «Licht Wohnen» (Licht schalten) anlegen und zuordnen: "
        "Schalten 2/0/0, Status 2/6/0.")


def test_config_roundtrip():
    config = ProjectConfig(plan_ets_functions=True)
    assert ProjectConfig.from_dict(config.to_dict()).plan_ets_functions
    assert not ProjectConfig.from_dict({}).plan_ets_functions


def test_compare_after_reimport(project):
    project.config.plan_ets_functions = True
    rooms = _rooms(project)
    # vollständig, unter anderem Namen
    rooms["Wohnen"].ets_functions.append(EtsFunction("Stehlampe", "FT-1", [
        EtsFunctionRef("SwitchOnOff", "2/0/0", "L_01_01 E/A", "DPST-1-1"),
        EtsFunctionRef("InfoOnOff", "2/6/0", "L_01_01 RM", "DPST-1-1")]))
    # ETS-GA statt der geplanten Rückmeldung, Dimmwert fehlt
    dim = _plan(project, "Licht Decke")
    rooms["Wohnen"].ets_functions.append(EtsFunction("Licht Decke", "FT-6", [
        EtsFunctionRef("SwitchOnOff", "2/0/5", "", "DPST-1-1"),
        EtsFunctionRef("DimmingControl", "2/0/6", "", "DPST-3-7"),
        EtsFunctionRef("DimmingValue", "2/0/7", "", "DPST-5-1"),
        EtsFunctionRef("InfoOnOff", "12/1/1", "Status", "DPST-1-1")]))
    # Jalousie im falschen Raum
    blinds = _plan(project, "Jalousie Wohnen")
    rooms["Küche"].ets_functions.append(EtsFunction("Jalousie", "FT-7", [
        EtsFunctionRef(r.role, r.address, "", r.datapoint_type) for r in blinds.refs]))

    statuses = {s.planned.name: s for s in compare_plan(project)}
    assert statuses["Licht Wohnen"].state == "ok"
    deck = statuses["Licht Decke"]
    assert deck.state == "ergänzen"
    assert [(n.address, o.address) for n, o in deck.replaced] == [(dim.refs[3].address, "12/1/1")]
    assert [r.address for r in deck.missing] == [dim.refs[4].address]
    assert statuses["Jalousie Wohnen"].state == "ok" and statuses["Jalousie Wohnen"].other_room
    assert statuses["Heizung Wohnen"].state == "anlegen"

    msgs = [i.message for i in check_plan(project)]
    assert not any("Stehlampe" in m for m in msgs)
    assert any("«Licht Decke» unvollständig: Status 2/6/5 statt 12/1/1; Dimmwert 2/6/7" in m
               for m in msgs)
    assert any("«Jalousie» liegt in Raum 02 Küche" in m for m in msgs)


def test_worklist_group_and_done_after_reimport(project):
    project.config.plan_ets_functions = True
    ets_worklist.sync_worklist(project, today="01.10.2026")
    worklist = ets_worklist.build_worklist(project)
    funcs = worklist.by_priority()[ets_worklist.PRIO_FUNC]
    assert len(funcs) == 6 and funcs[0].where == "Raum 01 Wohnen"
    # Integrator legt "Licht Wohnen" an und ordnet zu -> Re-Import
    light = _plan(project, "Licht Wohnen")
    _rooms(project)["Wohnen"].ets_functions.append(EtsFunction("Licht", "FT-1", list(light.refs)))
    diff = ets_worklist.sync_worklist(project, today="02.10.2026")
    assert diff.done == 1
    assert len(ets_worklist.build_worklist(project).by_priority()[ets_worklist.PRIO_FUNC]) == 5


def test_worklist_exports(project, tmp_path):
    project.config.plan_ets_functions = True
    ets_worklist.export_excel(project, str(tmp_path / "a.xlsx"))
    ets_worklist.export_pdf(project, str(tmp_path / "a.pdf"))
    assert (tmp_path / "a.xlsx").exists() and (tmp_path / "a.pdf").exists()


def test_view_plan_tab(project):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.views.ets_functions_view import EtsFunctionsView
    _app = QApplication.instance() or QApplication([])
    view = EtsFunctionsView()
    seen = []
    view.changed.connect(lambda: seen.append(1))
    view.set_project(project)
    assert view._plan_tree.topLevelItemCount() == 1
    assert view._plan_tree.topLevelItem(0).childCount() == 6
    assert view._plan_tree.topLevelItem(0).child(0).text(4) == "in der ETS anlegen"
    view._plan_check.setChecked(True)
    assert project.config.plan_ets_functions and seen == [1]
