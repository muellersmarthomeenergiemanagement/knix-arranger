"""
Tests fuer TopologyEngine (FA-200, FA-208-210)
Testet automatische Topologie-Berechnung und Linienzuteilung.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.topology_engine import (
    TopologyEngine, RECOMMENDED_DEVICES, MAX_REALIZED, MAX_LINES_PER_AREA, MAX_AREAS,
    PRIORITY_ACTOR_TYPE, ACTOR_BLOCK_RESERVE,
    PRIORITY_SENSOR_TYPE, SENSOR_BLOCK_RESERVE,
)
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.topology import Topology


class TestTopologyBasic:
    """Grundlegende Topologie-Tests fuer EFH (Einzelzone)."""

    def test_simple_efh_topology(self, simple_efh):
        """EFH mit 4 Stockwerken, je 1 Wohnung: 1 Bereich, 1 Linie.

        Linienkoppler filtern Gruppenadressen. Da ein EFH nur eine Wohnung
        hat, gehoeren alle Raeume in eine einzige Linie.
        """
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_efh)

        assert isinstance(topology, Topology)
        assert len(topology.areas) == 1  # Ein Fluegel = ein Bereich
        assert topology.areas[0].name == "Hauptgebaeude"

        # Einzelzone (jedes Stockwerk hat nur 1 Wohnung) -> 1 Linie
        area = topology.areas[0]
        assert len(area.lines) == 1

    def test_line_name_is_wing(self, simple_efh):
        """EFH-Linie wird nach dem Fluegel benannt."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_efh)

        area = topology.areas[0]
        assert area.lines[0].name == "Hauptgebaeude"

    def test_coupler_addresses(self, simple_efh):
        """Kopplerdressen werden korrekt gesetzt."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_efh)

        area = topology.areas[0]
        assert area.coupler_address == "1.0.0"
        assert area.lines[0].coupler_address == "1.1.0"

    def test_device_count_all_rooms(self, simple_efh):
        """Alle Raeume des EFH in einer Linie zusammengefasst."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_efh)

        area = topology.areas[0]
        # 5 Raeume (UG:1, EG:2, OG:1, DG:1) * 6 Geraete = 30
        assert area.lines[0].device_count == 30

    def test_all_rooms_assigned(self, simple_efh):
        """Alle Raum-IDs sind der einzigen Linie zugeordnet."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_efh)

        line = topology.areas[0].lines[0]
        assert len(line.assigned_room_ids) == 5


class TestTopologyMultiZone:
    """Tests fuer Mehrfamilienhaus und Zweckbau (mehrere Zonen)."""

    def test_mfh_lines_per_apartment(self, simple_mfh):
        """MFH: Jede Wohnung bekommt eine eigene Linie.

        EG hat 2 Wohnungen, OG hat 2 Wohnungen -> multi-zone erkannt.
        Zonen: Allgemein, Wohnung 1, Wohnung 2, Wohnung 3, Wohnung 4.
        """
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_mfh)

        area = topology.areas[0]
        assert len(area.lines) == 5  # 5 verschiedene Zonennamen

    def test_mfh_line_names(self, simple_mfh):
        """MFH-Linien werden nach Wohnungsnamen benannt."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_mfh)

        area = topology.areas[0]
        line_names = [line.name for line in area.lines]
        assert "Allgemein" in line_names
        assert "Wohnung 1" in line_names
        assert "Wohnung 2" in line_names
        assert "Wohnung 3" in line_names
        assert "Wohnung 4" in line_names

    def test_mfh_room_counts_per_line(self, simple_mfh):
        """Raeume werden korrekt den Linien zugewiesen."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_mfh)

        area = topology.areas[0]
        # Finde Linien nach Name
        lines_by_name = {line.name: line for line in area.lines}

        # Allgemein: 2 Raeume (Keller 1, Technik) -> 12 Geraete
        assert lines_by_name["Allgemein"].device_count == 12
        assert len(lines_by_name["Allgemein"].assigned_room_ids) == 2

        # Wohnung 1: 3 Raeume -> 18 Geraete
        assert lines_by_name["Wohnung 1"].device_count == 18
        assert len(lines_by_name["Wohnung 1"].assigned_room_ids) == 3

        # Wohnung 2: 2 Raeume -> 12 Geraete
        assert lines_by_name["Wohnung 2"].device_count == 12

        # Wohnung 3: 2 Raeume -> 12 Geraete
        assert lines_by_name["Wohnung 3"].device_count == 12

        # Wohnung 4: 1 Raum -> 6 Geraete
        assert lines_by_name["Wohnung 4"].device_count == 6

    def test_mfh_coupler_addresses(self, simple_mfh):
        """MFH: Kuppleradressen fortlaufend."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_mfh)

        area = topology.areas[0]
        for i, line in enumerate(area.lines):
            assert line.coupler_address == f"1.{i+1}.0"

    def test_zweckbau_zones_merged(self, simple_zweckbau):
        """Zweckbau: Gleiche Zonennamen ueber Stockwerke werden zusammengefasst.

        EG und OG haben jeweils 'Zone Nord' und 'Zone Sued'.
        Ergebnis: 2 Linien (nicht 4).
        """
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_zweckbau)

        area = topology.areas[0]
        assert len(area.lines) == 2

    def test_zweckbau_zone_names(self, simple_zweckbau):
        """Zweckbau-Linien heissen nach Zonennamen."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_zweckbau)

        area = topology.areas[0]
        line_names = [line.name for line in area.lines]
        assert "Zone Nord" in line_names
        assert "Zone Sued" in line_names

    def test_zweckbau_rooms_merged_across_floors(self, simple_zweckbau):
        """Raeume beider Stockwerke in der gleichen Zone werden zusammengefasst."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_zweckbau)

        area = topology.areas[0]
        lines_by_name = {line.name: line for line in area.lines}

        # Zone Nord: EG (2 Raeume) + OG (2 Raeume) = 4 Raeume -> 24 Geraete
        assert lines_by_name["Zone Nord"].device_count == 24
        assert len(lines_by_name["Zone Nord"].assigned_room_ids) == 4

        # Zone Sued: EG (2 Raeume) + OG (1 Raum) = 3 Raeume -> 18 Geraete
        assert lines_by_name["Zone Sued"].device_count == 18
        assert len(lines_by_name["Zone Sued"].assigned_room_ids) == 3

    def test_total_devices_preserved(self, simple_mfh):
        """Gesamtgeraeteanzahl bleibt nach Zonenzuordnung gleich."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_mfh)

        total = sum(line.device_count for line in topology.areas[0].lines)
        # 10 Raeume * 6 Geraete = 60
        assert total == 60


class TestTopologyLineSplitting:
    """Tests fuer automatische Linienaufteilung bei >85 Geraeten."""

    def _create_floor_with_many_rooms(self, num_rooms: int,
                                       sensors_per_room: int = 4,
                                       actors_per_room: int = 2) -> Areal:
        """Hilfsfunktion: Erstellt ein Stockwerk mit vielen Raeumen."""
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Test")

        floor = Floor(name="Grosses EG", short_code="EG", main_group_number=2)
        apt = Apartment(name="EG")

        for i in range(num_rooms):
            room = Room(
                number=f"E{i+1:02d}", name=f"Raum {i+1}",
                planned_sensors=sensors_per_room,
                planned_actors=actors_per_room,
            )
            apt.rooms.append(room)

        floor.apartments.append(apt)
        wing.floors.append(floor)
        building.wings.append(wing)
        areal.buildings.append(building)
        return areal

    def test_no_split_under_85(self):
        """Unter 85 Geraeten: eine Linie."""
        # 14 Raeume * 6 = 84 Geraete < 85
        areal = self._create_floor_with_many_rooms(14)
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)

        assert len(topology.areas[0].lines) == 1
        assert topology.areas[0].lines[0].device_count == 84

    def test_split_over_85(self):
        """Ueber 85 Geraeten: Aufteilung auf mehrere Linien."""
        # 15 Raeume * 6 = 90 Geraete > 85 -> 2 Linien
        areal = self._create_floor_with_many_rooms(15)
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)

        assert len(topology.areas[0].lines) >= 2
        for line in topology.areas[0].lines:
            assert line.device_count <= RECOMMENDED_DEVICES

    def test_large_floor_multiple_splits(self):
        """Sehr grosses Stockwerk: Mehrere Linien."""
        # 50 Raeume * 6 = 300 Geraete -> 4 Linien
        areal = self._create_floor_with_many_rooms(50)
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)

        total_devices = sum(
            line.device_count for line in topology.areas[0].lines
        )
        assert total_devices == 300
        for line in topology.areas[0].lines:
            assert line.device_count <= RECOMMENDED_DEVICES


class TestTopologyPhysicalAddresses:
    """Tests fuer physikalische Adresszuweisung."""

    def test_assign_addresses(self, simple_efh):
        """Physikalische Adressen werden korrekt vergeben."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_efh)

        from knix_arranger.models.topology import Device
        # Manuell Geraete hinzufuegen
        line = topology.areas[0].lines[0]
        line.devices.append(Device(device_type="actor", product="Schaltaktor"))
        line.devices.append(Device(device_type="sensor", product="Taster"))

        engine.assign_physical_addresses(topology)

        assert line.devices[0].physical_address == "1.1.1"
        assert line.devices[1].physical_address == "1.1.101"

    def test_small_project_sensor_start(self, simple_efh):
        """Kleines Projekt: Sensoren ab Adresse 21."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_efh)

        from knix_arranger.models.topology import Device
        line = topology.areas[0].lines[0]
        line.devices.append(Device(device_type="sensor", product="Taster"))

        engine.assign_physical_addresses(topology, small_project=True)

        assert line.devices[0].physical_address == "1.1.21"


class TestTopologyValidation:
    """Tests fuer Topologie-Validierung (T-01 bis T-11)."""

    def test_valid_topology_no_issues(self, simple_efh):
        """Gueltige Topologie: Keine Probleme."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(simple_efh)

        issues = engine.validate_topology(topology)
        errors = [i for i in issues if i["level"] == "error"]
        assert len(errors) == 0

    def test_too_many_areas(self):
        """T-05: Mehr als 15 Bereiche = Fehler."""
        topology = Topology()
        from knix_arranger.models.topology import Area
        for i in range(16):
            topology.areas.append(Area(area_number=i + 1, name=f"Area {i+1}"))

        engine = TopologyEngine()
        issues = engine.validate_topology(topology)

        assert any(i["rule"] == "T-05" for i in issues)
        assert any(i["level"] == "error" for i in issues)

    def test_too_many_lines_per_area(self):
        """T-04: Mehr als 15 Linien pro Bereich = Fehler."""
        topology = Topology()
        from knix_arranger.models.topology import Area, Line

        area = Area(area_number=1, name="Test")
        for i in range(16):
            area.lines.append(Line(line_number=i + 1, name=f"Linie {i+1}"))
        topology.areas.append(area)

        engine = TopologyEngine()
        issues = engine.validate_topology(topology)

        assert any(i["rule"] == "T-04" for i in issues)

    def test_device_count_warning(self):
        """T-03: Ueber 85 Geraete = Warnung."""
        topology = Topology()
        from knix_arranger.models.topology import Area, Line

        area = Area(area_number=1, name="Test")
        line = Line(line_number=1, name="Volle Linie")
        line.device_count = 90  # > 85 aber < 100
        area.lines.append(line)
        topology.areas.append(area)

        engine = TopologyEngine()
        issues = engine.validate_topology(topology)

        assert any(i["rule"] == "T-03" and i["level"] == "warning" for i in issues)

    def test_device_count_error(self):
        """T-03: Ueber 100 Geraete = Fehler."""
        topology = Topology()
        from knix_arranger.models.topology import Area, Line

        area = Area(area_number=1, name="Test")
        line = Line(line_number=1, name="Uebervolle Linie")
        line.device_count = 105  # > 100
        area.lines.append(line)
        topology.areas.append(area)

        engine = TopologyEngine()
        issues = engine.validate_topology(topology)

        assert any(i["rule"] == "T-03" and i["level"] == "error" for i in issues)


class TestTopologyPopulateDevices:
    """Tests fuer populate_devices(): Linienteilnehmer gemaess KNX Projektrichtlinien."""

    def test_actors_inserted_into_line(self, eg_room_with_gewerke, gewerk_catalog):
        """Aktoren werden als Device-Objekte in Line.devices eingefuegt."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        actors = [d for d in line.devices if d.device_type == "actor"]
        assert len(actors) > 0

    def test_sensors_inserted_into_line(self, eg_room_with_gewerke, gewerk_catalog):
        """Sensoren werden als Device-Objekte in Line.devices eingefuegt."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        assert len(sensors) > 0

    def test_device_types_correct(self, eg_room_with_gewerke, gewerk_catalog):
        """Alle Devices haben einen gueltigen device_type."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        for device in line.devices:
            assert device.device_type in (
                "actor", "sensor", "coupler", "power_supply"
            )

    def test_physical_addresses_assigned(self, eg_room_with_gewerke, gewerk_catalog):
        """Physikalische Adressen fuer Aktoren und Sensoren (Kap. 9.1)."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        # Aktoren starten bei 1, Sensoren bei 101
        actors = [d for d in line.devices if d.device_type == "actor"]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        if actors:
            assert actors[0].physical_address == "1.1.1"
        if sensors:
            assert sensors[0].physical_address == "1.1.101"

    def test_device_count_updated(self, eg_room_with_gewerke, gewerk_catalog):
        """device_count wird auf Anzahl der eingefuegten Devices aktualisiert."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        assert line.device_count == len(line.devices)
        assert line.device_count > 0

    def test_idempotent(self, eg_room_with_gewerke, gewerk_catalog):
        """Zweimaliger Aufruf liefert gleiches Ergebnis."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)
        first_count = len(topology.areas[0].lines[0].devices)
        first_addresses = [
            d.physical_address for d in topology.areas[0].lines[0].devices
        ]

        engine.populate_devices(topology, all_rooms, gewerk_catalog)
        second_count = len(topology.areas[0].lines[0].devices)
        second_addresses = [
            d.physical_address for d in topology.areas[0].lines[0].devices
        ]

        assert first_count == second_count
        assert first_addresses == second_addresses

    def test_actor_product_info_mapped(self, eg_room_with_gewerke, gewerk_catalog):
        """Aktor-Typ wird korrekt in Device.product uebernommen."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        actors = [d for d in line.devices if d.device_type == "actor"]
        # eg_room_with_gewerke hat LD (Dimmaktor), J (Jalousieaktor), H (Heizungsaktor)
        actor_products = [a.product for a in actors]
        assert any("Dimmaktor" in p for p in actor_products)
        assert any("Jalousieaktor" in p for p in actor_products)
        assert any("Heizungsaktor" in p for p in actor_products)

    def test_line_coupler_present(self, eg_room_with_gewerke, gewerk_catalog):
        """Jede Linie hat einen Linienkoppler an Adresse B.L.0 (Kap. 3.5.2)."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        couplers = [d for d in line.devices if d.device_type == "coupler"]
        assert len(couplers) == 1
        assert couplers[0].product == "Linienkoppler"
        assert couplers[0].physical_address == "1.1.0"

    def test_power_supply_present(self, eg_room_with_gewerke, gewerk_catalog):
        """Jede Linie hat eine Spannungsversorgung (Kap. 3.2, T-06)."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        power_supplies = [d for d in line.devices if d.device_type == "power_supply"]
        assert len(power_supplies) == 1
        assert "Spannungsversorgung" in power_supplies[0].product

    def test_power_supply_line_address(self, eg_room_with_gewerke, gewerk_catalog):
        """Spannungsversorgung erhält Linien-Adresse im Format B.L.-"""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        power_supplies = [d for d in line.devices if d.device_type == "power_supply"]
        assert power_supplies[0].physical_address == "1.1.-"

    def test_device_order(self, eg_room_with_gewerke, gewerk_catalog):
        """Reihenfolge: Koppler, SV, Aktoren, Sensoren."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        types = [d.device_type for d in line.devices]
        assert types[0] == "coupler"
        assert types[1] == "power_supply"
        # Danach kommen Aktoren, dann Sensoren
        remaining = types[2:]
        actor_end = 0
        for i, t in enumerate(remaining):
            if t == "actor":
                actor_end = i
            elif t == "sensor":
                assert i > actor_end, "Sensoren muessen nach Aktoren kommen"

    def test_coupler_address_not_overwritten(self, eg_room_with_gewerke, gewerk_catalog):
        """Koppleradresse wird durch assign_physical_addresses nicht ueberschrieben."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        coupler = [d for d in line.devices if d.device_type == "coupler"][0]
        assert coupler.physical_address == line.coupler_address

    def test_no_area_coupler_single_area(self, eg_room_with_gewerke, gewerk_catalog):
        """Bei nur einem Bereich: kein Bereichskoppler (FA-207)."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        area_couplers = [
            d for d in line.devices
            if d.device_type == "coupler" and d.product == "Bereichskoppler"
        ]
        assert len(area_couplers) == 0

    def test_area_coupler_multi_area(self, gewerk_catalog):
        """Bei mehreren Bereichen: Bereichskoppler in erster Linie (FA-207)."""
        from knix_arranger.models.building import (
            Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
        )
        areal = Areal(name="Multi")
        building = Building(name="Test")

        # Zwei Fluegel = zwei Bereiche
        for wing_name in ("Fluegel A", "Fluegel B"):
            wing = Wing(name=wing_name)
            floor = Floor(name="EG", short_code="EG", main_group_number=2)
            apt = Apartment(name="EG")
            room = Room(number="E01", name="Raum 1")
            room.gewerk_assignments = [
                GewerkAssignment(gewerk_code="LD", count=1),
            ]
            apt.rooms.append(room)
            floor.apartments.append(apt)
            wing.floors.append(floor)
            building.wings.append(wing)

        areal.buildings.append(building)

        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        all_rooms = areal.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        assert len(topology.areas) == 2
        for area in topology.areas:
            first_line = area.lines[0]
            area_couplers = [
                d for d in first_line.devices
                if d.device_type == "coupler" and d.product == "Bereichskoppler"
            ]
            assert len(area_couplers) == 1
            assert area_couplers[0].physical_address == area.coupler_address

    def test_small_project_actor_address_limit(self, eg_room_with_gewerke, gewerk_catalog):
        """Kleines Projekt: Aktoradressen beginnen bei 1 (FA-222)."""
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog, small_project=True)

        line = topology.areas[0].lines[0]
        actors = [d for d in line.devices if d.device_type == "actor"]
        sensors = [d for d in line.devices if d.device_type == "sensor"]

        # Aktoren starten bei 1
        if actors:
            assert actors[0].physical_address == "1.1.1"
        # Sensoren starten bei 21
        if sensors:
            assert sensors[0].physical_address == "1.1.21"

    def test_devices_grouped_by_type(self, eg_room_with_gewerke, gewerk_catalog):
        """Aktoren und Sensoren werden nach Geraetetyp gruppiert nummeriert.

        eg_room_with_gewerke hat LD (Dimmaktor), 2x J (Jalousieaktor), H (Heizungsaktor).
        Sortiert: Dimmaktor, Heizungsaktor, Jalousieaktor -> fortlaufende Adressen.
        """
        engine = TopologyEngine()
        topology = engine.calculate_topology(eg_room_with_gewerke)
        all_rooms = eg_room_with_gewerke.all_rooms

        engine.populate_devices(topology, all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        actors = [d for d in line.devices if d.device_type == "actor"]

        # Mindestens 3 verschiedene Aktortypen (Dimm, Heizung, Jalousie)
        assert len(actors) >= 3

        # Gleiche Typen muessen zusammenhaengende Adressen haben
        actor_types = [a.product for a in actors]
        for i in range(1, len(actor_types)):
            if actor_types[i] == actor_types[i - 1]:
                # Gleicher Typ -> Adresse muss direkt folgen
                prev_addr = int(actors[i - 1].physical_address.split(".")[-1])
                curr_addr = int(actors[i].physical_address.split(".")[-1])
                assert curr_addr == prev_addr + 1, (
                    f"Luecke bei {actors[i].product}: "
                    f"{actors[i-1].physical_address} -> {actors[i].physical_address}"
                )

        # Typen muessen alphabetisch sortiert sein (Gruppierung)
        unique_types_in_order = []
        for t in actor_types:
            if not unique_types_in_order or unique_types_in_order[-1] != t:
                unique_types_in_order.append(t)
        assert unique_types_in_order == sorted(unique_types_in_order)


class TestActorBlockOrdering:
    """Tests fuer Aktorblock-Sortierung und Reserve-Adressen zwischen Bloecken."""

    def _make_areal_with_actor_types(self, gewerk_codes: list[str]) -> "Areal":
        """Hilfsfunktion: Erstellt ein Areal mit einem Raum und den angegebenen Gewerken."""
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        floor = Floor(name="EG", short_code="EG", main_group_number=2)
        apt = Apartment(name="EG")
        room = Room(number="E01", name="Raum")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code=code, count=1) for code in gewerk_codes
        ]
        apt.rooms.append(room)
        floor.apartments.append(apt)
        wing.floors.append(floor)
        building.wings.append(wing)
        areal.buildings.append(building)
        return areal

    def test_reserve_gap_between_actor_types(self, gewerk_catalog):
        """Zwischen verschiedenen Aktortyp-Bloecken muessen ACTOR_BLOCK_RESERVE Adressen frei bleiben."""
        # L -> Schaltaktor, LD -> Dimmaktor: zwei verschiedene Typen -> eine Luecke
        areal = self._make_areal_with_actor_types(["L", "LD"])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        actors = [d for d in line.devices if d.device_type == "actor"]
        assert len(actors) >= 2

        # Erste Adresse des zweiten Blocks muss = letzte Adresse des ersten Blocks + 1 + ACTOR_BLOCK_RESERVE
        addrs = [int(a.physical_address.split(".")[-1]) for a in actors]
        # Blockwechsel finden
        base_types = [a.product.split(" ")[0] for a in actors]
        for i in range(1, len(base_types)):
            if base_types[i] != base_types[i - 1]:
                gap = addrs[i] - addrs[i - 1] - 1
                assert gap == ACTOR_BLOCK_RESERVE, (
                    f"Luecke zwischen '{base_types[i-1]}' und '{base_types[i]}': "
                    f"erwartet {ACTOR_BLOCK_RESERVE}, erhalten {gap}"
                )

    def test_no_gap_within_same_type(self, gewerk_catalog):
        """Innerhalb desselben Aktortyps darf es keine Luecke geben."""
        # 2x J -> 2 Jalousieaktoren desselben Typs
        areal = self._make_areal_with_actor_types(["J", "J"])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        actors = [d for d in line.devices if d.device_type == "actor"]

        for i in range(1, len(actors)):
            prev = int(actors[i - 1].physical_address.split(".")[-1])
            curr = int(actors[i].physical_address.split(".")[-1])
            assert curr == prev + 1, (
                f"Unerwartete Luecke bei gleichem Typ: {prev} -> {curr}"
            )

    def test_tasterblock_priority_first(self, gewerk_catalog):
        """Tasterblock-Aktoren erhalten immer Adresse 1 (vor allen anderen Typen)."""
        from knix_arranger.models.topology import Device

        engine = TopologyEngine()
        topology = engine.calculate_topology(self._make_areal_with_actor_types([]))

        from knix_arranger.models.topology import Area, Line
        area = topology.areas[0] if topology.areas else None
        if area is None:
            area = Area(area_number=1, name="Test")
            topology.areas.append(area)
        if not area.lines:
            line = Line(line_number=1, name="Test", coupler_address="1.1.0")
            area.lines.append(line)
        else:
            line = area.lines[0]
        line.devices.clear()

        # Schaltaktor vor Tasterblock hinzufuegen (umgekehrte Reihenfolge als Eingabe)
        line.devices.append(Device(device_type="actor", product="Schaltaktor 4-fach"))
        line.devices.append(Device(device_type="actor", product=f"{PRIORITY_ACTOR_TYPE} 4-fach"))

        # Manuell sortieren wie populate_devices es tut
        line.devices.sort(key=lambda d: (
            0 if d.product.split(" ")[0] == PRIORITY_ACTOR_TYPE else 1,
            d.product,
        ) if d.device_type == "actor" else ("", ""))

        engine.assign_physical_addresses(topology)

        actors = [d for d in line.devices if d.device_type == "actor"]
        assert actors[0].product.startswith(PRIORITY_ACTOR_TYPE), (
            f"Tasterblock sollte zuerst kommen, stattdessen: {actors[0].product}"
        )
        assert actors[0].physical_address == "1.1.1"

    def test_multiple_blocks_gaps_cumulate(self, gewerk_catalog):
        """Bei drei verschiedenen Aktortypen gibt es zwei Luecken."""
        # L (Schaltaktor), LD (Dimmaktor), J (Jalousieaktor)
        areal = self._make_areal_with_actor_types(["L", "LD", "J"])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        actors = [d for d in line.devices if d.device_type == "actor"]
        base_types = [a.product.split(" ")[0] for a in actors]
        unique_blocks = []
        for bt in base_types:
            if not unique_blocks or unique_blocks[-1] != bt:
                unique_blocks.append(bt)

        assert len(unique_blocks) == 3, f"Erwartet 3 Aktortypen, erhalten: {unique_blocks}"

        # Jeder Blockwechsel muss genau ACTOR_BLOCK_RESERVE Adressen Abstand haben
        addrs = [int(a.physical_address.split(".")[-1]) for a in actors]
        transition_count = 0
        for i in range(1, len(base_types)):
            if base_types[i] != base_types[i - 1]:
                gap = addrs[i] - addrs[i - 1] - 1
                assert gap == ACTOR_BLOCK_RESERVE
                transition_count += 1
        assert transition_count == 2


class TestSensorBlockOrdering:
    """Tests fuer Sensorblock-Sortierung und Reserve-Adressen zwischen Bloecken."""

    def _make_areal_with_sensor_types(self, gewerk_codes: list[str]) -> "Areal":
        """Hilfsfunktion: Erstellt ein Areal mit einem Raum und den angegebenen Gewerken."""
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        floor = Floor(name="EG", short_code="EG", main_group_number=2)
        apt = Apartment(name="EG")
        room = Room(number="E01", name="Raum")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code=code, count=1) for code in gewerk_codes
        ]
        apt.rooms.append(room)
        floor.apartments.append(apt)
        wing.floors.append(floor)
        building.wings.append(wing)
        areal.buildings.append(building)
        return areal

    def test_taster_starts_at_sensor_base_address(self, gewerk_catalog):
        """Taster erhaelt immer die niedrigste Sensoradresse (101 / 21)."""
        # L -> Taster, H -> Raumthermostat: Taster muss zuerst kommen
        areal = self._make_areal_with_sensor_types(["H", "L"])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        assert len(sensors) >= 2
        assert sensors[0].product.startswith(PRIORITY_SENSOR_TYPE), (
            f"Erster Sensor sollte '{PRIORITY_SENSOR_TYPE}' sein, ist: {sensors[0].product}"
        )
        assert sensors[0].physical_address.endswith(".101")

    def test_reserve_gap_between_sensor_types(self, gewerk_catalog):
        """Zwischen verschiedenen Sensortyp-Bloecken muessen SENSOR_BLOCK_RESERVE Adressen frei bleiben."""
        # L -> Taster, H -> Raumthermostat: zwei Typen -> eine Luecke
        areal = self._make_areal_with_sensor_types(["L", "H"])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        assert len(sensors) >= 2

        addrs = [int(s.physical_address.split(".")[-1]) for s in sensors]
        sensor_types = [s.product for s in sensors]
        for i in range(1, len(sensor_types)):
            if sensor_types[i] != sensor_types[i - 1]:
                gap = addrs[i] - addrs[i - 1] - 1
                assert gap == SENSOR_BLOCK_RESERVE, (
                    f"Luecke zwischen '{sensor_types[i-1]}' und '{sensor_types[i]}': "
                    f"erwartet {SENSOR_BLOCK_RESERVE}, erhalten {gap}"
                )

    def test_no_gap_within_same_sensor_type(self, gewerk_catalog):
        """Innerhalb desselben Sensortyps darf es keine Luecke geben."""
        # 2x L -> 2 Taster desselben Typs
        areal = self._make_areal_with_sensor_types(["L", "L"])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]

        for i in range(1, len(sensors)):
            prev = int(sensors[i - 1].physical_address.split(".")[-1])
            curr = int(sensors[i].physical_address.split(".")[-1])
            assert curr == prev + 1, (
                f"Unerwartete Luecke bei gleichem Sensortyp: {prev} -> {curr}"
            )

    def test_taster_jalousie_and_regular_taster_both_priority(self, gewerk_catalog):
        """Taster und Taster (Jalousie-Wippe) kommen beide vor anderen Sensortypen."""
        # L -> Taster, J -> Taster (Jalousie-Wippe), H -> Raumthermostat
        areal = self._make_areal_with_sensor_types(["H", "L", "J"])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        sensor_types = [s.product for s in sensors]

        # Raumthermostat darf nicht vor einem Taster-Typ kommen
        raumthermostat_idx = next(
            (i for i, t in enumerate(sensor_types) if t == "Raumthermostat"), None
        )
        taster_indices = [
            i for i, t in enumerate(sensor_types) if t.startswith(PRIORITY_SENSOR_TYPE)
        ]
        if raumthermostat_idx is not None and taster_indices:
            assert raumthermostat_idx > max(taster_indices), (
                "Raumthermostat darf nicht vor Taster-Typen kommen"
            )

    def test_small_project_taster_starts_at_21(self, gewerk_catalog):
        """Kleines Projekt: Taster startet bei Sensoradresse 21."""
        areal = self._make_areal_with_sensor_types(["H", "L"])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog, small_project=True)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        assert sensors[0].product.startswith(PRIORITY_SENSOR_TYPE)
        assert sensors[0].physical_address.endswith(".21")


class TestSensorRoomOrdering:
    """Tests fuer raumbasierte Sensor-Reihenfolge (FA-TE-ORDER).

    Szenario: Mehrere Raeume auf einer Linie, ein Raum hat taster_indices=[1,2].
    Erwartet: Raum A TE1, Raum A TE2, Raum B TE1 — nicht Raum A TE1, Raum B TE1, Raum A TE2.
    """

    def _make_two_room_areal(self, room_a_indices, room_b_indices=None):
        """Zwei Raeume auf derselben Linie: Raum A mit room_a_indices, Raum B mit room_b_indices."""
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        floor = Floor(name="EG", short_code="EG", main_group_number=2)
        apt = Apartment(name="EG")

        room_a = Room(number="E01", name="Raum A")
        room_a.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=1, taster_indices=room_a_indices)
        ]
        apt.rooms.append(room_a)

        if room_b_indices is not None:
            room_b = Room(number="E02", name="Raum B")
            room_b.gewerk_assignments = [
                GewerkAssignment(gewerk_code="LD", count=1, taster_indices=room_b_indices)
            ]
            apt.rooms.append(room_b)

        floor.apartments.append(apt)
        wing.floors.append(floor)
        building.wings.append(wing)
        areal.buildings.append(building)
        return areal

    def test_te2_follows_te1_same_room_single_room(self, gewerk_catalog):
        """Einzelner Raum mit TE1+TE2: TE1 vor TE2."""
        areal = self._make_two_room_areal(room_a_indices=[1, 2])
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        assert len(sensors) == 2
        # TE1 bekommt 101, TE2 bekommt 102
        assert sensors[0].physical_address.endswith(".101")
        assert sensors[1].physical_address.endswith(".102")

    def test_te2_grouped_with_room_multi_room(self, gewerk_catalog):
        """Multi-Raum: Raum A TE1, Raum A TE2, Raum B TE1 — nicht Raum A TE1, Raum B TE1, Raum A TE2."""
        areal = self._make_two_room_areal(
            room_a_indices=[1, 2],   # Raum A hat TE1 + TE2
            room_b_indices=[1],      # Raum B hat nur TE1
        )
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        assert len(sensors) == 3

        room_a_id = areal.all_rooms[0].id
        room_b_id = areal.all_rooms[1].id

        # Reihenfolge: Raum A (idx 0,1), dann Raum B (idx 2)
        assert sensors[0].room_id == room_a_id, "Sensor 0 muss Raum A sein"
        assert sensors[1].room_id == room_a_id, "Sensor 1 muss Raum A sein (TE2)"
        assert sensors[2].room_id == room_b_id, "Sensor 2 muss Raum B sein"

        # Adressen konsekutiv: 101, 102, 103
        assert sensors[0].physical_address.endswith(".101")
        assert sensors[1].physical_address.endswith(".102")
        assert sensors[2].physical_address.endswith(".103")

    def test_te2_grouped_preserve_manual(self, gewerk_catalog):
        """preserve_manual=True: programmierter TE1 (Raum A) eingewoben, TE2 direkt dahinter."""
        areal = self._make_two_room_areal(
            room_a_indices=[1, 2],
            room_b_indices=[1],
        )
        engine = TopologyEngine()
        topology = engine.calculate_topology(areal)
        # Erste Berechnung
        engine.populate_devices(topology, areal.all_rooms, gewerk_catalog)

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]

        # Raum A TE1 als programmiert markieren
        room_a_id = areal.all_rooms[0].id
        ra_te1 = next(d for d in sensors if d.room_id == room_a_id)
        ra_te1.is_programmed = True

        # Neuberechnung mit preserve_manual=True
        engine.populate_devices(
            topology, areal.all_rooms, gewerk_catalog, preserve_manual=True
        )

        line = topology.areas[0].lines[0]
        sensors = [d for d in line.devices if d.device_type == "sensor"]
        assert len(sensors) == 3

        room_b_id = areal.all_rooms[1].id
        # Reihenfolge bleibt: Raum A TE1 (prog), Raum A TE2, Raum B TE1
        assert sensors[0].room_id == room_a_id
        assert sensors[1].room_id == room_a_id
        assert sensors[2].room_id == room_b_id
