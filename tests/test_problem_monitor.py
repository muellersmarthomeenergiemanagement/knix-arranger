"""
Sofortmeldung neuer Probleme (FA-620a) und Warnungen der GA-Generierung in
der Validierung (FA-620).

Auslöser: Projekt_23 – Jalousie COG01 stand unbemerkt auf 19, HG 2 lief
über; die Warnung der Generierung erschien nur im Wizard-Schritt 7.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.problem_monitor import ProblemMonitor, current_problems
from knix_arranger.services.validation_engine import ValidationEngine


# Mehr Jalousie-GAs, als die freien Mittelgruppen einer HG fassen
_OVERFLOW = 250


def _project(gewerk_catalog, jalousien: int = 1) -> KnxProject:
    room = Room(number="E01", name="Halle")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="J", count=jalousien)]
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=1)
    floor.apartments = [Apartment(name="Wohnung", rooms=[room])]
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(name="Haus", wings=[Wing(name="Haus", floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    regenerate_addresses(project)
    return project


def _set_jalousien(project, count: int) -> None:
    project.all_rooms[0].gewerk_assignments[0].count = count
    regenerate_addresses(project)


def test_overflow_warning_is_validation_error(gewerk_catalog):
    project = _project(gewerk_catalog)
    _set_jalousien(project, _OVERFLOW)          # bestehender Block wächst
    assert any("Keine freie Mittelgruppe" in w for w in project.group_addresses.warnings)
    issues = [i for i in ValidationEngine().validate(project.group_addresses, project=project)
              if i.rule_id == "FA-620"]
    assert issues and all(i.level == "error" for i in issues)


def test_other_generation_warnings_are_warnings(gewerk_catalog):
    project = _project(gewerk_catalog)
    project.group_addresses.warnings = ["'Szene': Szenennummer(n) [1] sind mehrfach vergeben"]
    issues = [i for i in ValidationEngine().validate(project.group_addresses)
              if i.rule_id == "FA-620"]
    assert [i.level for i in issues] == ["warning"]


def test_monitor_reports_only_new_problems(gewerk_catalog):
    project = _project(gewerk_catalog)
    monitor = ProblemMonitor()
    monitor.adopt(project)
    assert monitor.check(project) == []          # nichts geändert

    _set_jalousien(project, _OVERFLOW)           # Überlauf entsteht
    new = monitor.check(project)
    assert new and new[0].level == "error"
    assert any(i.rule_id == "FA-620" for i in new)
    assert monitor.check(project) == []          # bekannt: keine zweite Meldung

    _set_jalousien(project, 1)                   # behoben
    assert monitor.check(project) == []
    _set_jalousien(project, _OVERFLOW)           # erneut entstanden: wieder melden
    assert monitor.check(project)


def test_monitor_adopts_other_project_silently(gewerk_catalog):
    monitor = ProblemMonitor()
    first = _project(gewerk_catalog)
    monitor.adopt(first)
    broken = _project(gewerk_catalog)
    _set_jalousien(broken, _OVERFLOW)
    assert current_problems(broken)
    assert monitor.check(broken) == []           # anderes Projekt: still übernommen
    monitor.adopt(broken)                         # Speichern desselben Projekts
    assert monitor.check(broken) == []


def test_infos_never_reported(gewerk_catalog):
    project = _project(gewerk_catalog)
    assert all(i.level in ("error", "warning") for i in current_problems(project))
    assert current_problems(None) == []


def test_shrinking_overflowed_block_keeps_its_gas(gewerk_catalog):
    """Generator: ein geänderter Block belegt seinen alten Platz nicht mehr.
    Vorher fehlten nach 250 -> 1 alle GAs des Gewerks bis zur nächsten
    Neuberechnung, die Meldungen wechselten (Projekt_23, COG01)."""
    project = _project(gewerk_catalog)
    before = sorted(g.address for g in project.group_addresses.all_addresses())
    _set_jalousien(project, _OVERFLOW)
    _set_jalousien(project, 1)
    assert project.group_addresses.warnings == []
    assert sorted(g.address for g in project.group_addresses.all_addresses()) == before


def test_summarize_groups_and_puts_cause_first():
    from knix_arranger.services.problem_monitor import summarize
    from knix_arranger.services.validation_engine import ValidationIssue
    issues = [ValidationIssue("warning", "FA-605", "Lücke")]
    issues += [ValidationIssue("error", "FA-607", "Gewerk J in falscher MG: 5", f"2/5/{n}")
               for n in range(3)]
    issues.append(ValidationIssue("error", "FA-620", "HG 2: Keine freie Mittelgruppe mehr"))
    assert summarize(issues) == [
        ("error", "HG 2: Keine freie Mittelgruppe mehr", 1),
        ("error", "Gewerk J in falscher MG: 5", 3),
        ("warning", "Lücke", 1),
    ]
