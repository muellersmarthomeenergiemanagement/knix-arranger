"""
Erweiterung im Bestand (FA-642). Nachgebaut nach dem Chalet: Storen im OG
in HG 3 / MG 1 mit 5er-Blöcken "J.OG.02.01_move  ( Bibliothek )".
"""
from __future__ import annotations
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.extension_plan import (
    NAMING_SWISS, ExtensionItem, ExtensionPlan,
)
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.extension_service import (
    evaluate, new_ga_structure, split_designation,
)

_FUNCS = [("move", "DPST-1-8"), ("step", "DPST-1-7"), ("hoehe", "DPST-5-1"),
          ("winkel", "DPST-5-1"), ("beschattung", "DPST-1-22")]


def _block(start: int, room: str, element: int, label: str) -> list[GroupAddress]:
    gas = []
    for offset, (func, dpt) in enumerate(_FUNCS):
        name = f"J.OG.{room}.{element:02d}_{func}" + (f"  ( {label} )" if offset == 0 else "")
        gas.append(GroupAddress(main_group=3, middle_group=1, sub_group=start + offset,
                                designation=name, datapoint_type=dpt, gewerk_code="J"))
    return gas


def _project():
    project = KnxProject(name="Chalet")
    bibliothek = Room(number="02", name="Bibliothek")
    wohnen = Room(number="03", name="Wohnen")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[Floor(
        name="OG", short_code="OG", apartments=[Apartment(rooms=[bibliothek, wohnen])])])])])
    gas = _block(0, "02", 1, "Pult") + _block(5, "02", 2, "Fenster") + _block(10, "03", 1, "Süd")
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=3, name="OG", middle_groups=[MiddleGroup(number=1, name="Jalousie",
                                                       group_addresses=gas)])])
    actor = Device(physical_address="1.1.17", device_type="actor",
                   product="Jalousieaktor 4-fach",
                   communication_objects=[
                       CommunicationObject(name=f"Kanal {c} Auf/Ab", connected_gas=[ga])
                       for c, ga in zip("ABC", ("3/1/0", "3/1/5", "3/1/10"))])
    project.topology = Topology(is_imported=True, areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[actor])])])
    return project, bibliothek, wohnen


def test_split_designation():
    assert split_designation("J.OG.02.01_move  ( Pult )") == ("J.OG.02.01", "_", "move  ( Pult )")
    assert split_designation("J_OG_02_01 AUF/AB (Pult)") == ("J_OG_02_01", " ", "AUF/AB (Pult)")
    assert split_designation("Zentral Aus") is None


def test_plant_schema_continued():
    project, _bibliothek, wohnen = _project()
    plan = ExtensionPlan(name="Storen OG", items=[
        ExtensionItem(room_id=wohnen.id, gewerk_code="J", count=2, label="Fenster West")])
    (item,) = evaluate(project, plan).items
    assert item.middle_group == "3/1" and item.template == "J.OG.03.01"
    names = [ga.designation for ga in item.gas]
    assert names[:2] == ["J.OG.03.02_move  ( Fenster West )", "J.OG.03.02_step"]
    assert names[5] == "J.OG.03.03_move  ( Fenster West )"
    assert [ga.address for ga in item.gas][:1] == ["3/1/15"]        # nach dem Wohnen-Block
    assert [ga.dpt for ga in item.gas][:5] == [d for _f, d in _FUNCS]
    # Aktor 4-fach mit 3 belegten Kanälen: einer frei, einer fehlt
    assert [(a.device.physical_address, a.channels) for a in item.actors] == [("1.1.17", 1)]
    assert item.missing_channels == 1


def test_swiss_naming_and_csv(tmp_path):
    project, bibliothek, _wohnen = _project()
    plan = ExtensionPlan(name="Storen OG", naming=NAMING_SWISS, items=[
        ExtensionItem(room_id=bibliothek.id, gewerk_code="J", count=1, label="Dachfenster")])
    result = evaluate(project, plan)
    assert result.gas[0].designation == "J_OG_02_01 AUF/AB (Dachfenster)"
    assert result.gas[0].naming == "KNX Swiss"
    structure = new_ga_structure(project, result)
    (mg,) = structure.main_groups[0].middle_groups
    assert mg.name == "Jalousie" and all(g.description == plan.comment
                                         for g in mg.group_addresses)
    from knix_arranger.services.csv_export_service import CsvExportService
    path = tmp_path / "ext.csv"
    CsvExportService().export_csv(structure, str(path))
    assert "J_OG_02_01 AUF/AB (Dachfenster)" in path.read_text(encoding="cp1252")


def test_round_trip_dialog_and_report(tmp_path):
    from PySide6.QtWidgets import QApplication
    from knix_arranger.services.report_service import ReportService
    from knix_arranger.ui.dialogs.extension_dialog import ExtensionDialog
    QApplication.instance() or QApplication([])
    project, _bibliothek, wohnen = _project()
    plan = ExtensionPlan(name="Storen OG", items=[
        ExtensionItem(room_id=wohnen.id, gewerk_code="J", count=1, label="Fenster West")])
    project.extension_plans = [plan]
    loaded = KnxProject.from_dict(project.to_dict())
    assert loaded.extension_plans[0].items[0].label == "Fenster West"
    dlg = ExtensionDialog(project, plan)
    assert dlg._preview.rowCount() == 5
    assert dlg._preview.item(0, 1).text() == "J.OG.03.02_move  ( Fenster West )"
    path = tmp_path / "ext.pdf"
    ReportService(project).generate_extension_report(str(path), plan)
    import fitz
    text = "".join(p.get_text() for p in fitz.open(str(path)))
    assert "Erweiterung Storen OG" in text and "3/1/15" in text
    assert "Neuer Aktor" not in text                     # ein Kanal ist frei


def test_one_label_per_element():
    """Zwei Wetterstationen «Rotten, Berg»: je Element ein eigener Klartext,
    ein Systemsensor braucht keine Aktorkanäle."""
    project, bibliothek, wohnen = _project()
    plan = ExtensionPlan(name="Wetter", naming=NAMING_SWISS, items=[
        ExtensionItem(room_id=bibliothek.id, gewerk_code="W", count=2, label="Rotten, Berg")])
    (item,) = evaluate(project, plan).items
    labels = {ga.element: ga.label for ga in item.gas}
    assert labels == {1: "Rotten", 2: "Berg"}
    first = [ga.designation for ga in item.gas if ga.element == 1]
    second = [ga.designation for ga in item.gas if ga.element == 2]
    assert first and all("(Rotten)" in d for d in first)
    assert second and all("(Berg)" in d for d in second)
    assert item.actors == [] and item.missing_channels == 0
    # Zahl der Namen passt nicht zur Anzahl: ganzer Text für alle
    plan.items = [ExtensionItem(room_id=wohnen.id, gewerk_code="J", count=3,
                                label="Fenster West, Ost")]
    (item,) = evaluate(project, plan).items
    assert {ga.label for ga in item.gas} == {"Fenster West, Ost"}


def test_labels_split():
    assert ExtensionItem(count=2, label="Rotten; Berg").labels() == ["Rotten", "Berg"]
    assert ExtensionItem(count=1, label="Rotten, Berg").labels() == ["Rotten, Berg"]
    assert ExtensionItem(count=2, label="").labels("Balkon") == ["Balkon", "Balkon"]
    assert ExtensionItem(count=2, label="Rotten,").labels() == ["Rotten,", "Rotten,"]
