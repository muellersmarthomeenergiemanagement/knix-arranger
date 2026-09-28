"""Bedienelement übernimmt das Produkt seines Geräts, auch wenn es schon existiert."""
from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, Room, Wing,
)
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.knxproj_import_service import KnxprojImportService


def test_existing_element_takes_product_of_device():
    room = Room(number="02", name="Bibliothek")
    room.bedienelemente = [Bedienelement(
        element_type="Tastereinheit", participant_number="1.1.40",
        manufacturer="Feller", order_number="370x-x.FMI.xx",
        product_name="Taster EDIZIOdue 1-8fach",
    )]
    areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="OG", apartments=[Apartment(rooms=[room])])])])])
    device = Device(
        physical_address="1.1.40", device_type="sensor", room_id=room.id,
        manufacturer="Feller", order_number="470x-x-B.xxx",
        product="EDIZIOdue colore 1-8fach Taster RGB Temp",
    )
    topology = Topology(areas=[Area(area_number=1, lines=[Line(line_number=1, devices=[device])])])

    KnxprojImportService._create_bedienelemente_from_topology(topology, areal)

    [be] = room.bedienelemente
    assert be.order_number == "470x-x-B.xxx"
    assert be.product_name == "EDIZIOdue colore 1-8fach Taster RGB Temp"
