"""
Berichte: Funktionen und bedienende GA einer Taste (Chalet 1.1.52).
"""
from __future__ import annotations

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.ets_function import EtsFunction, EtsFunctionRef
from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.project import KnxProject
from knix_arranger.services.bedienelement_layout import ButtonKey, ButtonRow, row_function_label
from knix_arranger.services.report_service import _function_names
from knix_arranger.services.user_manual import operating_ga


def _ga(address, designation, dpt, code="J"):
    hg, mg, sub = (int(p) for p in address.split("/"))
    return GroupAddress(main_group=hg, middle_group=mg, sub_group=sub, designation=designation,
                        datapoint_type=dpt, gewerk_code=code)


WIND = _ga("0/5/5", "J.Sicherheit_ea", "DPST-1-5")
MOVE = _ga("3/1/250", "J.Bibliothek Berg Bewegen", "DPST-1-8")


def test_alarm_object_does_not_name_the_key():
    """Die Wind-GA steht vor der Bewegen-GA, bedient die Taste aber nicht."""
    assert operating_ga([WIND, MOVE]) is MOVE
    assert operating_ga([WIND]) is WIND
    assert operating_ga([]) is None


def test_function_name_on_the_key():
    row = ButtonRow(ButtonKey(2), gas=[WIND, MOVE])
    catalog = KnxProject().gewerk_catalog
    assert row_function_label(row, catalog, "Bibliothek", {"3/1/250": "J.Bibliothek Berg"}) == (
        "Jalousie", "Funktion J.Bibliothek Berg")


def test_function_names_include_ets_functions():
    room = Room(number="02", name="Bibliothek", ets_functions=[EtsFunction(
        "J.Bibliothek Berg", "FT-7", [EtsFunctionRef("MoveUpDown", "3/1/250")])])
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="OG", apartments=[Apartment(rooms=[room])])])])])
    assert _function_names(project) == {"3/1/250": "J.Bibliothek Berg"}


def test_floors_bottom_up_when_known():
    from knix_arranger.services.report_sorting import floors_bottom_up
    floors = [Floor(short_code=c) for c in ("OG", "UG", "EG", "DG")]
    assert [f.short_code for f in floors_bottom_up(floors)] == ["UG", "EG", "OG", "DG"]
    # nicht ersichtlich: wie angelegt
    odd = [Floor(short_code="Galerie"), Floor(short_code="EG")]
    assert floors_bottom_up(odd) == odd


def test_owner_package_parts():
    from knix_arranger.services.revision_package import is_owner_package, part_audience
    assert is_owner_package({"anleitung", "raeume", "zusammenfassung"})
    assert not is_owner_package({"anleitung", "ga_uebersicht"})
    assert part_audience("anleitung") == "Bauherr"
    assert part_audience("topologie") == "Inbetriebnahme"


def test_room_book_shortens_many_data_points():
    """Vitogate im Raumbuch: Kurzfassung ohne technischen Vorsatz statt
    60 Objektnamen, die über den Seitenrand laufen."""
    from knix_arranger.models.topology import Device
    from knix_arranger.services.room_sheet import _device_row
    names = [f"1_1_CU401B_G__ / ({n}) Wert {n}" for n in range(10)]
    usage = _device_row(Device(physical_address="1.1.32"), names).usage
    assert usage.startswith("10 Datenpunkte belegt: (0) Wert 0, (1) Wert 1")
    assert "1_1_CU401B" not in usage and "(9) Wert 9" not in usage
    assert usage.endswith("vollständig im Bericht «Bedienelemente und Sensoren»")
    # wenige Objekte: wie bisher einzeln
    assert _device_row(Device(), ["Sollwert", "Betriebsart"]).usage == "Sollwert, Betriebsart"
