"""
Räume aus dem Bus (FA-3105c): Raumvorschläge aus den Verknüpfungen, Zuordnen
mit Umbenennen der GAs, Vorschläge nach einem Tastendruck.
"""
from __future__ import annotations

from datetime import datetime

from knix_arranger.models.group_address import GroupAddress, MainGroup, MiddleGroup
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line
from knix_arranger.services import ga_meaning as gm
from knix_arranger.services import room_from_bus as rb
from knix_arranger.services.bus_access import LiveTelegram


def _co(number, name, function, gas, size="1 Bit", flags="K-S---", dpt=""):
    return CommunicationObject(object_number=number, name=name, object_function=function,
                               connected_gas=gas, object_size=size, flags=flags, data_type=dpt)


def _project():
    """Schaltaktor 1.1.1 (A, B), Storen 1.1.4 (M1), Zentral-GA an drei
    Kanälen, Taster 1.1.30 schaltet A direkt und hat eine Szene, Taster
    1.1.31 spricht nur mit einem Logikserver (GA ohne Aktor), Taster
    1.1.32 fährt M1, Sensor 1.1.40 mit Temperatur."""
    project = KnxProject()
    switch = Device(physical_address="1.1.1", device_type="actor",
                    product="AT/S8.16.5 Switch Actuator", communication_objects=[
                        _co(0, "Ausgang A", "Schalten", ["0/2/1", "0/2/9"]),
                        _co(1, "Ausgang A", "Telegr. Status", ["0/2/2"], flags="K--Ü--"),
                        _co(2, "Ausgang A", "Szene", ["0/4/1"], size="1 Byte",
                            dpt="DPST-17-1"),
                        _co(10, "Ausgang B", "Schalten", ["0/2/3", "0/2/9"]),
                        _co(11, "Ausgang B", "Telegr. Status", ["0/2/4"], flags="K--Ü--")])
    blinds = Device(physical_address="1.1.4", device_type="actor",
                    product="9x blind actuator JAX-9", communication_objects=[
                        _co(0, "Bedienung Storen (M1), Endlage", "Auf/Ab", ["0/1/1", "0/2/9"],
                            dpt="DPST-1-8"),
                        _co(1, "Bedienung Storen (M1), Wippen", "Stopp", ["0/1/2"])])
    button = Device(physical_address="1.1.30", device_type="sensor",
                    product="Taster EDIZIOdue 1-8fach", communication_objects=[
                        _co(0, "Taste 1", "Schalten", ["0/2/1"], flags="K-SÜ--"),
                        _co(1, "Taste 1, Signal LED", "Status", ["0/2/2"], flags="K-S---"),
                        _co(5, "Taste 2", "Szene", ["0/4/1"], size="1 Byte", flags="K--Ü--",
                            dpt="DPST-17-1")])
    logic = Device(physical_address="1.1.31", device_type="sensor",
                   product="Taster EDIZIOdue 1-8fach", communication_objects=[
                       _co(0, "Taste 1", "Schalten", ["3/4/20"], flags="K-SÜ--")])
    blinds_button = Device(physical_address="1.1.32", device_type="sensor",
                           product="Taster EDIZIOdue 1-8fach", communication_objects=[
                               _co(0, "Taste 1", "Auf/Ab", ["0/1/1"], flags="K-SÜ--"),
                               _co(1, "Taste 1", "Stopp", ["0/1/2"], flags="K-SÜ--")])
    sensor = Device(physical_address="1.1.40", device_type="sensor",
                    product="Raumbediengerät", communication_objects=[
                        _co(70, "Raumtemperatur", "Temperatur", ["3/2/22"], size="2 Byte",
                            flags="K-LÜ--", dpt="DPST-9-1")])
    devices = [switch, blinds, button, logic, blinds_button, sensor]
    project.topology.areas.append(Area(area_number=1, lines=[Line(line_number=1,
                                                                  devices=devices)]))
    project.topology.is_imported = True
    names = {}
    for device in devices:
        for co in device.communication_objects:
            for address in co.connected_gas:
                names.setdefault(address, f"{co.name} {co.object_function} "
                                          f"({device.physical_address})")
    groups: dict[int, MainGroup] = {}
    for address, name in sorted(names.items()):
        main, middle, sub = (int(p) for p in address.split("/"))
        hg = groups.setdefault(main, MainGroup(number=main, name=f"Hauptgruppe {main}"))
        mg = next((m for m in hg.middle_groups if m.number == middle), None)
        if mg is None:
            mg = MiddleGroup(number=middle, name=f"Mittelgruppe {main}/{middle}")
            hg.middle_groups.append(mg)
        mg.group_addresses.append(GroupAddress(main_group=main, middle_group=middle,
                                               sub_group=sub, designation=name))
    project.group_addresses.main_groups.extend(groups.values())
    gm.apply(project, gm.propose(project))
    return project


def _by_address(project):
    return {ga.address: ga for ga in project.group_addresses.all_addresses()}


def test_operators_and_channels():
    plan = rb.analyse(_project())
    assert set(plan.operators) == {"1.1.30", "1.1.31", "1.1.32", "1.1.40"}
    # Taster 1 schaltet A, LED zeigt den Status von A; Szene und Zentral-GA
    # (0/2/9 an A, B und M1) verbinden nicht
    assert plan.operators["1.1.30"].channels == [("1.1.1", "Ausgang A")]
    assert plan.operators["1.1.32"].channels == [("1.1.4", "Bedienung Storen (M1)")]
    assert plan.operators["1.1.31"].channels == []
    assert plan.operators["1.1.31"].addresses == ["3/4/20"]      # zum Logikserver
    assert plan.operators["1.1.40"].addresses == ["3/2/22"]
    assert "0/2/9" not in plan.channels[("1.1.1", "Ausgang A")].addresses
    assert "0/4/1" not in plan.channels[("1.1.1", "Ausgang A")].addresses
    assert [c.key for c in plan.orphan_channels()] == [("1.1.1", "Ausgang B")]
    groups = {tuple(ops): chs for ops, chs in plan.groups}
    assert groups[("1.1.30",)] == [("1.1.1", "Ausgang A")]


def test_assign_renames_with_room():
    project = _project()
    plan = rb.analyse(project)
    room = rb.add_room(project, "EG", "05", "Wohnen")
    result = rb.assign(project, plan, room, "1.1.30", [("1.1.1", "Ausgang A")])
    assert result.device_moved and result.channels == 1
    gas = _by_address(project)
    assert gas["0/2/1"].designation == "L_EG_05_01 E/A (Wohnen Ausgang A)"
    assert gas["0/2/2"].designation == "L_EG_05_01 RM (Wohnen Ausgang A)"
    assert gas["0/2/1"].room_id == room.id and gas["0/2/1"].element_number == 1
    # Zentral-GA bleibt
    assert gas["0/2/9"].designation.startswith("SF_ZE_") or "_ZE_" in gas["0/2/9"].designation
    # Raum am Taster, bei importierten Projekten in der Korrekturschicht
    from knix_arranger.services.device_scan import project_devices
    device = next(d for d in project_devices(project) if d.physical_address == "1.1.30")
    assert device.room_id == room.id
    assert project.ets_corrections.room_by_device["1.1.30"]["room"] == "EG|05"

    # zweiter Kanal im selben Raum und Gewerk: nächste Nummer
    rb.assign(project, plan, room, "", [("1.1.1", "Ausgang B")])
    assert _by_address(project)["0/2/3"].designation == "L_EG_05_02 E/A (Wohnen Ausgang B)"

    # Umziehen: Raumname im Klartext wird ersetzt, nicht gestapelt
    other = rb.add_room(project, "OG", "", "Bibliothek")
    rb.assign(project, plan, other, "", [("1.1.1", "Ausgang A")])
    assert _by_address(project)["0/2/1"].designation == "L_OG_01 E/A (Bibliothek Ausgang A)"


def test_sensor_gas_follow_the_device():
    project = _project()
    plan = rb.analyse(project)
    room = rb.add_room(project, "EG", "05", "Wohnen")
    rb.assign(project, plan, room, "1.1.40")
    ga = _by_address(project)["3/2/22"]
    assert ga.room_id == room.id
    assert ga.designation.startswith("H_EG_05_01 IST (Wohnen")


def test_own_name_keeps_text():
    project = _project()
    gas = _by_address(project)
    from knix_arranger.services.ets_corrections import set_ga_field
    set_ga_field(project, gas["0/2/3"], "designation", "Licht Gang")
    plan = rb.analyse(project)
    room = rb.add_room(project, "EG", "05", "Wohnen")
    rb.assign(project, plan, room, "", [("1.1.1", "Ausgang B")])
    assert gas["0/2/3"].designation == "Licht Gang"
    assert gas["0/2/3"].room_id == room.id


def test_channels_after_key_press():
    plan = rb.analyse(_project())
    # Taster 1.1.31 -> Logikserver -> schaltet B (0/2/3), B meldet Status (0/2/4)
    assert rb.channels_in_telegrams(plan, ["3/4/20", "0/2/3", "0/2/4"]) == [
        ("1.1.1", "Ausgang B")]


def test_add_room_creates_floor_once():
    project = _project()
    rb.add_room(project, "EG", "01", "Küche")
    rb.add_room(project, "eg", "02", "Essen")
    floors = [f for b in project.areal.buildings for f in b.all_floors]
    assert [f.short_code for f in floors].count("EG") == 1
    assert [label for label, _f, _r in rb.all_rooms(project)] == ["EG 01 Küche", "EG 02 Essen"]


def _telegram(source, destination, seconds_ago=0.0, service="Write"):
    from datetime import timedelta
    return LiveTelegram(datetime.now() - timedelta(seconds=seconds_ago), source, destination,
                        service, "01", 0)


def test_key_objects_only():
    plan = rb.analyse(_project())
    # Taste mit Senden-Flag zählt, LED (ohne Senden) und Temperatur nicht
    assert plan.operators["1.1.30"].key_gas == {"0/2/1", "0/4/1"}
    assert plan.operators["1.1.40"].key_gas == set()
    assert not rb.is_key_object(_co(0, "Rauchm.:Alarm (1: Aktiv)", "", ["1/1/1"],
                                    flags="K-LÜ--"))
    assert not rb.is_key_object(_co(0, "Helligkeitswert", "", ["1/1/1"], size="2 Bytes",
                                    flags="K-LÜ--"))
    assert rb.is_key_object(_co(0, "Taste 2, rechts (langer Tastendruck)", "", ["1/1/1"],
                                flags="K--Ü--"))


def test_session_records_presses_without_noise():
    plan = rb.analyse(_project())
    # 1.1.31 sendet vor dem Start regelmässig auf 3/4/20 -> Grundrauschen
    history = [_telegram("1.1.31", "3/4/20", 90), _telegram("1.1.31", "3/4/20", 30),
               _telegram("1.1.30", "0/2/1", 20)]           # einmal: kein Rauschen
    session = rb.RoomSession(plan, history)
    assert session.noise == {("1.1.31", "3/4/20")}
    assert session.feed(_telegram("1.1.31", "3/4/20"), 0.0) == ""
    assert session.feed(_telegram("1.1.40", "3/2/22"), 0.5) == ""     # Messwert
    assert session.feed(_telegram("1.1.30", "0/2/1"), 1.0) == "1.1.30"
    session.feed(_telegram("1.1.60", "0/2/3"), 2.0)       # Logikserver schaltet B
    session.feed(_telegram("1.1.1", "0/2/4"), 9.0)        # zu spät
    assert session.pressed["1.1.30"].count == 1
    assert session.candidates() == [(("1.1.1", "Ausgang A"), "verknüpft"),
                                    (("1.1.1", "Ausgang B"), "nach Tastendruck")]
    session.remove("1.1.30")
    assert session.feed(_telegram("1.1.30", "0/2/1"), 10.0) == ""
    assert session.candidates() == []
    session.add("1.1.32")
    assert session.candidates() == [(("1.1.4", "Bedienung Storen (M1)"), "verknüpft")]


class _Monitor:
    listening = True

    def __init__(self):
        self.listeners = []
        self.sent = []

    def add_listener(self, listener):
        self.listeners.append(listener)

    def remove_listener(self, listener):
        self.listeners.remove(listener)

    def history(self):
        return list(self.sent)

    def send(self, source, destination):
        telegram = _telegram(source, destination)
        self.sent.append(telegram)
        for listener in list(self.listeners):
            listener(telegram)


def _app():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])


def test_tour_dialog_room_keys_reaction():
    _app()
    from PySide6.QtCore import Qt
    from knix_arranger.ui.dialogs import room_tour_dialog as rt
    project = _project()
    room = rb.add_room(project, "EG", "05", "Wohnen")
    monitor = _Monitor()
    dialog = rt.RoomTourDialog(project, monitor)
    assert monitor.listeners
    monitor.send("1.1.30", "0/2/1")                       # vor dem Raum: zählt nicht
    dialog._room_combo.setCurrentIndex(dialog._room_combo.findData(room.id))
    dialog._go_next()
    assert dialog._pages.currentIndex() == rt._KEYS
    assert dialog._session.pressed == {}
    # Taster über den Logikserver, danach Status von B; Temperatur stört nicht
    monitor.send("1.1.40", "3/2/22")
    monitor.send("1.1.31", "3/4/20")
    monitor.send("1.1.60", "0/2/3")
    monitor.send("1.1.1", "0/2/4")
    assert list(dialog._session.pressed) == ["1.1.31"]
    assert dialog._pressed.count() == 1
    dialog._go_next()
    assert dialog._pages.currentIndex() == rt._REACT
    gewerk = dialog._tree.topLevelItem(0)
    item = gewerk.child(0)
    assert item.data(0, Qt.UserRole) == ("1.1.1", "Ausgang B")
    assert item.checkState(0) == Qt.Checked
    dialog._go_next()                                    # Raum abschliessen
    assert dialog._pages.currentIndex() == rt._DONE
    gas = _by_address(project)
    assert gas["0/2/3"].designation == "L_EG_05_01 E/A (Wohnen Ausgang B)"
    assert gas["3/4/20"].room_id == room.id
    assert "EG 05 Wohnen" in dialog._done_title.text()
    assert "Zugeordnet: 1 von 4" in dialog._progress.text()
    dialog._go_next()                                    # nächster Raum
    assert dialog._pages.currentIndex() == rt._ROOM
    assert dialog._room_combo.currentData() == ""
    dialog.done(0)
    assert not monitor.listeners


def test_overview_dialog_without_live():
    _app()
    from knix_arranger.ui.dialogs.room_assign_dialog import RoomAssignDialog
    project = _project()
    room = rb.add_room(project, "EG", "05", "Wohnen")
    monitor = _Monitor()
    dialog = RoomAssignDialog(project, monitor)
    assert not monitor.listeners                          # springt nicht mehr
    dialog._select(("op", "1.1.30"))
    dialog._room.setCurrentIndex(dialog._room.findData(room.id))
    dialog._do_assign()
    assert _by_address(project)["0/2/1"].designation == "L_EG_05_01 E/A (Wohnen Ausgang A)"
    dialog.done(0)
