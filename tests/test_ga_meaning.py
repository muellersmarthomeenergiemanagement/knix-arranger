"""
Bedeutung ergänzen (FA-3105b): Gewerk, Funktion, Element und Name nach dem
Namensschema für GAs, die aus den Geräten gelesen wurden.
"""
from __future__ import annotations

from knix_arranger.models.group_address import GroupAddress, MainGroup, MiddleGroup
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line
from knix_arranger.services import ga_meaning as gm


def _co(number, name, function, gas, size="1 Bit", flags="K-S---", dpt=""):
    return CommunicationObject(object_number=number, name=name, object_function=function,
                               connected_gas=gas, object_size=size, flags=flags, data_type=dpt)


def _project():
    project = KnxProject()
    dali = Device(physical_address="1.1.9", device_type="gateway",
                  product="DALI-Gateway KNX plus", communication_objects=[
                      _co(10, "G1, Schalten,", "An/Aus", ["0/0/1"]),
                      _co(11, "G1, Dimmen,", "Heller/Dunkler", ["0/0/2"], size="4 Bit"),
                      _co(15, "G1, Status,", "An/Aus", ["0/0/3"], flags="K-LÜ--")])
    blinds = Device(physical_address="1.1.4", device_type="actor",
                    product="9x blind actuator JAX-9", communication_objects=[
                        _co(0, "Bedienung Storen (M1), Endlage", "Auf/Ab", ["0/1/1"],
                            dpt="DPST-1-8"),
                        _co(1, "Bedienung Storen (M1), Wippen", "Stopp", ["0/1/2"]),
                        _co(20, "Bedienung Storen (M2), Endlage", "Auf/Ab", ["0/1/3"])])
    switch = Device(physical_address="1.1.1", device_type="actor",
                    product="AT/S8.16.5 Switch Actuator", communication_objects=[
                        _co(0, "Ausgang A", "Schalten", ["0/2/1"]),
                        _co(1, "Ausgang A", "Telegr. Status", ["0/2/2"], flags="K--Ü--")])
    heating = Device(physical_address="1.1.7", device_type="actor",
                     product="Actuator for thermal positioners", communication_objects=[
                         _co(0, "Stellgröße, Kanal 1", "Schalten", ["0/3/1"])])
    button = Device(physical_address="1.1.30", device_type="sensor",
                    product="Taster EDIZIOdue 1-8fach", communication_objects=[
                        _co(0, "Taste 1", "Schalten", ["0/2/1"], flags="K-SÜ--"),
                        _co(5, "Taste 2", "Szene", ["0/4/1"], size="1 Byte", flags="K--Ü--",
                            dpt="DPST-17-1")])
    project.topology.areas.append(Area(area_number=1, lines=[Line(
        line_number=1, devices=[dali, blinds, switch, heating, button])]))
    project.topology.is_imported = True
    groups = {}
    for device in (dali, blinds, switch, heating, button):
        for co in device.communication_objects:
            for address in co.connected_gas:
                groups.setdefault(address, f"{co.name} {co.object_function} "
                                           f"({device.physical_address})")
    groups["0/2/9"] = "L.EG.01_ea (Küche)"          # Name aus der ETS: bleibt
    hg = MainGroup(number=0, name="Hauptgruppe 0")
    for address, name in sorted(groups.items()):
        main, middle, sub = (int(p) for p in address.split("/"))
        mg = next((m for m in hg.middle_groups if m.number == middle), None)
        if mg is None:
            mg = MiddleGroup(number=middle, name=f"Mittelgruppe 0/{middle}")
            hg.middle_groups.append(mg)
        mg.group_addresses.append(GroupAddress(main_group=main, middle_group=middle,
                                               sub_group=sub, designation=name))
    project.group_addresses.main_groups.append(hg)
    return project


def test_provisional_names():
    assert gm.is_provisional(GroupAddress(designation="Ausgang A Schalten (1.1.5)"))
    assert gm.is_provisional(GroupAddress(designation=""))
    assert not gm.is_provisional(GroupAddress(designation="L.EG.01_ea (Küche)"))


def test_channel_from_ko_name():
    assert gm._channel(_co(0, "G9, Status,", "", [])) == "G9"
    assert gm._channel(_co(0, "Stellgröße, Kanal 1", "", [])) == "Kanal 1"
    assert gm._channel(_co(0, "Bedienung Storen (M1), Endlage", "", [])) == \
        "Bedienung Storen (M1)"
    assert gm._channel(_co(0, "Ausgang A", "", [])) == "Ausgang A"
    assert gm._channel(_co(7, "", "", [])) == "KO 7"


def test_propose_and_apply():
    project = _project()
    by = {m.address: m for m in gm.propose(project)}
    assert "0/2/9" not in by                                    # ETS-Name bleibt
    # Produkt vor KO-Text: DALI-Gateway «Dimmen» ist LDA
    assert (by["0/0/1"].designation, by["0/0/2"].designation, by["0/0/3"].designation) == (
        "LDA_1.1.9_01 E/A (G1)", "LDA_1.1.9_01 DIM (G1)", "LDA_1.1.9_01 RM (G1)")
    assert by["0/1/1"].designation == "J_1.1.4_01 AUF/AB (Bedienung Storen (M1))"
    assert by["0/1/2"].designation == "J_1.1.4_01 STOPP (Bedienung Storen (M1))"
    assert by["0/1/3"].element == 2
    # Schalten am Aktor, nicht an der Taste; Status als Rückmeldung
    assert by["0/2/1"].designation == "L_1.1.1_01 E/A (Ausgang A)"
    assert by["0/2/2"].function == "RM"
    # schaltende Stellgrösse (1 Bit) heisst nach Schema E/A
    assert by["0/3/1"].gewerk == "H" and by["0/3/1"].function == "E/A"
    assert by["0/4/1"].function == "SZENE"
    stellwert = _co(3, "Ausgang A", "Stellwert (PWM)", [], size="1 Byte")
    assert gm._function_of(stellwert, "") == "STELLGROESSE"
    assert gm._function_of(_co(4, "Temperaturwert", "Senden", [], size="2 Bytes",
                               flags="K-LÜ--"), "", "DPST-9-1") == "IST"
    assert gm._function_of(_co(4, "Feuchte", "Messwert", [], size="2 Bytes"), "",
                           "DPST-9-7") == "MESSWERT"

    result = gm.apply(project, list(by.values()))
    assert result.named == 10 and result.gewerke["LDA"] == 3
    gas = {g.address: g for g in project.group_addresses.all_addresses()}
    assert gas["0/0/2"].designation == "LDA_1.1.9_01 DIM (G1)"
    assert gas["0/0/2"].gewerk_code == "LDA" and gas["0/0/2"].function_name == "DIM"
    assert gas["0/2/9"].designation == "L.EG.01_ea (Küche)"
    # in der Korrekturschicht: der vorläufige Name ist der «ETS»-Wert
    entry = project.ets_corrections.ga_fields["0/0/2"]["designation"]
    assert entry["ets"] == "G1, Dimmen, Heller/Dunkler (1.1.9)"
    # Mittelgruppen nach Gewerk, Hauptgruppe nur bei klarer Mehrheit
    names = {mg.number: mg.name for mg in project.group_addresses.main_groups[0].middle_groups}
    assert names[0] == "Licht dimmbar DALI" and names[1] == "Jalousie"
    assert project.group_addresses.main_groups[0].name == "Hauptgruppe 0"
    # Szene (DPT 17) erkannt
    assert result.scenes == 1
    assert "10 GAs benannt" in result.text()
    # zweites Mal: nichts mehr vorläufig
    assert not [m for m in gm.propose(project) if m.designation]


def test_central_ga_and_unique_names():
    """GA an drei und mehr Aktorkanälen = Zentral-GA «ZE»; gleiche Namen
    werden nummeriert."""
    project = _project()
    switch = project.topology.areas[0].lines[0].devices[2]
    switch.communication_objects += [
        _co(2, "Ausgang B", "Schalten", ["0/2/5"]),
        _co(4, "Ausgang C", "Schalten", ["0/2/5"])]
    switch.communication_objects[0].connected_gas.append("0/2/5")
    switch.communication_objects[0].connected_gas.append("0/2/6")    # zweiter Weg
    mg = project.group_addresses.main_groups[0].middle_groups[2]
    for sub in (5, 6):
        mg.group_addresses.append(GroupAddress(main_group=0, middle_group=2, sub_group=sub,
                                               designation=f"Ausgang A Schalten (1.1.1)"))
    by = {m.address: m for m in gm.propose(project)}
    assert by["0/2/5"].designation == "L_ZE_01 E/A (3 Kanäle)"
    names = [m.designation for m in by.values() if m.designation]
    assert len(names) == len(set(names))
    assert by["0/2/6"].designation == "L_1.1.1_01 E/A (Ausgang A · 2)"
