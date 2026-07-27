"""
Tests fuer reconcile_reimport: Export -> Anpassung in ETS/Excel -> Re-Import
darf keine IDs-basierten Verknuepfungen (Materialliste, KNX Secure, DALI) und
keine raumgebundenen KNiX-Planungsdaten verwaisen lassen. Formatunabhaengig --
gilt fuer .knxproj- UND XLSX-Re-Importe gleichermassen.
"""
from __future__ import annotations
from knix_arranger.services.project_reconcile_service import reconcile_reimport
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment, Bedienelement,
)


def _project_with_device_and_room(phys_addr="1.1.1", room_number="E01",
                                   product_name="", manufacturer="", order_number=""):
    device = Device(
        physical_address=phys_addr, device_type="actor",
        product="Schaltaktor 4-fach", product_name=product_name,
        manufacturer=manufacturer, order_number=order_number,
        datasheets=["https://example.com/datasheet.pdf"],
        manually_split=True, manual_functions=["L", "J"],
    )
    line = Line(line_number=1, name="HL", coupler_address="1.1.0")
    line.devices.append(device)
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    room = Room(number=room_number, name="Wohnzimmer")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=2)]
    room.bedienelemente = [Bedienelement(element_type="Tastereinheit", participant_number="1.1.5")]
    room.bauherr_notes = "Bitte Dimmer statt Schalter"
    apt = Apartment(name="Wohnung 1", rooms=[room])
    floor = Floor(name="EG", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    project = KnxProject(name="Test")
    project.topology = topology
    project.areal = areal
    return project, device, room


def test_reconcile_preserves_device_id_by_physical_address():
    old_project, old_device, _ = _project_with_device_and_room(
        product_name="Gira 2 fach Schalter", manufacturer="Gira", order_number="012345",
    )
    new_project, new_device, _ = _project_with_device_and_room(
        product_name="", manufacturer="M-0002", order_number="generic",
    )
    assert new_device.id != old_device.id

    reconcile_reimport(old_project, new_project)

    assert new_device.id == old_device.id
    # Produktzuweisung (product_name wird nie vom Import gesetzt) muss erhalten
    # bleiben, inkl. der dazugehoerigen Hersteller-/Bestellnummer -- nicht durch
    # den generischen Hardware-Wert ueberschrieben werden.
    assert new_device.product_name == "Gira 2 fach Schalter"
    assert new_device.manufacturer == "Gira"
    assert new_device.order_number == "012345"


def test_reconcile_keeps_fresh_values_when_no_prior_assignment():
    """Ohne vorherige Produktzuweisung (product_name leer) muessen die frisch
    importierten Hersteller-/Bestellnummer-Werte erhalten bleiben."""
    old_project, _, _ = _project_with_device_and_room(
        product_name="", manufacturer="", order_number="",
    )
    new_project, new_device, _ = _project_with_device_and_room(
        product_name="", manufacturer="M-0002", order_number="ABC-123",
    )
    reconcile_reimport(old_project, new_project)
    assert new_device.manufacturer == "M-0002"
    assert new_device.order_number == "ABC-123"


def test_reconcile_carries_over_knix_only_device_fields():
    old_project, old_device, _ = _project_with_device_and_room()
    new_project, new_device, _ = _project_with_device_and_room()
    # Simuliert einen echten frischen Import: keine Datenblaetter/manuellen
    # Flags, da weder ETS noch Excel diese Konzepte kennen.
    new_device.datasheets = []
    new_device.manually_split = False
    new_device.manual_functions = []

    reconcile_reimport(old_project, new_project)

    assert new_device.datasheets == old_device.datasheets
    assert new_device.manually_split is True
    assert new_device.manual_functions == ["L", "J"]


def test_reconcile_preserves_room_id_and_gewerk_assignments():
    old_project, _, old_room = _project_with_device_and_room()
    new_project, _, new_room = _project_with_device_and_room()
    assert new_room.id != old_room.id
    # Simuliert einen echten frischen Import: keine Gewerk-Zuweisungen/
    # Bedienelemente/Notizen, da weder ETS noch Excel diese Konzepte kennen.
    new_room.gewerk_assignments = []
    new_room.bedienelemente = []
    new_room.bauherr_notes = ""

    reconcile_reimport(old_project, new_project)

    assert new_room.id == old_room.id
    assert len(new_room.gewerk_assignments) == 1
    assert new_room.gewerk_assignments[0].gewerk_code == "L"
    assert len(new_room.bedienelemente) == 1
    assert new_room.bauherr_notes == "Bitte Dimmer statt Schalter"


def test_reconcile_no_match_leaves_new_ids_untouched():
    """Geraet/Raum, die es im alten Projekt nicht gibt, behalten ihre frisch
    vergebenen IDs (kein falsches Matching)."""
    old_project, _, _ = _project_with_device_and_room(
        phys_addr="1.1.9", room_number="E09",
    )
    new_project, new_device, new_room = _project_with_device_and_room(
        phys_addr="1.1.1", room_number="E01",
    )
    fresh_device_id, fresh_room_id = new_device.id, new_room.id

    reconcile_reimport(old_project, new_project)

    assert new_device.id == fresh_device_id
    assert new_room.id == fresh_room_id


def test_reconcile_diff_detects_new_and_removed():
    """Geräte/Räume, die im alten Projekt existierten aber im neuen Import
    fehlen, müssen als 'removed' erkannt werden (riskanter Fall: KNiX-
    Planungsdaten könnten verwaist sein) -- und umgekehrt neue als 'new'."""
    old_project, _, _ = _project_with_device_and_room(
        phys_addr="1.1.1", room_number="E01",
    )
    new_project, _, _ = _project_with_device_and_room(
        phys_addr="1.1.2", room_number="E02",
    )

    diff = reconcile_reimport(old_project, new_project)

    assert diff.devices_matched == 0
    assert diff.devices_new == ["1.1.2"]
    assert diff.devices_removed == ["1.1.1"]
    assert diff.rooms_matched == 0
    assert diff.rooms_new == ["E02"]
    assert diff.rooms_removed == ["E01"]
    assert diff.has_removed is True


def test_reconcile_diff_no_removed_when_everything_matches():
    old_project, _, _ = _project_with_device_and_room()
    new_project, _, _ = _project_with_device_and_room()

    diff = reconcile_reimport(old_project, new_project)

    assert diff.devices_matched == 1
    assert diff.rooms_matched == 1
    assert diff.devices_new == []
    assert diff.devices_removed == []
    assert diff.has_removed is False
