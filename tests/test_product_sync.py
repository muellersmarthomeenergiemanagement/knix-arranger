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
    product_mismatches,
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


def test_importiert_ohne_abgleich():
    project, *_ = _project(imported=True)
    assert product_mismatches(project) == []


def test_validierung_warnt():
    project, *_ = _project()
    issues = [i for i in ValidationEngine().validate(GroupAddressStructure(), project)
              if i.rule_id == "FA-621"]
    assert len(issues) == 1 and issues[0].level == "warning"
    assert "1.2.113" in issues[0].message and "Standard des Gewerks" in issues[0].message
