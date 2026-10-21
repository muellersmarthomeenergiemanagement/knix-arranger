"""Funktionen planen (FA-530, FA-637): Gruppenbedienung mehrerer Elemente
mit eigenen GAs, z.B. "Fensterfront" für drei Jalousien."""
import logging

import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.ets_function import (
    EtsFunction, EtsFunctionRef, FunctionMember, KnixFunction,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services import ets_worklist
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.belegungsplan_service import BelegungsplanService
from knix_arranger.services.co_linking_service import CoLinkingService
from knix_arranger.services.ets_function_plan import (
    check_plan, compare_plan, function_gas, restore_function_ids, sync_function_gas,
)
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.services.validation_engine import ValidationEngine


def _build(variant="A"):
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="Funktionen")
    project.config.mg_variant = variant
    blinds = GewerkAssignment(gewerk_code="J", count=3,
                              element_labels=["Links", "Mitte", "Rechts"])
    lights = GewerkAssignment(gewerk_code="LD", count=2)
    wohnen = Room(number="01", name="Wohnen", gewerk_assignments=[blinds, lights])
    kueche = Room(number="02", name="Küche",
                  gewerk_assignments=[GewerkAssignment(gewerk_code="LD", count=1)])
    zone = Apartment(name="Wohnzone", rooms=[wohnen, kueche])
    floor = Floor(name="EG", short_code="EG", main_group_number=2, apartments=[zone])
    project.areal = Areal(buildings=[Building(name="H", wings=[Wing(floors=[floor])])])
    engine = TopologyEngine(project.config.topology_mode)
    project.topology = engine.calculate_topology(project.areal)
    engine.populate_devices(project.topology, project.all_rooms, project.gewerk_catalog)
    front = KnixFunction(name="Fensterfront", function_type="FT-7", room_id=wohnen.id,
                         members=[FunctionMember(blinds.id, n) for n in (1, 2, 3)])
    project.functions.append(front)
    regenerate_addresses(project)
    return project


@pytest.fixture
def project():
    yield _build()
    logging.disable(logging.NOTSET)


def _gas(project, function=None):
    function = function or project.functions[0]
    return {ga.function_name: ga for ga in function_gas(project.group_addresses)
            if ga.function_id == function.id}


def _channel_kos(project, with_function=True):
    """Je Jalousie ein Gerät mit KOs je Funktion, wie aus der ETS: die GA
    des Elements und (soll) die Funktions-GA."""
    from knix_arranger.models.topology import CommunicationObject, Device
    from knix_arranger.services.ets_function_plan import member_links
    line = project.topology.areas[0].lines[0]
    devices = {}
    for member, fga, own, wanted in member_links(project, project.functions[0]):
        nr = member.element_number
        device = devices.get(nr)
        if device is None:
            device = devices[nr] = Device(physical_address=f"1.1.{100 + nr}")
            line.devices.append(device)
        co = next((c for c in device.communication_objects
                   if own.address in c.connected_gas), None)
        if co is None:
            co = CommunicationObject(object_number=len(device.communication_objects),
                                     name=own.function_name, connected_gas=[own.address])
            device.communication_objects.append(co)
        if with_function and wanted:
            co.connected_gas.append(fga.address)


def _cos_with(project, address):
    return [co for a in project.topology.areas for ln in a.lines for d in ln.devices
            for co in d.communication_objects if address in co.connected_gas]


def test_addresses_from_ug_200(project):
    gas = _gas(project)
    assert {f: (ga.address, ga.datapoint_type) for f, ga in gas.items()} == {
        "AUF/AB": ("2/1/200", "DPST-1-8"), "STOPP": ("2/1/201", "DPST-1-7"),
        "STATUS POSITION HOEHE": ("2/1/202", "DPST-5-1"),
        "STATUS POSITION LAMELLEN": ("2/1/203", "DPST-5-1")}
    assert gas["AUF/AB"].designation == "J_01_F1 AUF/AB (Fensterfront)"
    # Element-Blöcke bleiben vorne
    element = [ga for ga in project.group_addresses.all_addresses()
               if ga.gewerk_code == "J" and not ga.function_id and not ga.is_placeholder]
    assert max(ga.sub_group for ga in element) < 200


def test_variant_b_status_in_mg7_without_findings():
    project = _build("B")
    gas = _gas(project)
    assert gas["STATUS POSITION HOEHE"].address == "2/7/202"
    issues = ValidationEngine(project.gewerk_catalog).validate(
        project.group_addresses, project=project)
    addresses = {ga.address for ga in gas.values()}
    assert not [i for i in issues if i.address in addresses]


def test_stable_and_second_function_next_block(project):
    before = {ga.id: ga.address for ga in function_gas(project.group_addresses)}
    rooms = {r.name: r for r in project.all_rooms}
    zone = project.areal.all_floors[0].apartments[0]
    lights = [(r, a) for r in rooms.values() for a in r.gewerk_assignments if a.gewerk_code == "LD"]
    project.functions.append(KnixFunction(
        name="Licht Wohnzone", function_type="FT-6", zone_id=zone.id,
        members=[FunctionMember(a.id, 1) for _r, a in lights]))
    project.functions.append(KnixFunction(
        name="Ganze Front", function_type="FT-7", room_id=rooms["Wohnen"].id, number=2,
        members=[FunctionMember(project.functions[0].members[0].assignment_id, 1)]))
    regenerate_addresses(project)
    after = {ga.id: ga.address for ga in function_gas(project.group_addresses)}
    assert all(after[i] == a for i, a in before.items())
    assert _gas(project, project.functions[2])["AUF/AB"].address == "2/1/205"
    zone_gas = _gas(project, project.functions[1])
    assert zone_gas["E/A"].address == "2/0/200"
    assert zone_gas["E/A"].designation == "LD_EG_F1 E/A (Licht Wohnzone)"


def test_without_status(project):
    project.functions[0].with_status = False
    sync_function_gas(project)
    assert set(_gas(project)) == {"AUF/AB", "STOPP"}


def test_rows_on_all_member_channels_status_only_lead(project):
    rows = BelegungsplanService().generate(project).actor_rows
    by_ga = {}
    for row in rows:
        by_ga.setdefault(row.ga_address, set()).add((row.physical_address, row.channel_number))
    assert len(by_ga["2/1/200"]) == 3 and len(by_ga["2/1/201"]) == 3
    assert len(by_ga["2/1/202"]) == 1
    project.functions[0].lead = 2
    rows = BelegungsplanService().generate(project).actor_rows
    lead_row = next(r for r in rows if r.ga_address == "2/1/202")
    third = next(r for r in rows if r.ga_designation.startswith("J_01_03 AUF/AB"))
    assert lead_row.channel_number == third.channel_number


def test_co_linking_proposals(project):
    proposals = CoLinkingService().generate_proposals(project)
    assert {p.ga_address for p in proposals} >= {"2/1/200", "2/1/201", "2/1/202", "2/1/203"}


def test_link_checks(project):
    _channel_kos(project)
    assert len(_cos_with(project, "2/1/200")) == 3
    assert len(_cos_with(project, "2/1/202")) == 1
    assert not [i for i in check_plan(project) if i.rule_id == "FA-637"]
    # ein Kanal ohne Funktions-GA, zweiter Sender auf dem Status
    _cos_with(project, "2/1/200")[1].connected_gas.remove("2/1/200")
    own_status = next(ga for ga in project.group_addresses.all_addresses()
                      if ga.designation.startswith("J_01_02 STATUS POSITION HOEHE"))
    _cos_with(project, own_status.address)[0].connected_gas.append("2/1/202")
    messages = [i.message for i in check_plan(project)]
    assert any("Funktions-GA 2/1/200 fehlt" in m for m in messages)
    assert any("Rückmeldung 2/1/202 wird von 2 Kanälen gesendet" in m for m in messages)
    project.topology.is_imported = True
    items = ets_worklist.current_items(project)
    must = [i for i in items if i.rule_id == "FA-637"]
    assert must and all(i.priority == ets_worklist.PRIO_MUST for i in must)


def test_compare_with_ets(project):
    wohnen = next(r for r in project.all_rooms if r.name == "Wohnen")
    assert not check_plan(project)                   # nichts eingelesen: keine Aufgabe
    wohnen.ets_functions.append(EtsFunction("Andere", "FT-1", []))
    issues = check_plan(project)
    assert [i.details["kind"] for i in issues] == ["anlegen"]
    assert "anlegen und zuordnen: Bewegen 2/1/200, Schritt/Stop 2/1/201, " \
           "Position 2/1/202, Lamellenstellung 2/1/203." in issues[0].details["task"]
    wohnen.ets_functions.append(EtsFunction("Front", "FT-7", [
        EtsFunctionRef("MoveUpDown", "2/1/200"), EtsFunctionRef("StopStepUpDown", "2/1/201"),
        EtsFunctionRef("CurrentAbsolutePositionBlindsPercentage", "12/1/3")]))
    status = compare_plan(project)[0]
    assert status.state == "ergänzen" and status.ets.name == "Front"
    assert [ga.address for ga in status.missing] == ["2/1/202", "2/1/203"]
    project.topology.is_imported = True
    items = [i for i in ets_worklist.current_items(project) if i.rule_id == "FA-637"]
    assert [i.priority for i in items] == [ets_worklist.PRIO_FUNC]
    assert items[0].task == "Funktion «Front»: Position 2/1/202, Lamellenstellung 2/1/203 zuordnen."


def test_restore_after_reimport(project):
    for ga in function_gas(project.group_addresses):
        ga.function_id = ""
    assert restore_function_ids(project) == 4
    assert len(_gas(project)) == 4


def test_renumbering_keeps_function_gas(project):
    from knix_arranger.services.renumber_service import plan_renumbering
    plan = plan_renumbering(project)
    gas = [ga for ga in plan.structure.all_addresses() if ga.function_id]
    assert sorted(ga.address for ga in gas) == ["2/1/200", "2/1/201", "2/1/202", "2/1/203"]
    assert not [c for c in plan.changes if "_F1" in c.new_designation]


def test_roundtrip(project):
    again = KnxProject.from_dict(project.to_dict())
    assert again.functions == project.functions
    assert len([ga for ga in again.group_addresses.all_addresses() if ga.function_id]) == 4


def test_removed_member_reported(project):
    project.functions[0].members.append(FunctionMember("weg", 1))
    assert any("entfernte(s) Element(e)" in i.message for i in check_plan(project))


def test_view_and_dialog(project):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.views.ets_functions_view import EtsFunctionsView
    from knix_arranger.ui.dialogs.function_edit_dialog import FunctionEditDialog
    _app = QApplication.instance() or QApplication([])
    view = EtsFunctionsView()
    view.set_project(project)
    place = view._plan_tree.topLevelItem(0)
    function_item = place.child(0)
    assert function_item.text(0) == "Fensterfront (Sonnenschutz)"
    assert function_item.childCount() == 4 + 3
    assert function_item.child(4).text(4) == "Leitkanal (Rückmeldung)"

    dialog = FunctionEditDialog(project, project.functions[0])
    assert dialog._members.count() == 3
    assert all(dialog._members.item(i).checkState() == Qt.Checked for i in range(3))
    dialog._members.item(2).setCheckState(Qt.Unchecked)
    dialog._status.setCurrentIndex(dialog._status.findData("none"))
    dialog._accept()
    edited = dialog.result_function()
    assert len(edited.members) == 2 and not edited.with_status
    assert edited.number == 1
