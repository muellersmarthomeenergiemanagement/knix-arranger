"""ETS-Funktionen (FA-529, FA-636) und Auffang-HG 13 (FA-411b).

Auszug aus dem XML-Export von "Chalet Franziska 2005" (ETS 6.4, 2026-10-21):
Raum "04 Schlafen" mit sieben Funktionen; die ETS hat die GAs in HG 12
angelegt, wo das Projekt eigene Revox-GAs führt.
"""
import xml.etree.ElementTree as ET

from knix_arranger.models.building import Room, Floor, ETS_FUNCTION_MAIN_GROUP
from knix_arranger.models.ets_function import EtsFunction, EtsFunctionRef
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.building_service import BuildingService
from knix_arranger.services.ets_function_service import (
    check_functions, overview_rows, role_label, is_ets_generated,
)
from knix_arranger.services.knxproj_import_service import KnxprojImportService
from knix_arranger.services.validation_engine import ValidationEngine

_XML = """<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="http://knx.org/xml/project/23"><Project Id="P-06C2"><Installations>
<Installation Name="">
<Locations>
 <Space Type="Building" Id="P-06C2-0_BP-2" Name="Gebäude">
  <Space Type="BuildingPart" Id="P-06C2-0_BP-6" Name="DG" Number="30">
   <Space Type="Room" Id="P-06C2-0_BP-25" Name="04  Schlafen">
    <Function Id="P-06C2-0_F-1" Name="Raum abdunkeln" Type="FT-0" />
    <Function Id="P-06C2-0_F-2" Name="Leselampen" Type="FT-1">
     <GroupAddressRef Id="P-06C2-0_GF-1" Name="" Role="SwitchOnOff" RefId="P-06C2-0_GA-3388" />
     <GroupAddressRef Id="P-06C2-0_GF-2" Name="" Role="InfoOnOff" RefId="P-06C2-0_GA-3389" />
    </Function>
    <Function Id="P-06C2-0_F-3" Name="Schlafzimmer dimmen" Type="FT-6">
     <GroupAddressRef Id="P-06C2-0_GF-5" Name="" Role="DimmingControl" RefId="P-06C2-0_GA-3392" />
     <GroupAddressRef Id="P-06C2-0_GF-6" Name="" Role="InfoDimmingValue" RefId="P-06C2-0_GA-3393" />
     <GroupAddressRef Id="P-06C2-0_GF-7" Name="" Role="DimmingValue" RefId="P-06C2-0_GA-3394" />
    </Function>
    <Function Id="P-06C2-0_F-4" Name="Jalousien Balkon" Type="FT-7">
     <GroupAddressRef Id="P-06C2-0_GF-8" Name="" Role="MoveUpDown" RefId="P-06C2-0_GA-3395" />
     <GroupAddressRef Id="P-06C2-0_GF-10" Name="" Role="WindAlarm" RefId="P-06C2-0_GA-3397" />
    </Function>
    <Function Id="P-06C2-0_F-5" Name="Jalousien Schlafzimmer" Type="FT-7">
     <GroupAddressRef Id="P-06C2-0_GF-14" Name="" Role="MoveUpDown" RefId="P-06C2-0_GA-1744" />
     <GroupAddressRef Id="P-06C2-0_GF-16" Name="" Role="c91dc81c-a2c1-4afc-aee7-a54653a01633" RefId="P-06C2-0_GA-3397" />
    </Function>
    <Function Id="P-06C2-0_F-6" Name="Heizung Schlafzimmer" Type="FT-9">
     <GroupAddressRef Id="P-06C2-0_GF-22" Name="" Role="ValvePosition" RefId="P-06C2-0_GA-3407" />
     <GroupAddressRef Id="P-06C2-0_GF-24" Name="" Role="WindowStatus" RefId="P-06C2-0_GA-9999" />
    </Function>
   </Space>
  </Space>
 </Space>
</Locations>
<GroupAddresses><GroupRanges>
 <GroupRange Id="P-06C2-0_GR-1" RangeStart="1" RangeEnd="2047" Name="Zentral">
  <GroupRange Id="P-06C2-0_GR-696" RangeStart="256" RangeEnd="511" Name="Jalousie">
   <GroupAddress Id="P-06C2-0_GA-1744" Address="361" Name="J.DG.04.02-04_move" DatapointType="DPST-1-1" />
  </GroupRange>
 </GroupRange>
 <GroupRange Id="P-06C2-0_GR-705" RangeStart="24576" RangeEnd="26623" Name="Revox">
  <GroupRange Id="P-06C2-0_GR-706" RangeStart="24832" RangeEnd="25087" Name="Musikanlage">
   <GroupAddress Id="P-06C2-0_GA-3143" Address="24832" Name="MM.UG.02.01_ea Raum (Waschen)" DatapointType="DPST-1-1" />
   <GroupAddress Id="P-06C2-0_GA-3388" Address="24838" Name="Schalten" DatapointType="DPST-1-1" />
   <GroupAddress Id="P-06C2-0_GA-3389" Address="24839" Name="Status" DatapointType="DPST-1-1" />
   <GroupAddress Id="P-06C2-0_GA-3392" Address="24842" Name="Dimmen" DatapointType="DPST-3-7" />
   <GroupAddress Id="P-06C2-0_GA-3393" Address="24843" Name="Dimmwert" DatapointType="DPST-5-1" />
   <GroupAddress Id="P-06C2-0_GA-3394" Address="24856" Name="Wert" DatapointType="DPST-5-1" />
   <GroupAddress Id="P-06C2-0_GA-3395" Address="24857" Name="Bewegen" DatapointType="DPST-1-8" />
   <GroupAddress Id="P-06C2-0_GA-3397" Address="24859" Name="Windalarm" DatapointType="DPST-1-5" />
   <GroupAddress Id="P-06C2-0_GA-3407" Address="24887" Name="stetige Stellgröße" DatapointType="DPST-5-1" />
  </GroupRange>
 </GroupRange>
</GroupRanges></GroupAddresses>
</Installation></Installations></Project></KNX>
"""


def _import():
    root = ET.fromstring(_XML)
    svc = KnxprojImportService()
    installation = svc._find_installation(root)
    project = KnxProject()
    project.group_addresses = svc._parse_group_addresses(installation)
    project.areal, _ = svc._parse_building(installation)
    svc._resolve_function_refs(installation, project)
    project.topology.is_imported = True
    return project


def _room(project) -> Room:
    return next(r for r in project.areal.all_rooms if r.ets_functions)


def _fn(project, name):
    return next(f for f in _room(project).ets_functions if f.name == name)


def test_functions_read_per_room():
    project = _import()
    room = _room(project)
    assert room.name == "Schlafen"
    assert [f.function_type for f in room.ets_functions] == [
        "FT-0", "FT-1", "FT-6", "FT-7", "FT-7", "FT-9"]
    lamps = _fn(project, "Leselampen")
    assert [(r.role, r.address, r.ga_name, r.datapoint_type) for r in lamps.refs] == [
        ("SwitchOnOff", "12/1/6", "Schalten", "DPST-1-1"),
        ("InfoOnOff", "12/1/7", "Status", "DPST-1-1"),
    ]
    assert _fn(project, "Raum abdunkeln").refs == []


def test_guid_role_resolved_via_other_function():
    """Wind-/Regenalarm in der zweiten Jalousie: GUID statt Rolle."""
    refs = _fn(_import(), "Jalousien Schlafzimmer").refs
    assert refs[1].role == "WindAlarm"
    assert refs[1].address == "12/1/27"


def test_role_labels_in_german():
    project = _import()
    dim = _fn(project, "Schlafzimmer dimmen")
    assert [role_label("FT-6", r) for r in dim.refs] == ["Dimmen", "Dimmwert", "Wert"]
    heating = _fn(project, "Heizung Schlafzimmer")
    assert role_label("FT-9", heating.refs[0]) == "stetige Stellgrösse"


def test_ets_generated_detected_with_eszett():
    heating = _fn(_import(), "Heizung Schlafzimmer")
    assert is_ets_generated(heating.refs[0])          # "stetige Stellgröße" in HG 12
    blinds = _fn(_import(), "Jalousien Schlafzimmer")
    assert not is_ets_generated(blinds.refs[0])       # eigene GA in HG 0


def test_checks():
    issues = check_functions(_import())
    texts = [i.message for i in issues]
    # FT-0 ohne GA ist kein Hinweis
    assert not any("Raum abdunkeln" in t for t in texts)
    # GA fehlt
    assert any("Fensterkontakt: GA nicht gefunden" in t for t in texts)
    # zugeordnete bestehende GA mit falschem DPT (1.001 statt 1.008)
    dpt = [i for i in issues if "DPT 1.001" in i.message]
    assert len(dpt) == 1 and dpt[0].address == "0/1/105"
    # von der ETS angelegt (Windalarm zählt in beiden Jalousie-Funktionen)
    assert sum("von der ETS angelegt" in t for t in texts) == 9
    # ohne Topologie: alles ohne KO
    assert any("«Leselampen», Schalten: GA auf kein KO verknüpft" in t for t in texts)
    # eigene Revox-GA in HG 12
    own = [i for i in issues if i.address == "HG 12"]
    assert len(own) == 1 and "1 eigene GA" in own[0].message
    assert own[0].level == "info"


def test_linked_ga_without_ko_hint():
    project = _import()
    device = Device(physical_address="1.1.1")
    device.communication_objects.append(
        CommunicationObject(object_number=0,connected_gas=["12/1/6"]))
    line = Line(line_number=1)
    line.devices.append(device)
    area = Area(area_number=1)
    area.lines.append(line)
    project.topology.areas.append(area)
    texts = [i.message for i in check_functions(project)]
    assert not any("«Leselampen», Schalten: GA auf kein KO" in t for t in texts)


def test_overview_rows():
    rows = overview_rows(_import())
    empty = [r for r in rows if r.function == "Raum abdunkeln"]
    assert len(empty) == 1 and empty[0].hints == [] and empty[0].type_label == "Benutzerdefiniert"
    move = next(r for r in rows if r.address == "0/1/105")
    assert move.role == "Bewegen" and move.datapoint_type == "1.001"


def test_roundtrip():
    room = Room(name="R")
    room.ets_functions = [EtsFunction("Licht", "FT-1", [
        EtsFunctionRef("SwitchOnOff", "1/1/1", "Schalten", "DPST-1-1")])]
    again = Room.from_dict(room.to_dict())
    assert again.ets_functions == room.ets_functions
    assert "ets_functions" not in Room(name="X").to_dict()


def test_reimport_from_excel_keeps_functions():
    from knix_arranger.services.project_reconcile_service import reconcile_reimport
    old = _import()
    new = KnxProject()
    floor = Floor(name="DG", short_code="DG")
    from knix_arranger.models.building import Building, Wing, Apartment
    building, wing, apt = Building(name="G"), Wing(name=""), Apartment(name="")
    new.areal.buildings.append(building)
    building.wings.append(wing)
    wing.floors.append(floor)
    floor.apartments.append(apt)
    apt.rooms.append(Room(number=_room(old).number, name="Schlafen"))
    old_floor = old.areal.all_floors[0]
    floor.short_code = old_floor.short_code
    reconcile_reimport(old, new)
    assert len(new.areal.all_rooms[0].ets_functions) == 6


# ── FA-411b: HG 13 «ETS-Funktionen» ────────────────────────────────────

def test_hg13_skipped_automatically():
    project = KnxProject()
    areal = project.areal
    from knix_arranger.models.building import Building, Wing
    building, wing = Building(name="G"), Wing(name="")
    areal.buildings.append(building)
    building.wings.append(wing)
    for n in range(1, 12):
        wing.floors.append(Floor(name=f"S{n}", short_code=f"S{n}", main_group_number=n))
    assert BuildingService.next_free_main_group(areal, ETS_FUNCTION_MAIN_GROUP) == 12
    assert BuildingService.next_free_main_group(areal, 12) == 12   # nicht mehr reserviert
    wing.floors.append(Floor(name="X", short_code="X"))
    BuildingService.assign_main_groups(areal)
    assert wing.floors[-1].main_group_number == 12


def test_hg13_manual_warning():
    project = KnxProject()
    from knix_arranger.models.building import Building, Wing
    building, wing = Building(name="G"), Wing(name="")
    project.areal.buildings.append(building)
    building.wings.append(wing)
    wing.floors.append(Floor(name="Annex", short_code="AN", main_group_number=13))
    issues = ValidationEngine()._check_ets_function_main_group(project)
    assert len(issues) == 1 and issues[0].rule_id == "FA-411b"
    project.topology.is_imported = True
    assert ValidationEngine()._check_ets_function_main_group(project) == []


def test_planned_structure_gets_empty_catch_main_group(eg_room_with_gewerke):
    """Die ETS legt neue Funktionen in die erste freie MG der höchsten HG:
    geplante Projekte enden mit der leeren HG 13, auch im CSV-Export."""
    from knix_arranger.services.address_generator import regenerate_addresses
    from knix_arranger.services.csv_export_service import CsvExportService
    from knix_arranger.services.ets_function_service import check_functions
    project = KnxProject()
    project.areal = eg_room_with_gewerke
    assert any("Neue ETS-Funktionen landen in HG 2" in i.message
               for i in check_functions(project)) is False   # noch keine GAs
    regenerate_addresses(project)
    top = project.group_addresses.main_groups[-1]
    assert (top.number, top.name, top.middle_groups) == (13, "ETS-Funktionen", [])
    assert not [i for i in check_functions(project) if i.address.startswith("HG")]
    project.group_addresses.main_groups.pop()
    assert any("Neue ETS-Funktionen landen in HG 2" in i.message
               for i in check_functions(project))
    regenerate_addresses(project)
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "ga.csv")
    CsvExportService().export_csv(project.group_addresses, path)
    assert '"ETS-Funktionen"' in open(path, encoding="cp1252").read()


# ── Ansicht unter "Adressen & Logik" ─────────────────────────────────────

def test_view_in_sidebar_and_filled():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.widgets.sidebar import NAV_GROUPS
    from knix_arranger.ui.views.ets_functions_view import EtsFunctionsView
    _app = QApplication.instance() or QApplication([])
    group = dict(NAV_GROUPS)["Adressen & Logik"]
    assert "ets_functions" in [key for key, _, _ in group]
    view = EtsFunctionsView()
    view.set_project(_import())
    assert view._tree.topLevelItemCount() == 1
    room = view._tree.topLevelItem(0)
    assert room.childCount() == 6
    assert room.child(1).childCount() == 2          # Leselampen
    assert "6 Funktion(en)" in view._summary.text()
    view.set_project(KnxProject())
    assert view._tree.topLevelItemCount() == 0


def test_ets_generated_in_any_main_group():
    """ETS 6.4.1: erste freie MG der höchsten HG -- 13/0 nach vollem HG 12,
    ohne HG 12/13 auch 4/3 (Lücke im DG)."""
    from knix_arranger.models.ets_function import EtsFunctionRef
    assert is_ets_generated(EtsFunctionRef("MoveUpDown", "13/0/0", "Bewegen"))
    assert is_ets_generated(EtsFunctionRef("SwitchOnOff", "4/3/0", "Schalten"))
    assert not is_ets_generated(EtsFunctionRef("MoveUpDown", "13/0/0", "J_DG_04_F1 AUF/AB"))


def test_ets_named_ga_in_home_group_only_renamed():
    """Chalet 261021: Integrator hat die OG-Funktion nach 3/0 verschoben, die
    Namen der ETS aber behalten -> nur benennen, nicht verschieben."""
    from knix_arranger.services.ets_function_service import ref_hints
    ref = EtsFunctionRef("SwitchOnOff", "3/0/245", "Schalten", "DPST-1-1")
    linked = {"3/0/245", "12/1/200", "3/1/0"}
    assert ref_hints("FT-6", ref, linked, (3, 0)) == [
        "von der ETS benannt: nach den Richtlinien benennen"]
    assert ref_hints("FT-6", ref, linked, (3, 1)) == [
        "von der ETS angelegt: in MG 3/1 verschieben und benennen"]
    blinds = EtsFunctionRef("MoveUpDown", "12/1/200", "Bewegen", "DPST-1-8")
    assert ref_hints("FT-7", blinds, linked, (4, 1)) == [
        "von der ETS angelegt: in MG 4/1 verschieben und benennen"]
    assert ref_hints("FT-0", blinds, linked, (4, None)) == [
        "von der ETS angelegt: in HG 4 verschieben und benennen"]
    assert role_label("FT-7", EtsFunctionRef("", "3/1/0", "Beschattung")) == "zusätzliche GA"


def test_status_ga_of_function():
    """Status-GA je Funktion: darf in den Rückmelde-MGs liegen, braucht genau
    ein Status-KO, das auf sie sendet (Chalet 261021: 3/0/246 hing als zweite
    GA an drei Status-KOs)."""
    from knix_arranger.services.ets_function_service import ref_hints
    from knix_arranger.services.multi_ga_check import KoSender
    status = EtsFunctionRef("InfoOnOff", "3/7/10", "L_OG_05_01 RM", "DPST-1-1")
    linked = {"3/7/10"}
    one = KoSender("1.1.5", 12, "Status", True)
    assert ref_hints("FT-1", status, linked, (3, 0), {"3/7/10": [(one, "3/7/10")]}) == []
    assert ref_hints("FT-1", status, linked, (3, 0), {}) == ["Status: an keinem Status-KO"]
    assert ref_hints("FT-1", status, linked, (3, 0), {"3/7/10": [(one, "3/7/0")]}) == [
        "Status: KO sendet auf 3/7/0"]
    assert ref_hints("FT-1", status, linked, (3, 0),
                     {"3/7/10": [(one, "3/7/0"), (one, "3/7/5")]}) == [
        "Status: an 2 Status-KOs – Wert springt"]
    # Befehls-GA in MG 7: falsche MG
    switch = EtsFunctionRef("SwitchOnOff", "3/7/11", "Schalten", "DPST-1-1")
    assert ref_hints("FT-1", switch, {"3/7/11"}, (3, 0), {}) == [
        "von der ETS angelegt: in MG 3/0 verschieben und benennen"]


def test_floor_on_main_group_14_or_higher_warns():
    """FA-411c: HG 14/15 ungefiltert, 16–31 bei älteren Kopplern unsicher."""
    from knix_arranger.models.building import Building, Wing, main_group_risk
    project = KnxProject()
    building, wing = Building(name="G"), Wing(name="")
    project.areal.buildings.append(building)
    building.wings.append(wing)
    for n, code in ((12, "A"), (14, "B"), (20, "C")):
        wing.floors.append(Floor(name=code, short_code=code, main_group_number=n))
    issues = ValidationEngine()._check_main_group_range(project)
    assert [(i.rule_id, i.address) for i in issues] == [("FA-411c", "HG 14"), ("FA-411c", "HG 20")]
    assert "ungefiltert" in issues[0].message and "ältere Koppler" in issues[1].message
    assert main_group_risk(13) == ""
    project.topology.is_imported = True
    assert ValidationEngine()._check_main_group_range(project) == []
