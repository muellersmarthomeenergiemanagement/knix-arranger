"""KOs von Tastern/Sensoren je Gerät zuordnen (sensor_channels).

Projekt_23: der Busch-Watchdog Sky 6131/40 schaltet über «P1: Bewegung
(Master)» (KO 10, Obj_SwitchOnOff) das Licht -- nicht über «Externer
Taster» (KO 13, empfängt nur) oder «Bewegung (Slave)» (KO 11). Seine
eigenen GAs (Gewerk A) heissen wie seine KOs ohne Klammerzusatz.
"""
from knix_arranger.models.topology import CommunicationObject
from knix_arranger.services.actor_channels import device_com_objects
from knix_arranger.services.co_linking_service import CoLinkingService
from knix_arranger.services.sensor_channels import (
    SENSOR_CO_KEY, chosen_sensor_co, ga_key, sensor_links, suggested_sensor_co_map,
)

from tests.test_ga_links import _project


def _melder_cos():
    return [
        CommunicationObject(object_number=1, name="Obj_Enable",
                            object_function="P1: Freigabe Bewegung", data_type="DPST-1-1",
                            flags="K-Ü-U"),
        CommunicationObject(object_number=10, name="Obj_SwitchOnOff",
                            object_function="P1: Bewegung (Master)", data_type="DPST-1-1",
                            flags="K--S-"),
        CommunicationObject(object_number=11, name="Obj_TimedStartStop",
                            object_function="P1: Bewegung (Slave)", data_type="DPST-1-1",
                            flags="K-ÜS-"),
        CommunicationObject(object_number=13, name="Obj_ExternalSwitch",
                            object_function="P1: Externer Taster", data_type="DPST-1-1",
                            flags="K-Ü-U"),
    ]


def _setup():
    project = _project()
    devices = {d.physical_address: d for area in project.topology.areas
               for line in area.lines for d in line.devices}
    melder = devices["1.2.105"]
    melder.communication_objects = _melder_cos()
    # Der Melder schaltet in Waschen auch das Licht (Kanal 1)
    from knix_arranger.models.building import FunctionAssignment, SensorFunktion
    waschen = project.all_rooms[0]
    be = waschen.bedienelemente[1]
    be.funktionen.append(SensorFunktion(gewerk_code="L", element_number=1))
    be.function_assignments = [FunctionAssignment(
        button_channel="Kanal 1", function_ga="L_CUG01_01 E/A (Waschen Deckenlicht)")]
    return project, melder


def test_gas_des_melders():
    project, melder = _setup()
    links = {link.ga_address: link for link in sensor_links(project, melder)
             if not link.role}
    assert set(links) == {"4/0/1", "4/5/1"}  # Licht schalten, eigenes Element (A)
    assert links["4/5/1"].channel == "Gewerk A 1"
    assert links["4/0/1"].channel.startswith("Kanal") and not links["4/0/1"].feedback


def test_vorschlag_nach_name_und_ausgang():
    project, melder = _setup()
    links = sensor_links(project, melder)
    selection = suggested_sensor_co_map(melder, links, device_com_objects(melder))
    by_address = {link.ga_address: selection.get(link.key) for link in links
                  if not link.role}
    assert by_address["4/5/1"] == 10        # «P1: Bewegung» = KO 10 (Master)
    # Licht schalten: derselbe sendende Ausgang, nicht «Externer Taster»
    # (empfängt nur) oder «Bewegung (Slave)»
    assert by_address["4/0/1"] == 10


def test_ga_key_bleibt_ohne_adresse():
    project, _melder = _setup()
    ga = next(g for g in project.group_addresses.all_addresses() if g.address == "4/0/1")
    key = ga_key(ga)
    ga.sub_group = 99
    assert ga_key(ga) == key and key.endswith("|E/A")


def test_verknuepfung_nach_auswahl():
    project, melder = _setup()
    ga = next(g for g in project.group_addresses.all_addresses() if g.address == "4/5/1")
    melder.co_map = {SENSOR_CO_KEY: {ga_key(ga): 10}}
    assert chosen_sensor_co(melder, ga).object_number == 10
    service = CoLinkingService()
    proposals = [p for p in service.generate_proposals(project)
                 if p.physical_address == "1.2.105"]
    assert [(p.co_number, p.ga_address) for p in proposals] == [(10, "4/5/1")]
    service.apply_proposals(project, proposals)
    co = next(c for c in melder.communication_objects if c.object_number == 10)
    assert co.connected_gas == ["4/5/1"]


def test_gleichnamige_kos_nach_nummer():
    """ABB RM/S4.1: alle KOs von Ausgang A heissen «Ausgang A (6 A)» -- die
    RM-GA gehört an KO 55, nicht an den ersten gleichnamigen KO 50."""
    project, _melder = _setup()
    actor = next(d for area in project.topology.areas for line in area.lines
                 for d in line.devices if d.physical_address == "1.2.13")
    actor.communication_objects = [
        CommunicationObject(object_number=50, name="Ausgang A (6 A)",
                            object_function="Schalten", data_type="DPST-1-1", flags="K-Ü--"),
        CommunicationObject(object_number=55, name="Ausgang A (6 A)",
                            object_function="Status Schalten", data_type="DPST-1-1",
                            flags="KL-S-"),
    ]
    from knix_arranger.services.actor_channels import circuit_key
    waschen = project.all_rooms[0]
    actor.co_map = {circuit_key(waschen.id, "L", 1): {"E/A": 50, "RM": 55}}
    service = CoLinkingService()
    proposals = [p for p in service.generate_proposals(project)
                 if p.physical_address == "1.2.13" and p.ga_address.startswith("4/0/")]
    service.apply_proposals(project, proposals)
    linked = {co.object_number: co.connected_gas for co in actor.communication_objects}
    assert linked[50] == ["4/0/1"] and linked[55] == ["4/0/2"]


def test_zweites_element_auf_zweiten_kanal():
    """Garage: ein 6131/40 trägt A ×2, beide Elemente heissen «P1: …» --
    das zweite gehört auf die KOs von P2."""
    from knix_arranger.services.sensor_channels import SensorLink, _nth_channel
    assert _nth_channel("P1: Bewegung", 1) == "P2: Bewegung"
    assert _nth_channel("Bewegung", 1) == "Bewegung"
    cos = _melder_cos() + [CommunicationObject(
        object_number=26, name="Obj_SwitchOnOff", object_function="P2: Bewegung (Master)",
        data_type="DPST-1-1", flags="K--S-")]
    links = [SensorLink(f"k{n}", f"Gewerk A {n}", "P1: Bewegung", f"3/3/{n}", "",
                        "P1: Bewegung", "DPST-1-1", False) for n in (1, 2)]
    assert suggested_sensor_co_map(None, links, cos) == {"k1": 10, "k2": 26}


def test_rollen_an_vorhandene_gas():
    """Der Melder schaltet L «Deckenlicht»: «Aktorstatus» hört auf dessen RM,
    «Externer Taster» auf dessen E/A -- keine eigenen GAs."""
    project, melder = _setup()
    melder.communication_objects.append(CommunicationObject(
        object_number=4, name="Obj_InputOnOff", object_function="P1: Aktorstatus",
        data_type="DPST-1-1", flags="K-Ü-U"))
    links = sensor_links(project, melder)
    roles = {link.role: link for link in links if link.role}
    assert set(roles) == {"aktorstatus", "extern"}
    assert (roles["aktorstatus"].ga_address, roles["aktorstatus"].feedback) == ("4/0/2", True)
    assert roles["extern"].ga_address == "4/0/1"
    selection = suggested_sensor_co_map(melder, links, device_com_objects(melder))
    assert selection[roles["aktorstatus"].key] == 4
    assert selection[roles["extern"].key] == 13
    # KO-Verknüpfung: E/A an KO 10 (senden) und KO 13 (hören)
    melder.co_map = {SENSOR_CO_KEY: selection}
    service = CoLinkingService()
    service.apply_proposals(project, service.generate_proposals(project))
    linked = {co.object_number: co.connected_gas for co in melder.communication_objects}
    assert "4/0/1" in linked[10] and linked[13] == ["4/0/1"] and linked[4] == ["4/0/2"]


def test_ohne_rollen_ko_keine_rolle():
    project, melder = _setup()
    melder.communication_objects = [co for co in melder.communication_objects
                                    if co.object_number != 13]
    assert not [link for link in sensor_links(project, melder) if link.role]


def _with_weather_station(project, melder):
    """Wetterstation (Gewerk W) mit Helligkeit Ost/Süd und ein Melder-KO
    «P1: Externe Helligkeit»."""
    from knix_arranger.models.group_address import GroupAddress, MiddleGroup
    hg = next(h for h in project.group_addresses.main_groups if h.number == 4)
    hg.middle_groups.append(MiddleGroup(number=4, name="Wetter", group_addresses=[
        GroupAddress(main_group=4, middle_group=4, sub_group=1, designation="W HELLIGKEIT OST",
                     gewerk_code="W", function_name="HELLIGKEIT OST", datapoint_type="DPST-9-4"),
        GroupAddress(main_group=4, middle_group=4, sub_group=2, designation="W HELLIGKEIT SUED",
                     gewerk_code="W", function_name="HELLIGKEIT SUED", datapoint_type="DPST-9-4"),
        # Lichtwert (DPT 5) ist keine Helligkeit in Lux
        GroupAddress(main_group=4, middle_group=4, sub_group=3, designation="LC HELLIGKEIT",
                     gewerk_code="LC", function_name="HELLIGKEIT", datapoint_type="DPST-5-1"),
    ]))
    melder.communication_objects.append(CommunicationObject(
        object_number=6, name="Obj_BrightnessExternal", object_function="P1: Externe Helligkeit",
        data_type="DPT-9", flags="K-Ü-U"))


def test_externe_helligkeit_von_der_wetterstation():
    from knix_arranger.services.sensor_channels import SOURCE_KEY, brightness_sources
    project, melder = _setup()
    _with_weather_station(project, melder)
    assert [ga.function_name for ga in brightness_sources(project, melder)] == [
        "HELLIGKEIT SUED", "HELLIGKEIT OST"]
    links = [link for link in sensor_links(project, melder) if link.role == "helligkeit"]
    # je Kanal des Melders ein Link, Vorgabe Süd
    assert {(link.channel, link.ga_function, link.feedback) for link in links} == {
        ("Gewerk A 1", "HELLIGKEIT SUED", True), ("Kanal 2", "HELLIGKEIT SUED", True)}
    own = next(link for link in links if link.channel == "Gewerk A 1")
    selection = suggested_sensor_co_map(melder, links, device_com_objects(melder))
    assert selection[own.key] == 6
    # Andere Quelle gewählt (Dialog): die Verknüpfung folgt ihr
    ost = brightness_sources(project, melder)[1]
    selection = {own.key: 6}
    melder.co_map = {SENSOR_CO_KEY: selection, SOURCE_KEY: {own.key: ga_key(ost)}}
    service = CoLinkingService()
    service.apply_proposals(project, service.generate_proposals(project))
    co = next(c for c in melder.communication_objects if c.object_number == 6)
    assert co.connected_gas == ["4/4/1"]


def test_ohne_quelle_keine_externe_helligkeit():
    project, melder = _setup()
    melder.communication_objects.append(CommunicationObject(
        object_number=6, name="Obj_BrightnessExternal", object_function="P1: Externe Helligkeit",
        data_type="DPT-9", flags="K-Ü-U"))
    assert not [link for link in sensor_links(project, melder) if link.role == "helligkeit"]
