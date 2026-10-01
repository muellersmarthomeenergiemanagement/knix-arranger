"""Bedienungsanleitung für den Bauherrn (FA-2001 bis FA-2004)."""
from knix_arranger.services.bedienelement_layout import ButtonKey
from knix_arranger.services.user_manual import (
    describe_from_dpt, describe_from_params, led_text, object_label,
    parse_button_configuration, sensor_sentence,
)
from knix_arranger.models.group_address import GroupAddress

CONFIG = """Anzahl Tasten: 4
Bedienphilosophie Taste 1: 2x 1-Tastenbedienung
Bedienphilosophie Taste 4: 2-Tastenbedienung
Bedienphilosophie Taste 5: Raumthermostat

Taste 1, links:
  Funktion Taste: Schalten
  Funktion Schalten: Drücken: UM
  Funktion LED: Status Signal-LED-Objekt (externes Signal)
  LED Anzeigemodus: Status normal
  LED Farbe: blau
  Langer Tastendruck Taste links: aktiv
  Zeit für langen Tastendruck: 2 Sek.
  Funktion langer Tastendruck: Schalten
  Funktion Schalten: AUS

Taste 3, links:
  Funktion Taste: Dimmen
  Funktion Dimmen: EIN/heller     (kurz/lang)
  Funktion LED: nicht aktiv (immer ausgeschaltet)

Taste 4:
  Funktion Taste: Jalousie
  Funktion Jalousie links: AUF (EIB, kurz: Schritt/Stop, lang: Fahren)
  Funktion Jalousie rechts: AB (EIB, kurz: Schritt/Stop, lang: Fahren)
  erweiterte Funktionen Jalousie: fahren Beschattung (Doppelklick: lang/kurz)
"""


def test_parameter_werden_gelesen():
    cfg = parse_button_configuration(CONFIG)
    assert cfg.philosophy[4] == "2-Tastenbedienung"
    assert cfg.philosophy[5] == "Raumthermostat"
    t1 = cfg.params(ButtonKey(1, "links"))
    assert t1.values == {"Funktion Schalten": "Drücken: UM"}
    assert t1.long_values == {"Funktion Schalten": "AUS"}
    assert t1.led_color == "blau"
    # Wippe "Taste 4:" gilt für links und rechts
    assert cfg.params(ButtonKey(4, "rechts")).function == "Jalousie"


def test_bedienung_in_alltagssprache():
    cfg = parse_button_configuration(CONFIG)
    short, how = describe_from_params(cfg.params(ButtonKey(1, "links")), "links")
    assert short == "Ein/Aus"
    assert how == ["drücken: Ein/Aus", "lang drücken (2 Sek.): Aus"]
    short, how = describe_from_params(cfg.params(ButtonKey(3, "links")), "links")
    assert how == ["kurz drücken: Ein · lang drücken: heller"]
    _short, how = describe_from_params(cfg.params(ButtonKey(4)), "")
    assert "links: auf · rechts: ab" in how
    assert "Doppelklick: in die Beschattungsposition fahren" in how
    assert led_text(cfg.params(ButtonKey(1, "links"))) == \
        "Leuchtanzeige blau: leuchtet, wenn eingeschaltet"
    assert led_text(cfg.params(ButtonKey(3, "links"))) == ""


def test_ohne_parameter_aus_dem_dpt():
    dim = GroupAddress(datapoint_type="DPST-3-7")
    assert describe_from_dpt([dim])[1] == ["kurz drücken: Ein/Aus · lang drücken: dimmen"]
    assert describe_from_dpt([GroupAddress(datapoint_type="DPST-1-8")])[0] == "Auf / Ab"


def test_beschriftung_ohne_technische_bezeichnung():
    ga = GroupAddress(main_group=2, designation="T.EG.01.03_ea   ( Tor Einstellhalle Berg )")
    assert object_label(ga, None, "Haupteingang") == "Tor Einstellhalle Berg"
    assert object_label(GroupAddress(designation="Anwesend-1bit"), None, "") == "Anwesend"
    assert object_label(GroupAddress(designation="Raum1_Szene High   ( Carnozet )"),
                        None, "") == "Szene High"


def test_sensoren_als_satz():
    assert sensor_sentence("Rauchmelder").startswith("Rauchmelder: warnt")
    assert "automatisch" in sensor_sentence("Präsenzmelder")


def test_musik_lautstaerke_und_titel():
    """Praxisfall Chalet 1.1.51: Taste 3 Lautstärke, Taste 4 Titel vor/zurück."""
    from knix_arranger.services.user_manual import adapt_to_target
    vol = GroupAddress(designation="MM.OG.02.01_dim Lautstärke (Wohnen)",
                       datapoint_type="Dimmer Schritt")
    label = object_label(vol, None, "Halle")
    assert label == "Musik Wohnen – Lautstärke"
    short, how = adapt_to_target("Ein / heller", ["kurz drücken: Ein · lang drücken: heller"],
                                 [vol], label, "Dimmen")
    assert (short, how) == ("lauter", ["lang drücken: lauter"])

    step = GroupAddress(designation="MM.OG.03.01_schritt Rückw/Vorw (Wohnen)",
                        datapoint_type="Schritt")
    label = object_label(step, None, "Halle")
    assert label == "Musik Wohnen – Titel zurück/vor"
    assert adapt_to_target("Aus", ["drücken: Aus"], [step], label, "Schalten") == \
        ("zurück", ["drücken: zurück"])

    music = GroupAddress(designation="MM_S1_MusikChalet_ea", datapoint_type="Schalten")
    assert object_label(music, None, "Halle") == "Musik Chalet – S1"


def test_licht_dimmen_bleibt_heller():
    from knix_arranger.services.user_manual import adapt_to_target
    gas = [GroupAddress(designation="LDA.EG.00.04_ea ( Wandleuchten )", datapoint_type="DPST-1-1"),
           GroupAddress(designation="LDA.EG.00.04_dim ( Wandleuchten )", datapoint_type="DPST-3-7")]
    assert adapt_to_target("Ein / heller", ["kurz drücken: Ein · lang drücken: heller"],
                           gas, "Wandleuchten", "Dimmen")[1] == \
        ["kurz drücken: Ein · lang drücken: heller"]


def test_szenen_namen_aus_ga_kommentar():
    """Chalet 1.1.61: Wert-Tasten auf 0/4/1 mit Kommentar "#1: Anwesend …"."""
    from knix_arranger.services.user_manual import name_scene_values
    cfg = parse_button_configuration(
        "Taste 1, rechts:\n"
        "  Funktion Taste: Wert\n"
        "  Funktion Wert: 1Byte Wert senden\n"
        "  1Byte Wert (0..255): 1\n"
        "  Langer Tastendruck Taste rechts: aktiv\n"
        "  Zeit für langen Tastendruck: 2 Sek.\n"
        "  Funktion langer Tastendruck: Wert\n"
        "  Funktion Wert: 1Byte Wert senden\n"
        "  1Byte Wert (0..255): 2\n")
    params = cfg.params(ButtonKey(1, "rechts"))
    assert (params.value, params.long_value) == ("1", "2")
    ga = GroupAddress(designation="Anwesendheit Chalet", datapoint_type="Szenensteuerung",
                      comment="#1: Anwesend\n#2: Abwesend\n#3: Ferien")
    short, how = describe_from_params(params, "rechts")
    short, how = name_scene_values(params, ga, short, how)
    assert short == "Abwesend"
    assert how == ["drücken: «Abwesend»", "lang drücken (2 Sek.): «Ferien»"]


def test_tor_statt_jalousie():
    from knix_arranger.services.user_manual import adapt_to_target
    short, how = adapt_to_target("Auf", ["lang drücken: auffahren · kurz drücken: Stopp / Lamellen"],
                                 [], "Garagentor", "Jalousie")
    assert (short, how) == ("öffnen", ["lang drücken: öffnen · kurz drücken: Stopp"])


def test_geplantes_projekt_szenen_und_ga_per_bezeichnung():
    """Test Musik: geplante Belegung verweist per GA-Bezeichnung, Taste ruft Szene auf."""
    from knix_arranger.models.project import KnxProject
    from knix_arranger.models.scene import Scene
    from knix_arranger.models.building import (
        Areal, Building, Wing, Floor, Apartment, Room, Bedienelement,
        SensorFunktion, FunctionAssignment,
    )
    from knix_arranger.models.group_address import (
        GroupAddressStructure, MainGroup, MiddleGroup,
    )
    from knix_arranger.services.user_manual import UserManualBuilder

    project = KnxProject(name="Test Musik")
    konzert = Scene(name="Konzert", scene_number=5, scope="apartment")
    project.scenes = [konzert]
    mg = MiddleGroup(number=0, name="Licht")
    mg.group_addresses = [
        GroupAddress(main_group=1, middle_group=0, sub_group=1, gewerk_code="LDA",
                     designation="LDA_M01_01 E/A (Musikzimmer)", datapoint_type="DPST-1-1"),
        GroupAddress(main_group=1, middle_group=0, sub_group=2, gewerk_code="LDA",
                     designation="LDA_M01_01 DIM (Musikzimmer)", datapoint_type="DPST-3-7"),
        GroupAddress(main_group=1, middle_group=0, sub_group=9, gewerk_code="LDA",
                     designation="LDA_M01_01 SZENE (Musikzimmer)", datapoint_type="DPST-17-1"),
    ]
    project.group_addresses = GroupAddressStructure(
        main_groups=[MainGroup(number=1, name="EG", middle_groups=[mg])])
    sf = SensorFunktion(label="Konzert", scene_id=konzert.id,
                        ga_designation="LDA_M01_01 SZENE", action_type="kurz")
    be = Bedienelement(element_type="Tastereinheit", is_auto=False, funktionen=[sf],
                       function_assignments=[
                           FunctionAssignment(button_channel="Taste 1",
                                              function_ga="LDA_M01_01 E/A (Musikzimmer)"),
                           FunctionAssignment(button_channel="Taste 1",
                                              function_ga="LDA_M01_01 DIM", action_type="lang"),
                           FunctionAssignment(button_channel="Taste 3", sf_id=sf.id,
                                              function_ga="LDA_M01_01 SZENE"),
                       ])
    room = Room(number="01", name="Musikzimmer", bedienelemente=[be])
    floor = Floor(name="EG", short_code="EG")
    floor.apartments = [Apartment(name="Studio", rooms=[room])]
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])

    builder = UserManualBuilder(project)
    lines = {kl.key.label(): kl for kl in builder.key_lines(be, room.name)}
    assert lines["1"].label == "Licht"
    assert lines["1"].how == ["kurz drücken: Ein/Aus · lang drücken: dimmen"]
    assert lines["3"].label == "Szene «Konzert»"
    assert lines["3"].how == ["drücken: Szene abrufen"]


def test_szenenbeschreibung():
    from knix_arranger.models.project import KnxProject
    from knix_arranger.models.scene import Scene, SceneAction
    from knix_arranger.models.group_address import (
        GroupAddressStructure, MainGroup, MiddleGroup,
    )
    from knix_arranger.services.user_manual import UserManualBuilder
    project = KnxProject(name="X")
    call = GroupAddress(main_group=1, middle_group=0, sub_group=9, gewerk_code="LDA",
                        designation="LDA_M01_01 SZENE", datapoint_type="DPST-17-1")
    dim = GroupAddress(main_group=1, middle_group=0, sub_group=3, gewerk_code="LDA",
                       designation="LDA_M01_01 WERT (Decke)", datapoint_type="DPST-5-1")
    mg = MiddleGroup(number=0, name="Licht", group_addresses=[call, dim])
    project.group_addresses = GroupAddressStructure(
        main_groups=[MainGroup(number=1, name="EG", middle_groups=[mg])])
    scene = Scene(name="Konzert", actions=[
        SceneAction(group_address="LDA_M01_01 SZENE", ga_address="1/0/9"),
        SceneAction(group_address="LDA_M01_01 WERT (Decke)", value="30 %", ga_address="1/0/3"),
    ])
    builder = UserManualBuilder(project)
    assert builder.scene_description(scene, call, "Musikzimmer") == "Decke 30 %"
    assert builder.scene_description(Scene(name="Nacht"), call, "Musikzimmer") == \
        "stellt das Licht im Raum ein"
