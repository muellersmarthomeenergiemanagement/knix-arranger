"""
Tests fuer freie Raumnummern-Schemata (BZ-03, FA-610):
Pruefrahmen, Vorschlag fuer neue Raeume, Doppelt-Warnung, Validierung
gegen die Gebaeudestruktur und DALI-Erkennung.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.dali_service import _LDA_PREFIX_RE
from knix_arranger.services.room_numbering import room_number_warnings, suggest_room_number
from knix_arranger.services.validation_engine import ValidationEngine
from knix_arranger.utils.validators import (
    designation_room_number, is_valid_designation, room_number_problems,
)


def _chalet() -> tuple[Areal, Wing]:
    """Zonen-Praefix-Schema wie im Chalet Franziska (C/S/L + Stockwerk + Nr)."""
    eg = Floor(name="Erdgeschoss", short_code="EG")
    ug = Floor(name="Untergeschoss", short_code="UG")
    eg.apartments = [
        Apartment(name="Chalet Wohnung", rooms=[
            Room(number="CEG01", name="Eingang", floor_id=eg.id),
            Room(number="CEG02", name="Durchgang", floor_id=eg.id),
        ]),
        Apartment(name="Chalet Studio", rooms=[
            Room(number="SEG01", name="Eingang", floor_id=eg.id),
        ]),
        Apartment(name="Lift"),
    ]
    ug.apartments = [
        Apartment(name="Chalet Wohnung", rooms=[
            Room(number="CUG01", name="Technik", floor_id=ug.id),
        ]),
        Apartment(name="Lift", rooms=[
            Room(number="LUG01", name="Liftschacht", floor_id=ug.id),
        ]),
    ]
    wing = Wing(name="Hauptgebaeude", floors=[eg, ug])
    return Areal(buildings=[Building(name="Chalet", wings=[wing])]), wing


class TestPruefrahmen:

    @pytest.mark.parametrize("number", ["E01", "OG03", "SEG02", "S-EG02", "S.EG.02", "001"])
    def test_erlaubte_raumnummern(self, number):
        assert room_number_problems(number) == []

    @pytest.mark.parametrize("number, grund", [
        ("S_EG02", "Unterstrich"),
        ("S EG02", "Leerzeichen"),
        ("seg02", "Kleinbuchstaben"),
        ("RÄUM1", "Ä"),
        ("S/EG02", "/"),
        ("-E01", "nur zwischen"),
        ("E01.", "nur zwischen"),
    ])
    def test_ausserhalb_pruefrahmen(self, number, grund):
        problems = room_number_problems(number)
        assert problems and grund in " ".join(problems)

    @pytest.mark.parametrize("designation, room", [
        ("L_E01_01 E/A (Wohnen)", "E01"),
        ("LDA_SEG02_01 DIM", "SEG02"),
        ("J_S-EG02_03 AUF/AB", "S-EG02"),
        ("MM_S.EG.02_01 STATUS", "S.EG.02"),
    ])
    def test_bezeichnung_mit_freier_raumnummer(self, designation, room):
        assert is_valid_designation(designation)
        assert designation_room_number(designation) == room

    def test_bezeichnung_nicht_konform(self):
        assert not is_valid_designation("Licht Wohnzimmer An")
        assert designation_room_number("Licht Wohnzimmer An") == ""


class TestVorschlag:

    def test_schema_der_zone_wird_uebernommen(self):
        areal, wing = _chalet()
        eg = wing.floors[0]
        assert suggest_room_number(areal, wing, eg.apartments[0], eg) == "CEG03"
        assert suggest_room_number(areal, wing, eg.apartments[1], eg) == "SEG02"

    def test_praefix_von_anderem_stockwerk(self):
        """Lift hat nur im UG Raeume -- im EG wird trotzdem L vorgeschlagen."""
        areal, wing = _chalet()
        eg = wing.floors[0]
        assert suggest_room_number(areal, wing, eg.apartments[2], eg) == "LEG01"

    def test_neue_zone_erhaelt_freien_buchstaben(self):
        areal, wing = _chalet()
        ug = wing.floors[1]
        keller = Apartment(name="Weinkeller")
        ug.apartments.append(keller)
        assert suggest_room_number(areal, wing, keller, ug) == "WUG01"
        # "S" ist vergeben (Chalet Studio) -> naechster Buchstabe
        studio2 = Apartment(name="Sauna")
        ug.apartments.append(studio2)
        assert suggest_room_number(areal, wing, studio2, ug) == "AUG01"

    def test_trennzeichen_wird_uebernommen(self):
        eg = Floor(short_code="EG")
        apt = Apartment(name="Studio", rooms=[Room(number="S-EG01", floor_id=eg.id)])
        eg.apartments = [apt]
        wing = Wing(floors=[eg])
        areal = Areal(buildings=[Building(wings=[wing])])
        assert suggest_room_number(areal, wing, apt, eg) == "S-EG02"

    def test_klassisches_schema_ohne_praefix(self):
        eg = Floor(short_code="E")
        apt = Apartment(name="EFH", rooms=[Room(number="E01"), Room(number="E02")])
        eg.apartments = [apt]
        wing = Wing(floors=[eg])
        areal = Areal(buildings=[Building(wings=[wing])])
        assert suggest_room_number(areal, wing, apt, eg) == "E03"

    def test_leeres_projekt(self):
        eg = Floor(short_code="EG")
        apt = Apartment(name="EFH")
        eg.apartments = [apt]
        wing = Wing(floors=[eg])
        areal = Areal(buildings=[Building(wings=[wing])])
        assert suggest_room_number(areal, wing, apt, eg) == "EG01"

    def test_vorschlag_ist_im_projekt_eindeutig(self):
        areal, wing = _chalet()
        eg = wing.floors[0]
        # CEG03 schon in einer anderen Zone vergeben
        eg.apartments[2].rooms.append(Room(number="CEG03", floor_id=eg.id))
        assert suggest_room_number(areal, wing, eg.apartments[0], eg) == "CEG04"


class TestWarnungen:

    def test_doppelte_raumnummer(self):
        areal, wing = _chalet()
        room = wing.floors[0].apartments[1].rooms[0]
        room.number = "CEG01"
        warnings = room_number_warnings(areal, room)
        assert any("bereits vergeben" in w and "Eingang" in w for w in warnings)

    def test_ohne_nummer_keine_warnung(self):
        """Verteiler-Pseudoraeume haben bewusst keine Nummer (Schritt 3b)."""
        areal, wing = _chalet()
        room = Room(number="", name="Verteiler")
        wing.floors[0].apartments[0].rooms.append(room)
        assert room_number_warnings(areal, room) == []

    def test_konforme_eindeutige_nummer(self):
        areal, wing = _chalet()
        assert room_number_warnings(areal, wing.floors[0].apartments[0].rooms[0]) == []


def _project_with(designations: list[str], imported: bool = False) -> KnxProject:
    areal, _wing = _chalet()
    project = KnxProject(name="Chalet")
    project.areal = areal
    project.topology.is_imported = imported
    structure = GroupAddressStructure()
    hg = MainGroup(number=3, name="EG")
    mg = MiddleGroup(number=0, name="Licht")
    mg.group_addresses.extend(
        GroupAddress(main_group=3, middle_group=0, sub_group=n, designation=d)
        for n, d in enumerate(designations))
    hg.middle_groups.append(mg)
    structure.main_groups.append(hg)
    project.group_addresses = structure
    return project


class TestValidierung:

    def test_zonen_praefix_ist_konform(self):
        project = _project_with(["L_SEG01_01 E/A", "L_CUG01_01 E/A"])
        issues = ValidationEngine().validate(project.group_addresses, project)
        assert [i for i in issues if i.rule_id == "FA-610"] == []

    def test_unbekannter_raum_bei_geplantem_projekt(self):
        project = _project_with(["L_SEG01_01 E/A", "L_SEG21_01 E/A"])
        issues = [i for i in ValidationEngine().validate(project.group_addresses, project)
                  if i.rule_id == "FA-610"]
        assert len(issues) == 1
        assert issues[0].level == "error"
        assert issues[0].details["room"] == "SEG21"

    def test_importiertes_projekt_nur_formatpruefung(self):
        project = _project_with(["L_XEG09_01 E/A"], imported=True)
        issues = ValidationEngine().validate(project.group_addresses, project)
        assert [i for i in issues if i.rule_id == "FA-610"] == []


class TestDaliErkennung:

    @pytest.mark.parametrize("designation, room", [
        ("LDA_SEG02_01 E/A", "SEG02"),
        ("LDA_S-EG02_01 E/A", "S-EG02"),
        ("LDA_S.EG.02_01 DIM", "S.EG.02"),
    ])
    def test_raumteil(self, designation, room):
        m = _LDA_PREFIX_RE.match(designation)
        assert m and m.group(1) == room
