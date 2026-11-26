"""
Anlage ohne Projektdatei aufnehmen (FA-3105e): Schritte und Stand aus den
Projektdaten, Einstieg beim neuen Projekt, Rückfragen in «Teilnehmer suchen».
"""
from __future__ import annotations

from knix_arranger.models.group_address import GroupAddress, MainGroup, MiddleGroup
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line
from knix_arranger.services import reconstruction_steps as rs
from knix_arranger.services import room_from_bus as rb


def _states(project, connected=False, findings=0):
    return {s.key: s.state for s in rs.steps(project, connected, findings)}


def _with_devices(project, linked=True, name="Ausgang A Schalten (1.1.1)"):
    co = CommunicationObject(object_number=0, name="Ausgang A", object_function="Schalten",
                             connected_gas=["0/0/1"] if linked else [])
    device = Device(physical_address="1.1.1", device_type="actor", communication_objects=[co])
    project.topology.areas.append(Area(area_number=1, lines=[Line(line_number=1,
                                                                  devices=[device])]))
    project.topology.is_imported = True
    if linked:
        mg = MiddleGroup(number=0, name="MG", group_addresses=[
            GroupAddress(main_group=0, middle_group=0, sub_group=1, designation=name)])
        project.group_addresses.main_groups.append(MainGroup(number=0, name="HG",
                                                             middle_groups=[mg]))
    return project


def test_empty_project_starts_with_connect():
    project = KnxProject()
    assert rs.applies(project)
    step_list = rs.steps(project)
    assert [s.number for s in step_list] == [1, 2, 3, 4, 5, 6, 7]
    assert all(s.state == rs.OPEN for s in step_list)
    assert rs.current(step_list, connected=False) == rs.CONNECT
    assert rs.current(rs.steps(project, connected=True), connected=True) == rs.SEARCH


def test_found_but_not_adopted():
    project = KnxProject()
    states = _states(project, connected=True, findings=70)
    assert states[rs.SEARCH] == rs.DONE and states[rs.ADOPT] == rs.OPEN
    assert rs.current(rs.steps(project, True, 70), True) == rs.ADOPT


def test_adopted_without_links_needs_bus_for_reading():
    project = _with_devices(KnxProject(), linked=False)
    states = _states(project)
    assert states[rs.SEARCH] == rs.DONE           # nach dem Laden: Geräte = gesucht
    assert states[rs.ADOPT] == rs.DONE and states[rs.LINKS] == rs.OPEN
    # GAs lesen braucht den Bus
    assert rs.current(rs.steps(project), connected=False) == rs.CONNECT


def test_meaning_building_and_tour():
    project = _with_devices(KnxProject())
    step_list = rs.steps(project, connected=True)
    assert {s.key: s.state for s in step_list}[rs.MEANING] == rs.OPEN   # vorläufig
    assert rs.current(step_list, True) == rs.MEANING
    ga = next(iter(project.group_addresses.all_addresses()))
    ga.designation = "L_1.1.1_01 E/A (Ausgang A)"
    step_list = rs.steps(project, connected=True)
    assert rs.current(step_list, True) == rs.BUILDING
    room = rb.add_room(project, "EG", "EG01", "Wohnen", zone="Innen")
    assert rs.current(rs.steps(project, True), True) == rs.TOUR
    ga.room_id = room.id
    tour = next(s for s in rs.steps(project, True) if s.key == rs.TOUR)
    assert tour.state == rs.PARTIAL and "1/1 GAs mit Raum" in tour.detail


def test_planned_project_with_devices_has_no_steps():
    project = _with_devices(KnxProject())
    project.topology.is_imported = False
    assert not rs.applies(project)


def _view(project):
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.views.device_scan_view import DeviceScanView
    QApplication.instance() or QApplication([])
    view = DeviceScanView()
    view.set_project(project)
    return view


def test_view_shows_steps_and_next_step():
    view = _view(KnxProject())
    assert not view._steps_box.isHidden()
    connect = view._step_buttons[rs.CONNECT]
    assert connect.text() == "1 Verbinden"
    assert connect.toolTip().startswith("Nächster Schritt")
    assert not view._step_buttons[rs.ADOPT].isEnabled()
    planned = _with_devices(KnxProject())
    planned.topology.is_imported = False
    view.set_project(planned)
    assert view._steps_box.isHidden()


def test_tour_without_rooms_offers_building(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    project = _with_devices(KnxProject())
    view = _view(project)
    targets = []
    view.navigate_requested.connect(targets.append)

    clicked = {}

    def fake_exec(box):
        clicked["box"] = box
        building = next(b for b in box.buttons() if b.text() == "Zuerst Gebäude erfassen")
        building.click()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    view._assign_rooms(tour=True)
    assert "box" in clicked and targets == ["building"]


def test_adopt_into_planned_project_warns(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from knix_arranger.services import device_scan as ds
    project = _with_devices(KnxProject())
    project.topology.is_imported = False
    view = _view(project)
    view._findings = [ds.ScanFinding(address="1.1.9", answered=True)]
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    view._adopt()
    assert asked and "mit KNiX geplant" in asked[0]
    assert "1.1.9" not in {d.physical_address for d in ds.project_devices(project)}


def test_new_project_dialog_reconstruct():
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.dialogs.new_project_dialog import NewProjectDialog
    QApplication.instance() or QApplication([])
    dialog = NewProjectDialog()
    assert not dialog.reconstruct and dialog.template_key == "efh" and dialog.start_wizard
    dialog._mode_reconstruct.setChecked(True)
    assert dialog.reconstruct
    assert dialog.template_key == "empty"           # kein Gebäude aus der Vorlage
    assert not dialog.start_wizard
    assert not dialog._template_box.isEnabled()
