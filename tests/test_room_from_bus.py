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
                        _co(1, "Bedienung Storen (M1), Wippen", "Stopp", ["0/1/2"]),
                        _co(5, "Sonnenschutz (M1), Position Höhe", "Status", ["0/6/1"],
                            size="1 Byte", flags="K-LÜ--", dpt="DPST-5-1")])
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
    # Status unter anderem Namen, gleicher Motor: ein Kanal
    assert plan.channels[("1.1.4", "Bedienung Storen (M1)")].addresses == [
        "0/1/1", "0/1/2", "0/6/1"]
    assert len(plan.channels) == 3
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
    # nur eine Rückmeldung (zyklisch, zufällig in diesen Sekunden): kein Kanal
    assert rb.channels_in_telegrams(plan, ["3/4/20", "0/2/4"]) == []
    assert rb.channels_in_telegrams(plan, ["0/6/1"]) == []


M1, M2 = ("1.1.4", "Bedienung Storen (M1)"), ("1.1.4", "Bedienung Storen (M2)")


def _device(project, address):
    return next(d for a in project.topology.areas for line in a.lines for d in line.devices
                if d.physical_address == address)


def _two_blinds_project():
    """Chalet Bibliothek: Taste 2 von 1.1.31 fährt M1 und M2 über die
    gemeinsame GA 0/1/9 (Gruppenbedienung); M2 hat eigene GA 0/1/5."""
    project = _project()
    blinds = _device(project, "1.1.4")
    blinds.communication_objects.append(
        _co(20, "Bedienung Storen (M2), Endlage", "Auf/Ab", ["0/1/5", "0/1/9"],
            dpt="DPST-1-8"))
    blinds.communication_objects.append(
        _co(21, "Bedienung Storen (M2), Wippen", "Stopp", ["0/1/6"]))
    blinds.communication_objects[0].connected_gas.append("0/1/9")
    _device(project, "1.1.31").communication_objects.append(
        _co(2, "Taste 2", "Auf/Ab", ["0/1/9"], flags="K-SÜ--"))
    mg = next(m for m in project.group_addresses.main_groups[0].middle_groups if m.number == 1)
    for sub, dpt in ((5, "DPST-1-8"), (6, "DPST-1-7"), (9, "DPST-1-8")):
        mg.group_addresses.append(GroupAddress(main_group=0, middle_group=1, sub_group=sub,
                                               designation=f"Storen 0/1/{sub} (1.1.4)",
                                               datapoint_type=dpt))
    gm.apply(project, gm.propose(project))
    return project


def test_group_ga_of_two_blinds_reaches_both_channels():
    plan = rb.analyse(_two_blinds_project())
    assert set(plan.operators["1.1.31"].channels) == {M1, M2}
    # die Gruppen-GA gehört keinem Kanal: «Einzeln ansteuern» fährt nur einen Storen
    assert plan.group_gas["0/1/9"] == [M1, M2]
    assert "0/1/9" not in plan.channels[M1].addresses
    assert plan.channels[M1].functions["AUF/AB"] == "0/1/1"
    # Logikserver auf die Gruppen-GA: beide Kanäle
    assert set(rb.channels_in_telegrams(plan, ["0/1/9"])) == {M1, M2}


def test_finish_room_gewerke_labels_and_function():
    project = _two_blinds_project()
    plan = rb.analyse(project)
    room = rb.add_room(project, "OG", "05", "Bibliothek")
    rb.assign(project, plan, room, "1.1.31", [M1, M2, ("1.1.1", "Ausgang B")])
    rb.set_channel_gewerk(project, plan, ("1.1.1", "Ausgang B"), "S")    # Steckdose
    summary = rb.finish_room(project, plan, room,
                             {M1: "Fenster gross Berg", M2: "Fenster klein Berg"})
    assert summary.gewerke == {"J": 2, "S": 1}
    assignment = next(a for a in room.gewerk_assignments if a.gewerk_code == "J")
    assert assignment.count == 2
    assert assignment.element_labels == ["Fenster gross Berg", "Fenster klein Berg"]
    gas = _by_address(project)
    assert gas["0/1/1"].designation == "J_OG_05_01 AUF/AB (Bibliothek Fenster gross Berg)"
    assert gas["0/1/5"].designation == "J_OG_05_02 AUF/AB (Bibliothek Fenster klein Berg)"
    assert gas["0/1/1"].assignment_id == assignment.id
    assert gas["0/2/3"].designation.startswith("S_OG_05_01 E/A (Bibliothek")
    # Gruppen-GA = Funktion mit den beiden Elementen, Name aus dem Klartext
    assert summary.functions == ["Fenster Berg"]
    function = project.functions[0]
    assert function.function_type == "FT-7" and function.room_id == room.id
    assert {(m.assignment_id, m.element_number) for m in function.members} == {
        (assignment.id, 1), (assignment.id, 2)}
    assert gas["0/1/9"].function_id == function.id
    assert gas["0/1/9"].designation == "J_OG_05_F1 AUF/AB (Fenster Berg)"
    # zweites Abschliessen: Klartext bleibt, Funktion wird nicht doppelt angelegt
    summary = rb.finish_room(project, plan, room, {}, {frozenset([M1, M2]): "Storen Berg"})
    assert len(project.functions) == 1 and project.functions[0].name == "Storen Berg"
    assert gas["0/1/9"].designation == "J_OG_05_F1 AUF/AB (Storen Berg)"
    assert gas["0/1/5"].designation == "J_OG_05_02 AUF/AB (Bibliothek Fenster klein Berg)"


def test_finish_room_temperature_without_heating_channel():
    project = _project()
    plan = rb.analyse(project)
    room = rb.add_room(project, "EG", "05", "Wohnen")
    rb.assign(project, plan, room, "1.1.40")
    summary = rb.finish_room(project, plan, room)
    assert summary.gewerke == {"H": 1}
    assert summary.hints and "kein Heizkanal" in summary.hints[0]
    assert _by_address(project)["3/2/22"].designation.startswith("H_EG_05_01 IST (Wohnen")


def test_suggest_function_name():
    assert rb.suggest_function_name(["Fenster gross Berg", "Fenster klein Berg"]) == \
        "Fenster Berg"
    assert rb.suggest_function_name(["Pult Ost", "Balkon"]) == "Pult Ost + Balkon"
    assert rb.suggest_function_name(["", ""]) == ""


def test_names_get_room_when_meaning_comes_after_assign():
    # Rundgang vor der Herstellerdatei: der Raum steht, der Name ist vorläufig
    project = _project()
    gas = _by_address(project)
    from knix_arranger.services.ets_corrections import set_ga_field
    for address in ("0/2/3", "0/2/4"):
        set_ga_field(project, gas[address], "designation", f"Ausgang B ({address})")
    plan = rb.analyse(project)
    room = rb.add_room(project, "EG", "05", "Wohnen")
    rb.assign(project, plan, room, "", [("1.1.1", "Ausgang B")])
    assert gas["0/2/3"].room_id == room.id and gas["0/2/3"].designation == "Ausgang B (0/2/3)"
    # nun «Bedeutung ergänzen» bzw. Herstellerdatei nachgeführt
    for address in ("0/2/3", "0/2/4"):
        set_ga_field(project, gas[address], "designation", f"Ausgang B Schalten (1.1.1)")
    gm.apply(project, [m for m in gm.propose(project) if m.address in ("0/2/3", "0/2/4")])
    assert gas["0/2/3"].designation == "L_EG_05_01 E/A (Wohnen Ausgang B)"
    assert gas["0/2/4"].designation == "L_EG_05_01 RM (Wohnen Ausgang B)"
    assert gas["0/2/3"].room_id == room.id


def test_finish_room_again_repairs_device_address_names():
    project = _project()
    gas = _by_address(project)
    plan = rb.analyse(project)
    room = rb.add_room(project, "EG", "05", "Wohnen")
    for address in ("0/2/3", "0/2/4"):       # Stand im RekChalet: Raum ja, Name alt
        gas[address].room_id = room.id
    assert gas["0/2/3"].designation.startswith("L_1.1.1_")
    result = rb.assign(project, plan, room, "", [("1.1.1", "Ausgang B")])
    assert result.renamed == 2
    assert gas["0/2/3"].designation == "L_EG_05_01 E/A (Wohnen Ausgang B)"


def test_add_room_creates_floor_once():
    project = _project()
    rb.add_room(project, "EG", "01", "Küche")
    rb.add_room(project, "eg", "02", "Essen")
    floors = [f for b in project.areal.buildings for f in b.all_floors]
    assert [f.short_code for f in floors].count("EG") == 1
    assert [label for label, _f, _r in rb.all_rooms(project)] == ["EG 01 Küche", "EG 02 Essen"]


def test_add_room_with_zones_innen_aussen():
    """Chalet: Innen über zwei Stockwerke (eine Zone), Aussen auf dem EG."""
    project = _project()
    kitchen = rb.add_room(project, "EG", "01", "Küche", zone="Innen")
    terrace = rb.add_room(project, "EG", "02", "Terrasse", zone="Aussen")
    library = rb.add_room(project, "OG", "01", "Bibliothek", zone="innen")
    eg = rb.find_floor(project.areal.buildings[0], "EG")
    assert [a.name for a in eg.apartments] == ["Innen", "Aussen"]   # keine leere «EG»
    og = rb.find_floor(project.areal.buildings[0], "OG")
    assert [a.name for a in og.apartments] == ["Innen"]             # Schreibweise bleibt
    assert project.areal.zone_name_for_room(library.id) == "Innen"
    assert project.areal.zone_name_for_room(terrace.id) == "Aussen"
    assert rb.zone_names(project) == ["Innen", "Aussen"]
    assert rb.room_label(project, kitchen.id) == "EG 01 Küche (Innen)"
    assert rb.room_place(project, terrace.id) == ("EG", "Aussen")
    # ohne Zone: die erste des Stockwerks, keine neue
    rb.add_room(project, "EG", "03", "Gang")
    assert len(eg.apartments) == 2


def test_add_room_existing_floor_gets_zone():
    """Bestehende leere Standardzone eines Stockwerks übernimmt den Namen."""
    from knix_arranger.services.building_service import BuildingService
    project = _project()
    project.areal = BuildingService.create_default_areal("Chalet")
    BuildingService.add_floor(project.areal.buildings[0].wings[0], "Erdgeschoss", "EG",
                              areal=project.areal)
    rb.add_room(project, "EG", "01", "Garten", zone="Aussen")
    eg = rb.find_floor(project.areal.buildings[0], "EG")
    assert [a.name for a in eg.apartments] == ["Aussen"]
    rb.add_room(project, "EG", "02", "Wohnen", zone="Innen")
    assert [a.name for a in eg.apartments] == ["Aussen", "Innen"]


def test_new_room_dialog_zone_and_confirmation(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from knix_arranger.ui.dialogs.room_assign_dialog import NewRoomDialog
    QApplication.instance() or QApplication([])
    project = _project()
    rb.add_room(project, "EG", "01", "Küche", zone="Innen")
    rb.add_room(project, "EG", "02", "Terrasse", zone="Aussen")
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    dialog = NewRoomDialog(project, None, "EG", "Aussen")
    assert dialog.zone.currentText() == "Aussen"
    dialog.floor.setCurrentText("1.OG")                 # vertippt
    dialog.name.setText("Balkon")
    dialog._accept()
    assert asked and "Stockwerk «1.OG»" in asked[0] and dialog.result() == 0
    dialog.floor.setCurrentText("EG")
    dialog.zone.setCurrentText("Aussen")
    asked.clear()
    dialog._accept()
    assert not asked
    room = dialog.create_room()
    assert project.areal.zone_name_for_room(room.id) == "Aussen"


def test_new_room_dialog_unique_number(monkeypatch):
    """Nummer nach dem Schema von Schritt 3; doppelte Nummer nur nach Rückfrage
    (sonst gleiche GA-Namen in zwei Räumen)."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    from knix_arranger.ui.dialogs.room_assign_dialog import NewRoomDialog
    QApplication.instance() or QApplication([])
    project = _project()
    rb.add_room(project, "EG", "EG01", "Küche", zone="Innen")
    rb.add_room(project, "EG", "EG02", "Wohnen", zone="Innen")
    asked = []
    # neue Zone: Ja; doppelte Nummer: Nein
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or (
                            QMessageBox.Yes if "noch nicht" in a[2] else QMessageBox.No))
    dialog = NewRoomDialog(project, None, "EG", "Aussen")
    assert dialog.number.text() not in ("", "EG01", "EG02")      # frei im Projekt
    dialog.number.setText("EG01")
    dialog.name.setText("Terrasse")
    dialog._accept()
    assert asked and "EG01" in asked[-1] and dialog.result() == 0


def test_add_room_in_second_wing():
    """Zwei Gebäudeteile mit je einem EG: der Raum kommt in den gewählten."""
    from knix_arranger.models.building import Wing
    from knix_arranger.services.building_service import BuildingService
    project = _project()
    project.areal = BuildingService.create_default_areal("Hotel")
    building = project.areal.buildings[0]
    north = building.wings[0]
    south = Wing(name="Süd")
    building.wings.append(south)
    BuildingService.add_floor(north, "Erdgeschoss", "EG", areal=project.areal)
    BuildingService.add_floor(south, "Erdgeschoss", "EG", areal=project.areal)
    room = rb.add_room(project, "EG", "EG01", "Lobby", wing=south)
    assert any(room in f.all_rooms for f in south.floors)
    assert rb.room_label(project, room.id) == "EG EG01 Lobby (Süd)"


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


def test_load_probe_like_function_test():
    project = _project()
    plan = rb.analyse(project)
    switch = plan.channels[("1.1.1", "Ausgang B")]
    assert switch.functions["E/A"] == "0/2/3" and switch.functions["RM"] == "0/2/4"
    step = rb.load_probe(project, switch)
    assert step.testable
    assert [(a.kind, a.address, a.payload) for a in rb.probe_actions(step)] == [
        ("send", "0/2/3", "01"), ("ask", "", ""), ("send", "0/2/3", "00")]
    blinds = rb.load_probe(project, plan.channels[("1.1.4", "Bedienung Storen (M1)")])
    assert [a.text or a.kind for a in rb.probe_actions(blinds)] == [
        "Ab", "wait", "Stopp", "ask", "Auf", "wait", "Stopp"]
    # Tor, Heizung: nie
    assert not rb.load_probe(project, rb.Channel("1.1.9", "Tor", "G", ["5/0/1"],
                                                 {"E/A": "5/0/1"})).testable
    assert not rb.load_probe(project, rb.Channel("1.1.9", "Kanal 1", "H", ["5/0/2"],
                                                 {"E/A": "5/0/2"})).testable
    # Schaltaktor im Storenbetrieb: Storen, ohne Stopp nicht
    pair = rb.Channel("1.1.15", "Ausgänge 1-2", "L", ["1/0/0", "1/0/1"],
                      {"AUF/AB": "1/0/0", "STOPP": "1/0/1"})
    assert rb.load_probe(project, pair).what().startswith("Ab")
    del pair.functions["STOPP"]
    assert rb.load_probe(project, pair).skip == "ohne GA STOPP"
    # offen: alle Kanäle ohne Raum
    room = rb.add_room(project, "EG", "05", "Wohnen")
    rb.assign(project, plan, room, "", [("1.1.1", "Ausgang A")])
    assert [c.key for c in rb.open_channels(project, plan)] == [
        ("1.1.1", "Ausgang B"), ("1.1.4", "Bedienung Storen (M1)")]


class _SendingMonitor(_Monitor):
    connected = True

    def send_telegram(self, address, service, payload, size, callback):
        self.sent.append((address, service, payload))
        callback("")


def _wait_until(condition, seconds=5.0):
    import time
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + seconds
    while not condition() and time.monotonic() < end:
        QApplication.processEvents()


def test_tour_load_search():
    _app()
    from PySide6.QtCore import Qt
    from knix_arranger.ui.dialogs import load_search_dialog as ls
    from knix_arranger.ui.dialogs import room_tour_dialog as rt
    project = _project()
    room = rb.add_room(project, "EG", "05", "Wohnen")
    monitor = _SendingMonitor()
    tour = rt.RoomTourDialog(project, monitor)
    tour._room_combo.setCurrentIndex(tour._room_combo.findData(room.id))
    tour._go_next()
    monitor.send("1.1.30", "0/2/1")                         # Taster -> Ausgang A
    tour._go_next()
    assert tour._loads_btn.isEnabled()
    channels = tour._loads_to_search()
    assert [c.key for c in channels] == [("1.1.1", "Ausgang B"),
                                         ("1.1.4", "Bedienung Storen (M1)")]

    dialog = ls.LoadSearchDialog(project, monitor, channels, "EG 05 Wohnen", {"L"})
    dialog.time_scale = 0
    # Gewerk des Raums angehakt, Storen nicht
    assert dialog.selected() == [("1.1.1", "Ausgang B")]
    dialog.set_checked([("1.1.1", "Ausgang B"), ("1.1.4", "Bedienung Storen (M1)")])
    answers = iter([True, False])
    dialog.ask = lambda step: next(answers)
    monitor.sent.clear()
    assert dialog.start(confirmed=True)
    _wait_until(lambda: not dialog._running)
    assert dialog.found == [("1.1.1", "Ausgang B")]
    # Licht Ein/Aus, Storen Ab-Stopp und zurück
    assert [(a, p) for a, _s, p in monitor.sent] == [
        ("0/2/3", "01"), ("0/2/3", "00"),
        ("0/1/1", "01"), ("0/1/2", "01"), ("0/1/1", "00"), ("0/1/2", "00")]

    tour._take_found(dialog.found)
    keys = {}
    for i in range(tour._tree.topLevelItemCount()):
        parent = tour._tree.topLevelItem(i)
        for j in range(parent.childCount()):
            item = parent.child(j)
            keys[item.data(0, Qt.UserRole)] = (item.text(3), item.checkState(0))
    assert keys[("1.1.1", "Ausgang B")] == ("Last gefunden", Qt.Checked)
    tour._go_next()                                         # Raum abschliessen
    gas = _by_address(project)
    assert gas["0/2/3"].room_id == room.id and gas["0/2/1"].room_id == room.id
    assert gas["0/1/1"].room_id != room.id
    tour.done(0)


def test_load_search_stop_resets_channel():
    _app()
    from knix_arranger.ui.dialogs import load_search_dialog as ls
    project = _project()
    plan = rb.analyse(project)
    monitor = _SendingMonitor()
    dialog = ls.LoadSearchDialog(project, monitor, rb.open_channels(project, plan), "Wohnen")
    dialog.time_scale = 0
    dialog.set_checked([("1.1.1", "Ausgang A"), ("1.1.1", "Ausgang B")])
    dialog.ask = lambda step: None                          # «Anhalten»
    dialog.start(confirmed=True)
    _wait_until(lambda: not dialog._running)
    # erster Kanal wieder aus, zweiter nicht mehr geschaltet
    assert [(a, p) for a, _s, p in monitor.sent] == [("0/2/1", "01"), ("0/2/1", "00")]
    assert dialog.found == []


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


def _tree_items(tour):
    from PySide6.QtCore import Qt
    items = {}
    for i in range(tour._tree.topLevelItemCount()):
        parent = tour._tree.topLevelItem(i)
        for j in range(parent.childCount()):
            item = parent.child(j)
            items[item.data(0, Qt.UserRole) or item.data(0, Qt.UserRole + 1)] = item
    return items


def test_tour_identify_blinds_and_function():
    """Zwei Storen auf einer Taste: einzeln ansteuern, Klartext eintragen,
    Gewerk korrigieren; beim Abschliessen Gewerke und Funktion."""
    _app()
    from knix_arranger.ui.dialogs import load_search_dialog as ls
    from knix_arranger.ui.dialogs import room_tour_dialog as rt
    project = _two_blinds_project()
    room = rb.add_room(project, "OG", "05", "Bibliothek")
    monitor = _SendingMonitor()
    tour = rt.RoomTourDialog(project, monitor)
    tour._room_combo.setCurrentIndex(tour._room_combo.findData(room.id))
    tour._go_next()
    monitor.send("1.1.31", "0/1/9")                          # Taste 2: beide Storen
    tour._go_next()
    items = _tree_items(tour)
    assert M1 in items and M2 in items
    function = items[frozenset([M1, M2])]
    assert function.text(rt._C_LABEL) == "Bedienung Storen (M1) + Bedienung Storen (M2)"
    assert tour._identify_btn.isEnabled()

    # einzeln ansteuern: jeder Storen für sich, nie über die Gruppen-GA
    channels = [tour._plan.channels[k] for k in (M1, M2)]
    dialog = ls.IdentifyDialog(project, monitor, channels, "OG 05 Bibliothek", {}, tour)
    dialog.time_scale = 0
    assert set(dialog.selected()) == {M1, M2}
    answers = iter([(ls.IDENTIFIED, "Fenster gross Berg"), (ls.IDENTIFIED, "Fenster klein Berg")])
    dialog.ask = lambda step: next(answers)
    monitor.sent.clear()
    assert dialog.start(confirmed=True)
    _wait_until(lambda: not dialog._running)
    assert "0/1/9" not in {a for a, _s, _p in monitor.sent}
    assert [a for a, _s, p in monitor.sent if p == "01"] == ["0/1/1", "0/1/2", "0/1/5", "0/1/6"]
    tour._take_identified(dialog.answers)
    items = _tree_items(tour)
    assert items[M1].text(rt._C_LABEL) == "Fenster gross Berg"
    assert items[frozenset([M1, M2])].text(rt._C_LABEL) == "Fenster Berg"
    assert "reagiert" in items[M2].text(rt._C_ORIGIN)

    tour._go_next()                                          # Raum abschliessen
    assert tour._pages.currentIndex() == rt._DONE
    assert "J ×2" in tour._done_text.text() and "Fenster Berg" in tour._done_text.text()
    gas = _by_address(project)
    assert gas["0/1/5"].designation == "J_OG_05_02 AUF/AB (Bibliothek Fenster klein Berg)"
    assert gas["0/1/9"].designation == "J_OG_05_F1 AUF/AB (Fenster Berg)"
    tour.done(0)
