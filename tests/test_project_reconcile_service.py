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
from knix_arranger.models.group_address import GroupAddress


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


def test_reconcile_restores_manual_ga_not_present_in_fresh_import():
    """Manuell hinzugefuegte GAs (is_manual=True) werden vom Import nicht
    geliefert, da group_addresses beim Re-Import komplett ersetzt wird --
    reconcile_reimport() muss sie in die frische Struktur uebernehmen."""
    old_project, _, _ = _project_with_device_and_room()
    old_project.group_addresses.main_groups = []
    manual_ga = GroupAddress(
        main_group=9, middle_group=0, sub_group=1,
        designation="Sonderfunktion", is_manual=True,
    )
    from knix_arranger.services.address_generator import insert_ga as _insert_ga
    _insert_ga(old_project.group_addresses, manual_ga)

    new_project, _, _ = _project_with_device_and_room()

    diff = reconcile_reimport(old_project, new_project)

    restored = new_project.group_addresses.find_address(9, 0, 1)
    assert restored is not None
    assert restored.designation == "Sonderfunktion"
    assert restored.is_manual is True
    assert diff.manual_gas_restored == 1
    assert diff.manual_gas_conflicts == []


def test_reconcile_skips_manual_ga_on_address_conflict():
    """Kollidiert die manuelle GA-Adresse mit einer frisch importierten GA
    (z.B. weil der Integrator diese Adresse inzwischen in ETS belegt hat),
    darf die echte importierte GA nicht ueberschrieben werden."""
    old_project, _, _ = _project_with_device_and_room()
    old_project.group_addresses.main_groups = []
    manual_ga = GroupAddress(
        main_group=9, middle_group=0, sub_group=1,
        designation="Alte manuelle GA", is_manual=True,
    )
    from knix_arranger.services.address_generator import insert_ga as _insert_ga
    _insert_ga(old_project.group_addresses, manual_ga)

    new_project, _, _ = _project_with_device_and_room()
    fresh_ga = GroupAddress(
        main_group=9, middle_group=0, sub_group=1,
        designation="Echte ETS-GA", is_manual=False,
    )
    _insert_ga(new_project.group_addresses, fresh_ga)

    diff = reconcile_reimport(old_project, new_project)

    kept = new_project.group_addresses.find_address(9, 0, 1)
    assert kept.designation == "Echte ETS-GA"
    assert diff.manual_gas_restored == 0
    assert diff.manual_gas_conflicts == ["9/0/1"]
    assert diff.has_ga_conflicts is True


def _project_with_unnumbered_verteiler_room(phys_addr="1.1.1", vt_room_id=None):
    """Baut ein Projekt mit einem Geraet in einem unnummerierten Verteiler-
    Raum (wie von XlsxImportService.create_verteiler_rooms erzeugt: number="",
    name=Einbauort-Text, z.B. 'HV  HV')."""
    from knix_arranger.models.building import Verteiler
    device = Device(physical_address=phys_addr, device_type="actor", product="Schaltaktor")
    line = Line(line_number=1, name="HL", coupler_address="1.1.0")
    line.devices.append(device)
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    room = Room(number="", name="HV  HV")
    room.verteiler = [Verteiler(name="HV  HV", verteiler_type="HV")]
    if vt_room_id:
        room.id = vt_room_id
    device.room_id = room.id
    line.assigned_room_ids = [room.id]

    apt = Apartment(name="VT", rooms=[room])
    floor = Floor(name="Verteiler", short_code="VT", apartments=[apt])
    wing = Wing(name="Haupthaus", floors=[floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    project = KnxProject(name="Test")
    project.topology = topology
    project.areal = areal
    return project, device, room, line


def test_reconcile_remaps_device_room_id_for_unnumbered_verteiler_room():
    """Regression: create_verteiler_rooms() legt bei jedem Import einen NEUEN
    Verteiler-Raum mit neuer ID an; link_rooms_to_lines() verknuepft Geraete
    damit BEVOR reconcile_reimport() laeuft. reconcile_reimport() erkennt den
    Verteiler-Raum am Namen wieder und ueberschreibt room.id mit der alten ID
    -- ohne Remap bliebe device.room_id auf der frischen (jetzt verwaisten)
    ID haengen, das Geraet waere im importierten Projekt in keinem Raum mehr
    auffindbar (genau das vom Nutzer gemeldete Symptom: 'Verteiler nach dem
    zweiten Import leer')."""
    old_project, _, old_room, _ = _project_with_unnumbered_verteiler_room()

    new_project, new_device, new_room, new_line = _project_with_unnumbered_verteiler_room()
    assert new_room.id != old_room.id
    fresh_room_id = new_room.id
    assert new_device.room_id == fresh_room_id
    assert new_line.assigned_room_ids == [fresh_room_id]

    diff = reconcile_reimport(old_project, new_project)

    assert new_room.id == old_room.id
    assert diff.rooms_matched == 1
    # device.room_id und line.assigned_room_ids muessen auf die (wieder-
    # hergestellte) alte Raum-ID zeigen, nicht auf die verworfene frische ID.
    assert new_device.room_id == old_room.id
    assert new_device.room_id != fresh_room_id
    assert new_line.assigned_room_ids == [old_room.id]


# ---------------------------------------------------------------------------
# Regression: Raumnummer wiederholt sich auf verschiedenen Stockwerken (z.B.
# "01" auf UG UND EG -- so nummeriert der ETS6-'Gebäude'-Report Räume real,
# siehe XlsxImportService.derive_building_structure_from_building_report).
# Ein reiner Nummer-Abgleich in reconcile_reimport() fuehrte beide "01"-Räume
# auf denselben alten Raum zusammen, wodurch Geräte des einen Raums (z.B.
# ein Taster in "01 Carnotzet" auf EG) beim Re-Import faelschlich im anderen
# gleichnummerigen Raum (z.B. "01 Technikraum" auf UG) auftauchten.
# ---------------------------------------------------------------------------

def _project_with_two_same_numbered_rooms_on_different_floors():
    technikraum = Room(number="01", name="Technikraum")
    ug_floor = Floor(name="Untergeschoss", short_code="UG", apartments=[
        Apartment(name="UG", rooms=[technikraum]),
    ])

    carnotzet = Room(number="01", name="Carnotzet")
    eg_floor = Floor(name="Erdgeschoss", short_code="EG", apartments=[
        Apartment(name="EG", rooms=[carnotzet]),
    ])

    wing = Wing(name="Haupthaus", floors=[ug_floor, eg_floor])
    building = Building(name="Haus", wings=[wing])
    areal = Areal(buildings=[building])

    device_technik = Device(
        physical_address="1.1.1", device_type="actor", product="Aktor Technik",
        room_id=technikraum.id,
    )
    device_carnotzet = Device(
        physical_address="1.1.41", device_type="sensor", product="Taster EDIZIOdue",
        room_id=carnotzet.id,
    )
    line = Line(line_number=1, name="HL")
    line.devices = [device_technik, device_carnotzet]
    line.assigned_room_ids = [technikraum.id, carnotzet.id]
    area = Area(area_number=1, name="Bereich 1")
    area.lines.append(line)
    topology = Topology(areas=[area])

    project = KnxProject(name="Test")
    project.topology = topology
    project.areal = areal
    return project, device_technik, device_carnotzet, technikraum, carnotzet


def test_same_room_number_on_different_floors_not_merged():
    old_project, _, _, old_technikraum, old_carnotzet = (
        _project_with_two_same_numbered_rooms_on_different_floors()
    )
    new_project, new_dev_technik, new_dev_carnotzet, new_technikraum, new_carnotzet = (
        _project_with_two_same_numbered_rooms_on_different_floors()
    )

    diff = reconcile_reimport(old_project, new_project)

    assert diff.rooms_matched == 2
    # Beide gleichnummerigen Räume muessen getrennt bleiben, nicht auf
    # denselben alten Raum zusammengefuehrt werden.
    assert new_technikraum.id == old_technikraum.id
    assert new_carnotzet.id == old_carnotzet.id
    assert new_technikraum.id != new_carnotzet.id

    # Jedes Geraet bleibt seinem eigenen Raum zugeordnet -- das Carnotzet-
    # Geraet darf nach dem Abgleich nicht im Technikraum landen (und
    # umgekehrt).
    assert new_dev_technik.room_id == old_technikraum.id
    assert new_dev_carnotzet.room_id == old_carnotzet.id
    assert new_dev_carnotzet.room_id != new_dev_technik.room_id
