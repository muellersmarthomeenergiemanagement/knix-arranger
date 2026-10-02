"""
Tests fuer Rueckmeldungen in Variante B (FA-608, GA-07): Rueckmeldungen
eingebetteter 10er-Bloecke (LDA, Farblicht) liegen in MG 6/7, jeweils
unter der Untergruppe ihres Befehls in MG 0/1.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.address_block import (
    create_dali_block_schema, create_lc_block_schema, create_light_block_schema_a,
    create_light_feedback_block_b, feedback_command, split_feedback_variant_b,
)
from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.gewerk import GewerkCatalog
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.services.validation_engine import ValidationEngine


@pytest.fixture(scope="module")
def catalog():
    c = GewerkCatalog()
    c.load_defaults()
    return c


def _areal(*assignments: tuple[str, int]) -> Areal:
    room = Room(number="SEG02", name="Wohnraum")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code=c, count=n) for c, n in assignments]
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=3,
                  apartments=[Apartment(name="Studio", rooms=[room])])
    return Areal(buildings=[Building(wings=[Wing(floors=[floor])])])


def _gas(structure: GroupAddressStructure) -> dict[str, GroupAddress]:
    return {ga.address: ga for ga in structure.all_addresses()}


class TestSplit:

    @pytest.mark.parametrize("feedback, commands, expected", [
        ("RM", ["E/A", "DIM"], "E/A"),
        ("RM WERT", ["E/A", "WERT"], "WERT"),
        ("RM WERT", ["E/A", "HELLIGKEIT"], "HELLIGKEIT"),
        ("RM CCT", ["FARBTEMPERATUR"], "FARBTEMPERATUR"),
        ("RM FARBE", ["FARBE RGBW"], "FARBE RGBW"),
        ("STATUS POSITION HOEHE", ["POSITION HOEHE"], "POSITION HOEHE"),
        ("SZENE", ["E/A"], None),
    ])
    def test_feedback_command(self, feedback, commands, expected):
        assert feedback_command(feedback, commands) == expected

    def test_dali(self):
        forward, fb = split_feedback_variant_b(create_dali_block_schema(), 6)
        assert [e.function for e in forward.entries][:5] == ["E/A", "DIM", "WERT", "", ""]
        assert forward.block_size == fb.block_size == 10
        assert fb.middle_group == 6
        assert {e.offset: e.function for e in fb.entries if e.function} == {0: "RM", 2: "RM WERT"}

    def test_farblicht(self):
        _forward, fb = split_feedback_variant_b(create_lc_block_schema(), 6)
        assert {e.offset: e.function for e in fb.entries if e.function} == {
            0: "RM", 2: "RM FARBE", 3: "RM WERT"}

    def test_entspricht_handgepflegtem_licht_block(self):
        _forward, fb = split_feedback_variant_b(create_light_block_schema_a(), 6)
        expected = create_light_feedback_block_b()
        assert [(e.offset, e.function) for e in fb.entries] == \
            [(e.offset, e.function) for e in expected.entries]


class TestGenerator:

    def test_lda_variante_b(self, catalog):
        structure = AddressGenerator(catalog, variant="B").generate(
            _areal(("L", 1), ("LDA", 2), ("S", 1)))
        gas = _gas(structure)
        mg0 = [g for g in gas.values() if g.main_group == 3 and g.middle_group == 0]
        assert not any(g.function_name.startswith("RM") for g in mg0)
        for ga in gas.values():
            if ga.main_group == 3 and ga.middle_group == 6 and not ga.is_placeholder:
                cmd = gas[f"3/0/{ga.sub_group}"]
                assert (cmd.gewerk_code, cmd.element_number) == (ga.gewerk_code, ga.element_number)
        lda2 = next(g for g in mg0 if g.gewerk_code == "LDA" and g.element_number == 2
                    and g.function_name == "E/A")
        assert gas[f"3/6/{lda2.sub_group}"].function_name == "RM"
        assert gas[f"3/6/{lda2.sub_group + 2}"].function_name == "RM WERT"

    def test_lda_variante_a_unveraendert(self, catalog):
        structure = AddressGenerator(catalog, variant="A").generate(_areal(("LDA", 1)))
        functions = [g.function_name for g in structure.all_addresses()
                     if g.gewerk_code == "LDA"]
        assert "RM" in functions and "RM WERT" in functions
        assert not any(g.middle_group == 6 for g in structure.all_addresses()
                       if g.main_group == 3)

    def test_farblicht_variante_b(self, catalog):
        structure = AddressGenerator(catalog, variant="B").generate(_areal(("LC", 1)))
        gas = _gas(structure)
        fb = {g.function_name: g.sub_group for g in gas.values()
              if g.main_group == 3 and g.middle_group == 6 and not g.is_placeholder}
        cmd = {g.function_name: g.sub_group for g in gas.values()
               if g.main_group == 3 and g.middle_group == 0 and not g.is_placeholder}
        assert fb["RM"] == cmd["E/A"]
        assert fb["RM FARBE"] == cmd["FARBE RGB"]
        assert fb["RM WERT"] == cmd["HELLIGKEIT"]

    def test_versetzte_rueckmeldungen_werden_ausgerichtet(self, catalog):
        gen = AddressGenerator(catalog, variant="B")
        areal = _areal(("L", 2))
        first = gen.generate(areal)
        # Rueckmeldungen um einen Block versetzen (Stand vor der Korrektur)
        for ga in first.all_addresses():
            if ga.main_group == 3 and ga.middle_group == 6:
                ga.sub_group += 5
        second = gen.generate(areal, existing=first)
        gas = _gas(second)
        for ga in gas.values():
            if ga.main_group == 3 and ga.middle_group == 6 and not ga.is_placeholder:
                assert gas[f"3/0/{ga.sub_group}"].element_number == ga.element_number

    def test_ausgerichtete_rueckmeldungen_behalten_id(self, catalog):
        gen = AddressGenerator(catalog, variant="B")
        areal = _areal(("LDA", 1))
        first = gen.generate(areal)
        ids = {ga.address: ga.id for ga in first.all_addresses() if ga.main_group == 3}
        second = gen.generate(areal, existing=first)
        assert {ga.address: ga.id for ga in second.all_addresses()
                if ga.main_group == 3} == ids


class TestValidierung:

    def _structure(self, mg0: list[GroupAddress], mg6: list[GroupAddress]):
        structure = GroupAddressStructure(variant="B")
        hg = MainGroup(number=3, name="EG")
        hg.middle_groups = [MiddleGroup(number=0, name="Licht", group_addresses=mg0),
                            MiddleGroup(number=6, name="RM", group_addresses=mg6)]
        structure.main_groups.append(hg)
        return structure

    def _ga(self, mg, sub, function, element=1):
        return GroupAddress(main_group=3, middle_group=mg, sub_group=sub,
                            designation=f"LDA_SEG02_{element:02d} {function}",
                            gewerk_code="LDA", room_number="SEG02",
                            element_number=element, function_name=function)

    def _fa608(self, structure):
        return [i for i in ValidationEngine().validate(structure) if i.rule_id == "FA-608"]

    def test_rueckmeldung_in_mg0(self):
        issues = self._fa608(self._structure(
            [self._ga(0, 10, "E/A"), self._ga(0, 13, "RM")],
            [self._ga(6, 10, "RM")]))
        assert [i.address for i in issues] == ["3/0/13"]

    def test_versetzte_rueckmeldung(self):
        issues = self._fa608(self._structure(
            [self._ga(0, 10, "E/A"), self._ga(0, 20, "E/A", element=2)],
            [self._ga(6, 10, "RM"), self._ga(6, 15, "RM", element=2)]))
        assert [i.address for i in issues] == ["3/6/15"]

    def test_rueckmeldung_unter_fremdem_befehl(self):
        issues = self._fa608(self._structure(
            [self._ga(0, 10, "E/A"), self._ga(0, 20, "E/A", element=2)],
            [self._ga(6, 10, "RM", element=2)]))
        assert [i.address for i in issues] == ["3/6/10"]

    def test_korrekt_ausgerichtet(self):
        assert self._fa608(self._structure(
            [self._ga(0, 10, "E/A"), self._ga(0, 12, "WERT")],
            [self._ga(6, 10, "RM"), self._ga(6, 12, "RM WERT")])) == []
