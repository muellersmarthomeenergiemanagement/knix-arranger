"""
Gateways am Produktnamen (Chalet: Viessmann «Vitogate 200, type KNX» wurde
als Sensor und im Raum als «Wassermelder» eingelesen).
"""
from __future__ import annotations

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.knxproj_import_service import KnxprojImportService
from knix_arranger.services.project_service import correct_gateway_types
from knix_arranger.services.room_sheet import _strip_common_prefix


def test_compound_gate_is_a_gateway():
    infer = KnxprojImportService._infer_device_type
    assert infer("Vitogate 200, type KNX", []) == "gateway"
    assert infer("KNX-Gateway", []) == "gateway"
    # Tor-Aktor bleibt Aktor
    assert infer("Garage gate actuator", []) == "actor"


def test_warm_water_is_no_water_detector():
    cos = [CommunicationObject(name="1_1_CU401B_G__ / Warmwassertemperatur oben")]
    assert not KnxprojImportService._has_ko_hint(cos, KnxprojImportService._WASSERMELDER_KO_HINTS)
    leak = [CommunicationObject(name="Leckage Alarm")]
    assert KnxprojImportService._has_ko_hint(leak, KnxprojImportService._WASSERMELDER_KO_HINTS)


def _project(imported=True):
    gate = Device(device_type="sensor", physical_address="1.1.32",
                  product="Vitogate 200, type KNX",
                  communication_objects=[CommunicationObject(name="1_1_CU401B_G__ / Verdichter")])
    taster = Device(device_type="sensor", physical_address="1.1.50", product="Taster EDIZIOdue",
                    communication_objects=[CommunicationObject(name="Taste 1")])
    technik = Room(name="Technik", bedienelemente=[
        Bedienelement(element_type="Wassermelder", participant_number="1.1.32", is_auto=False),
        Bedienelement(element_type="Tastereinheit", participant_number="1.1.50")])
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="UG", apartments=[Apartment(rooms=[technik])])])])])
    project.topology = Topology(is_imported=imported, areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[gate, taster])])])
    return project, gate, taster, technik


def test_saved_project_corrected_on_load():
    project, gate, taster, technik = _project()
    assert correct_gateway_types(project) == ["1.1.32"]
    assert (gate.device_type, taster.device_type) == ("gateway", "sensor")
    assert [be.participant_number for be in technik.bedienelemente] == ["1.1.50"]
    assert correct_gateway_types(project) == []          # einmal genügt


def test_saved_checklist_loses_gateway_items():
    """Gespeicherte Checkliste vor der Korrektur: Vitogate als «Wassermelder»
    mit Prüfpunkten im Raum. Offene Punkte fallen weg, ein abgezeichneter
    Geräte-Punkt geht in die Verteiler-Checkliste über."""
    from knix_arranger.models.documentation import (
        ITEM_KIND_FUNCTION, ChecklistItem, CommissioningChecklist)
    project, _gate, _taster, technik = _project()

    def item(number, check, result="", kind="device", ga=""):
        return ChecklistItem(be_type="Wassermelder" if number == "1.1.32" else "Tastereinheit",
                             be_number=number, check_type=check, result=result,
                             item_kind=kind, function_ga=ga, checked_by="MM" if result else "")
    room_cl = CommissioningChecklist(room_id=technik.id, items=[
        item("1.1.32", "Montage", "OK"), item("1.1.32", "Applikation"),
        item("1.1.32", "", kind=ITEM_KIND_FUNCTION, ga="0/2/101"),
        item("1.1.50", "Montage")])
    verteiler = CommissioningChecklist(room_id="__verteiler__UV1", items=[
        ChecklistItem(be_type="Vitogate", be_number="1.1.32", check_type="Montage")])
    project.checklists = [room_cl, verteiler]

    correct_gateway_types(project)
    assert [(i.be_number, i.check_type) for i in room_cl.items] == [("1.1.50", "Montage")]
    assert (verteiler.items[0].result, verteiler.items[0].checked_by) == ("OK", "MM")


def test_planned_project_untouched():
    project, gate, _taster, _technik = _project(imported=False)
    assert correct_gateway_types(project) == [] and gate.device_type == "sensor"


def test_technical_prefix_only_for_codes():
    assert _strip_common_prefix(["1_1_CU401B_G__ / (2000) Raumtemperatur Soll",
                                 "Auf / Beschattung"]) == [
        "(2000) Raumtemperatur Soll", "Auf / Beschattung"]


def test_main_window_applies_corrections_on_open(tmp_path, monkeypatch):
    """Der Ladeweg des Programms (MainWindow.open_file), nicht nur
    ProjectService.load_project: bis 1.4.58 liefen die Korrekturen dort nie
    (Chalet: Präsenzmelder blieben Aktor, Vitogate blieb «Wassermelder»)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    from knix_arranger.models.documentation import ChecklistItem, CommissioningChecklist
    from knix_arranger.services.project_service import ProjectService
    from knix_arranger.ui.main_window import MainWindow

    project, _gate, _taster, technik = _project()
    project.topology.areas[0].lines[0].devices.append(
        Device(device_type="actor", physical_address="1.1.29", product="compact office EIB",
               manufacturer="Theben HTS"))
    project.checklists = [CommissioningChecklist(room_id=technik.id, items=[
        ChecklistItem(be_type="Wassermelder", be_number="1.1.32", check_type="Montage")])]
    path = tmp_path / "chalet.knxarr"
    project.save(str(path))

    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(ProjectService, "add_to_recent", lambda self, p: None)
    window = MainWindow()
    try:
        window.open_file(str(path))
        loaded = window._project
        types = {d.physical_address: d.device_type for a in loaded.topology.areas
                 for line in a.lines for d in line.devices}
        assert types["1.1.32"] == "gateway" and types["1.1.29"] == "sensor"
        room = next(r for r in loaded.all_rooms if r.name == "Technik")
        assert "1.1.32" not in [be.participant_number for be in room.bedienelemente]
        assert not any(i.be_number == "1.1.32" for cl in loaded.checklists for i in cl.items)
        assert any("als Sensor eingeordnet: 1.1.29" in e.message
                   for e in loaded.changelog)
    finally:
        window._live_monitor_view.shutdown()
        window.deleteLater()


def test_presence_detector_families_get_their_name():
    """Nicht nur «Sensor»: Checkliste, Matrix und Anleitung nennen den Typ."""
    infer = KnxprojImportService._infer_element_type
    assert infer("compact office EIB", []) == "Präsenzmelder"
    assert infer("pirios 360P KNX", []) == "Präsenzmelder"
    assert infer("BE/S8.20.1 Binary Input,8-fold,Cont.Sc.,MDRC", []) == "Binäreingang"
    assert infer("Salva KNX TH", []) == "Sensor"
