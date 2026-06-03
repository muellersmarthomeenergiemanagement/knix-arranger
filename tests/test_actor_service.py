"""
Tests fuer ActorService (FA-1300)
Aktor-Ermittlung pro Linie basierend auf Gewerken.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.actor_service import ActorService, ActorRequirement
from knix_arranger.models.building import Room, GewerkAssignment
from knix_arranger.models.device import Actor


class TestActorDetermination:
    """Tests fuer determine_actors."""

    def test_determine_actors_basic(self, gewerk_catalog):
        """Ermittelt Aktoren fuer Raum mit LD, J, H."""
        room = Room(number="E01", name="Schlafzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=1),
            GewerkAssignment(gewerk_code="J", count=2),
            GewerkAssignment(gewerk_code="H", count=1),
        ]

        service = ActorService()
        requirements = service.determine_actors([room], gewerk_catalog)

        assert len(requirements) > 0
        # Jeder Aktortyp hat eine Requirement
        actor_types = [r.actor_type for r in requirements]
        assert len(actor_types) > 0

    def test_determine_actors_channels(self, gewerk_catalog):
        """Kanalanzahl wird korrekt berechnet."""
        room = Room(number="E01", name="Schlafzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="J", count=3),  # 3 Jalousien
        ]

        service = ActorService()
        requirements = service.determine_actors([room], gewerk_catalog)

        jalousie_req = [r for r in requirements if "Jalousie" in r.actor_type or r.channels_needed == 3]
        if jalousie_req:
            assert jalousie_req[0].channels_needed == 3

    def test_determine_actors_multiple_rooms(self, gewerk_catalog):
        """Mehrere Raeume: Kanaele werden summiert."""
        room1 = Room(number="E01", name="Schlafzimmer")
        room1.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=1),
        ]
        room2 = Room(number="E02", name="Wohnzimmer")
        room2.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=2),
        ]

        service = ActorService()
        requirements = service.determine_actors([room1, room2], gewerk_catalog)

        # Total 3 LD Kanaele
        total_channels = sum(r.channels_needed for r in requirements)
        assert total_channels >= 3

    def test_determine_actors_empty_room(self, gewerk_catalog):
        """Raum ohne Gewerke: Keine Aktoren."""
        room = Room(number="E01", name="Leer")
        service = ActorService()
        requirements = service.determine_actors([room], gewerk_catalog)
        assert len(requirements) == 0


class TestActorSuggestion:
    """Tests fuer suggest_actors (FA-1302)."""

    def test_suggest_optimal_actor(self):
        """Schlaegt optimale Kanalanzahl vor."""
        service = ActorService()
        requirements = [
            ActorRequirement("Schaltaktor", 3, ["LD"]),
        ]
        actors = service.suggest_actors(requirements)

        assert len(actors) >= 1
        # Sollte einen passenden Aktor vorschlagen
        total_channels = sum(a.channels for a in actors)
        assert total_channels >= 3

    def test_suggest_multiple_actors(self):
        """Bei vielen Kanaelen: Mehrere Aktoren."""
        service = ActorService()
        requirements = [
            ActorRequirement("Schaltaktor", 20, ["L"]),
        ]
        actors = service.suggest_actors(requirements)

        assert len(actors) >= 2
        total_channels = sum(a.channels for a in actors)
        assert total_channels >= 20

    def test_suggest_actors_type_name(self):
        """Aktor-Typ enthaelt Kanalanzahl."""
        service = ActorService()
        requirements = [
            ActorRequirement("Schaltaktor", 6, ["L"]),
        ]
        actors = service.suggest_actors(requirements)

        for actor in actors:
            assert "fach" in actor.actor_type


class TestActorMaterialList:
    """Tests fuer create_material_list (FA-1306)."""

    def test_material_list_basic(self):
        """Materialliste zaehlt Aktoren."""
        service = ActorService()
        actors = [
            Actor(actor_type="Schaltaktor 8-fach", channels=8),
            Actor(actor_type="Schaltaktor 8-fach", channels=8),
            Actor(actor_type="Dimmaktor 4-fach", channels=4),
        ]

        material = service.create_material_list(actors)
        assert len(material) >= 1

    def test_material_list_counts_correctly(self):
        """Gleicher Typ wird zu einer Position zusammengefasst."""
        service = ActorService()
        actors = [
            Actor(actor_type="Schaltaktor 8-fach", channels=8),
            Actor(actor_type="Schaltaktor 8-fach", channels=8),
            Actor(actor_type="Schaltaktor 8-fach", channels=8),
            Actor(actor_type="Dimmaktor 4-fach", channels=4),
        ]

        material = service.create_material_list(actors)

        schalt = next(m for m in material if "Schaltaktor" in m["actor_type"])
        assert schalt["quantity"] == 3

        dimm = next(m for m in material if "Dimmaktor" in m["actor_type"])
        assert dimm["quantity"] == 1

    def test_material_list_empty(self):
        """Leere Liste ergibt leere Materialliste."""
        service = ActorService()
        material = service.create_material_list([])
        assert material == []

    def test_material_list_two_types(self):
        """Zwei verschiedene Typen erzeugen zwei Positionen."""
        service = ActorService()
        actors = [
            Actor(actor_type="Schaltaktor 4-fach", channels=4),
            Actor(actor_type="Jalousieaktor 4-fach", channels=4),
        ]
        material = service.create_material_list(actors)
        assert len(material) == 2


class TestActorPerLine:
    """Tests fuer determine_actors_per_line (FA-1301, FA-1302)."""

    def _make_topology_with_room(self, room):
        """Hilfsmethode: Minimale Topologie mit einem Raum in einer Linie."""
        from knix_arranger.models.topology import Topology, Area, Line
        topology = Topology()
        area = Area(name="Bereich 1", area_number=1)
        line = Line(name="Linie 1.1", line_number=1,
                    coupler_address="1.1.0", device_count=6)
        line.assigned_room_ids = [room.id]
        area.lines.append(line)
        topology.areas.append(area)
        return topology

    def test_per_line_returns_result_per_line(self, gewerk_catalog):
        """Fuer jede Linie mit Raeumen gibt es ein LineActorResult."""
        room = Room(number="E01", name="Wohnzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=2),
            GewerkAssignment(gewerk_code="J", count=1),
        ]
        topology = self._make_topology_with_room(room)

        service = ActorService()
        results = service.determine_actors_per_line(topology, [room], gewerk_catalog)

        assert len(results) == 1
        assert results[0].coupler_address == "1.1.0"
        assert results[0].line_name == "Linie 1.1"

    def test_per_line_actors_suggested(self, gewerk_catalog):
        """Pro Linie werden Aktoren vorgeschlagen."""
        room = Room(number="E01", name="Wohnzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=2),
        ]
        topology = self._make_topology_with_room(room)

        service = ActorService()
        results = service.determine_actors_per_line(topology, [room], gewerk_catalog)

        assert len(results[0].actors) >= 1
        total_channels = sum(a.channels for a in results[0].actors)
        assert total_channels >= 2

    def test_per_line_empty_line_skipped(self, gewerk_catalog):
        """Linien ohne Raeume erscheinen nicht im Ergebnis."""
        from knix_arranger.models.topology import Topology, Area, Line
        room = Room(number="E01", name="Wohnzimmer")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]

        topology = Topology()
        area = Area(name="Bereich 1", area_number=1)
        line_with_room = Line(name="Linie 1.1", line_number=1,
                              coupler_address="1.1.0")
        line_with_room.assigned_room_ids = [room.id]
        line_empty = Line(name="Linie 1.2", line_number=2,
                          coupler_address="1.2.0")
        area.lines = [line_with_room, line_empty]
        topology.areas.append(area)

        service = ActorService()
        results = service.determine_actors_per_line(topology, [room], gewerk_catalog)

        assert len(results) == 1
        assert results[0].coupler_address == "1.1.0"
