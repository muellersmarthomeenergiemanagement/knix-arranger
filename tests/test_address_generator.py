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
from knix_arranger.models.group_address import GroupAddressStructure
from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
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
