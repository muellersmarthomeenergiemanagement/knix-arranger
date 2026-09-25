"""
Tests fuer BelegungsplanService (Sensor/Aktor-Belegungsplan).

Schwerpunkt: Kanal-Vergabe an Aktoren (channel_number).
Kernregel: Jede eindeutige (Raum, Gewerk, Element-Nr.) Kombination
erhält eine eigene fortlaufende Kanalnummer.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.project import KnxProject
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
    Bedienelement, FunctionAssignment,
)
from knix_arranger.models.topology import Topology, Area, Line, Device, CommunicationObject
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.scene import Scene
from knix_arranger.services.belegungsplan_service import (
    BelegungsplanService, build_ga_by_designation, resolve_ga_display,
)


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _make_project(rooms: list[Room], actor_product: str, gas: list[GroupAddress]) -> KnxProject:
    """Erstellt ein minimales Testprojekt mit einer Linie und einem Aktor."""
    project = KnxProject(name="Test")

    # Gebäude
    apt = Apartment(name="WG")
    apt.rooms = rooms
    floor = Floor(name="EG", short_code="EG", main_group_number=1)
    floor.apartments = [apt]
    wing = Wing(name="Haupt")
    wing.floors = [floor]
    building = Building(name="Test")
    building.wings = [wing]
    project.areal = Areal(name="Test", buildings=[building])

    # Topologie: eine Linie mit einem Aktor
    line = Line(name="Linie 1", line_number=1)
    line.assigned_room_ids = [r.id for r in rooms]
    actor = Device(device_type="actor", product=actor_product, physical_address="1.1.1")
    line.devices = [actor]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    topology = Topology()
    topology.areas = [area]
    project.topology = topology

    # Gruppenadressen
    mg = MiddleGroup(number=0, name="Test")
    mg.group_addresses = gas
    hg = MainGroup(number=1, name="EG")
    hg.middle_groups = [mg]
    structure = GroupAddressStructure()
    structure.main_groups = [hg]
    project.group_addresses = structure

    return project


def _ga(room: Room, gewerk: str, elem: int, fn: str, sub: int) -> GroupAddress:
    """Erstellt eine GroupAddress mit room_id, element_number und function_name."""
    return GroupAddress(
        main_group=1, middle_group=0, sub_group=sub,
        designation=f"{gewerk}_{room.number}_{elem:02d} {fn}",
        gewerk_code=gewerk,
        room_id=room.id,
        room_number=room.number,
        element_number=elem,
        function_name=fn,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestAktorKanalVergabe:

    def test_einzelelement_erhaelt_kanal_1(self):
        """Ein einzelnes Element pro Raum/Gewerk → Kanal 1."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [_ga(room, "L", 1, "E/A", 0), _ga(room, "L", 1, "DIM", 1)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) > 0
        assert all(r.channel_number == "1" for r in rows)

    def test_zwei_elemente_erhalten_separate_kanaele(self):
        """Zwei Elemente (element_number 1 und 2) in gleichem Raum/Gewerk → Kanal 1 und 2."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _ga(room, "L", 2, "E/A", 1),  # zweiter Stromkreis
        ]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2"], (
            "Zwei Elemente im gleichen Raum/Gewerk müssen separate Kanäle erhalten"
        )

    def test_drei_elemente_erhalten_drei_kanaele(self):
        """Drei Elemente (Küche: 3× Licht) → Kanal 1, 2, 3."""
        room = Room(number="E02", name="Kueche")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _ga(room, "L", 2, "E/A", 1),
            _ga(room, "L", 3, "E/A", 2),
        ]
        project = _make_project([room], "Schaltaktor 8-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2", "3"]

    def test_zwei_raeume_erhalten_separate_kanaele(self):
        """Zwei Räume mit je einem Element → Kanal 1 und 2."""
        room1 = Room(number="E01", name="Wohnzimmer")
        room2 = Room(number="E02", name="Schlafzimmer")
        gas = [
            _ga(room1, "L", 1, "E/A", 0),
            _ga(room2, "L", 1, "E/A", 1),
        ]
        project = _make_project([room1, room2], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2"]

    def test_jalousie_mehrere_elemente_pro_raum(self):
        """Jalousieaktor: 2 Jalousien im Wohnzimmer → 2 separate Kanäle."""
        room = Room(number="E04", name="Wohnzimmer")
        gas = [
            _ga(room, "J", 1, "AUF/AB", 0),
            _ga(room, "J", 1, "STOPP",  1),
            _ga(room, "J", 2, "AUF/AB", 2),  # zweite Jalousie
            _ga(room, "J", 2, "STOPP",  3),
        ]
        project = _make_project([room], "Jalousieaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2"], (
            "Zwei Jalousien im gleichen Raum müssen separate Kanäle erhalten"
        )

    def test_gleiche_funktion_gleicher_kanal(self):
        """Alle GAs desselben Elements teilen denselben Kanal."""
        room = Room(number="E01", name="Zimmer")
        gas = [
            _ga(room, "LD", 1, "E/A",   0),
            _ga(room, "LD", 1, "DIM",   1),
            _ga(room, "LD", 1, "WERT",  2),
            _ga(room, "LD", 1, "RM",    3),
        ]
        project = _make_project([room], "Dimmaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) == 4
        assert all(r.channel_number == "1" for r in rows), (
            "Alle GAs desselben Elements müssen denselben Kanal haben"
        )

    def test_gemischte_gewerke_erhalten_separate_kanaele(self):
        """Schaltaktor: Licht (L) und Steckdose (V) in gleichem Raum → je eigener Kanal."""
        room = Room(number="E02", name="Kueche")
        gas = [
            _ga(room, "L", 1, "E/A", 0),
            _ga(room, "V", 1, "E/A", 1),
        ]
        project = _make_project([room], "Schaltaktor 8-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_by_gewerk = {r.gewerk_code: r.channel_number for r in rows}
        assert channel_by_gewerk.get("L") != channel_by_gewerk.get("V"), (
            "Verschiedene Gewerke im gleichen Raum müssen separate Kanäle haben"
        )

    def test_kanaele_fortlaufend_ab_1(self):
        """Kanalnummern sind immer fortlaufend ab 1 ohne Lücken."""
        room1 = Room(number="E01", name="Zimmer 1")
        room2 = Room(number="E02", name="Zimmer 2")
        room3 = Room(number="E03", name="Zimmer 3")
        gas = [
            _ga(room1, "L", 1, "E/A", 0),
            _ga(room2, "L", 1, "E/A", 1),
            _ga(room3, "L", 1, "E/A", 2),
        ]
        project = _make_project([room1, room2, room3], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        nums = sorted(int(r.channel_number) for r in rows if r.channel_number.isdigit())
        assert nums == list(range(1, len(nums) + 1)), "Kanalnummern müssen lückenlos ab 1 sein"

    def test_raum_mit_mehreren_elementen_und_mehreren_raeumen(self):
        """
        Kombiniert: Wohnzimmer mit 2 Jalousien + Schlafzimmer mit 1 Jalousie
        → Jalousieaktor sollte 3 Kanäle vergeben.
        """
        wohn = Room(number="E04", name="Wohnzimmer")
        schlaf = Room(number="E05", name="Schlafzimmer")
        gas = [
            _ga(wohn,  "J", 1, "AUF/AB", 0),
            _ga(wohn,  "J", 2, "AUF/AB", 1),  # zweite Jalousie im Wohnzimmer
            _ga(schlaf,"J", 1, "AUF/AB", 2),
        ]
        project = _make_project([wohn, schlaf], "Jalousieaktor 8-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        channel_nums = sorted(set(r.channel_number for r in rows))
        assert channel_nums == ["1", "2", "3"]


class TestAktorRowFelder:

    def test_actor_row_hat_element_number(self):
        """ActorRow enthält das element_number-Feld."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 2, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) > 0
        assert rows[0].element_number == 2

    def test_actor_row_felder_vollstaendig(self):
        """ActorRow enthält alle erwarteten Felder."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        row = BelegungsplanService().generate(project).actor_rows[0]
        assert row.physical_address == "1.1.1"
        assert row.room_number == "E01"
        assert row.gewerk_code == "L"
        assert row.channel_number == "1"
        assert row.element_number == 1


class TestCoFallbackGleicherCoName:
    """Regression (Topologie-Ansicht zeigte GA scheinbar doppelt, Chalet
    Franziska 2005-Projekt): ein ETS6-importierter Aktor kann zwei
    Kommunikationsobjekte mit demselben co.name (z.B. "Ausgang A" -- der
    physische Kanalname) aber unterschiedlicher object_function tragen
    (kombiniertes "Schalten"-Objekt inkl. Statusempfang + separates
    "Telegr. Status"-Objekt), die beide auf dieselbe GA zeigen. function_name
    allein (== co.name) macht die zwei Zeilen fuer die Anzeige ununterscheidbar
    -- co_function muss die tatsaechliche Rolle tragen, sonst wirkt das wie
    eine doppelte GA."""

    def test_co_function_unterscheidet_gleichnamige_cos(self):
        room = Room(number="E01", name="Zimmer")
        project = _make_project([room], "Fremd-Aktor ohne Gewerk-Zuordnung", [])
        device = project.topology.areas[0].lines[0].devices[0]
        device.communication_objects = [
            CommunicationObject(
                object_number=0, name="Ausgang A", object_function="Schalten",
                data_type="1 bit", connected_gas=["3/0/65", "3/7/65"],
            ),
            CommunicationObject(
                object_number=16, name="Ausgang A", object_function="Telegr. Status",
                data_type="1 bit", connected_gas=["3/7/65"],
            ),
        ]

        rows = BelegungsplanService().generate(project).actor_rows
        shared_ga_rows = [r for r in rows if r.ga_address == "3/7/65"]
        assert len(shared_ga_rows) == 2
        assert {r.co_function for r in shared_ga_rows} == {"Schalten", "Telegr. Status"}
        # Beide gehoeren zum selben Kanal ("Ausgang A") -- die Kanal-Gruppierung
        # darf durch co_function nicht auseinandergerissen werden.
        assert {r.function_name for r in shared_ga_rows} == {"Ausgang A"}
        assert len({r.channel_number for r in shared_ga_rows}) == 1


class TestGatewayActorRows:
    """Regression: Gateway-Geraete (device_type='gateway', z.B. DALI, Modbus,
    KNX-Schnittstelle/MM) wurden bisher nirgends als Aktor-Zeile erfasst, da
    _collect_actor_rows strikt auf device_type == 'actor' filterte. Damit
    fehlten sie auch als Grundlage der CO-Verknuepfung."""

    def _make_gateway_project(self, rooms, gateway_product, gas):
        project = _make_project(rooms, gateway_product, gas)
        device = project.topology.areas[0].lines[0].devices[0]
        device.device_type = "gateway"
        return project

    def test_mm_gateway_produces_actor_rows(self):
        room = Room(number="M01", name="Musikzimmer")
        gas = [_ga(room, "MM", 1, "EIN/AUS", 0)]
        project = self._make_gateway_project(
            [room], "KNX-Schnittstelle 1-fach", gas,
        )

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) == 1
        assert rows[0].gewerk_code == "MM"
        assert rows[0].function_name == "EIN/AUS"
        assert rows[0].physical_address == "1.1.1"

    def test_dali_gateway_product_maps_to_lda(self):
        """DALI-Gateway war bereits vor diesem Fix in _ACTOR_TYPE_GEWERKE
        eingetragen -- nur der device_type-Filter fehlte."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "LDA", 1, "E/A", 0)]
        project = self._make_gateway_project(
            [room], "DALI-Gateway 16-fach", gas,
        )

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) == 1
        assert rows[0].gewerk_code == "LDA"

    def test_plain_actor_devices_unaffected(self):
        """Normale Aktoren (device_type='actor') funktionieren unveraendert."""
        room = Room(number="E01", name="Zimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        rows = BelegungsplanService().generate(project).actor_rows
        assert len(rows) == 1
        assert rows[0].gewerk_code == "L"


class TestVerknuepfungsmatrixFelder:
    """FA-2501 (Stockwerk-Filter) / FA-2502 (Funktionsspalten aus Gewerk-Code)."""

    def test_actor_row_hat_floor_name(self):
        """ActorRow traegt den Stockwerksnamen fuer den FA-2501 Stockwerk-Filter."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [_ga(room, "L", 1, "E/A", 0)]
        project = _make_project([room], "Schaltaktor 4-fach", gas)

        row = BelegungsplanService().generate(project).actor_rows[0]
        assert row.floor_name == "EG"

    def test_sensor_row_hat_gewerk_code_aus_co_gekoppelter_ga(self):
        """SensorRow.gewerk_code kommt von der ueber ein KO verknuepften GA --
        Grundlage der Funktionsspalten in der Verknuepfungsmatrix (FA-2502).

        Nutzt den CO-Fallback-Pfad (_sensor_rows_from_cos), da
        auto_assign_functions() manuell gesetzte function_assignments ohne
        zugehörige Gewerk-Zuweisung im Raum wieder verwirft.
        """
        room = Room(number="E01", name="Wohnzimmer")
        ga = _ga(room, "L", 1, "E/A", 0)
        project = _make_project([room], "Schaltaktor 4-fach", [ga])

        sensor_dev = Device(
            device_type="sensor", product="Taster 2-fach", physical_address="1.1.2",
        )
        sensor_dev.communication_objects = [
            CommunicationObject(object_number=1, name="Taste 1",
                                 object_function="Schalten", connected_gas=[ga.address]),
        ]
        project.topology.areas[0].lines[0].devices.append(sensor_dev)

        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2")
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        assert len(rows) == 1
        assert rows[0].gewerk_code == "L"
        assert rows[0].floor_name == "EG"

    def test_sensor_row_gewerk_code_leer_ohne_aufgeloeste_ga(self):
        """Ohne auflösbare GA (unbekannte Adresse im KO) bleibt gewerk_code
        leer statt zu raten."""
        room = Room(number="E01", name="Wohnzimmer")
        project = _make_project([room], "Schaltaktor 4-fach", [])

        sensor_dev = Device(
            device_type="sensor", product="Taster 2-fach", physical_address="1.1.2",
        )
        sensor_dev.communication_objects = [
            CommunicationObject(object_number=1, name="Taste 1",
                                 object_function="Schalten", connected_gas=["9/7/255"]),
        ]
        project.topology.areas[0].lines[0].devices.append(sensor_dev)

        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2")
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        assert len(rows) == 1
        assert rows[0].gewerk_code == ""

    def test_suppressed_bedienelement_excluded_from_sensor_rows(self):
        """Ein in der Gerätekonfiguration gelöschtes (suppressed) Bedienelement
        darf nicht in der Verknüpfungsmatrix auftauchen."""
        room = Room(number="E01", name="Wohnzimmer")
        ga = _ga(room, "L", 1, "E/A", 0)
        project = _make_project([room], "Schaltaktor 4-fach", [ga])

        sensor_dev = Device(
            device_type="sensor", product="Taster 2-fach", physical_address="1.1.2",
        )
        sensor_dev.communication_objects = [
            CommunicationObject(object_number=1, name="Taste 1",
                                 object_function="Schalten", connected_gas=[ga.address]),
        ]
        project.topology.areas[0].lines[0].devices.append(sensor_dev)

        be = Bedienelement(
            element_type="Tastereinheit", participant_number="1.1.2",
            is_auto=False, suppressed=True,
        )
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        assert rows == []

    def test_reines_meldeobjekt_wird_als_feedback_erkannt(self):
        """Regression (Chalet Franziska 2005, Formular K Verknuepfungsmatrix):
        ein reines Status-/Messwert-Objekt eines ETS6-importierten Sensors
        (z.B. Rauchmelder-Alarm, Temperatur-Messwert -- kein Schreiben-Flag,
        also nicht vom Bus ansteuerbar) wurde bisher IMMER mit is_feedback=
        False angelegt und erschien deshalb in der Verknuepfungsmatrix als
        aktive "Taste"-Zeile, obwohl niemand es "drueckt". Muss anhand der
        fehlenden 'S'-Flag als Feedback erkannt werden."""
        room = Room(number="E01", name="Wohnzimmer")
        project = _make_project([room], "Schaltaktor 4-fach", [])

        sensor_dev = Device(
            device_type="sensor", product="Rauchmelder", physical_address="1.1.2",
        )
        sensor_dev.communication_objects = [
            CommunicationObject(
                object_number=1, name="Rauchm.:Alarm (0: Aktiv)",
                object_function="Ausgang", flags="KL-Ü--",
                connected_gas=["1/0/0"],
            ),
        ]
        project.topology.areas[0].lines[0].devices.append(sensor_dev)

        be = Bedienelement(element_type="Sensor", participant_number="1.1.2")
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        assert len(rows) == 1
        assert rows[0].is_feedback is True

    def test_echte_taste_bleibt_aktiv(self):
        """Ein echtes Taster-Objekt (hat das Schreiben-Flag 'S', der Bus kann
        es also tatsaechlich ansteuern/ausloesen) bleibt is_feedback=False."""
        room = Room(number="E01", name="Wohnzimmer")
        project = _make_project([room], "Schaltaktor 4-fach", [])

        sensor_dev = Device(
            device_type="sensor", product="Taster 2-fach", physical_address="1.1.2",
        )
        sensor_dev.communication_objects = [
            CommunicationObject(
                object_number=1, name="Taste 1, links",
                object_function="EIN/AUS, Schalten", flags="K-SÜA-",
                connected_gas=["1/0/0"],
            ),
        ]
        project.topology.areas[0].lines[0].devices.append(sensor_dev)

        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2")
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        assert len(rows) == 1
        assert rows[0].is_feedback is False

    def test_leere_flags_bleiben_konservativ_kein_feedback(self):
        """Ohne bekannte Flags (z.B. synthetisch angelegtes CO ohne ETS-Import-
        Daten) bleibt das bisherige Verhalten erhalten: is_feedback=False."""
        room = Room(number="E01", name="Wohnzimmer")
        project = _make_project([room], "Schaltaktor 4-fach", [])

        sensor_dev = Device(
            device_type="sensor", product="Taster 2-fach", physical_address="1.1.2",
        )
        sensor_dev.communication_objects = [
            CommunicationObject(
                object_number=1, name="Taste 1", object_function="Schalten",
                flags="", connected_gas=["1/0/0"],
            ),
        ]
        project.topology.areas[0].lines[0].devices.append(sensor_dev)

        be = Bedienelement(element_type="Tastereinheit", participant_number="1.1.2")
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        assert len(rows) == 1
        assert rows[0].is_feedback is False


class TestFunctionGaMitAdressPraefixAufloesen:
    """Regression (Chalet Franziska 2005, Formular K Verknuepfungsmatrix):
    importierte Direkte-GA-SensorFunktionen speichern in ga_designation das
    kombinierte "Adresse  Bezeichnung"-Format (XlsxImportService.
    backfill_function_assignments), das direkt in FunctionAssignment.
    function_ga uebernommen wird (SensorService._expand_direct_ga). Der
    GA-Index in _collect_sensor_rows war aber nur nach der REINEN
    GroupAddress.designation (ohne Adresse) indiziert -- ein Lookup mit dem
    adress-praefixten function_ga schlug deshalb IMMER fehl, wodurch
    gewerk_code, ga_address und dpt leer blieben und die Zeile in der
    Verknuepfungsmatrix unter "Sonstige" statt im richtigen Gewerk landete
    (im echten Projekt: "Jalousie" erschien dadurch nur bei 1 von 13
    betroffenen Tastern)."""

    def test_gewerk_code_und_adresse_werden_trotz_praefix_aufgeloest(self):
        room = Room(number="E01", name="Küche")
        ga = GroupAddress(
            main_group=3, middle_group=1, sub_group=40,
            designation="J.OG.05.01_move  ( Küche )",
            gewerk_code="J", datapoint_type="DPST-1-8",
        )
        project = _make_project([room], "Schaltaktor 4-fach", [ga])

        from knix_arranger.models.building import SensorFunktion
        be = Bedienelement(
            element_type="Tastereinheit", participant_number="1.1.2", is_auto=False,
            funktionen=[
                # Adress-praefixtes ga_designation, wie es beim XLSX-Import
                # tatsaechlich entsteht.
                SensorFunktion(
                    label="Taste 2, rechts",
                    ga_designation="3/1/40  J.OG.05.01_move  ( Küche )",
                ),
            ],
        )
        room.bedienelemente = [be]

        rows = BelegungsplanService().generate(project).sensor_rows
        matching = [r for r in rows if r.taste_label == "Taste 2, rechts"]
        assert len(matching) == 1
        assert matching[0].gewerk_code == "J"
        assert matching[0].ga_address == "3/1/40"
        assert matching[0].dpt == "DPST-1-8"


def _central_ga(gewerk: str, fn: str, designation: str, sub: int, dpt: str = "DPST-1-1") -> GroupAddress:
    """Erstellt eine Zentral-GA (central='true'), z.B. 'ZENTRAL Alle Lichter AUS'."""
    return GroupAddress(
        main_group=0, middle_group=0, sub_group=sub,
        designation=designation, gewerk_code=gewerk, function_name=fn,
        datapoint_type=dpt, central="true",
    )


class TestZentralUndSzenenZeilen:
    """FA: Zentral-/Szenen-GAs (HG 0) muessen in den Belegungsplan aufgenommen
    werden, obwohl sie weder room_id noch room_number tragen."""

    def test_zentral_licht_ga_geht_an_alle_lichtaktoren(self):
        room1 = Room(number="E01", name="Wohnzimmer")
        room2 = Room(number="E02", name="Kueche")
        gas = [
            _ga(room1, "L", 1, "E/A", 1),
            _ga(room2, "L", 1, "E/A", 2),
            _central_ga("L", "E/A", "ZENTRAL Alle Lichter AUS", 0),
        ]
        project = _make_project([room1, room2], "Schaltaktor 4-fach", gas)
        # Zweiter Lichtaktor in derselben Linie
        actor2 = Device(device_type="actor", product="Schaltaktor 4-fach", physical_address="1.1.2")
        project.topology.areas[0].lines[0].devices.append(actor2)

        rows = BelegungsplanService().generate(project).actor_rows
        central_rows = [r for r in rows if r.ga_designation == "ZENTRAL Alle Lichter AUS"]
        addrs = {r.physical_address for r in central_rows}
        assert addrs == {"1.1.1", "1.1.2"}, (
            "Zentral-Licht-GA muss an JEDEN Lichtaktor gehen, unabhaengig vom Raum"
        )
        assert all(r.room_number == "" for r in central_rows)

    def test_szenen_ga_nur_an_aktoren_im_geltungsbereich(self):
        room1 = Room(number="E01", name="Wohnzimmer")
        room2 = Room(number="E02", name="Kueche")
        gas = [
            _ga(room1, "L", 1, "E/A", 1),
            _ga(room2, "L", 1, "E/A", 2),
            _central_ga("", "SZENE", "Szenenaufruf Wohnzimmer", 0, dpt="DPST-17-1"),
        ]
        # "1-fach" (Kapazitaet 1) erzwingt, dass Stromkreis 1 (Wohnzimmer) an
        # Aktor 1 geht und erst Stromkreis 2 (Kueche) an Aktor 2 wechselt --
        # damit bedient jeder Aktor eindeutig genau einen Raum.
        project = _make_project([room1, room2], "Schaltaktor 1-fach", gas)
        actor2 = Device(device_type="actor", product="Schaltaktor 1-fach", physical_address="1.1.2")
        project.topology.areas[0].lines[0].devices.append(actor2)

        scene = Scene(name="Kino", scene_number=1, scope="room", scope_id=room1.id)
        project.scenes.append(scene)

        rows = BelegungsplanService().generate(project).actor_rows
        szenen_rows = [r for r in rows if r.ga_designation == "Szenenaufruf Wohnzimmer"]
        assert len(szenen_rows) == 1, szenen_rows
        assert szenen_rows[0].physical_address == "1.1.1", (
            "Nur der Wohnzimmer-Aktor darf die 'Szenenaufruf Wohnzimmer'-Zeile "
            "bekommen, nicht der Kueche-Aktor"
        )
        assert szenen_rows[0].gewerk_code == ""
        assert szenen_rows[0].function_name == "SZENE"

    def test_zentrale_szene_ohne_scope_geht_an_alle(self):
        """Eine Szenen-GA, deren Bezeichnung zu keiner Scene-Gruppe passt
        (z.B. die fest eingebaute 'ZENTRAL Szene Abwesenheit'), gilt als
        projektweit -- keine Raum-Einschraenkung."""
        room = Room(number="E01", name="Wohnzimmer")
        gas = [
            _ga(room, "L", 1, "E/A", 1),
            _central_ga("", "SZENE", "ZENTRAL Szene Abwesenheit", 0, dpt="DPST-17-1"),
        ]
        project = _make_project([room], "Schaltaktor 4-fach", gas)
        actor2 = Device(device_type="actor", product="Schaltaktor 4-fach", physical_address="1.1.2")
        project.topology.areas[0].lines[0].devices.append(actor2)

        rows = BelegungsplanService().generate(project).actor_rows
        szenen_rows = [r for r in rows if r.ga_designation == "ZENTRAL Szene Abwesenheit"]
        addrs = {r.physical_address for r in szenen_rows}
        assert addrs == {"1.1.1", "1.1.2"}


# ---------------------------------------------------------------------------
# build_ga_by_designation / resolve_ga_display (FA-1502c): wizard-geplante
# (Gewerk-basierte) function_assignments speichern in function_ga nur die
# GA-Bezeichnung, keine Adressnummer (SensorService._expand_funktionen
# uebernimmt GroupAddress.designation direkt) -- Views wie building_view.py
# und topology_view.py loesen die Adresse darueber nach, statt eine
# GA-Zeile ohne Adressnummer anzuzeigen.
# ---------------------------------------------------------------------------

class TestResolveGaDisplay:
    def _ga_structure_with(self, designation: str, address=(2, 0, 0)) -> GroupAddressStructure:
        gas = GroupAddressStructure()
        hg = MainGroup(number=address[0], name="Test")
        mg = MiddleGroup(number=address[1], name="Test")
        hg.middle_groups.append(mg)
        gas.main_groups.append(hg)
        mg.group_addresses.append(GroupAddress(
            main_group=address[0], middle_group=address[1], sub_group=address[2],
            designation=designation,
        ))
        return gas

    def test_pure_designation_gets_address_prefixed(self):
        gas = self._ga_structure_with("LD_E01_01 E/A")
        lookup = build_ga_by_designation(gas)
        assert resolve_ga_display("LD_E01_01 E/A", lookup) == "2/0/0  LD_E01_01 E/A"

    def test_matches_designation_without_parenthetical_suffix(self):
        """GA-Bezeichnung mit Raum-Zusatz in Klammern ('... (Schlafzimmer)')
        -- function_ga traegt manchmal nur den Teil ohne Klammer."""
        gas = self._ga_structure_with("LD_E01_01 E/A (Schlafzimmer)")
        lookup = build_ga_by_designation(gas)
        assert resolve_ga_display("LD_E01_01 E/A", lookup) == "2/0/0  LD_E01_01 E/A"

    def test_already_combined_import_text_stays_unchanged(self):
        """Importierte Direkte-GA-Zuordnungen speichern function_ga schon als
        "Adresse  Bezeichnung" -- darf nicht nochmal praefixiert werden, auch
        wenn die GA-Struktur zufaellig eine passende Bezeichnung kennt."""
        gas = self._ga_structure_with("L.UG.01.1_ea")
        lookup = build_ga_by_designation(gas)
        combined = "1/0/0  L.UG.01.1_ea  ( Technikraum )"
        assert resolve_ga_display(combined, lookup) == combined

    def test_unknown_designation_returned_unchanged(self):
        lookup = build_ga_by_designation(GroupAddressStructure())
        assert resolve_ga_display("Unbekannt", lookup) == "Unbekannt"

    def test_empty_function_ga_stays_empty(self):
        lookup = build_ga_by_designation(GroupAddressStructure())
        assert resolve_ga_display("", lookup) == ""


# ── Kanal-Gliederung der Kommunikationsobjekte (Baumansichten) ───────────────

def test_channel_label_at_end_of_name():
    from knix_arranger.services.belegungsplan_service import _extract_channel_label
    assert _extract_channel_label("Stellgröße, Kanal 1") == "Kanal 1"
    assert _extract_channel_label("Status Ventilstellung, Kanal 4") == "Kanal 4"
    assert _extract_channel_label("Bedienung Storen (M1), Endlage") == "Kanal M1"
    assert _extract_channel_label("Status Direktbetrieb") == ""


def test_group_cos_for_display():
    """Kanaele je Knoten; ohne Kanal nach ETS-Funktion gebuendelt (Vitogate),
    einzelne Objekte direkt unter dem Geraet (Name "")."""
    from knix_arranger.models.topology import CommunicationObject
    from knix_arranger.services.belegungsplan_service import group_cos_for_display

    def co(nr, name, function=""):
        return CommunicationObject(object_number=nr, name=name, object_function=function,
                                   connected_gas=[f"0/2/{nr}"])

    cos = [
        co(0, "Stellgröße, Kanal 1"), co(6, "Status Ventilstellung, Kanal 1"),
        co(10, "HK1 Raumtemperatur Soll", "Bedienung / Heizkreis A1/HK1"),
        co(11, "HK1 Red. Raumtemperatur Soll", "Bedienung / Heizkreis A1/HK1"),
        co(20, "Außentemperatur", "Überblick / Anlage"),
        co(30, "Sammelstörung", "Fehlermanagement"),
    ]
    groups = dict(group_cos_for_display(cos))
    assert [c.object_number for c in groups["Kanal 1"]] == [0, 6]
    assert [c.object_number for c in groups["Bedienung / Heizkreis A1/HK1"]] == [10, 11]
    assert [c.object_number for c in groups[""]] == [20, 30]
    assert list(groups)[-1] == ""
