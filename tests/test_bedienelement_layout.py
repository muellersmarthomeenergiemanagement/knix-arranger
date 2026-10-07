"""Tests fuer die Tastenbelegung im Bedienelemente-Bericht."""
from types import SimpleNamespace

import pytest
from knix_arranger.models.project import KnxProject
from knix_arranger.models.group_address import GroupAddress
from knix_arranger.services.bedienelement_layout import (
    parse_button, group_assignments, ga_function_label, button_plan, ButtonKey,
)
from knix_arranger.services.dpt_suggestion import dpt_number


@pytest.mark.parametrize("channel, expected", [
    ("Taste 3, links", (3, "links", "", False)),
    ("Taste 3, rechts, Signal-LED", (3, "rechts", "", True)),
    ("Taste 2, links, Signal LED", (2, "links", "", True)),
    ("Taste 1, Doppelklick", (1, "", "Doppelklick", False)),
    ("Taste 2, rechts (langer Tastendruck)", (2, "rechts", "lang", False)),
    ("Taste 4", (4, "", "", False)),
    ("Taste 4, Signal-LED", (4, "", "", True)),
    # Einzeltaster ohne Nummer (Projekt_23, Raum Technik): Taste 1
    ("Taste", (1, "", "", False)),
    ("Taste (langer Tastendruck)", (1, "", "lang", False)),
])
def test_parse_button(channel, expected):
    key, is_led = parse_button(channel)
    assert (key.number, key.side, key.variant, is_led) == expected


def test_kein_tastenbezug():
    assert parse_button("Nachtabsenkung LED's") is None
    assert parse_button("Raumtemperatur") is None
    assert parse_button("Status") is None
    assert parse_button("Tastereinheit") is None


def test_einzeltaster_bekommt_tastenplan():
    rows = group_assignments(
        [_fa("Taste", "L_CUG02_01 E/A (Wohnung / Technik)"),
         _fa("Status", "L_CUG02_01 RM (Wohnung / Technik)")],
        lambda t: None,
    )
    assert [r.key.label() if r.key else r.name for r in rows] == ["1", "Status"]
    assert [e["number"] for e in button_plan(rows, KnxProject().gewerk_catalog)] == [1]


def _fa(channel, ga):
    return SimpleNamespace(button_channel=channel, function_ga=ga, description="")


def test_eine_zeile_pro_taste_mit_led():
    move = GroupAddress(main_group=3, middle_group=1, sub_group=40,
                        designation="J.OG.04.02_move ( Fenster )", gewerk_code="J")
    step = GroupAddress(main_group=3, middle_group=1, sub_group=41,
                        designation="J.OG.04.02_step", gewerk_code="J")
    led = GroupAddress(main_group=0, middle_group=5, sub_group=5, designation="J.Sicherheit_ea")
    gas = {g.address: g for g in (move, step, led)}
    assignments = [
        _fa("Taste 2", "3/1/40  J.OG.04.02_move ( Fenster )"),
        _fa("Taste 2", "3/1/41  J.OG.04.02_step"),
        _fa("Taste 2, Signal-LED", "0/5/5  J.Sicherheit_ea"),
        _fa("Nachtabsenkung LED's", "0/4/250  Tag/Nacht_Chalet"),
    ]
    rows = group_assignments(assignments, lambda t: gas.get(t.split()[0]))

    assert [r.key.label() if r.key else r.name for r in rows] == ["2", "Nachtabsenkung LED's"]
    assert rows[0].gas == [move, step]
    assert rows[0].led_gas == [led]
    assert rows[1].gas == ["Tag/Nacht_Chalet"]            # unbekannte GA: Text ohne Adresse

    catalog = KnxProject().gewerk_catalog
    plan = button_plan(rows, catalog, room_name="Wohnen")
    assert plan == [{"number": 2, "cells": [(catalog.get("J").name, "Fenster")]}]


def test_beschriftung_szene_und_raumname():
    catalog = KnxProject().gewerk_catalog
    scene = GroupAddress(designation="Raum1_Szene High ( Toilette )")
    assert ga_function_label(scene, catalog, room_name="01 Toilette") == ("Szene", "High")
    light = GroupAddress(designation="LDA.OG.01.02_ea ( Wandleuchten )", gewerk_code="LDA")
    assert ga_function_label(light, catalog) == (catalog.get("LDA").name, "Wandleuchten")


def test_links_rechts_im_raster():
    rows = group_assignments(
        [_fa("Taste 1, links", "Licht A"), _fa("Taste 1, rechts", "Licht B"),
         _fa("Taste 1, Doppelklick", "Licht C")],
        lambda t: None,
    )
    plan = button_plan(rows, KnxProject().gewerk_catalog)
    assert plan == [{"number": 1, "cells": [("Licht A", ""), ("Licht B", "")]}]
    assert ButtonKey(1, "", "Doppelklick").label() == "1 Doppelklick"


def test_dpt_number():
    assert dpt_number("DPST-1-22") == "1.022"
    assert dpt_number("DPT-9") == "9.xxx"
    assert dpt_number("") == ""


def test_bedienbar_oder_sensor():
    from knix_arranger.models.building import Bedienelement
    assert Bedienelement(element_type="Tastereinheit").is_operable
    assert Bedienelement(element_type="Raumthermostat").is_operable
    assert not Bedienelement(element_type="Präsenzmelder").is_operable
    assert not Bedienelement(element_type="Wassermelder").is_operable


def test_bericht_bedienelemente_und_sensoren(tmp_path):
    fitz = pytest.importorskip("fitz")
    from knix_arranger.models.building import (
        Areal, Building, Wing, Floor, Apartment, Room, Bedienelement,
    )
    from knix_arranger.models.topology import Area, Line, Device
    from knix_arranger.services.report_service import ReportService

    room = Room(number="01", name="Technik")
    room.bedienelemente = [Bedienelement(element_type="Tastereinheit", participant_number="1.1.5")]
    project = KnxProject(name="BE")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="UG", short_code="UG", apartments=[Apartment(rooms=[room])])])])])
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1, devices=[
        Device(physical_address="1.1.5", device_type="sensor", product="Taster"),
        # im Raum, aber nicht als Bedienelement erfasst
        Device(physical_address="1.1.24", device_type="sensor", product="Leak KNX 2.0",
               room_id=room.id),
    ])])]
    path = str(tmp_path / "be.pdf")
    ReportService(project).generate_bedienelemente_report(path)
    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    toc = [t[1] for t in doc.get_toc()]
    doc.close()
    assert "Bedienelemente und Sensoren" in text
    assert "Sensoren" in text and "Wassermelder" in text
    assert "UG" in toc and "01 Technik" in toc


def test_vorschlaege_ohne_adresse_nur_im_wizard_projekt():
    from knix_arranger.models.building import Bedienelement
    vorschlag = Bedienelement(element_type="Raumthermostat", is_auto=True)
    ets = Bedienelement(element_type="Tastereinheit", is_auto=True, participant_number="1.1.5")
    manuell = Bedienelement(element_type="Tastereinheit", is_auto=False)
    assert vorschlag.is_shown(imported=False)
    assert not vorschlag.is_shown(imported=True)
    assert ets.is_shown(imported=True)
    assert manuell.is_shown(imported=True)
    assert not Bedienelement(suppressed=True).is_shown(imported=False)
