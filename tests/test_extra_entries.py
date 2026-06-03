"""
Tests fuer die Extra-GA-Funktionalität pro GewerkAssignment.

Prüft:
- GewerkAssignment.extra_entries: Serialisierung / Deserialisierung
- AddressGenerator: Extra-GAs werden korrekt ans Standardblock angehängt
- Blockkonsistenz: keine Lücken, keine Duplikate
- Varianten A und B
- ga_total-Berechnung (Gewerk-Ansicht)
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Areal, Building, Wing, Floor, Apartment, Room, GewerkAssignment,
)
from knix_arranger.models.gewerk import GewerkCatalog
from knix_arranger.services.address_generator import AddressGenerator


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _make_extra_entry(function: str, dpt: str, is_reserve: bool = False) -> dict:
    return {
        "offset": 0,          # wird beim Generieren überschrieben
        "function": "" if is_reserve else function,
        "designation": "" if is_reserve else function,
        "dpt": "" if is_reserve else dpt,
        "is_feedback": False,
        "is_reserve": is_reserve,
    }


def _make_areal_with_assignment(ga: GewerkAssignment, hg: int = 2) -> Areal:
    """Erstellt ein Minimal-Areal mit einem Raum und einer GewerkAssignment."""
    areal = Areal(name="Test")
    building = Building(name="Test")
    wing = Wing(name="Haupt")
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=hg)
    apt = Apartment(name="EG")
    room = Room(number="E01", name="Wohnzimmer")
    room.gewerk_assignments = [ga]
    apt.rooms.append(room)
    floor.apartments.append(apt)
    wing.floors.append(floor)
    building.wings.append(wing)
    areal.buildings.append(building)
    return areal


# ── GewerkAssignment Serialisierung ──────────────────────────────────────────

class TestGewerkAssignmentExtraEntries:
    """GewerkAssignment.extra_entries: Modell und Serialisierung."""

    def test_default_extra_entries_empty(self):
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        assert ga.extra_entries == []

    def test_extra_entries_set_and_read(self):
        entry = _make_extra_entry("SZENE", "DPST-17-1")
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = [entry]
        assert len(ga.extra_entries) == 1
        assert ga.extra_entries[0]["function"] == "SZENE"
        assert ga.extra_entries[0]["dpt"] == "DPST-17-1"

    def test_to_dict_includes_extra_entries(self):
        entry = _make_extra_entry("SZENE", "DPST-17-1")
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = [entry]
        d = ga.to_dict()
        assert "extra_entries" in d
        assert len(d["extra_entries"]) == 1
        assert d["extra_entries"][0]["function"] == "SZENE"

    def test_from_dict_restores_extra_entries(self):
        entry = _make_extra_entry("SPERREN", "DPST-1-1")
        ga = GewerkAssignment(gewerk_code="J", count=2)
        ga.extra_entries = [entry]
        d = ga.to_dict()

        restored = GewerkAssignment.from_dict(d)
        assert restored.gewerk_code == "J"
        assert restored.count == 2
        assert len(restored.extra_entries) == 1
        assert restored.extra_entries[0]["function"] == "SPERREN"
        assert restored.extra_entries[0]["dpt"] == "DPST-1-1"

    def test_from_dict_without_extra_entries_defaults_to_empty(self):
        """Rückwärtskompatibilität: altes Dict ohne extra_entries."""
        old_dict = {
            "id": "abc",
            "gewerk_code": "L",
            "count": 1,
            "datasheets": [],
            "taster_index": 1,
            "sensor_type_override": None,
        }
        ga = GewerkAssignment.from_dict(old_dict)
        assert ga.extra_entries == []

    def test_roundtrip_multiple_extras(self):
        entries = [
            _make_extra_entry("SZENE", "DPST-17-1"),
            _make_extra_entry("STATUS", "DPST-1-1"),
            _make_extra_entry("", "", is_reserve=True),
        ]
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = entries
        restored = GewerkAssignment.from_dict(ga.to_dict())
        assert len(restored.extra_entries) == 3
        assert restored.extra_entries[0]["function"] == "SZENE"
        assert restored.extra_entries[1]["function"] == "STATUS"
        assert restored.extra_entries[2]["is_reserve"] is True


# ── AddressGenerator mit extra_entries ───────────────────────────────────────

class TestAddressGeneratorWithExtraEntries:
    """AddressGenerator berücksichtigt extra_entries korrekt."""

    def test_extra_ga_appended_after_standard_block(self, gewerk_catalog):
        """Extra-GA erscheint direkt nach dem 5er-Standardblock."""
        entry = _make_extra_entry("SZENE", "DPST-17-1")
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = [entry]
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        gas = sorted(mg0.group_addresses, key=lambda g: g.sub_group)

        # Standard-Block: 5 GAs (Offsets 0–4), Extra: 1 GA (Offset 5)
        assert len(gas) == 6

        extra_ga = gas[5]
        assert extra_ga.sub_group == 5
        assert extra_ga.function_name == "SZENE"
        assert extra_ga.datapoint_type == "DPST-17-1"
        assert extra_ga.gewerk_code == "LD"
        assert extra_ga.is_placeholder is False

    def test_extra_ga_designation_correct(self, gewerk_catalog):
        """Extra-GA bekommt korrekte Bezeichnung nach KNX-Swiss-Schema."""
        entry = _make_extra_entry("SZENE", "DPST-17-1")
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = [entry]
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        extra_ga = sorted(mg0.group_addresses, key=lambda g: g.sub_group)[5]

        assert "LD_E01_01" in extra_ga.designation
        assert "SZENE" in extra_ga.designation

    def test_multiple_extra_gas(self, gewerk_catalog):
        """Zwei Extra-GAs werden korrekt mit aufsteigenden Offsets generiert."""
        entries = [
            _make_extra_entry("SZENE", "DPST-17-1"),
            _make_extra_entry("SPERREN", "DPST-1-1"),
        ]
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = entries
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        gas = sorted(mg0.group_addresses, key=lambda g: g.sub_group)

        assert len(gas) == 7  # 5 Standard + 2 Extra

        assert gas[5].function_name == "SZENE"
        assert gas[5].sub_group == 5
        assert gas[6].function_name == "SPERREN"
        assert gas[6].sub_group == 6

    def test_extra_reserve_is_placeholder(self, gewerk_catalog):
        """Extra-Eintrag als Reserve wird als Platzhalter generiert."""
        entries = [
            _make_extra_entry("SZENE", "DPST-17-1"),
            _make_extra_entry("", "", is_reserve=True),
        ]
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = entries
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        gas = sorted(mg0.group_addresses, key=lambda g: g.sub_group)

        assert gas[5].function_name == "SZENE"
        assert gas[5].is_placeholder is False
        assert gas[6].is_placeholder is True
        assert gas[6].designation == "--"

    def test_extra_ga_with_count_2(self, gewerk_catalog):
        """Bei count=2 werden Extra-GAs für jedes Element generiert."""
        entry = _make_extra_entry("SZENE", "DPST-17-1")
        ga = GewerkAssignment(gewerk_code="LD", count=2)
        ga.extra_entries = [entry]
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        gas = sorted(mg0.group_addresses, key=lambda g: g.sub_group)

        # 2 Elemente × 6 GAs = 12
        assert len(gas) == 12

        # Element 1 Extra: sub_group 5
        assert gas[5].function_name == "SZENE"
        assert gas[5].element_number == 1
        assert gas[5].sub_group == 5

        # Element 2 Extra: sub_group 11
        assert gas[11].function_name == "SZENE"
        assert gas[11].element_number == 2
        assert gas[11].sub_group == 11

    def test_extra_gas_no_impact_on_assignment_without_extras(self, gewerk_catalog):
        """Andere Zuweisungen ohne extras bleiben unverändert."""
        ga_with = GewerkAssignment(gewerk_code="LD", count=1)
        ga_with.extra_entries = [_make_extra_entry("SZENE", "DPST-17-1")]

        ga_without = GewerkAssignment(gewerk_code="L", count=1)
        # ga_without.extra_entries bleibt leer

        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        floor = Floor(name="EG", short_code="EG", main_group_number=2)
        apt = Apartment(name="EG")
        room = Room(number="E01", name="Zimmer")
        room.gewerk_assignments = [ga_with, ga_without]
        apt.rooms.append(room)
        floor.apartments.append(apt)
        wing.floors.append(floor)
        building.wings.append(wing)
        areal.buildings.append(building)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        gas = sorted(mg0.group_addresses, key=lambda g: g.sub_group)

        # LD (mit Extra): 6 GAs; L (ohne Extra): 5 GAs → gesamt 11
        assert len(gas) == 11

        # Letzter LD-Block endet bei sub_group 5, L-Block beginnt bei 6
        assert gas[5].function_name == "SZENE"    # LD extra
        assert gas[6].function_name == "E/A"      # L Block 1

    def test_extra_entries_with_jalousie_10er_block(self, gewerk_catalog):
        """Extra-GA nach 10er-Block (Jalousie) wird korrekt angehängt."""
        entry = _make_extra_entry("NOTIZ", "DPST-1-1")
        ga = GewerkAssignment(gewerk_code="J", count=1)
        ga.extra_entries = [entry]
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)
        mg1 = next(mg for mg in hg2.middle_groups if mg.number == 1)
        gas = sorted(mg1.group_addresses, key=lambda g: g.sub_group)

        # Standard Jalousie: 10 GAs; Extra: 1 → gesamt 11
        assert len(gas) == 11
        assert gas[10].function_name == "NOTIZ"
        assert gas[10].sub_group == 10


# ── Blockkonsistenz mit extra_entries ────────────────────────────────────────

class TestBlockIntegrityWithExtraEntries:
    """Keine Lücken und keine Duplikate wenn extra_entries gesetzt sind."""

    def test_no_gaps_with_extra_entries(self, gewerk_catalog):
        """Adressbloecke bleiben lueckenlos wenn extras definiert sind."""
        entries = [
            _make_extra_entry("SZENE", "DPST-17-1"),
            _make_extra_entry("SPERREN", "DPST-1-1"),
        ]
        ga = GewerkAssignment(gewerk_code="LD", count=3)
        ga.extra_entries = entries
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        for hg in structure.main_groups:
            for mg in hg.middle_groups:
                gas = sorted(mg.group_addresses, key=lambda g: g.sub_group)
                for i in range(len(gas) - 1):
                    assert gas[i + 1].sub_group == gas[i].sub_group + 1, (
                        f"Lücke in {hg.number}/{mg.number}: "
                        f"{gas[i].sub_group} → {gas[i + 1].sub_group}"
                    )

    def test_no_duplicates_with_extra_entries(self, gewerk_catalog):
        """Keine doppelten Adressen wenn extras definiert sind."""
        entries = [_make_extra_entry("SZENE", "DPST-17-1")]
        ga_ld = GewerkAssignment(gewerk_code="LD", count=2)
        ga_ld.extra_entries = entries

        ga_j = GewerkAssignment(gewerk_code="J", count=1)

        areal = Areal(name="Test")
        building = Building(name="Test")
        wing = Wing(name="Haupt")
        floor = Floor(name="EG", short_code="EG", main_group_number=2)
        apt = Apartment(name="EG")
        room = Room(number="E01", name="Zimmer")
        room.gewerk_assignments = [ga_ld, ga_j]
        apt.rooms.append(room)
        floor.apartments.append(apt)
        wing.floors.append(floor)
        building.wings.append(wing)
        areal.buildings.append(building)

        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(areal)

        all_gas = structure.all_addresses()
        addresses = [ga.address for ga in all_gas]
        assert len(addresses) == len(set(addresses)), (
            f"Doppelte Adressen: {[a for a in addresses if addresses.count(a) > 1]}"
        )

    def test_no_gaps_variante_b_with_extra_entries(self, gewerk_catalog):
        """Variante B: Keine Lücken auch mit extra_entries in Licht-Gewerk."""
        entry = _make_extra_entry("SZENE", "DPST-17-1")
        ga = GewerkAssignment(gewerk_code="LD", count=2)
        ga.extra_entries = [entry]
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="B")
        structure = gen.generate(areal)

        for hg in structure.main_groups:
            for mg in hg.middle_groups:
                gas = sorted(mg.group_addresses, key=lambda g: g.sub_group)
                for i in range(len(gas) - 1):
                    assert gas[i + 1].sub_group == gas[i].sub_group + 1, (
                        f"Lücke in Var.B {hg.number}/{mg.number}: "
                        f"{gas[i].sub_group} → {gas[i + 1].sub_group}"
                    )

    def test_extra_entries_not_applied_to_feedback_block(self, gewerk_catalog):
        """Variante B: extra_entries werden NICHT auf den Rückmeldungsblock angewendet."""
        entry = _make_extra_entry("SZENE", "DPST-17-1")
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = [entry]
        areal = _make_areal_with_assignment(ga)

        gen = AddressGenerator(gewerk_catalog, variant="B")
        structure = gen.generate(areal)

        hg2 = next(hg for hg in structure.main_groups if hg.number == 2)

        # MG 0 (forward): 5 Standard + 1 Extra = 6
        mg0 = next(mg for mg in hg2.middle_groups if mg.number == 0)
        assert len(mg0.group_addresses) == 6

        # MG 6 (feedback): unverändert 5 (kein Extra)
        mg6 = next(mg for mg in hg2.middle_groups if mg.number == 6)
        assert len(mg6.group_addresses) == 5


# ── GA-Total-Berechnung (Gewerk-Ansicht) ─────────────────────────────────────

class TestGaTotalCalculation:
    """Berechnung von GA/Element und GA Total inklusive extra_entries."""

    def test_ga_per_without_extras(self, gewerk_catalog):
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        gewerk = gewerk_catalog.get("LD")
        ga_per = gewerk.ga_count + len(ga.extra_entries)
        assert ga_per == 5   # Standard-Blockgrösse

    def test_ga_per_with_one_extra(self, gewerk_catalog):
        ga = GewerkAssignment(gewerk_code="LD", count=1)
        ga.extra_entries = [_make_extra_entry("SZENE", "DPST-17-1")]
        gewerk = gewerk_catalog.get("LD")
        ga_per = gewerk.ga_count + len(ga.extra_entries)
        assert ga_per == 6

    def test_ga_total_with_count_and_extras(self, gewerk_catalog):
        ga = GewerkAssignment(gewerk_code="LD", count=3)
        ga.extra_entries = [
            _make_extra_entry("SZENE", "DPST-17-1"),
            _make_extra_entry("SPERREN", "DPST-1-1"),
        ]
        gewerk = gewerk_catalog.get("LD")
        ga_per = gewerk.ga_count + len(ga.extra_entries)   # 5 + 2 = 7
        ga_total = ga_per * ga.count                        # 7 × 3 = 21
        assert ga_total == 21

    def test_ga_total_jalousie_with_extra(self, gewerk_catalog):
        ga = GewerkAssignment(gewerk_code="J", count=2)
        ga.extra_entries = [_make_extra_entry("NOTIZ", "DPST-1-1")]
        gewerk = gewerk_catalog.get("J")
        ga_per = gewerk.ga_count + len(ga.extra_entries)   # 10 + 1 = 11
        ga_total = ga_per * ga.count                        # 11 × 2 = 22
        assert ga_total == 22
