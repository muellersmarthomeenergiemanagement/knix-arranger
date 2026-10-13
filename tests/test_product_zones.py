"""
Produkte mit KOs je Raum (Revox Multiuser 3.0): jeder KNiX-Raum erhält nur
die KOs seines Raums im Gerät, die Systemobjekte nur ein Raum. Bisher
erzeugte jeder der 6 Lautsprecher-Räume alle ausgewählten KOs (Projekt_23
Chalet Franziska: 780 statt 130 GAs).
"""
from __future__ import annotations
import copy
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.product_zones import (
    co_zone, is_zoned, propose_zones, same_product_elements, selected_zones,
    zone_excluded_numbers, zone_function, zone_label, zone_scheme, zones_of,
)

_FUNCTIONS = ["ROOM_ON_OFF", "ROOM_STATUS", "VOLUME_VALUE", "MUTE_ON_OFF"]


def _co(number, name):
    return {"number": number, "name": name, "function_text": name.replace("_", " "),
            "datapoint_type": "DPT-1 DPST-1-1", "communication_flag": True,
            "write_flag": True}


def _revox(zones=4) -> dict:
    cos = [_co(1, "SYSTEM_OFF"), _co(2, "SCENE_RECEIVE")]
    for z in range(1, zones + 1):
        for f in _FUNCTIONS:
            cos.append(_co(len(cos) + 1, f"R_{z}_{f}"))
    # Ausgewählt: Ein/Aus und Lautstärke in Raum 1, System Off
    keep = {"SYSTEM_OFF", "R_1_ROOM_ON_OFF", "R_1_VOLUME_VALUE"}
    return {"manufacturer": "Weinzierl", "order_number": "Revox Multiuser 3.0",
            "product_name": "Revox Multiuser 3.0", "com_objects": cos,
            "excluded_co_numbers": [c["number"] for c in cos if c["name"] not in keep]}


def test_zone_of_com_objects():
    revox = _revox()
    scheme = zone_scheme(revox)
    assert scheme.label == "Raum"
    assert co_zone({"name": "R_12_VOLUME_VALUE"}, scheme) == 12
    assert co_zone({"name": "SYSTEM_OFF"}, scheme) is None
    assert (zone_function({"name": "R_12_VOLUME_VALUE"}, scheme)
            == zone_function({"name": "R_3_VOLUME_VALUE"}, scheme))
    assert is_zoned(revox) and not is_zoned({"com_objects": [_co(1, "SYSTEM_OFF")]})
    assert selected_zones(revox) == [1]
    assert zone_label(revox, 3) == "Raum 3"


def _product(*texts, name_from_text=False):
    cos = [{"number": i, "name": t if name_from_text else f"KO {i}", "function_text": t,
            "datapoint_type": "", "communication_flag": True, "write_flag": True}
           for i, t in enumerate(texts, 1)]
    return {"manufacturer": "X", "order_number": "Y", "com_objects": cos}


def test_schemes_of_other_products():
    # Theben KNX-OT-Box: Zone/Raum, dazu Systemobjekte
    ot_box = _product("H1 Basissollwert Vorlauf", "Aussentemperatur",
                      "H1 Max. Stellgrösse Zone/Raum 1 bedarfsgesteuert",
                      "H1 Max. Stellgrösse Zone/Raum 2 bedarfsgesteuert",
                      "H2 Max. Stellgrösse Zone/Raum 11 Witterung + Bedarf")
    assert zone_scheme(ot_box).label == "Raum" and zones_of(ot_box) == [1, 2, 11]
    # ABB-Aktor: Kanal A, B, … (Buchstaben)
    abb = _product("Kanal A: Schalten", "Kanal A: Status", "Kanal B: Schalten",
                   "Kanal B: Status", "Zentral Schalten")
    assert zones_of(abb) == [1, 2] and zone_label(abb, 2) == "Kanal B"
    # Hager-Aktor: Ausgang n
    hager = _product("Ausgang 1 Schalten", "Ausgang 2 Schalten", "Ausgang 3 Schalten")
    assert zone_scheme(hager).label == "Ausgang" and zone_label(hager, 3) == "Ausgang 3"
    # Name deutsch, Text englisch (ABB UK/S): dasselbe Muster
    uks = _product("Channel 1, multiple operation", "Channel 2, multiple operation")
    for co, name in zip(uks["com_objects"], ("Kanal 1, Mehrfachbetätigung",
                                              "Kanal 2, Mehrfachbetätigung")):
        co["name"] = name
    assert zone_scheme(uks).label == "Kanal" and zones_of(uks) == [1, 2]


def test_no_scheme_for_inputs_buttons_and_few_matches():
    assert zone_scheme(_product("Eingang 1", "Eingang 2", "Eingang 3")) is None
    assert zone_scheme(_product("Taste 1 Schalten", "Taste 2 Schalten")) is None
    # nur ein Kanal: keine Zonen
    assert zone_scheme(_product("Kanal 1 Schalten", "Kanal 1 Status")) is None
    # zu wenige KOs mit Zone (unter einem Viertel)
    few = _product("Kanal 1 Info", "Kanal 2 Info", *[f"Parameter {c}" for c in "abcdefghij"])
    assert zone_scheme(few) is None


def test_channel_zone_keeps_selected_functions():
    abb = _product("Kanal A: Schalten", "Kanal A: Status", "Kanal B: Schalten",
                   "Kanal B: Status", "Zentral Schalten")
    abb["excluded_co_numbers"] = [2, 4]          # nur Schalten gewählt
    abb["zone"] = 2
    names = sorted(c["function_text"] for c in abb["com_objects"]
                   if c["number"] not in zone_excluded_numbers(abb))
    assert names == ["Kanal B: Schalten"]
    abb["system_objects"] = True
    assert len(abb["com_objects"]) - len(zone_excluded_numbers(abb)) == 2


def _names(product):
    excluded = zone_excluded_numbers(product)
    return sorted(c["name"] for c in product["com_objects"] if c["number"] not in excluded)


def test_zone_takes_selected_functions_of_its_room():
    product = _revox()
    # ohne Zone: wie bisher die Auswahl
    assert _names(product) == ["R_1_ROOM_ON_OFF", "R_1_VOLUME_VALUE", "SYSTEM_OFF"]
    product["zone"] = 3
    assert _names(product) == ["R_3_ROOM_ON_OFF", "R_3_VOLUME_VALUE"]
    product["system_objects"] = True
    assert _names(product) == ["R_3_ROOM_ON_OFF", "R_3_VOLUME_VALUE", "SYSTEM_OFF"]


def test_propose_zones_keeps_existing():
    products = [_revox(), {**_revox(), "zone": 1}, _revox()]
    propose_zones(products)
    assert [p["zone"] for p in products] == [2, 1, 3]
    assert [p.get("system_objects", False) for p in products] == [True, False, False]


def _project(n_rooms=3) -> KnxProject:
    project = KnxProject(name="Revox")
    rooms = [Room(number=f"W0{i}", name=f"Raum {i}",
                  gewerk_assignments=[GewerkAssignment(gewerk_code="MM",
                                                       linked_product=_revox())])
             for i in range(1, n_rooms + 1)]
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2,
                  apartments=[Apartment(name="Wohnung", rooms=rooms)])
    project.areal = Areal(buildings=[Building(name="Haus", wings=[Wing(floors=[floor])])])
    return project


def _mm_gas(project):
    return sorted(g.function_name for g in project.group_addresses.all_addresses()
                  if g.gewerk_code == "MM")


def test_generator_one_room_per_zone():
    logging.disable(logging.CRITICAL)
    project = _project()
    regenerate_addresses(project)
    # ohne Zone: jeder Raum alle ausgewählten KOs, auch System Off dreifach
    assert len(_mm_gas(project)) == 9
    elements = same_product_elements(project, _revox())
    products = [a.linked_product for _r, a, _nr in elements]
    propose_zones(products)
    regenerate_addresses(project)
    logging.disable(logging.NOTSET)
    gas = _mm_gas(project)
    assert len(gas) == 7
    assert sum("SYSTEM" in g for g in gas) == 1
    assert sum("R 3" in g for g in gas) == 2


def test_apply_to_other_rooms_keeps_zones():
    from knix_arranger.services.product_sync import apply_product_to
    project = _project(2)
    first, second = [a for r in project.all_rooms for a in r.gewerk_assignments]
    first.linked_product.update(zone=1, system_objects=True)
    second.linked_product.update(zone=2)
    source = copy.deepcopy(first.linked_product)
    source["excluded_co_numbers"] = []
    apply_product_to([(None, second)], source)
    assert second.linked_product["zone"] == 2
    assert "system_objects" not in second.linked_product
    assert second.linked_product["excluded_co_numbers"] == []


def test_zone_dialog_apply_and_warnings():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.product_zone_dialog import ProductZoneDialog
    rows = [("Wohnen", {**_revox(), "zone": 1, "system_objects": True}),
            ("Bad", _revox())]
    dlg = ProductZoneDialog("Revox", rows)
    assert dlg.windowTitle() == "Raum im Gerät zuordnen"
    assert dlg.values() == [(1, True), (0, False)]
    combo = dlg._combos[1]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "alle", "Raum 1", "Raum 2", "Raum 3", "Raum 4"]
    combo.setCurrentIndex(combo.findData(1))
    assert "mehreren KNiX-Räumen" in dlg._warning.text()
    combo.setCurrentIndex(combo.findData(4))
    dlg._checks[1].setChecked(True)
    assert "Systemobjekte" in dlg._warning.text()
    dlg._checks[1].setChecked(False)
    assert dlg._warning.text() == ""
    dlg.apply()
    assert rows[1][1]["zone"] == 4 and rows[1][1]["system_objects"] is False
    combo.setCurrentIndex(0)
    dlg.apply()
    assert "zone" not in rows[1][1]
