"""Produkt von Gerät und GA-Planung abgleichen (FA-621).

Projekt_23 Technik: Gewerk A ×2 (Rauchmelder, Wassermelder); der
Wassermelder 1.2.113 ist in der Materialliste ein Elsner Leak, die GAs von
Element 2 folgten aber dem Standard des Gewerks.
"""
from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, GewerkAssignment, Room,
    SensorFunktion, Wing,
)
from knix_arranger.models.group_address import GroupAddressStructure
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line
from knix_arranger.services.product_sync import (
    apply_device_product, communication_objects_of, device_elements, device_product,
    product_mismatches, release_sensor_products, sensor_products_on_actor_gewerke,
)
from knix_arranger.services.validation_engine import ValidationEngine

_LEAK_COS = [
    {"number": 2, "name": "Leckage Alarm", "function_text": "Leckage Alarm",
     "datapoint_type": "DPST-1-1", "communication_flag": True, "transmit_flag": True},
    {"number": 3, "name": "Alarm Text", "function_text": "{{0}}Leckage Alarm Text",
     "datapoint_type": "DPST-16-0", "communication_flag": True, "transmit_flag": True},
]


def _project(imported=False):
    room = Room(number="CUG02", name="Technik")
    assignment = GewerkAssignment(gewerk_code="A", count=2)
    assignment.set_element_labels(["Rauchmelder", "Wassermelder"])
    room.gewerk_assignments = [assignment]
    room.bedienelemente = [
        Bedienelement(element_type="Rauchmelder", participant_number="1.2.109", is_auto=False,
                      funktionen=[SensorFunktion(gewerk_code="A", element_number=1)]),
        Bedienelement(element_type="Wassermelder", participant_number="1.2.113", is_auto=False,
                      funktionen=[SensorFunktion(gewerk_code="A", element_number=2)]),
    ]
    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[Floor(
        name="UG", short_code="UG", main_group_number=4,
        apartments=[Apartment(name="Wohnung", rooms=[room])])])])])
    rauch = Device(physical_address="1.2.109", device_type="sensor",
                   product="Rauchmelder", room_id=room.id)
    wasser = Device(physical_address="1.2.113", device_type="sensor",
                    product="Wassermelder", room_id=room.id, manufacturer="Elsner",
                    order_number="70316", product_name="Leak KNX 2.0",
                    communication_objects=communication_objects_of(_LEAK_COS))
    project.topology.areas = [Area(area_number=1, lines=[
        Line(line_number=2, devices=[rauch, wasser], assigned_room_ids=[room.id])])]
    project.topology.is_imported = imported
    return project, room, assignment, wasser


def test_elemente_des_geraets():
    project, room, assignment, wasser = _project()
    assert device_elements(project, wasser) == [(room, assignment, 2)]


def test_abweichung_und_uebernahme():
    project, _room, assignment, wasser = _project()
    mismatches = product_mismatches(project)
    assert [(m.device.physical_address, m.element_nr) for m in mismatches] == [("1.2.113", 2)]
    assert mismatches[0].element_text == "Gewerk A, Element 2 Wassermelder"
    # Rauchmelder ohne Produkt: keine Abweichung

    product = device_product(wasser, catalog=None)   # ohne Katalog: KOs des Geräts
    assert [co["number"] for co in product["com_objects"]] == [2, 3]
    assert product["com_objects"][0]["transmit_flag"] is True
    apply_device_product(mismatches, product)
    assert assignment.element_products[2]["order_number"] == "70316"
    assert assignment.linked_product is None
    assert product_mismatches(project) == []


def test_ein_element_wird_produkt_fuer_alle():
    project, room, assignment, wasser = _project()
    assignment.count = 1
    room.bedienelemente[1].funktionen[0].element_number = 1
    apply_device_product(product_mismatches(project), device_product(wasser, catalog=None))
    assert assignment.linked_product["order_number"] == "70316"
    assert assignment.element_products == {}


def test_kommunikationsobjekte_aus_dem_katalog():
    """Ältere Zuweisungen speicherten die KOs nicht am Gerät (Projekt_23
    1.2.113) -- dann zählen die KOs des Katalogeintrags."""
    project, _room, _assignment, wasser = _project()
    wasser.communication_objects = []

    class Catalog:
        def find_product(self, manufacturer, order_number, product_name=""):
            return {"com_objects": _LEAK_COS} if order_number == "70316" else None
    assert product_mismatches(project, catalog=None) == []
    assert len(product_mismatches(project, catalog=Catalog())) == 1
    assert [co["number"] for co in device_product(wasser, Catalog())["com_objects"]] == [2, 3]


def test_gewerk_mit_aktor_bleibt_beim_aktor():
    """Projekt_23 Waschen: der Bewegungsmelder 1.2.105 schaltet L
    «Deckenlicht» und LDA -- deren GAs (E/A, RM) gehören dem Aktor, das
    Produkt des Melders darf sie nicht ersetzen."""
    project, room, assignment, wasser = _project()
    licht = GewerkAssignment(gewerk_code="L", count=1)
    dali = GewerkAssignment(gewerk_code="LDA", count=1)
    room.gewerk_assignments += [licht, dali]
    room.bedienelemente[1].funktionen += [SensorFunktion(gewerk_code="L", element_number=1),
                                          SensorFunktion(gewerk_code="LDA", element_number=1)]
    assert [(a.gewerk_code, nr) for _r, a, nr in device_elements(project, wasser)] == [
        ("A", 2), ("L", 1), ("LDA", 1)]
    assert [(m.assignment.gewerk_code, m.element_nr)
            for m in product_mismatches(project)] == [("A", 2)]


def test_rueckstand_sensorprodukt_auf_aktor_gewerk():
    """Projekt_23 Waschen: L «Deckenlicht» trug noch das Produkt des
    Bewegungsmelders -- der Aktor 1.2.13 erhielt «P1: Bewegung» statt E/A.
    Erkennen, warnen, entfernen."""
    project, room, _assignment, wasser = _project()
    licht = GewerkAssignment(gewerk_code="L", count=2)
    licht.element_products[1] = device_product(wasser, catalog=None)
    room.gewerk_assignments.append(licht)
    room.bedienelemente[1].funktionen.append(SensorFunktion(gewerk_code="L", element_number=1))
    found = sensor_products_on_actor_gewerke(project)
    assert [(m.assignment.gewerk_code, m.element_nr) for m in found] == [("L", 1)]
    issues = [i for i in ValidationEngine().validate(GroupAddressStructure(), project)
              if i.rule_id == "FA-621" and "gehören aber dem Aktor" in i.message]
    assert len(issues) == 1 and "Element 1" in issues[0].message
    release_sensor_products(found)
    assert licht.element_products == {}
    assert sensor_products_on_actor_gewerke(project) == []


def test_importiert_ohne_abgleich():
    project, *_ = _project(imported=True)
    assert product_mismatches(project) == []


def test_validierung_warnt():
    project, *_ = _project()
    issues = [i for i in ValidationEngine().validate(GroupAddressStructure(), project)
              if i.rule_id == "FA-621"]
    assert len(issues) == 1 and issues[0].level == "warning"
    assert "1.2.113" in issues[0].message and "Standard des Gewerks" in issues[0].message


_MELDER_COS = [
    {"number": 10, "name": "Obj_SwitchOnOff", "function_text": "P1: Bewegung (Master)",
     "datapoint_type": "DPST-1-1", "communication_flag": True, "transmit_flag": True},
    {"number": 1, "name": "Obj_Enable", "function_text": "P1: Freigabe Bewegung",
     "datapoint_type": "DPST-1-1", "communication_flag": True, "write_flag": True,
     "update_flag": True},
    {"number": 13, "name": "Obj_ExternalSwitch", "function_text": "P1: Externer Taster",
     "datapoint_type": "DPST-1-1", "communication_flag": True, "write_flag": True},
    {"number": 11, "name": "Obj_TimedStartStop", "function_text": "P1: Bewegung (Slave)",
     "datapoint_type": "DPST-1-1", "communication_flag": True, "write_flag": True,
     "transmit_flag": True},
]


def test_vorauswahl_was_der_sensor_meldet():
    """6131/40: eigene GA nur für «Bewegung (Master)» -- Eingänge nicht."""
    from knix_arranger.services.product_sync import default_excluded_numbers
    assert default_excluded_numbers(_MELDER_COS) == {1, 13, 11}
    # Meldet das Produkt nichts, bleibt alles ausgewählt
    assert default_excluded_numbers([_MELDER_COS[1]]) == set()


def test_produkt_ohne_rueckfrage_und_auswahl_gemerkt():
    """Eine Quelle fürs Produkt: keine Ja/Nein-Frage mehr, die KO-Auswahl
    startet mit der Vorauswahl bzw. der gemerkten Auswahl des Produkts."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    QApplication.instance() or QApplication([])
    from knix_arranger.services.ko_templates import load_ga_selection
    from knix_arranger.ui.dialogs import com_object_select_dialog as dialog_module
    from knix_arranger.ui.dialogs.product_sync_dialog import offer_device_product
    project, _room, assignment, wasser = _project()
    wasser.communication_objects = communication_objects_of(_LEAK_COS)
    seen = []

    def accept(dlg):
        seen.append(dlg.excluded_numbers())
        return QDialog.Accepted
    with patch.object(dialog_module.ComObjectSelectDialog, "exec", accept), \
            patch.object(QMessageBox, "question",
                         side_effect=AssertionError("keine Rückfrage")), \
            patch("knix_arranger.services.product_sync.shared_catalog", return_value=None):
        assert offer_device_product(None, project, [wasser]) is True
    assert seen == [set()]                       # Leak: beide KOs melden
    assert assignment.element_products[2]["order_number"] == "70316"
    assert load_ga_selection(wasser) == set()
