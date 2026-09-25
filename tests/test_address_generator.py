"""
Tests fuer AddressGenerator - Kern-Engine (FA-400)
Referenz: Pflichtenheft Anhang A

Testet Variante A und B mit dem Referenzbeispiel:
EG (HG 2), Raum E01 Schlafzimmer: 1x LD, 2x J, 1x H
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.services.gewerk_service import GewerkService
from knix_arranger.models.group_address import GroupAddressStructure
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment, Bedienelement,
)


class TestAddressGeneratorVarianteA:
    """Tests fuer Variante A (RM in gleicher MG)."""

    def test_generate_creates_structure(self, eg_room_with_gewerke, gewerk_catalog):
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        assert isinstance(structure, GroupAddressStructure)
        assert structure.variant == "A"

    def test_hg0_central_addresses(self, eg_room_with_gewerke, gewerk_catalog):
        """HG 0 enthaelt Zentraladressen (FA-441, FA-442)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg0 = structure.main_groups[0]
        assert hg0.number == 0
        assert hg0.name == "Zentraladressen"

        # MG 0: Licht zentral
        mg0 = hg0.middle_groups[0]
        assert mg0.number == 0
        assert len(mg0.group_addresses) >= 2
        assert mg0.group_addresses[0].address == "0/0/1"  # 0/0/0 ist Systemadresse (FA-444)
        assert "Alle Lichter AUS" in mg0.group_addresses[0].designation
        assert mg0.group_addresses[0].central == "true"

        # MG 1: Jalousie zentral
        mg1 = hg0.middle_groups[1]
        assert mg1.number == 1
        assert mg1.group_addresses[0].address == "0/1/1"  # 0/1/0 vermieden (FA-444)
        assert "Alle Jalousien AUF" in mg1.group_addresses[0].designation

    def test_hg2_eg_main_group(self, eg_room_with_gewerke, gewerk_catalog):
        """HG 2 = Erdgeschoss (FA-411)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        # HG 0 = Zentral, HG 2 = EG
        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        assert hg2.name == "Erdgeschoss"

    def test_mg0_licht_1x_ld_variante_a(self, eg_room_with_gewerke, gewerk_catalog):
        """MG 0 Licht: 1x LD ergibt 5er-Block mit RM (Var. A)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)

        # 1x LD = 5er-Block: E/A, DIM, WERT, RM, RM WERT
        assert len(mg0.group_addresses) == 5

        gas = sorted(mg0.group_addresses, key=lambda g: g.sub_group)

        # 2/0/0: LD_E01_01 E/A
        assert gas[0].address == "2/0/0"
        assert gas[0].gewerk_code == "LD"
        assert gas[0].function_name == "E/A"
        assert gas[0].datapoint_type == "DPST-1-1"
        assert gas[0].room_number == "E01"
        assert gas[0].element_number == 1

        # 2/0/1: DIM
        assert gas[1].address == "2/0/1"
        assert gas[1].function_name == "DIM"
        assert gas[1].datapoint_type == "DPST-3-7"

        # 2/0/2: WERT
        assert gas[2].address == "2/0/2"
        assert gas[2].function_name == "WERT"
        assert gas[2].datapoint_type == "DPST-5-1"

        # 2/0/3: RM (Rueckmeldung in gleicher MG bei Var. A)
        assert gas[3].address == "2/0/3"
        assert gas[3].function_name == "RM"
        assert gas[3].datapoint_type == "DPST-1-1"

        # 2/0/4: RM WERT
        assert gas[4].address == "2/0/4"
        assert gas[4].function_name == "RM WERT"
        assert gas[4].datapoint_type == "DPST-5-1"

    def test_mg1_jalousie_2x_j_variante_a(self, eg_room_with_gewerke, gewerk_catalog):
        """MG 1 Jalousie: 2x J ergibt 2x 10er-Block mit Status (Var. A)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg1 = next(mg for mg in hg2.middle_groups if mg.number == 1)

        # 2x J = 2x 10er-Block = 20 Adressen
        assert len(mg1.group_addresses) == 20

        gas = sorted(mg1.group_addresses, key=lambda g: g.sub_group)

        # Erster Block: J Element 1 (2/1/0 bis 2/1/9)
        assert gas[0].address == "2/1/0"
        assert gas[0].function_name == "AUF/AB"
        assert gas[0].datapoint_type == "DPST-1-8"
        assert gas[0].gewerk_code == "J"
        assert gas[0].element_number == 1

        assert gas[1].address == "2/1/1"
        assert gas[1].function_name == "STOPP"

        assert gas[2].address == "2/1/2"
        assert gas[2].function_name == "POSITION HOEHE"

        assert gas[5].address == "2/1/5"
        assert gas[5].function_name == "SPERREN"

        # STATUS in gleicher MG (Var. A)
        assert gas[6].address == "2/1/6"
        assert gas[6].function_name == "STATUS POSITION HOEHE"

        assert gas[7].address == "2/1/7"
        assert gas[7].function_name == "STATUS POSITION LAMELLEN"

        # Reserve-Plaetze
        assert gas[8].is_placeholder
        assert gas[9].is_placeholder

        # Zweiter Block: J Element 2 (2/1/10 bis 2/1/19)
        assert gas[10].address == "2/1/10"
        assert gas[10].function_name == "AUF/AB"
        assert gas[10].element_number == 2

        assert gas[19].address == "2/1/19"

    def test_mg2_heizung_1x_h(self, eg_room_with_gewerke, gewerk_catalog):
        """MG 2 Heizung: 1x H ergibt 10er-Block."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg2 = next(mg for mg in hg2.middle_groups if mg.number == 2)

        # 1x H = 10er-Block
        assert len(mg2.group_addresses) == 10

        gas = sorted(mg2.group_addresses, key=lambda g: g.sub_group)

        assert gas[0].address == "2/2/0"
        assert gas[0].function_name == "STELLGROESSE"
        assert gas[0].gewerk_code == "H"

        assert gas[1].function_name == "IST"
        assert gas[1].datapoint_type == "DPST-9-1"

        assert gas[2].function_name == "BASIS-SOLL"

        assert gas[4].function_name == "UMSCHALTEN BETRIEBSART"
        assert gas[4].datapoint_type == "DPST-20-102"

        assert gas[8].function_name == "STOERUNG"
        assert gas[9].function_name == "SPERREN"

    def test_total_ga_count_variante_a(self, eg_room_with_gewerke, gewerk_catalog):
        """Gesamtzahl GA: 1x LD(5) + 2x J(10) + 1x H(10) = 35 + Zentral."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        total_hg2 = sum(
            len(mg.group_addresses) for mg in hg2.middle_groups
        )
        # 5 (Licht) + 20 (2x Jalousie) + 10 (Heizung) = 35
        assert total_hg2 == 35

    def test_no_feedback_in_mg6_mg7_variante_a(self, eg_room_with_gewerke, gewerk_catalog):
        """Variante A: Keine separaten MG 6/7 fuer Rueckmeldungen."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg_numbers = [mg.number for mg in hg2.middle_groups]

        assert 6 not in mg_numbers
        assert 7 not in mg_numbers

    def test_block_integrity_no_gaps(self, eg_room_with_gewerke, gewerk_catalog):
        """Adressbloecke haben keine Luecken (FA-605)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        for hg in structure.main_groups:
            for mg in hg.middle_groups:
                gas = sorted(mg.group_addresses, key=lambda g: g.sub_group)
                for i in range(len(gas) - 1):
                    assert gas[i + 1].sub_group == gas[i].sub_group + 1, \
                        f"Luecke in {hg.number}/{mg.number}: {gas[i].sub_group} -> {gas[i+1].sub_group}"


class TestAddressGeneratorVarianteB:
    """Tests fuer Variante B (RM in separaten MG 6/7)."""

    def test_mg0_licht_no_rm_in_mg0(self, eg_room_with_gewerke, gewerk_catalog):
        """Var. B: MG 0 hat keine Rueckmeldungen (nur E/A, DIM, WERT + Reserve)."""
        gen = AddressGenerator(gewerk_catalog, variant="B")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)

        gas = sorted(mg0.group_addresses, key=lambda g: g.sub_group)
        assert len(gas) == 5  # 5er-Block bleibt

        # E/A, DIM, WERT + 2x Reserve
        assert gas[0].function_name == "E/A"
        assert gas[1].function_name == "DIM"
        assert gas[2].function_name == "WERT"
        assert gas[3].is_placeholder  # Reserve
        assert gas[4].is_placeholder  # Reserve

    def test_mg6_licht_rueckmeldung(self, eg_room_with_gewerke, gewerk_catalog):
        """Var. B: MG 6 enthaelt Licht-Rueckmeldungen."""
        gen = AddressGenerator(gewerk_catalog, variant="B")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg6 = next(mg for mg in hg2.middle_groups if mg.number == 6)

        gas = sorted(mg6.group_addresses, key=lambda g: g.sub_group)
        assert len(gas) == 5  # 5er Feedback-Block

        # RM, Reserve, RM WERT, Reserve, Reserve
        assert gas[0].function_name == "RM"
        assert gas[0].datapoint_type == "DPST-1-1"
        assert gas[2].function_name == "RM WERT"

    def test_mg1_jalousie_no_status(self, eg_room_with_gewerke, gewerk_catalog):
        """Var. B: MG 1 hat keinen Status (Reserve stattdessen)."""
        gen = AddressGenerator(gewerk_catalog, variant="B")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg1 = next(mg for mg in hg2.middle_groups if mg.number == 1)

        gas = sorted(mg1.group_addresses, key=lambda g: g.sub_group)

        # Block 1: Offsets 0-9, Offsets 6-9 sind alle Reserve
        assert gas[6].is_placeholder  # Reserve statt STATUS POSITION HOEHE
        assert gas[7].is_placeholder  # Reserve statt STATUS POSITION LAMELLEN
        assert gas[8].is_placeholder
        assert gas[9].is_placeholder

    def test_mg7_jalousie_rueckmeldung(self, eg_room_with_gewerke, gewerk_catalog):
        """Var. B: MG 7 enthaelt Jalousie-Rueckmeldungen."""
        gen = AddressGenerator(gewerk_catalog, variant="B")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg7 = next(mg for mg in hg2.middle_groups if mg.number == 7)

        gas = sorted(mg7.group_addresses, key=lambda g: g.sub_group)
        # 2x J = 2x 10er Feedback-Block = 20 Adressen
        assert len(gas) == 20

        # Offset 2: STATUS POSITION HOEHE
        assert gas[2].function_name == "STATUS POSITION HOEHE"
        assert gas[3].function_name == "STATUS POSITION LAMELLEN"

        # Zweiter Block ab Offset 10
        assert gas[12].function_name == "STATUS POSITION HOEHE"
        assert gas[12].element_number == 2

    def test_mg2_heizung_identical_both_variants(self, eg_room_with_gewerke, gewerk_catalog):
        """Heizung ist bei Var. A und B identisch."""
        gen_a = AddressGenerator(gewerk_catalog, variant="A")
        gen_b = AddressGenerator(gewerk_catalog, variant="B")

        struct_a = gen_a.generate(eg_room_with_gewerke)
        struct_b = gen_b.generate(eg_room_with_gewerke)

        hg2_a = next(hg for hg in struct_a.main_groups if hg.number == 2)
        hg2_b = next(hg for hg in struct_b.main_groups if hg.number == 2)

        mg2_a = next(mg for mg in hg2_a.middle_groups if mg.number == 2)
        mg2_b = next(mg for mg in hg2_b.middle_groups if mg.number == 2)

        assert len(mg2_a.group_addresses) == len(mg2_b.group_addresses)
        for ga_a, ga_b in zip(
            sorted(mg2_a.group_addresses, key=lambda g: g.sub_group),
            sorted(mg2_b.group_addresses, key=lambda g: g.sub_group),
        ):
            assert ga_a.function_name == ga_b.function_name
            assert ga_a.datapoint_type == ga_b.datapoint_type


class TestAddressGeneratorDesignation:
    """Tests fuer korrekte Bezeichnungen (BZ-01 bis BZ-06)."""

    def test_designation_format(self, eg_room_with_gewerke, gewerk_catalog):
        """Bezeichnung folgt Format GEWERK_RAUM_NR FUNKTION."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        ga = mg0.group_addresses[0]

        assert "LD_E01_01" in ga.designation
        assert "E/A" in ga.designation

    def test_placeholder_designation(self, eg_room_with_gewerke, gewerk_catalog):
        """Reserve-Plaetze haben '--' als Bezeichnung (FA-434)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg1 = next(mg for mg in hg2.middle_groups if mg.number == 1)
        gas = sorted(mg1.group_addresses, key=lambda g: g.sub_group)

        # Offsets 8 und 9 sind Reserve
        assert gas[8].is_placeholder
        assert gas[8].designation == "--"

    def test_room_name_in_first_address(self, eg_room_with_gewerke, gewerk_catalog):
        """Erste Adresse eines Blocks enthaelt Raumname als Klartext."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        first_ga = sorted(mg0.group_addresses, key=lambda g: g.sub_group)[0]

        assert "Schlafzimmer" in first_ga.designation


class TestAddressGeneratorMultiFloor:
    """Tests mit mehreren Stockwerken (simple_efh Fixture)."""

    def test_efh_all_floors_get_hg(self, simple_efh, gewerk_catalog):
        """EFH: Jedes Stockwerk bekommt eine eigene HG."""
        # Gewerke zuweisen fuer jedes Stockwerk
        for floor in simple_efh.all_floors:
            for room in floor.all_rooms:
                room.gewerk_assignments = [
                    __import__("knix_arranger.models.building", fromlist=["GewerkAssignment"])
                    .GewerkAssignment(gewerk_code="L", count=1)
                ]

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh)

        # HG 0 (Zentral) + HG 1 (UG) + HG 2 (EG) + HG 3 (OG) + HG 4 (DG) = 5
        assert len(structure.main_groups) == 5

        hg_numbers = [hg.number for hg in structure.main_groups]
        assert 0 in hg_numbers  # Zentral
        assert 1 in hg_numbers  # UG
        assert 2 in hg_numbers  # EG
        assert 3 in hg_numbers  # OG
        assert 4 in hg_numbers  # DG

    def test_find_address(self, eg_room_with_gewerke, gewerk_catalog):
        """find_address findet eine spezifische GA."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        ga = structure.find_address(2, 0, 0)
        assert ga is not None
        assert ga.gewerk_code == "LD"
        assert ga.function_name == "E/A"

    def test_all_addresses_count(self, eg_room_with_gewerke, gewerk_catalog):
        """all_addresses() gibt alle GAs zurueck."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        all_gas = structure.all_addresses()
        assert len(all_gas) > 0

        # Zentral + Floor GAs
        hg0_count = sum(
            len(mg.group_addresses) for mg in structure.main_groups[0].middle_groups
        )
        hg2_count = 35  # 5 + 20 + 10
        assert len(all_gas) >= hg0_count + hg2_count


class TestAddressGeneratorNoDuplicates:
    """Tests dass keine doppelten Gruppenadressen generiert werden."""

    def test_no_duplicate_addresses(self, eg_room_with_gewerke, gewerk_catalog):
        """Keine GA darf doppelt vorkommen."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        all_gas = structure.all_addresses()
        addresses = [ga.address for ga in all_gas]
        assert len(addresses) == len(set(addresses)), \
            f"Doppelte Adressen gefunden: {[a for a in addresses if addresses.count(a) > 1]}"

    def test_no_duplicate_addresses_multi_floor(self, simple_efh, gewerk_catalog):
        """Keine Duplikate bei mehreren Stockwerken."""
        from knix_arranger.models.building import GewerkAssignment
        for floor in simple_efh.all_floors:
            for room in floor.all_rooms:
                room.gewerk_assignments = [
                    GewerkAssignment(gewerk_code="LD", count=1),
                    GewerkAssignment(gewerk_code="J", count=1),
                ]

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh)

        all_gas = structure.all_addresses()
        addresses = [ga.address for ga in all_gas]
        assert len(addresses) == len(set(addresses)), \
            f"Doppelte Adressen: {[a for a in addresses if addresses.count(a) > 1]}"

    def test_floors_with_same_hg_merged(self, gewerk_catalog):
        """Stockwerke mit gleicher HG-Nummer werden zusammengefuehrt."""
        from knix_arranger.models.building import (
            Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
        )
        areal = Areal(name="Merge-Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")

        # Zwei Stockwerke mit gleicher HG-Nummer
        f1 = Floor(name="EG-A", short_code="EG", main_group_number=2)
        apt1 = Apartment(name="EG-A")
        r1 = Room(number="A01", name="Raum A")
        r1.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]
        apt1.rooms.append(r1)
        f1.apartments.append(apt1)

        f2 = Floor(name="EG-B", short_code="EG", main_group_number=2)
        apt2 = Apartment(name="EG-B")
        r2 = Room(number="B01", name="Raum B")
        r2.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]
        apt2.rooms.append(r2)
        f2.apartments.append(apt2)

        wing.floors = [f1, f2]
        building.wings.append(wing)
        areal.buildings.append(building)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        # Es darf nur EINE HG 2 geben (zusammengefuehrt)
        hg2_list = [hg for hg in structure.main_groups if hg.number == 2]
        assert len(hg2_list) == 1, \
            f"Erwartet 1x HG 2, gefunden: {len(hg2_list)}"

        # Beide Raeume muessen in der MG vorhanden sein
        hg2 = hg2_list[0]
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        # 2x Licht = 2x 5er-Block = 10 Adressen
        assert len(mg0.group_addresses) == 10

        # Keine doppelten Adressen
        addresses = [ga.address for ga in mg0.group_addresses]
        assert len(addresses) == len(set(addresses))

    def test_no_duplicate_addresses_variante_b(self, eg_room_with_gewerke, gewerk_catalog):
        """Keine Duplikate bei Variante B."""
        gen = AddressGenerator(gewerk_catalog, variant="B")
        structure = gen.generate(eg_room_with_gewerke)

        all_gas = structure.all_addresses()
        addresses = [ga.address for ga in all_gas]
        assert len(addresses) == len(set(addresses)), \
            f"Doppelte Adressen in Var. B: {[a for a in addresses if addresses.count(a) > 1]}"


class TestGaEditing:
    """Tests fuer GA-Bearbeitung (GA-Edit-Dialog Logik)."""

    def test_ga_fields_are_mutable(self):
        """GA-Felder koennen geaendert werden."""
        from knix_arranger.models.group_address import GroupAddress
        ga = GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="LD_E01_01 E/A",
            datapoint_type="DPST-1-1",
            gewerk_code="LD",
            room_number="E01",
            element_number=1,
            function_name="E/A",
        )
        ga.designation = "Neue Bezeichnung"
        ga.description = "Test-Beschreibung"
        ga.datapoint_type = "DPST-5-1"
        ga.function_name = "WERT"
        ga.central = "true"
        ga.is_placeholder = True

        assert ga.designation == "Neue Bezeichnung"
        assert ga.description == "Test-Beschreibung"
        assert ga.datapoint_type == "DPST-5-1"
        assert ga.function_name == "WERT"
        assert ga.central == "true"
        assert ga.is_placeholder is True

    def test_ga_address_updates_on_field_change(self):
        """address-Property aktualisiert sich bei Aenderung der Felder."""
        from knix_arranger.models.group_address import GroupAddress
        ga = GroupAddress(main_group=2, middle_group=0, sub_group=0)
        assert ga.address == "2/0/0"

        ga.main_group = 3
        ga.middle_group = 1
        ga.sub_group = 5
        assert ga.address == "3/1/5"

    def test_edited_ga_persists_in_structure(self, eg_room_with_gewerke, gewerk_catalog):
        """Aenderung an GA ist in der Struktur sichtbar."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        ga = structure.find_address(2, 0, 0)
        assert ga is not None
        original_id = ga.id

        ga.designation = "Geaendert"
        ga.description = "Test-Edit"

        # Gleiche GA nochmal suchen - muss die Aenderung haben
        ga_again = structure.find_address(2, 0, 0)
        assert ga_again.id == original_id
        assert ga_again.designation == "Geaendert"
        assert ga_again.description == "Test-Edit"


# Beispiel-ComObjects einer Wetterstation (KNXPROD-Import-Format)
_WEATHER_COM_OBJECTS = [
    {
        "number": 1, "name": "Helligkeit Ost", "function_text": "Helligkeit Ost",
        "datapoint_type": "DPST-9-4",
        "communication_flag": True, "read_flag": False,
        "write_flag": False, "transmit_flag": True, "update_flag": False,
    },
    {
        "number": 2, "name": "Wind Geschwindigkeit", "function_text": "Wind Geschwindigkeit",
        "datapoint_type": "DPST-9-5",
        "communication_flag": True, "read_flag": False,
        "write_flag": False, "transmit_flag": True, "update_flag": False,
    },
    {
        "number": 3, "name": "Regen", "function_text": "Regen",
        "datapoint_type": "DPST-1-2",
        "communication_flag": True, "read_flag": False,
        "write_flag": False, "transmit_flag": True, "update_flag": False,
    },
    {
        "number": 4, "name": "Sperren Wind", "function_text": "Sperren Wind",
        "datapoint_type": "DPST-1-1",
        "communication_flag": True, "read_flag": False,
        "write_flag": True, "transmit_flag": False, "update_flag": False,
    },
    {
        # Kein needs_ga (kein Flag gesetzt) - darf nicht ins Schema uebernommen werden
        "number": 5, "name": "Reserve", "function_text": "Reserve",
        "datapoint_type": "DPST-1-1",
        "communication_flag": True, "read_flag": False,
        "write_flag": False, "transmit_flag": False, "update_flag": False,
    },
]


@pytest.fixture
def eg_room_with_weather_station():
    """EG Raum E01 mit Gewerk 'W' (Wetterstation), verknuepft mit Produkt."""
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")

    eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
    eg_apt = Apartment(name="EG")

    room = Room(number="E01", name="Schlafzimmer")
    room.gewerk_assignments = [
        GewerkAssignment(
            gewerk_code="W", count=1,
            linked_product={
                "manufacturer": "Test-Hersteller",
                "order_number": "WS-100",
                "product_name": "Wetterstation Pro",
                "com_objects": _WEATHER_COM_OBJECTS,
                "material_entry_id": "test-entry-id",
            },
        ),
    ]
    eg_apt.rooms.append(room)
    eg.apartments.append(eg_apt)

    wing.floors.append(eg)
    building.wings.append(wing)
    areal.buildings.append(building)
    return areal


class TestAddressGeneratorProductSchema:
    """Tests fuer produktbasierte GA-Generierung (verknuepftes Produkt)."""

    def test_product_schema_replaces_generic_block(
        self, eg_room_with_weather_station, gewerk_catalog,
    ):
        """GAs der 'W'-Zuweisung entsprechen den ComObjects des Produkts,
        nicht dem generischen 10er-Schema (E/A, WERT 1, WERT 2, ...)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_weather_station)

        gewerk = gewerk_catalog.get("W")
        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg = next(m for m in hg2.middle_groups if m.number == gewerk.middle_group)

        designations = [ga.designation for ga in mg.group_addresses]
        function_names = [ga.function_name for ga in mg.group_addresses]
        dpts = [ga.datapoint_type for ga in mg.group_addresses]

        # Generisches Schema darf nicht mehr vorkommen
        assert not any("WERT 1" in d for d in designations)
        assert not any("WERT 2" in d for d in designations)

        # Produkt-ComObjects (mit needs_ga) muessen vorkommen, in dieser Reihenfolge
        assert "Helligkeit Ost" in function_names
        assert "Wind Geschwindigkeit" in function_names
        assert "Regen" in function_names
        assert "Sperren Wind" in function_names

        # Reserve-ComObject (kein Flag) darf nicht uebernommen werden
        assert "Reserve" not in function_names

        # DPTs aus dem Produkt
        idx = function_names.index("Helligkeit Ost")
        assert dpts[idx] == "DPST-9-4"

        # Genau 4 GAs (5 ComObjects, 1 davon ohne needs_ga)
        assert len([f for f in function_names if f]) == 4

    def test_extra_entries_appended_to_product_schema(
        self, eg_room_with_weather_station, gewerk_catalog,
    ):
        """Zusaetzliche manuelle GAs (extra_entries) werden an den
        Produkt-Block angehaengt."""
        room = eg_room_with_weather_station.all_floors[0].apartments[0].rooms[0]
        assignment = room.gewerk_assignments[0]
        assignment.extra_entries = [{
            "offset": 0, "function": "ZUSATZ", "designation": "ZUSATZ",
            "dpt": "DPST-1-1", "is_feedback": False, "is_reserve": False,
        }]

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_weather_station)

        gewerk = gewerk_catalog.get("W")
        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg = next(m for m in hg2.middle_groups if m.number == gewerk.middle_group)

        function_names = [ga.function_name for ga in mg.group_addresses]
        assert "ZUSATZ" in function_names
        # 4 Produkt-GAs + 1 Extra-GA
        assert len([f for f in function_names if f]) == 5

    def test_linked_product_without_com_objects_falls_back_to_w_schema(
        self, eg_room_with_weather_station, gewerk_catalog,
    ):
        """Ohne ComObjects (z.B. Produkt nicht via KNXPROD importiert) greift
        das gewerk-spezifische Wetterstation-Schema (kein generischer Block)."""
        room = eg_room_with_weather_station.all_floors[0].apartments[0].rooms[0]
        room.gewerk_assignments[0].linked_product["com_objects"] = []

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_weather_station)

        gewerk = gewerk_catalog.get("W")
        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg = next(m for m in hg2.middle_groups if m.number == gewerk.middle_group)

        function_names = [ga.function_name for ga in mg.group_addresses]
        assert "HELLIGKEIT OST" in function_names
        assert "WERT 1" not in function_names

    def test_linked_product_to_dict_round_trip(self):
        """GewerkAssignment.linked_product wird korrekt (de-)serialisiert."""
        ga = GewerkAssignment(
            gewerk_code="W", count=1,
            linked_product={
                "manufacturer": "Test-Hersteller",
                "order_number": "WS-100",
                "product_name": "Wetterstation Pro",
                "com_objects": _WEATHER_COM_OBJECTS,
                "material_entry_id": "test-entry-id",
            },
        )
        data = ga.to_dict()
        assert data["linked_product"]["order_number"] == "WS-100"

        restored = GewerkAssignment.from_dict(data)
        assert restored.linked_product == ga.linked_product

    def test_linked_product_defaults_to_none(self):
        """Bestehende Projekte ohne linked_product laden mit None."""
        restored = GewerkAssignment.from_dict({"gewerk_code": "L", "count": 1})
        assert restored.linked_product is None

    def test_excluded_co_numbers_removed_from_schema(
        self, eg_room_with_weather_station, gewerk_catalog,
    ):
        """Ausgeschlossene ComObject-Nummern (Integrator-Auswahl) erzeugen
        keine GA, obwohl sie needs_ga erfuellen."""
        room = eg_room_with_weather_station.all_floors[0].apartments[0].rooms[0]
        room.gewerk_assignments[0].linked_product["excluded_co_numbers"] = [2, 4]

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_weather_station)

        gewerk = gewerk_catalog.get("W")
        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg = next(m for m in hg2.middle_groups if m.number == gewerk.middle_group)

        function_names = [ga.function_name for ga in mg.group_addresses if ga.function_name]
        assert "Helligkeit Ost" in function_names
        assert "Regen" in function_names
        assert "Wind Geschwindigkeit" not in function_names  # Nr. 2, ausgeschlossen
        assert "Sperren Wind" not in function_names           # Nr. 4, ausgeschlossen
        assert len(function_names) == 2  # 4 needs_ga minus 2 ausgeschlossene

    def test_missing_excluded_co_numbers_behaves_like_before(
        self, eg_room_with_weather_station, gewerk_catalog,
    ):
        """Alte Projekte ohne den neuen Schluessel verhalten sich unveraendert."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_weather_station)

        gewerk = gewerk_catalog.get("W")
        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg = next(m for m in hg2.middle_groups if m.number == gewerk.middle_group)
        function_names = [ga.function_name for ga in mg.group_addresses if ga.function_name]
        assert len(function_names) == 4  # alle needs_ga-ComObjects wie bisher


class TestGewerkServiceProductGaCount:
    """Tests fuer GA-Zaehlung mit verknuepftem Produkt (gewerk_service)."""

    def test_calculate_ga_count_uses_product_com_objects(
        self, eg_room_with_weather_station, gewerk_catalog,
    ):
        from knix_arranger.services.gewerk_service import GewerkService

        room = eg_room_with_weather_station.all_floors[0].apartments[0].rooms[0]
        gewerk = gewerk_catalog.get("W")

        service = GewerkService(gewerk_catalog)
        count = service.calculate_ga_count(room)

        # 4 GA-relevante ComObjects statt gewerk.ga_count (10)
        assert count == 4
        assert count != gewerk.ga_count

    def test_room_summary_reflects_product_ga_count(
        self, eg_room_with_weather_station, gewerk_catalog,
    ):
        from knix_arranger.services.gewerk_service import GewerkService

        room = eg_room_with_weather_station.all_floors[0].apartments[0].rooms[0]
        service = GewerkService(gewerk_catalog)
        summary = service.get_room_summary(room)

        assert summary[0]["code"] == "W"
        assert summary[0]["ga_per_element"] == 4
        assert summary[0]["total_ga"] == 4


class TestAddressGeneratorGatewaySchemas:
    """Default-Schemata fuer Gateway-/Sensor-Gewerke ohne Produktverknuepfung
    (W=Wetterstation, WP=Waermepumpe, MM=Multimedia/Musikanlage)."""

    @pytest.mark.parametrize("code,expected_function,expected_mg", [
        ("W", "HELLIGKEIT OST", 4),
        ("WP", "BETRIEBSART", 2),
        ("MM", "EIN/AUS", 4),
    ])
    def test_default_schema_used_without_linked_product(
        self, gewerk_catalog, code, expected_function, expected_mg,
    ):
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
        eg_apt = Apartment(name="EG")
        room = Room(number="E01", name="Technik")
        room.gewerk_assignments = [GewerkAssignment(gewerk_code=code, count=1)]
        eg_apt.rooms.append(room)
        eg.apartments.append(eg_apt)
        wing.floors.append(eg)
        building.wings.append(wing)
        areal.buildings.append(building)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        gewerk = gewerk_catalog.get(code)
        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg = next(m for m in hg2.middle_groups if m.number == expected_mg)

        function_names = [ga.function_name for ga in mg.group_addresses]
        assert expected_function in function_names
        assert "WERT 1" not in function_names
        assert len(mg.group_addresses) == gewerk.block_size


class TestAddressGeneratorStableRegeneration:
    """Tests fuer stabile Neugenerierung mit existing=: unveraenderte
    Zuweisungsbloecke bleiben an Position/id, geaenderte/neue werden ans
    Ende der Mittelgruppe angehaengt statt die Struktur neu durchzunummerieren."""

    @staticmethod
    def _room_with_weather_and_energy():
        """EG Raum mit 'W' (Wetterstation, Produkt-Schema) und 'E' (generisch),
        beide in Mittelgruppe 4 - zum Testen von Nachbar-Isolation."""
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
        eg_apt = Apartment(name="EG")
        room = Room(number="E01", name="Schlafzimmer")
        room.gewerk_assignments = [
            GewerkAssignment(
                gewerk_code="W", count=1,
                linked_product={
                    "manufacturer": "Test", "order_number": "WS-100",
                    "product_name": "Wetterstation Pro",
                    "com_objects": list(_WEATHER_COM_OBJECTS),
                    "material_entry_id": "entry-w",
                },
            ),
            GewerkAssignment(gewerk_code="E", count=1),
        ]
        eg_apt.rooms.append(room)
        eg.apartments.append(eg_apt)
        wing.floors.append(eg)
        building.wings.append(wing)
        areal.buildings.append(building)
        return areal, room

    def test_unchanged_assignment_keeps_position_and_id(
        self, eg_room_with_gewerke, gewerk_catalog,
    ):
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure1 = gen.generate(eg_room_with_gewerke)

        h_before = next(ga for ga in structure1.all_addresses() if ga.gewerk_code == "H")
        addr_before, id_before = h_before.address, h_before.id

        # Unveraendertes Modell erneut generieren, diesmal mit existing=
        structure2 = gen.generate(eg_room_with_gewerke, existing=structure1)

        h_after = next(ga for ga in structure2.all_addresses() if ga.gewerk_code == "H")
        assert h_after.id == id_before
        assert h_after.address == addr_before

    def test_resized_product_block_appends_at_end_sibling_unchanged(self, gewerk_catalog):
        areal, room = self._room_with_weather_and_energy()
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure1 = gen.generate(areal)

        hg2 = next(hg for hg in structure1.main_groups if hg.number == 2)
        mg4 = next(mg for mg in hg2.middle_groups if mg.number == 4)
        e_before = next(ga for ga in mg4.group_addresses if ga.gewerk_code == "E")
        e_id_before, e_addr_before = e_before.id, e_before.address
        max_sub_before = max(ga.sub_group for ga in mg4.group_addresses)

        # Produkt vergroessern: ein zusaetzliches GA-relevantes ComObject
        room.gewerk_assignments[0].linked_product["com_objects"] = list(_WEATHER_COM_OBJECTS) + [{
            "number": 99, "name": "Zusatz", "function_text": "Zusatz",
            "datapoint_type": "DPST-1-1",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": True, "update_flag": False,
        }]

        structure2 = gen.generate(areal, existing=structure1)
        hg2_2 = next(hg for hg in structure2.main_groups if hg.number == 2)
        mg4_2 = next(mg for mg in hg2_2.middle_groups if mg.number == 4)

        # E (unveraendert) behaelt Position und Identitaet
        e_after = next(ga for ga in mg4_2.group_addresses if ga.gewerk_code == "E")
        assert e_after.id == e_id_before
        assert e_after.address == e_addr_before

        # W (vergroessert) wurde verworfen und komplett neu ans Ende angehaengt
        w_after = [ga for ga in mg4_2.group_addresses if ga.gewerk_code == "W"]
        assert len(w_after) == 5  # 4 vorher + 1 neu
        assert all(ga.sub_group > max_sub_before for ga in w_after)

    def test_removed_assignment_produces_no_gas_others_unaffected(
        self, eg_room_with_gewerke, gewerk_catalog,
    ):
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure1 = gen.generate(eg_room_with_gewerke)

        ld_before = next(ga for ga in structure1.all_addresses() if ga.gewerk_code == "LD")
        ld_id_before, ld_addr_before = ld_before.id, ld_before.address

        room = eg_room_with_gewerke.all_floors[0].apartments[0].rooms[0]
        j_assignment = next(g for g in room.gewerk_assignments if g.gewerk_code == "J")
        room.gewerk_assignments.remove(j_assignment)

        structure2 = gen.generate(eg_room_with_gewerke, existing=structure1)

        # Nur die Raum-HG pruefen: HG 0 enthaelt weiterhin die zentralen
        # Jalousie-Taster (immer vorhanden, unabhaengig von Raum-Zuweisungen).
        hg2 = next(hg for hg in structure2.main_groups if hg.number == 2)
        room_addresses = [ga for m in hg2.middle_groups for ga in m.group_addresses]
        assert not any(ga.gewerk_code == "J" for ga in room_addresses)

        ld_after = next(ga for ga in structure2.all_addresses() if ga.gewerk_code == "LD")
        assert ld_after.id == ld_id_before
        assert ld_after.address == ld_addr_before

    def test_variant_switch_ignores_existing(self, eg_room_with_gewerke, gewerk_catalog):
        gen_a = AddressGenerator(gewerk_catalog, variant="A")
        structure_a = gen_a.generate(eg_room_with_gewerke)

        gen_b = AddressGenerator(gewerk_catalog, variant="B")
        structure_b_fresh = gen_b.generate(eg_room_with_gewerke)
        structure_b_with_existing = gen_b.generate(eg_room_with_gewerke, existing=structure_a)

        addrs_fresh = sorted(ga.address for ga in structure_b_fresh.all_addresses())
        addrs_with_existing = sorted(ga.address for ga in structure_b_with_existing.all_addresses())
        assert addrs_fresh == addrs_with_existing

    def test_existing_gas_without_assignment_id_are_treated_as_new(
        self, eg_room_with_gewerke, gewerk_catalog,
    ):
        """Migrationsfall: alte Projektdateien ohne das neue Feld duerfen
        nicht abstuerzen und liefern dieselbe Anzahl GAs wie ein Fresh-Generate."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure1 = gen.generate(eg_room_with_gewerke)
        for ga in structure1.all_addresses():
            ga.assignment_id = ""

        structure2 = gen.generate(eg_room_with_gewerke, existing=structure1)
        fresh = gen.generate(eg_room_with_gewerke)
        assert len(structure2.all_addresses()) == len(fresh.all_addresses())

    def test_relink_assignment_ids_restores_stable_reuse_after_reimport(
        self, eg_room_with_gewerke, gewerk_catalog,
    ):
        """FA-521e End-to-End: nach einem Reimport (assignment_id verloren,
        weder .knxproj noch XLSX-GA-Report kennen dieses interne Feld)
        verknuepft GewerkService.relink_assignment_ids() die GAs wieder mit
        ihrer GewerkAssignment, damit die naechste Neugenerierung sie
        in-place wiederverwendet statt sie durch einen neuen Block an
        anderer Position zu ersetzen (siehe Kontrast:
        test_existing_gas_without_assignment_id_are_treated_as_new)."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure1 = gen.generate(eg_room_with_gewerke)

        h_before = next(ga for ga in structure1.all_addresses() if ga.gewerk_code == "H")
        addr_before, id_before = h_before.address, h_before.id

        for ga in structure1.all_addresses():
            ga.assignment_id = ""

        relinked = GewerkService(gewerk_catalog).relink_assignment_ids(
            structure1, eg_room_with_gewerke,
        )
        # HG0 (Zentraladressen) bleibt bewusst unverknuepft -- nur die
        # raumgebundenen GAs (HG2) werden einer GewerkAssignment zugeordnet.
        assert relinked > 0
        assert relinked < len(structure1.all_addresses())

        structure2 = gen.generate(eg_room_with_gewerke, existing=structure1)

        h_after = next(ga for ga in structure2.all_addresses() if ga.gewerk_code == "H")
        assert h_after.id == id_before
        assert h_after.address == addr_before


def _synthetic_com_objects(count: int) -> list[dict]:
    """Erzeugt `count` GA-relevante ComObject-Dicts (wie ein grosses
    Gateway-Produkt mit vielen ComObjects, z.B. Revox mit 491)."""
    return [
        {
            "number": i, "name": f"Objekt {i}", "function_text": f"Funktion {i}",
            "datapoint_type": "DPST-1-1",
            "communication_flag": True, "read_flag": False,
            "write_flag": True, "transmit_flag": False, "update_flag": False,
        }
        for i in range(count)
    ]


class TestAddressGeneratorMultiMgOverflow:
    """Tests fuer automatisches Verteilen eines Ueberlauf-Blocks auf mehrere
    Mittelgruppen derselben Hauptgruppe (z.B. Gateway-Produkt mit >256
    GA-relevanten ComObjects, wie das Revox-Multimedia-Gateway mit 491)."""

    @staticmethod
    def _room_with_big_gateway(count: int, gewerk_code: str = "MM"):
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
        eg_apt = Apartment(name="EG")
        room = Room(number="E01", name="Technik")
        room.gewerk_assignments = [
            GewerkAssignment(
                gewerk_code=gewerk_code, count=1,
                linked_product={
                    "manufacturer": "Test", "order_number": "GW-1",
                    "product_name": "Grosses Gateway",
                    "com_objects": _synthetic_com_objects(count),
                    "material_entry_id": "entry-gw",
                },
            ),
        ]
        eg_apt.rooms.append(room)
        eg.apartments.append(eg_apt)
        wing.floors.append(eg)
        building.wings.append(wing)
        areal.buildings.append(building)
        return areal, room

    def test_overflow_spans_two_middle_groups_no_invalid_sub_group(self, gewerk_catalog):
        areal, room = self._room_with_big_gateway(300)
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        assert structure.warnings == []
        all_gas = structure.all_addresses()
        assert not any(ga.sub_group > 255 for ga in all_gas)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        assignment_id = room.gewerk_assignments[0].id
        mgs_used = {mg.number for mg in hg2.middle_groups
                    for ga in mg.group_addresses if ga.assignment_id == assignment_id}
        assert len(mgs_used) == 2

        total = sum(
            1 for mg in hg2.middle_groups for ga in mg.group_addresses
            if ga.assignment_id == assignment_id
        )
        assert total == 300

        overflow_mg = next(mg for mg in hg2.middle_groups if mg.number in mgs_used
                            and mg.number != gewerk_catalog.get("MM").middle_group)
        assert "(Forts.)" in overflow_mg.name

    def test_overflow_block_stable_across_regenerate(self, gewerk_catalog):
        areal, room = self._room_with_big_gateway(300)
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure1 = gen.generate(areal)

        assignment_id = room.gewerk_assignments[0].id
        before = {
            ga.id: ga.address for ga in structure1.all_addresses()
            if ga.assignment_id == assignment_id
        }

        structure2 = gen.generate(areal, existing=structure1)
        after = {
            ga.id: ga.address for ga in structure2.all_addresses()
            if ga.assignment_id == assignment_id
        }
        assert before == after
        assert structure2.warnings == []

    def test_hg_exhaustion_records_warning_and_never_emits_invalid_ga(self, gewerk_catalog):
        """Alle 7 in der Standardkonfiguration genutzten Heimat-MGs (0-6)
        sind durch andere Gewerke belegt, der Ueberlauf-Pool hat nur MG 7
        frei -> das Gateway (600 ComObjects, passt nicht in home(256)+MG7(256))
        muss zwangsweise etwas unplatziert lassen, darf dabei aber nie eine
        ungueltige GA erzeugen."""
        areal, room = self._room_with_big_gateway(600, gewerk_code="E")  # Heimat-MG 4
        eg_apt = areal.all_floors[0].apartments[0]
        filler_room = Room(number="E02", name="Nebenraum")
        filler_room.gewerk_assignments = [
            GewerkAssignment(gewerk_code="L", count=1),   # MG 0
            GewerkAssignment(gewerk_code="F", count=1),   # MG 1
            GewerkAssignment(gewerk_code="H", count=1),   # MG 2
            GewerkAssignment(gewerk_code="A", count=1),   # MG 3
            GewerkAssignment(gewerk_code="KL", count=1),  # MG 5
            GewerkAssignment(gewerk_code="EV", count=1),  # MG 6
        ]
        eg_apt.rooms.append(filler_room)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        assert len(structure.warnings) == 1
        assert "Keine freie Mittelgruppe" in structure.warnings[0]

        all_gas = structure.all_addresses()
        assert not any(ga.sub_group > 255 for ga in all_gas)

        assignment_id = room.gewerk_assignments[0].id
        placed = sum(1 for ga in all_gas if ga.assignment_id == assignment_id)
        assert placed == 512  # 256 (Heimat-MG 4) + 256 (einzige freie MG 7)

    def test_no_overflow_no_warnings(self, eg_room_with_gewerke, gewerk_catalog):
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)
        assert structure.warnings == []


def _taster_com_objects() -> list[dict]:
    """ComObjects einer Tastereinheit mit eingebautem Temperaturfühler
    (Schalten = normale Funktion, bereits über Gewerke abgedeckt;
    Temperatur = echte Zusatzsensorik)."""
    return [
        {
            "number": 1, "name": "Schalten", "function_text": "Schalten",
            "datapoint_type": "DPST-1-1",
            "communication_flag": True, "read_flag": False,
            "write_flag": True, "transmit_flag": False, "update_flag": False,
        },
        {
            "number": 2, "name": "Temperatur", "function_text": "Temperatur",
            "datapoint_type": "DPST-9-1",
            "communication_flag": True, "read_flag": False,
            "write_flag": False, "transmit_flag": True, "update_flag": False,
        },
    ]


class TestAddressGeneratorBedienelementZusatzsensorik:
    """Tests fuer echte GAs aus Taster-Zusatzsensorik (Bedienelement.linked_product)."""

    @staticmethod
    def _room_with_bedienelemente(bedienelemente: list[Bedienelement]):
        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        eg = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2)
        eg_apt = Apartment(name="EG")
        room = Room(number="E01", name="Wohnzimmer")
        room.bedienelemente = bedienelemente
        eg_apt.rooms.append(room)
        eg.apartments.append(eg_apt)
        wing.floors.append(eg)
        building.wings.append(wing)
        areal.buildings.append(building)
        return areal, room

    def test_selected_extra_com_object_creates_ts_ga(self, gewerk_catalog):
        be = Bedienelement(
            element_type="Tastereinheit",
            linked_product={
                "manufacturer": "Test", "order_number": "TA-1",
                "product_name": "Glastaster mit Temperaturfühler",
                "com_objects": _taster_com_objects(),
                "excluded_co_numbers": [1],  # nur "Temperatur" (Nr. 2) ausgewählt
            },
        )
        areal, room = self._room_with_bedienelemente([be])

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        ts_gas = [
            ga for mg in hg2.middle_groups for ga in mg.group_addresses
            if ga.gewerk_code == "TS"
        ]
        assert len(ts_gas) == 1
        assert ts_gas[0].function_name == "Temperatur"
        assert ts_gas[0].assignment_id == f"be:{be.id}"

    def test_no_selection_creates_no_ga(self, gewerk_catalog):
        be = Bedienelement(
            element_type="Tastereinheit",
            linked_product={
                "manufacturer": "Test", "order_number": "TA-1",
                "product_name": "Glastaster",
                "com_objects": _taster_com_objects(),
                "excluded_co_numbers": [1, 2],  # nichts ausgewählt
            },
        )
        areal, _room = self._room_with_bedienelemente([be])

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        assert not any(ga.gewerk_code == "TS" for ga in structure.all_addresses())

    def test_suppressed_bedienelement_creates_no_ga(self, gewerk_catalog):
        be = Bedienelement(
            element_type="Tastereinheit",
            suppressed=True,
            linked_product={
                "manufacturer": "Test", "order_number": "TA-1",
                "product_name": "Glastaster",
                "com_objects": _taster_com_objects(),
                "excluded_co_numbers": [1],
            },
        )
        areal, _room = self._room_with_bedienelemente([be])

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        assert not any(ga.gewerk_code == "TS" for ga in structure.all_addresses())

    def test_two_bedienelemente_same_room_get_distinct_designations(self, gewerk_catalog):
        be1 = Bedienelement(
            element_type="Tastereinheit",
            linked_product={
                "manufacturer": "Test", "order_number": "TA-1",
                "product_name": "Glastaster Süd",
                "com_objects": _taster_com_objects(),
                "excluded_co_numbers": [1],
            },
        )
        be2 = Bedienelement(
            element_type="Tastereinheit",
            linked_product={
                "manufacturer": "Test", "order_number": "TA-2",
                "product_name": "Glastaster Nord",
                "com_objects": _taster_com_objects(),
                "excluded_co_numbers": [1],
            },
        )
        areal, _room = self._room_with_bedienelemente([be1, be2])

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        ts_gas = [ga for ga in structure.all_addresses() if ga.gewerk_code == "TS"]
        assert len(ts_gas) == 2
        designations = {ga.designation for ga in ts_gas}
        assert len(designations) == 2  # unterscheidbar

    def test_stable_across_regenerate(self, gewerk_catalog):
        be = Bedienelement(
            element_type="Tastereinheit",
            linked_product={
                "manufacturer": "Test", "order_number": "TA-1",
                "product_name": "Glastaster",
                "com_objects": _taster_com_objects(),
                "excluded_co_numbers": [1],
            },
        )
        areal, _room = self._room_with_bedienelemente([be])

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure1 = gen.generate(areal)
        ts_before = next(ga for ga in structure1.all_addresses() if ga.gewerk_code == "TS")

        structure2 = gen.generate(areal, existing=structure1)
        ts_after = next(ga for ga in structure2.all_addresses() if ga.gewerk_code == "TS")

        assert ts_after.id == ts_before.id
        assert ts_after.address == ts_before.address


class TestSceneAddressGeneration:
    """Szenen-GAs (MG 4 'Szenen', FA-441): eine gemeinsame Szenenaufruf-GA
    pro Geltungsbereich statt einer eigenen GA pro Szene (KNX-Konvention
    DPT 17/18: eine GA traegt bis zu 64 Szenen als 1-Byte-Wert 0-63)."""

    def _szenen_gas(self, structure):
        hg0 = structure.main_groups[0]
        mg_szenen = next(mg for mg in hg0.middle_groups if mg.number == 4)
        return mg_szenen.group_addresses

    def test_scenes_in_same_scope_share_one_ga(self, simple_efh, gewerk_catalog):
        from knix_arranger.models.scene import Scene

        scenes = [
            Scene(name="Kino", scene_number=1, scope="central"),
            Scene(name="Lesen", scene_number=2, scope="central"),
        ]
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, scenes=scenes)

        gas = self._szenen_gas(structure)
        # Feste Abwesenheits-GA + genau EINE gemeinsame Szenenaufruf-GA
        # (nicht eine pro Szene).
        assert len(gas) == 2
        assert gas[0].designation == "ZENTRAL Szene Abwesenheit"
        assert gas[1].designation == "ZENTRAL Szenenaufruf"
        assert gas[1].datapoint_type == "DPST-17-1"

    def test_shared_scene_ga_description_maps_byte_values(self, simple_efh, gewerk_catalog):
        from knix_arranger.models.scene import Scene

        scenes = [
            Scene(name="Abwesenheit", scene_number=1, scope="central"),
            Scene(name="Abwesenheit", scene_number=2, scope="central"),
            Scene(name="Dinner", scene_number=3, scope="central"),
        ]
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, scenes=scenes)

        gas = self._szenen_gas(structure)
        szenenaufruf = next(g for g in gas if g.designation == "ZENTRAL Szenenaufruf")
        assert szenenaufruf.description == "0=Abwesenheit, 1=Abwesenheit, 2=Dinner"

    def test_room_scoped_scenes_get_named_channel(self, simple_efh, gewerk_catalog):
        from knix_arranger.models.scene import Scene

        room = next(r for r in simple_efh.all_rooms if r.name == "Schlafzimmer")
        scenes = [Scene(name="Aufwachen", scene_number=1, scope="room", scope_id=room.id)]
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, scenes=scenes)

        gas = self._szenen_gas(structure)
        designations = {ga.designation for ga in gas}
        assert "Szenenaufruf Schlafzimmer" in designations

    def test_detected_scenes_are_not_regenerated(self, simple_efh, gewerk_catalog):
        from knix_arranger.models.scene import Scene

        scenes = [Scene(name="Importiert", scene_number=1, scope="central",
                         is_detected=True, source_ga_addresses=["0/4/1"])]
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, scenes=scenes)

        gas = self._szenen_gas(structure)
        # Nur die feste Abwesenheits-GA -- keine zweite GA fuer die bereits
        # importierte Szene.
        assert len(gas) == 1

    def test_duplicate_scene_number_in_same_scope_warns(self, simple_efh, gewerk_catalog):
        from knix_arranger.models.scene import Scene

        scenes = [
            Scene(name="Kino", scene_number=3, scope="central"),
            Scene(name="Lesen", scene_number=3, scope="central"),
        ]
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, scenes=scenes)

        assert any("3" in w and "ZENTRAL Szenenaufruf" in w for w in structure.warnings)


class TestManualGaLinking:
    """FA-521f: bereits importierte GAs manuell mit einer GewerkAssignment
    verknuepfen (services/gewerk_channel_matching.py + step05_gewerke.py
    ._assign_channel) statt bei der Generierung zu duplizieren."""

    def _light_gas(self, structure, hg_number: int):
        hg = next(h for h in structure.main_groups if h.number == hg_number)
        mg = next(m for m in hg.middle_groups if m.number == 0)
        return mg.group_addresses

    def test_linked_slot_is_skipped_not_duplicated(self, simple_efh, gewerk_catalog):
        from knix_arranger.models.building import GewerkAssignment
        from knix_arranger.models.group_address import (
            GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
        )

        room = next(r for r in simple_efh.all_rooms if r.name == "Schlafzimmer")
        imported_ga = GroupAddress(
            main_group=2, middle_group=0, sub_group=50,
            designation="L.E01.01_ea  ( Schlafzimmer, aus ETS )",
            datapoint_type="DPST-1-1", is_manual=True,
        )
        existing = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(imported_ga)
        hg.middle_groups.append(mg)
        existing.main_groups.append(hg)

        assignment = GewerkAssignment(
            gewerk_code="L", count=1,
            linked_ga_ids={"E/A": imported_ga.id},
        )
        room.gewerk_assignments.append(assignment)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, existing=existing)

        light_gas = self._light_gas(structure, hg_number=2)
        # Keine neue GA fuer E/A -- nur die 4 uebrigen Slots (DIM/WERT/RM/RM WERT)
        assert len(light_gas) == 4
        assert {ga.function_name for ga in light_gas} == {"DIM", "WERT", "RM", "RM WERT"}
        # Die manuell verknuepfte GA bleibt komplett unangetastet (nicht in
        # der neuen Struktur -- Erhalt ist Aufgabe des Aufrufers ueber
        # is_manual, siehe step05_gewerke._regenerate_gas/_insert_manual_ga)
        assert imported_ga.designation == "L.E01.01_ea  ( Schlafzimmer, aus ETS )"
        assert imported_ga.function_name == ""

    def test_fully_linked_assignment_generates_nothing_new(self, simple_efh, gewerk_catalog):
        from knix_arranger.models.building import GewerkAssignment
        from knix_arranger.models.group_address import (
            GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
        )

        room = next(r for r in simple_efh.all_rooms if r.name == "Schlafzimmer")
        existing = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        linked_ids = {}
        for i, fn in enumerate(["E/A", "DIM", "WERT", "RM", "RM WERT"]):
            ga = GroupAddress(main_group=2, middle_group=0, sub_group=50 + i,
                               designation=f"L.E01.01_{fn}", is_manual=True)
            mg.group_addresses.append(ga)
            linked_ids[fn] = ga.id
        hg.middle_groups.append(mg)
        existing.main_groups.append(hg)

        assignment = GewerkAssignment(gewerk_code="L", count=1, linked_ga_ids=linked_ids)
        room.gewerk_assignments.append(assignment)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, existing=existing)

        assert self._light_gas(structure, hg_number=2) == []

    def test_stale_link_falls_back_to_auto_generation_with_warning(
        self, simple_efh, gewerk_catalog,
    ):
        """Verweist linked_ga_ids auf eine nicht mehr existierende GA (vom
        Nutzer geloescht), wird der Eintrag bereinigt und der Slot normal
        generiert statt die Zuweisung stillschweigend unvollstaendig zu
        lassen."""
        from knix_arranger.models.building import GewerkAssignment
        from knix_arranger.models.group_address import GroupAddressStructure

        room = next(r for r in simple_efh.all_rooms if r.name == "Schlafzimmer")
        assignment = GewerkAssignment(
            gewerk_code="L", count=1,
            linked_ga_ids={"E/A": "geloeschte-ga-id"},
        )
        room.gewerk_assignments.append(assignment)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, existing=GroupAddressStructure())

        light_gas = self._light_gas(structure, hg_number=2)
        assert {ga.function_name for ga in light_gas} == {"E/A", "DIM", "WERT", "RM", "RM WERT"}
        assert "E/A" not in assignment.linked_ga_ids
        assert any("E/A" in w for w in structure.warnings)

    def test_multi_count_links_are_skipped_per_element(self, simple_efh, gewerk_catalog):
        """Bei count>1 hat jedes Element seine eigenen Verknuepfungen: nur
        die verknuepften Slots des jeweiligen Elements entfallen."""
        from knix_arranger.models.building import GewerkAssignment
        from knix_arranger.models.group_address import (
            GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
        )

        room = next(r for r in simple_efh.all_rooms if r.name == "Schlafzimmer")
        existing = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        ga_2_ea = GroupAddress(main_group=2, middle_group=0, sub_group=60,
                               designation="L.E01.02_ea", is_manual=True)
        ga_2_rm = GroupAddress(main_group=2, middle_group=0, sub_group=61,
                               designation="L.E01.02_rm", is_manual=True)
        mg.group_addresses.extend([ga_2_ea, ga_2_rm])
        hg.middle_groups.append(mg)
        existing.main_groups.append(hg)

        assignment = GewerkAssignment(gewerk_code="L", count=2)
        assignment.element_links(2).update({"E/A": ga_2_ea.id, "RM": ga_2_rm.id})
        room.gewerk_assignments.append(assignment)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, existing=existing)

        light_gas = self._light_gas(structure, hg_number=2)
        by_element = {}
        for ga in light_gas:
            by_element.setdefault(ga.element_number, set()).add(ga.function_name)
        assert by_element[1] == {"E/A", "DIM", "WERT", "RM", "RM WERT"}
        assert by_element[2] == {"DIM", "WERT", "RM WERT"}

    def test_links_beyond_count_are_removed(self, simple_efh, gewerk_catalog):
        from knix_arranger.models.building import GewerkAssignment
        from knix_arranger.models.group_address import GroupAddressStructure

        room = next(r for r in simple_efh.all_rooms if r.name == "Schlafzimmer")
        assignment = GewerkAssignment(gewerk_code="L", count=1)
        assignment.element_links(2)["E/A"] = "irgendeine-id"
        room.gewerk_assignments.append(assignment)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(simple_efh, existing=GroupAddressStructure())

        assert assignment.all_element_links() == {}
        assert len(self._light_gas(structure, hg_number=2)) == 5
        assert any("Element 2" in w for w in structure.warnings)


class TestAstroGasSurviveRegeneration:
    """Astro-GAs (HG0/MG7, FA-3308) werden per Zeitsteuerung angelegt und
    dürfen bei keiner Neugenerierung (Wizard Schritt 5/10, RecalcService)
    verloren gehen."""

    @staticmethod
    def _project(areal, catalog, variant="A"):
        from types import SimpleNamespace
        gen = AddressGenerator(catalog, variant=variant)
        return SimpleNamespace(
            areal=areal, scenes=[], gewerk_catalog=catalog, time_programs=[],
            config=SimpleNamespace(mg_variant=variant),
            group_addresses=gen.generate(areal),
        )

    @staticmethod
    def _astro(structure):
        return [
            ga for ga in structure.all_addresses()
            if ga.main_group == 0 and ga.middle_group == 7
        ]

    def test_regenerate_keeps_astro_gas(self, eg_room_with_gewerke, gewerk_catalog):
        from knix_arranger.services.address_generator import regenerate_addresses
        from knix_arranger.services.time_program_service import ensure_astro_gas

        project = self._project(eg_room_with_gewerke, gewerk_catalog)
        assert ensure_astro_gas(project) == 4
        project.group_addresses.find_address(0, 7, 1).designation = "Eigene Bezeichnung"
        ids_before = {ga.id for ga in self._astro(project.group_addresses)}

        result = regenerate_addresses(project)

        astro = self._astro(project.group_addresses)
        assert {ga.id for ga in astro} == ids_before
        assert project.group_addresses.find_address(0, 7, 1).designation == "Eigene Bezeichnung"
        assert not result.changed

    def test_variant_switch_keeps_astro_gas(self, eg_room_with_gewerke, gewerk_catalog):
        from knix_arranger.services.address_generator import regenerate_addresses
        from knix_arranger.services.time_program_service import ensure_astro_gas

        project = self._project(eg_room_with_gewerke, gewerk_catalog)
        ensure_astro_gas(project)
        regenerate_addresses(project, variant="B")
        assert len(self._astro(project.group_addresses)) == 4

    def test_manual_astro_ga_not_duplicated(self, eg_room_with_gewerke, gewerk_catalog):
        from knix_arranger.services.address_generator import regenerate_addresses
        from knix_arranger.services.time_program_service import ensure_astro_gas

        project = self._project(eg_room_with_gewerke, gewerk_catalog)
        ensure_astro_gas(project)
        project.group_addresses.find_address(0, 7, 2).is_manual = True
        regenerate_addresses(project)
        assert len(self._astro(project.group_addresses)) == 4

    def test_regenerate_reports_changes(self, eg_room_with_gewerke, gewerk_catalog):
        from knix_arranger.models.building import GewerkAssignment
        from knix_arranger.services.address_generator import regenerate_addresses

        project = self._project(eg_room_with_gewerke, gewerk_catalog)
        eg_room_with_gewerke.all_rooms[0].gewerk_assignments.append(
            GewerkAssignment(gewerk_code="L", count=1)
        )
        result = regenerate_addresses(project)
        assert result.changed and result.added and not result.removed
        assert result.summary().startswith("Gruppenadressen aktualisiert: +")
