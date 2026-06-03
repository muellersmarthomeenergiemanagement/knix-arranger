"""
Tests fuer ValidationEngine (FA-600)
Prueft GA-Strukturen auf Konformitaet.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.validation_engine import ValidationEngine, ValidationIssue
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)


class TestValidationClean:
    """Validierung einer korrekt generierten Struktur."""

    def test_generated_structure_no_errors(self, eg_room_with_gewerke, gewerk_catalog):
        """Generierte Struktur hat keine Fehler."""
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        validator = ValidationEngine(gewerk_catalog)
        issues = validator.validate(structure)

        errors = [i for i in issues if i.level == "error"]
        assert len(errors) == 0, \
            f"Unerwartete Fehler: {[e.message for e in errors]}"

    def test_generated_structure_b_no_errors(self, eg_room_with_gewerke, gewerk_catalog):
        """Generierte Variante B Struktur hat keine Fehler."""
        gen = AddressGenerator(gewerk_catalog, variant="B")
        structure = gen.generate(eg_room_with_gewerke)

        validator = ValidationEngine(gewerk_catalog)
        issues = validator.validate(structure)

        errors = [i for i in issues if i.level == "error"]
        assert len(errors) == 0, \
            f"Unerwartete Fehler: {[e.message for e in errors]}"


class TestValidationDuplicates:
    """FA-602: Duplikat-Erkennung."""

    def test_detect_duplicate_address(self):
        """Erkennt doppelte Gruppenadressen."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="Test 1", datapoint_type="DPST-1-1",
        ))
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="Test 2", datapoint_type="DPST-1-1",
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        dup_issues = [i for i in issues if i.rule_id == "FA-602"]
        assert len(dup_issues) == 1
        assert dup_issues[0].level == "error"

    def test_no_duplicate_for_unique(self):
        """Keine Duplikat-Meldung bei eindeutigen Adressen."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="Test 1", datapoint_type="DPST-1-1",
        ))
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=1,
            designation="Test 2", datapoint_type="DPST-1-1",
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        dup_issues = [i for i in issues if i.rule_id == "FA-602"]
        assert len(dup_issues) == 0


class TestValidationDPT:
    """FA-603, FA-604: DPT-Pruefung."""

    def test_missing_dpt_warning(self):
        """FA-604: Fehlender DPT = Warnung."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="LD_E01_01 E/A", function_name="E/A",
            datapoint_type="",  # Fehlend!
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        dpt_issues = [i for i in issues if i.rule_id == "FA-604"]
        assert len(dpt_issues) == 1

    def test_wrong_dpt_warning(self):
        """FA-603: Falscher DPT fuer Funktion = Warnung."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="LD_E01_01 E/A", function_name="E/A",
            datapoint_type="DPST-5-1",  # Falsch! Sollte DPST-1-1 sein
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        dpt_issues = [i for i in issues if i.rule_id == "FA-603"]
        assert len(dpt_issues) == 1

    def test_correct_dpt_no_issue(self):
        """Korrekter DPT: Kein Problem."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="LD_E01_01 E/A", function_name="E/A",
            datapoint_type="DPST-1-1",
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        dpt_issues = [i for i in issues if i.rule_id in ("FA-603", "FA-604")]
        assert len(dpt_issues) == 0


class TestValidationNaming:
    """FA-610: Bezeichnungskonformitaet."""

    def test_nonconform_naming(self):
        """Nicht-konforme Bezeichnung wird gemeldet."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="Licht Wohnzimmer An",  # Nicht KNX Swiss konform
            datapoint_type="DPST-1-1",
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        naming_issues = [i for i in issues if i.rule_id == "FA-610"]
        assert len(naming_issues) == 1
        assert naming_issues[0].level == "info"


class TestValidationBlockIntegrity:
    """FA-605: Block-Integritaet."""

    def test_gap_in_addresses(self):
        """Luecke in Adressbloecken wird erkannt."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="LD_E01_01 E/A", datapoint_type="DPST-1-1",
        ))
        # Luecke: sub_group 1 fehlt!
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=2,
            designation="LD_E01_01 WERT", datapoint_type="DPST-5-1",
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        gap_issues = [i for i in issues if i.rule_id == "FA-605"]
        assert len(gap_issues) == 1


class TestValidationVarianteB:
    """FA-608: Variante B Rueckmeldungen."""

    def test_missing_feedback_mg6(self):
        """Var. B: Licht in MG 0 ohne MG 6 = Warnung."""
        structure = GroupAddressStructure(variant="B")
        hg = MainGroup(number=2, name="EG")

        mg0 = MiddleGroup(number=0, name="Licht")
        mg0.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="LD_E01_01 E/A", datapoint_type="DPST-1-1",
        ))
        hg.middle_groups.append(mg0)
        # MG 6 fehlt!
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        fb_issues = [i for i in issues if i.rule_id == "FA-608"]
        assert len(fb_issues) >= 1

    def test_missing_feedback_mg7(self):
        """Var. B: Jalousie in MG 1 ohne MG 7 = Warnung."""
        structure = GroupAddressStructure(variant="B")
        hg = MainGroup(number=2, name="EG")

        mg1 = MiddleGroup(number=1, name="Jalousie")
        mg1.group_addresses.append(GroupAddress(
            main_group=2, middle_group=1, sub_group=0,
            designation="J_E01_01 AUF/AB", datapoint_type="DPST-1-8",
        ))
        hg.middle_groups.append(mg1)
        # MG 7 fehlt!
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        fb_issues = [i for i in issues if i.rule_id == "FA-608"]
        assert len(fb_issues) >= 1

    def test_variante_a_no_feedback_check(self):
        """Var. A: Kein Feedback-Check."""
        structure = GroupAddressStructure(variant="A")
        hg = MainGroup(number=2, name="EG")
        mg0 = MiddleGroup(number=0, name="Licht")
        mg0.group_addresses.append(GroupAddress(
            main_group=2, middle_group=0, sub_group=0,
            designation="LD_E01_01 E/A", datapoint_type="DPST-1-1",
        ))
        hg.middle_groups.append(mg0)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        fb_issues = [i for i in issues if i.rule_id == "FA-608"]
        assert len(fb_issues) == 0


class TestValidationMiddleGroup:
    """FA-607: Mittelgruppen-Zuordnung."""

    def test_wrong_middle_group(self, gewerk_catalog):
        """Gewerk in falscher MG wird erkannt."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=2, name="EG")
        mg = MiddleGroup(number=1, name="Jalousie")  # MG 1

        # LD gehoert in MG 0, nicht MG 1
        mg.group_addresses.append(GroupAddress(
            main_group=2, middle_group=1, sub_group=0,
            designation="LD_E01_01 E/A", datapoint_type="DPST-1-1",
            gewerk_code="LD",
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine(gewerk_catalog)
        issues = validator.validate(structure)

        mg_issues = [i for i in issues if i.rule_id == "FA-607"]
        assert len(mg_issues) == 1


class TestValidationGA08:
    """FA-444/GA-08: GA 0/0/0 darf nicht verwendet werden."""

    def test_address_000_is_error(self):
        """GA 0/0/0 fuehrt zu Error GA-08."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=0, name="Zentraladressen")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=0, middle_group=0, sub_group=0,
            designation="Falsche Zentraladresse",
            datapoint_type="DPST-1-1",
            central="true",
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        ga08_issues = [i for i in issues if i.rule_id == "GA-08"]
        assert len(ga08_issues) == 1
        assert ga08_issues[0].level == "error"
        assert "0/0/0" in ga08_issues[0].message

    def test_address_001_is_valid(self):
        """GA 0/0/1 ist eine gueltige Zentraladresse."""
        structure = GroupAddressStructure()
        hg = MainGroup(number=0, name="Zentraladressen")
        mg = MiddleGroup(number=0, name="Licht")
        mg.group_addresses.append(GroupAddress(
            main_group=0, middle_group=0, sub_group=1,
            designation="ZENTRAL Alle Lichter AUS",
            datapoint_type="DPST-1-1",
            central="true",
        ))
        hg.middle_groups.append(mg)
        structure.main_groups.append(hg)

        validator = ValidationEngine()
        issues = validator.validate(structure)

        ga08_issues = [i for i in issues if i.rule_id == "GA-08"]
        assert len(ga08_issues) == 0

    def test_generated_structure_has_no_address_000(self, eg_room_with_gewerke, gewerk_catalog):
        """Generierte Struktur enthaelt nie die Adresse 0/0/0 (FA-444)."""
        from knix_arranger.services.address_generator import AddressGenerator
        gen = AddressGenerator(gewerk_catalog, variant="A")
        structure = gen.generate(eg_room_with_gewerke)

        all_gas = structure.all_addresses()
        forbidden = [ga for ga in all_gas if ga.address == "0/0/0"]
        assert len(forbidden) == 0, "0/0/0 darf nicht generiert werden (FA-444)"


class TestValidationIssueModel:
    """Tests fuer ValidationIssue Datenklasse."""

    def test_to_dict(self):
        issue = ValidationIssue(
            level="error", rule_id="FA-602",
            message="Duplikat", address="2/0/0",
            suggestion="Adresse aendern"
        )
        d = issue.to_dict()
        assert d["level"] == "error"
        assert d["rule_id"] == "FA-602"
        assert d["message"] == "Duplikat"
        assert d["address"] == "2/0/0"
        assert d["suggestion"] == "Adresse aendern"
