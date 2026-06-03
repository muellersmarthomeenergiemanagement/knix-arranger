"""
Tests fuer SensorService (FA-1400)
Sensor-Ermittlung pro Raum basierend auf Gewerken.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.sensor_service import SensorService, SensorRequirement
from knix_arranger.models.building import Room, GewerkAssignment
from knix_arranger.models.device import Sensor
from knix_arranger.services.address_generator import AddressGenerator


class TestSensorDetermination:
    """Tests fuer determine_sensors."""

    def test_determine_sensors_basic(self, gewerk_catalog):
        """Ermittelt Sensoren fuer Raum mit LD, J, H."""
        room = Room(number="E01", name="Schlafzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=1),
            GewerkAssignment(gewerk_code="J", count=2),
            GewerkAssignment(gewerk_code="H", count=1),
        ]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        assert len(requirements) > 0

    def test_determine_sensors_room_info(self, gewerk_catalog):
        """Sensoren enthalten Rauminformationen."""
        room = Room(number="E01", name="Schlafzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=1),
        ]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        if requirements:
            assert requirements[0].room_id == room.id
            assert "E01" in requirements[0].room_name

    def test_determine_sensors_count(self, gewerk_catalog):
        """Anzahl wird korrekt uebernommen."""
        room = Room(number="E01", name="Schlafzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="J", count=3),
        ]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        if requirements:
            j_req = [r for r in requirements if r.gewerk_code == "J"]
            if j_req:
                assert j_req[0].count == 3

    def test_determine_sensors_empty_room(self, gewerk_catalog):
        """Raum ohne Gewerke: Keine Sensoren."""
        room = Room(number="E01", name="Leer")
        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)
        assert len(requirements) == 0


class TestSensorSuggestion:
    """Tests fuer suggest_sensors."""

    def test_suggest_sensors(self):
        """Schlaegt Sensoren vor."""
        service = SensorService()
        requirements = [
            SensorRequirement(
                sensor_type="Taster 4-fach",
                room_id="test-id",
                room_name="E01 Schlafzimmer",
                gewerk_code="LD",
                count=1,
            ),
        ]
        sensors = service.suggest_sensors(requirements)

        assert len(sensors) == 1
        assert sensors[0].sensor_type == "Taster 4-fach"

    def test_suggest_sensors_preserves_room(self):
        """Vorgeschlagene Sensoren behalten Raum-ID."""
        service = SensorService()
        requirements = [
            SensorRequirement(
                sensor_type="Taster 2-fach",
                room_id="room-123",
                room_name="E01 Test",
                gewerk_code="L",
                count=1,
            ),
        ]
        sensors = service.suggest_sensors(requirements)

        assert sensors[0].room_id == "room-123"


class TestSensorMaterialList:
    """Tests fuer create_material_list (FA-1405)."""

    def test_material_list(self):
        """Materialliste zaehlt Sensoren."""
        service = SensorService()
        sensors = [
            Sensor(sensor_type="Taster 4-fach"),
            Sensor(sensor_type="Taster 4-fach"),
            Sensor(sensor_type="Temperaturfuehler"),
        ]

        material = service.create_material_list(sensors)
        assert len(material) >= 1

    def test_material_list_counts_correctly(self):
        """Gleicher Typ wird zu einer Position zusammengefasst."""
        service = SensorService()
        sensors = [
            Sensor(sensor_type="Taster 4-fach"),
            Sensor(sensor_type="Taster 4-fach"),
            Sensor(sensor_type="Temperaturfuehler"),
        ]

        material = service.create_material_list(sensors)

        taster = next(m for m in material if "Taster" in m["sensor_type"])
        assert taster["quantity"] == 2

        temp = next(m for m in material if "Temperaturfuehler" in m["sensor_type"])
        assert temp["quantity"] == 1

    def test_material_list_empty(self):
        """Leere Liste ergibt leere Materialliste."""
        service = SensorService()
        material = service.create_material_list([])
        assert material == []

    def test_material_list_has_required_fields(self):
        """Jede Materiallisten-Position enthaelt sensor_type und quantity."""
        service = SensorService()
        sensors = [Sensor(sensor_type="Taster 2-fach")]
        material = service.create_material_list(sensors)

        assert "sensor_type" in material[0]
        assert "quantity" in material[0]
        assert material[0]["quantity"] == 1


class TestSensorPerLine:
    """Tests fuer determine_sensors_per_line (FA-1401, FA-1404)."""

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
        """Fuer jede Linie mit Raeumen gibt es ein LineSensorResult."""
        room = Room(number="E01", name="Wohnzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=1),
            GewerkAssignment(gewerk_code="H", count=1),
        ]
        topology = self._make_topology_with_room(room)

        service = SensorService()
        results = service.determine_sensors_per_line(topology, [room], gewerk_catalog)

        assert len(results) == 1
        assert results[0].coupler_address == "1.1.0"
        assert results[0].line_name == "Linie 1.1"

    def test_per_line_sensors_suggested(self, gewerk_catalog):
        """Pro Linie werden Sensoren vorgeschlagen."""
        room = Room(number="E01", name="Wohnzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="LD", count=2),
        ]
        topology = self._make_topology_with_room(room)

        service = SensorService()
        results = service.determine_sensors_per_line(topology, [room], gewerk_catalog)

        assert len(results[0].sensors) >= 1

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

        service = SensorService()
        results = service.determine_sensors_per_line(topology, [room], gewerk_catalog)

        assert len(results) == 1
        assert results[0].coupler_address == "1.1.0"

    def test_per_line_room_info_preserved(self, gewerk_catalog):
        """Rauminformationen sind in den Requirements enthalten."""
        room = Room(number="E01", name="Schlafzimmer")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="LD", count=1)]
        topology = self._make_topology_with_room(room)

        service = SensorService()
        results = service.determine_sensors_per_line(topology, [room], gewerk_catalog)

        assert len(results) == 1
        reqs = results[0].requirements
        assert any("E01" in r.room_name for r in reqs)


class TestAutoAssignFunctions:
    """Tests fuer auto_assign_functions – primaere und Rueckmelde-GAs (FA-1502)."""

    def _make_room_with_gas(self, gewerk_assignments, gewerk_catalog, variant="A"):
        """Hilfsmethode: Raum + passende GA-Struktur generieren."""
        from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        eg = Floor(name="EG", short_code="EG", main_group_number=2)
        apt = Apartment(name="EG")
        room = Room(number="E01", name="Wohnzimmer")
        room.gewerk_assignments = gewerk_assignments
        apt.rooms.append(room)
        eg.apartments.append(apt)
        wing.floors.append(eg)
        building.wings.append(wing)
        areal.buildings.append(building)

        gen = AddressGenerator(gewerk_catalog, variant=variant)
        structure = gen.generate(areal)
        return room, structure

    def test_licht_primary_ea_assigned(self, gewerk_catalog):
        """Licht LD: E/A-GA wird dem Sensor zugeordnet."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="LD", count=1)], gewerk_catalog,
        )
        service = SensorService()
        service.auto_assign_functions([room], structure)

        assert len(room.bedienelemente) == 1
        fn_names = [fa.function_ga for fa in room.bedienelemente[0].function_assignments]
        assert any("E/A" in n for n in fn_names)

    def test_licht_feedback_rm_assigned(self, gewerk_catalog):
        """Licht LD: RM-GA (Rueckmeldung) wird zusaetzlich dem Sensor zugeordnet."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="LD", count=1)], gewerk_catalog,
        )
        service = SensorService()
        service.auto_assign_functions([room], structure)

        all_gas = [fa.function_ga for fa in room.bedienelemente[0].function_assignments]
        # RM-GA muss enthalten sein
        assert any("RM" in ga for ga in all_gas), \
            f"Kein RM-GA gefunden. Zugeordnete GAs: {all_gas}"

    def test_licht_feedback_rm_wert_assigned(self, gewerk_catalog):
        """Licht LD: RM WERT-GA wird fuer Dimmwert-Rueckmeldung zugeordnet."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="LD", count=1)], gewerk_catalog,
        )
        service = SensorService()
        service.auto_assign_functions([room], structure)

        all_gas = [fa.function_ga for fa in room.bedienelemente[0].function_assignments]
        assert any("RM WERT" in ga for ga in all_gas), \
            f"Kein RM WERT-GA gefunden. Zugeordnete GAs: {all_gas}"

    def test_jalousie_feedback_status_assigned(self, gewerk_catalog):
        """Jalousie J: Status-GAs fuer Position werden zugeordnet."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="J", count=1)], gewerk_catalog,
        )
        service = SensorService()
        service.auto_assign_functions([room], structure)

        all_gas = [fa.function_ga for fa in room.bedienelemente[0].function_assignments]
        assert any("STATUS POSITION" in ga for ga in all_gas), \
            f"Kein STATUS POSITION-GA gefunden. Zugeordnete GAs: {all_gas}"

    def test_feedback_channel_label_is_status(self, gewerk_catalog):
        """Rueckmelde-Kanaele sind als 'Status' gekennzeichnet."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="LD", count=1)], gewerk_catalog,
        )
        service = SensorService()
        service.auto_assign_functions([room], structure)

        channel_labels = [fa.button_channel for fa in room.bedienelemente[0].function_assignments]
        assert any("Status" in lbl for lbl in channel_labels), \
            f"Kein Status-Label gefunden. Labels: {channel_labels}"

    def test_multiple_elements_feedback_per_element(self, gewerk_catalog):
        """Bei 2x LD: Jedes Element bekommt seine eigene Rueckmeldung."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="LD", count=2)], gewerk_catalog,
        )
        service = SensorService()
        service.auto_assign_functions([room], structure)

        all_fas = room.bedienelemente[0].function_assignments
        # 2x LD → je E/A + DIM + RM + RM WERT = 8 Zuordnungen
        status_fas = [fa for fa in all_fas if "Status" in fa.button_channel]
        # Mindestens 2 RM-Zuordnungen (eine pro Element)
        rm_fas = [fa for fa in status_fas if "RM" in fa.function_ga]
        assert len(rm_fas) >= 2

    def test_no_feedback_without_ga(self, gewerk_catalog):
        """Ohne GAs werden BEs angelegt (Sensor-Vorschau), aber ohne function_assignments."""
        # Direkt leere GA-Struktur ohne RM-GAs verwenden
        from knix_arranger.models.group_address import GroupAddressStructure
        room = Room(number="E01", name="Wohnzimmer")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="LD", count=1)]
        empty_structure = GroupAddressStructure()

        service = SensorService()
        service.auto_assign_functions([room], empty_structure)

        # BE wird erstellt (Sensor-Ermittlung zeigt Vorschau auch ohne GAs)
        assert len(room.bedienelemente) == 1
        # Aber keine function_assignments, da keine GAs vorhanden
        assert room.bedienelemente[0].function_assignments == []

    def test_duplicate_room_number_correct_designation(self, gewerk_catalog):
        """Zwei Räume mit gleicher Raumnummer auf gleichem Stockwerk erhalten
        jeweils den korrekten eigenen Raumnamen in der GA-Bezeichnung (FA-1502).

        Bug-Szenario: Wohnung 1 = E01 'Wohnzimmer', Wohnung 2 = E01 'Küche'.
        Ohne room_id-Lookup überschreibt der zweite Raum den ersten im ga_lookup
        und Wohnzimmer bekommt fälschlicherweise '(Küche)' angezeigt.
        """
        from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment

        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        eg = Floor(name="EG", short_code="EG", main_group_number=2)

        # Wohnung 1: E01 Wohnzimmer
        apt1 = Apartment(name="Wohnung 1")
        room1 = Room(number="E01", name="Wohnzimmer")
        room1.gewerk_assignments = [GewerkAssignment(gewerk_code="LD", count=1)]
        apt1.rooms.append(room1)

        # Wohnung 2: E01 Küche – gleiche Raumnummer, anderer Name
        apt2 = Apartment(name="Wohnung 2")
        room2 = Room(number="E01", name="Küche")
        room2.gewerk_assignments = [GewerkAssignment(gewerk_code="LD", count=1)]
        apt2.rooms.append(room2)

        eg.apartments.extend([apt1, apt2])
        wing.floors.append(eg)
        building.wings.append(wing)
        areal.buildings.append(building)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        service = SensorService()
        service.auto_assign_functions([room1, room2], structure)

        # room1 (Wohnzimmer) muss einen EA-Eintrag mit "(Wohnzimmer)" haben
        fas1 = room1.bedienelemente[0].function_assignments
        ea1 = next((fa for fa in fas1 if "E/A" in fa.function_ga), None)
        assert ea1 is not None, "Kein E/A-Eintrag für Wohnzimmer"
        assert "Wohnzimmer" in ea1.function_ga, (
            f"Falscher Raumname in GA-Bezeichnung von Wohnzimmer: {ea1.function_ga}"
        )

        # room2 (Küche) muss einen EA-Eintrag mit "(Küche)" haben
        fas2 = room2.bedienelemente[0].function_assignments
        ea2 = next((fa for fa in fas2 if "E/A" in fa.function_ga), None)
        assert ea2 is not None, "Kein E/A-Eintrag für Küche"
        assert "Küche" in ea2.function_ga, (
            f"Falscher Raumname in GA-Bezeichnung von Küche: {ea2.function_ga}"
        )


class TestSensorTypeOverride:
    """Tests fuer FA-1407: manueller Sensortyp-Override."""

    def test_override_replaces_auto_type(self, gewerk_catalog):
        """sensor_type_override hat Vorrang vor automatisch ermitteltem Typ."""
        room = Room(number="E01", name="Flur")
        assignment = GewerkAssignment(gewerk_code="LD", count=1)
        assignment.sensor_type_override = "Bewegungsmelder"
        room.gewerk_assignments = [assignment]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        assert len(requirements) == 1
        assert requirements[0].sensor_type == "Bewegungsmelder"

    def test_override_is_flagged(self, gewerk_catalog):
        """is_overridden ist True wenn sensor_type_override gesetzt ist."""
        room = Room(number="E01", name="Flur")
        assignment = GewerkAssignment(gewerk_code="LD", count=1)
        assignment.sensor_type_override = "Praesenzmelder"
        room.gewerk_assignments = [assignment]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        assert requirements[0].is_overridden is True

    def test_no_override_not_flagged(self, gewerk_catalog):
        """is_overridden ist False wenn kein Override gesetzt ist."""
        room = Room(number="E01", name="Flur")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code="LD", count=1)]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        assert requirements[0].is_overridden is False

    def test_assignment_id_in_requirement(self, gewerk_catalog):
        """assignment_id wird korrekt in SensorRequirement uebertragen."""
        room = Room(number="E01", name="Flur")
        assignment = GewerkAssignment(gewerk_code="LD", count=1)
        room.gewerk_assignments = [assignment]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        assert requirements[0].assignment_id == assignment.id

    def test_override_reset_to_none_uses_auto_type(self, gewerk_catalog):
        """Wenn Override auf None zurueckgesetzt wird, wird der automatische Typ verwendet."""
        room = Room(number="E01", name="Flur")
        assignment = GewerkAssignment(gewerk_code="LD", count=1)
        assignment.sensor_type_override = None  # kein Override
        room.gewerk_assignments = [assignment]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        from knix_arranger.models.device import GEWERK_TO_SENSOR_TYPE
        expected_auto = GEWERK_TO_SENSOR_TYPE.get("LD")
        assert requirements[0].sensor_type == expected_auto
        assert requirements[0].is_overridden is False

    def test_override_persisted_in_to_dict(self):
        """sensor_type_override wird in to_dict serialisiert (FA-1407d)."""
        assignment = GewerkAssignment(gewerk_code="LD", count=1)
        assignment.sensor_type_override = "Bewegungsmelder"
        d = assignment.to_dict()
        assert d["sensor_type_override"] == "Bewegungsmelder"

    def test_override_loaded_from_dict(self):
        """sensor_type_override wird aus dict deserialisiert (FA-1407d)."""
        data = {"gewerk_code": "LD", "count": 1, "sensor_type_override": "Bewegungsmelder"}
        assignment = GewerkAssignment.from_dict(data)
        assert assignment.sensor_type_override == "Bewegungsmelder"

    def test_override_none_loaded_from_dict(self):
        """Fehlendes sensor_type_override in dict ergibt None."""
        data = {"gewerk_code": "LD", "count": 1}
        assignment = GewerkAssignment.from_dict(data)
        assert assignment.sensor_type_override is None

    def test_two_assignments_same_gewerk_one_overridden(self, gewerk_catalog):
        """Bei zwei Zuweisungen desselben Gewerks, eine davon mit Override,
        entstehen zwei separate SensorRequirements."""
        room = Room(number="E01", name="Buero")
        a1 = GewerkAssignment(gewerk_code="LD", count=1)
        a2 = GewerkAssignment(gewerk_code="LD", count=1)
        a2.sensor_type_override = "Bewegungsmelder"
        room.gewerk_assignments = [a1, a2]

        service = SensorService()
        requirements = service.determine_sensors([room], gewerk_catalog)

        types = [r.sensor_type for r in requirements]
        from knix_arranger.models.device import GEWERK_TO_SENSOR_TYPE
        auto_type = GEWERK_TO_SENSOR_TYPE.get("LD")
        assert auto_type in types
        assert "Bewegungsmelder" in types


class TestTastereinheiten:
    """Tests fuer Viele-zu-viele Tastereinheiten (FA-1410)."""

    def _make_room_with_gas(self, gewerk_assignments, gewerk_catalog):
        """Raum + GA-Struktur generieren."""
        from knix_arranger.models.building import Areal, Building, Wing, Floor, Apartment
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        eg = Floor(name="EG", short_code="EG", main_group_number=2)
        apt = Apartment(name="EG")
        room = Room(number="E01", name="Wohnzimmer")
        room.gewerk_assignments = gewerk_assignments
        apt.rooms.append(room)
        eg.apartments.append(apt)
        wing.floors.append(eg)
        building.wings.append(wing)
        areal.buildings.append(building)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)
        return room, structure

    def test_two_te_creates_two_bes(self, gewerk_catalog):
        """LD auf taster_indices=[1,2] erzeugt zwei separate Bedienelemente."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="LD", count=1, taster_indices=[1, 2])],
            gewerk_catalog,
        )
        service = SensorService()
        service.auto_assign_functions([room], structure)

        assert len(room.bedienelemente) == 2, (
            f"Erwartet 2 BEs fuer taster_indices=[1,2], erhalten: {len(room.bedienelemente)}"
        )

    def test_te_type_praesenzmelder_element_type(self, gewerk_catalog):
        """TE mit Typ 'Präsenzmelder' erzeugt BE mit element_type='Präsenzmelder'."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="LD", count=1, taster_indices=[2])],
            gewerk_catalog,
        )
        room.set_te_type(2, "Präsenzmelder")

        service = SensorService()
        service.auto_assign_functions([room], structure)

        assert len(room.bedienelemente) == 1
        assert room.bedienelemente[0].element_type == "Präsenzmelder", (
            f"Erwartet 'Präsenzmelder', erhalten: '{room.bedienelemente[0].element_type}'"
        )

    def test_te_type_does_not_override_raumthermostat(self, gewerk_catalog):
        """H (Raumthermostat) auf 'Präsenzmelder'-TE bleibt 'Raumthermostat'."""
        from knix_arranger.models.device import GEWERK_TO_SENSOR_TYPE
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="H", count=1, taster_indices=[1])],
            gewerk_catalog,
        )
        room.set_te_type(1, "Präsenzmelder")

        service = SensorService()
        service.auto_assign_functions([room], structure)

        assert len(room.bedienelemente) == 1
        expected_type = GEWERK_TO_SENSOR_TYPE.get("H", "Raumthermostat")
        assert room.bedienelemente[0].element_type == expected_type, (
            f"TE-Typ 'Präsenzmelder' darf 'Raumthermostat' nicht überschreiben. "
            f"Erhalten: '{room.bedienelemente[0].element_type}'"
        )

    def test_manual_be_not_reused_for_second_te(self, gewerk_catalog):
        """Manuelles BE auf TE1 wird nicht für TE2 wiederverwendet.
        LD auf taster_indices=[1,2]: TE2 bekommt ein auto-BE."""
        room, structure = self._make_room_with_gas(
            [GewerkAssignment(gewerk_code="LD", count=1, taster_indices=[1, 2])],
            gewerk_catalog,
        )

        from knix_arranger.models.building import Bedienelement
        manual_be = Bedienelement(
            element_type="Tastereinheit",
            channels=4,
            is_auto=False,
            taster_index=1,
        )
        room.bedienelemente = [manual_be]

        service = SensorService()
        service.auto_assign_functions([room], structure)

        assert len(room.bedienelemente) == 2, (
            f"Erwartet 2 BEs (1 manuell + 1 auto), erhalten: {len(room.bedienelemente)}"
        )
        auto_bes = [b for b in room.bedienelemente if b.is_auto]
        assert len(auto_bes) == 1, "TE2 soll ein auto-BE erhalten"
        manual_bes = [b for b in room.bedienelemente if not b.is_auto]
        assert len(manual_bes) == 1, "Manuelles BE auf TE1 soll erhalten bleiben"
