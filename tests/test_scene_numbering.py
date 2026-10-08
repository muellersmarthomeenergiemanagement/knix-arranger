"""
Szenennummern (FA-1813 bis FA-1815): Ein Aktor unterscheidet nicht, über
welche Szenen-GA eine Nummer kommt.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject, ProjectConfig
from knix_arranger.models.scene import Scene, SceneAction
from knix_arranger.services.recalc_service import RecalcService
from knix_arranger.services.scene_numbering import (
    DEFAULT_RANGES, number_conflicts, scene_level, scene_range_problem,
    scene_ranges, scenes_by_actor, suggest_scene_number,
)
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.services.validation_engine import ValidationEngine


def _project(gewerk_catalog):
    wohnen = Room(number="E01", name="Wohnen")
    wohnen.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]
    kueche = Room(number="E02", name="Küche")
    kueche.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1)]
    apt = Apartment(name="Wohnung", rooms=[wohnen, kueche])
    project = KnxProject(name="Szenen")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="EG", short_code="EG", main_group_number=1, apartments=[apt])])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    RecalcService().recalc_actors_and_addresses(project)
    return project, wohnen, kueche, apt


def _licht(project, room) -> str:
    ga = next(g for g in project.group_addresses.all_addresses()
              if g.room_id == room.id and g.gewerk_code == "L" and g.function_name == "E/A")
    return ga.designation


def _scene(name, number, scope, scope_id, *designations):
    return Scene(name=name, scene_number=number, scope=scope, scope_id=scope_id,
                 actions=[SceneAction(group_address=d, value="Ein") for d in designations])


# ── Nummernbereiche (FA-1814) ───────────────────────────────────────────────

def test_levels_and_default_ranges():
    assert scene_level("room") == "room"
    assert scene_level("zone") == scene_level("apartment") == "apartment"
    assert scene_level("central") == scene_level("") == "central"
    project = KnxProject(name="x")
    assert scene_ranges(project) == DEFAULT_RANGES


def test_suggest_uses_range_of_level():
    project = KnxProject(name="x")
    assert suggest_scene_number(project, "room", set()) == 1
    assert suggest_scene_number(project, "apartment", set()) == 21
    assert suggest_scene_number(project, "central", {41, 42}) == 43
    # Bereich voll: nächste freie überhaupt
    assert suggest_scene_number(project, "room", set(range(1, 21))) == 21
    assert suggest_scene_number(project, "room", set(range(1, 65))) is None


def test_custom_ranges_saved_and_checked():
    project = KnxProject(name="x")
    project.config.scene_number_ranges = {"central": [55, 64]}
    assert scene_ranges(project)["central"] == (55, 64)
    assert suggest_scene_number(project, "central", set()) == 55
    loaded = ProjectConfig.from_dict(project.config.to_dict())
    assert loaded.scene_number_ranges == {"central": [55, 64]}
    assert scene_range_problem({"room": (1, 20), "apartment": (15, 40)})
    assert scene_range_problem({"room": (20, 10)})
    assert scene_range_problem(DEFAULT_RANGES) == ""


# ── Konflikte (FA-1813) ─────────────────────────────────────────────────────

def test_same_number_on_different_gas_with_shared_actor(gewerk_catalog):
    project, wohnen, _kueche, _apt = _project(gewerk_catalog)
    licht = _licht(project, wohnen)
    project.scenes = [
        _scene("Abend", 1, "room", wohnen.id, licht),
        _scene("Alles aus", 1, "central", "", licht),
    ]
    conflicts = number_conflicts(project)
    assert len(conflicts) == 1 and not conflicts[0].same_channel
    assert conflicts[0].shared                     # gemeinsamer Aktor genannt
    issues = [i for i in ValidationEngine().validate(project.group_addresses, project=project)
              if i.rule_id == "FA-1813"]
    assert [i.level for i in issues] == ["warning"]
    assert "Abend" in issues[0].message and "Alles aus" in issues[0].message


def test_rooms_on_same_actor_conflict_other_actor_not(gewerk_catalog):
    """Zwei Raumszenen mit Nummer 1: hängen beide Lichter am selben
    Schaltaktor, sieht er zweimal Szene 1 (Konflikt); ohne gemeinsamen
    Aktor ist die gleiche Nummer erlaubt."""
    project, wohnen, kueche, _apt = _project(gewerk_catalog)
    project.scenes = [
        _scene("Abend Wohnen", 1, "room", wohnen.id, _licht(project, wohnen)),
        _scene("Kochen", 1, "room", kueche.id, _licht(project, kueche)),
    ]
    conflicts = number_conflicts(project)
    assert len(conflicts) == 1 and conflicts[0].shared
    project.scenes[1].actions = []                   # Küche erreicht keinen Aktor
    assert number_conflicts(project) == []


def test_different_numbers_never_conflict(gewerk_catalog):
    project, wohnen, _kueche, _apt = _project(gewerk_catalog)
    licht = _licht(project, wohnen)
    project.scenes = [
        _scene("Abend", 1, "room", wohnen.id, licht),
        _scene("Alles aus", 41, "central", "", licht),
    ]
    assert number_conflicts(project) == []


def test_same_number_on_bound_ga(gewerk_catalog):
    """An eine bestehende GA gebundene Szenen: gleiche Nummer auf derselben
    GA ist immer ein Konflikt (die Generierung prüft nur ihre eigenen)."""
    project, wohnen, _kueche, _apt = _project(gewerk_catalog)
    address = project.group_addresses.all_addresses()[0].address
    a = _scene("A", 3, "central", "")
    b = _scene("B", 3, "central", "")
    a.source_ga_addresses = b.source_ga_addresses = [address]
    project.scenes = [a, b]
    conflicts = number_conflicts(project)
    assert len(conflicts) == 1 and conflicts[0].same_channel


def test_planned_duplicates_left_to_generation(gewerk_catalog):
    project, wohnen, _kueche, _apt = _project(gewerk_catalog)
    project.scenes = [_scene("A", 2, "room", wohnen.id), _scene("B", 2, "room", wohnen.id)]
    assert number_conflicts(project) == []         # meldet FA-620


# ── Szenen je Aktor (FA-1815) ───────────────────────────────────────────────

def test_scenes_by_actor(gewerk_catalog):
    project, wohnen, _kueche, _apt = _project(gewerk_catalog)
    licht = _licht(project, wohnen)
    project.scenes = [
        _scene("Abend", 1, "room", wohnen.id, licht),
        _scene("Alles aus", 41, "central", "", licht),
        _scene("Ohne Nummer", 0, "central", "", licht),
    ]
    per_actor = scenes_by_actor(project)
    assert len(per_actor) == 1
    label, items = next(iter(per_actor.values()))
    assert "1." in label                           # Aktor mit Adresse
    assert [(a.number, a.scene.name) for a in items] == [(1, "Abend"), (41, "Alles aus")]


@pytest.mark.parametrize("scope", ["room", "apartment", "central"])
def test_scene_view_suggests_number_of_level(gewerk_catalog, scope):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.views.scene_view import SceneView
    QApplication.instance() or QApplication([])
    project, wohnen, _kueche, apt = _project(gewerk_catalog)
    view = SceneView()
    view.set_project(project)
    scope_id = {"room": wohnen.id, "apartment": apt.id, "central": ""}[scope]
    scene = view._create_scene(scope, scope_id)
    assert scene.scene_number == DEFAULT_RANGES[scope][0]


def test_existing_numbering_outside_range_is_continued():
    """Szenen-Adresse mit Nummern ausserhalb des Bereichs (Import, ältere
    Projekte): weiterführen statt in den Bereich zu springen."""
    project = KnxProject(name="x")
    assert suggest_scene_number(project, "apartment", {1}) == 2
    assert suggest_scene_number(project, "apartment", {1, 21}) == 22
    assert suggest_scene_number(project, "central", {1, 2, 3}) == 4


def test_planned_scenes_without_actions_use_actors_of_scene_ga(gewerk_catalog):
    """Projekt_23: Zentral- und Wohnungsszene je Nummer 1, ohne Aktionen.
    Die Szenen-GAs sind im Belegungsplan mit den Aktoren ihres
    Geltungsbereichs verknüpft – darüber erreichen beide dieselben Aktoren."""
    project, _wohnen, _kueche, apt = _project(gewerk_catalog)
    project.scenes = [
        _scene("Komplex belegt", 1, "central", ""),
        _scene("Chalet Anwesend", 1, "apartment", apt.id),
    ]
    RecalcService().recalc_actors_and_addresses(project)   # Szenen-GAs erzeugen
    conflicts = number_conflicts(project)
    assert len(conflicts) == 1 and conflicts[0].shared


def test_action_on_other_scene_ga_is_not_a_receiver(gewerk_catalog):
    """Eine Aktion, die eine andere Szenen-GA aufruft, sendet dort ihren
    eigenen Wert – deren Aktoren erhalten nicht diese Szenennummer."""
    from knix_arranger.services.scene_numbering import scene_receivers
    project, wohnen, _kueche, apt = _project(gewerk_catalog)
    raum = _scene("Raum", 1, "room", wohnen.id)
    project.scenes = [raum]
    RecalcService().recalc_actors_and_addresses(project)
    raum_ga = next(g for g in project.group_addresses.all_addresses()
                   if g.function_name == "SZENE" and "Wohnen" in g.designation)
    zone = _scene("Zone", 1, "apartment", apt.id)
    zone.actions = [SceneAction(group_address=raum_ga.designation, ga_address=raum_ga.address)]
    project.scenes.append(zone)
    assert scene_receivers(project, raum)              # Raum-GA erreicht Aktoren
    receivers = scene_receivers(project, zone)
    # nur die Aktoren der eigenen (noch nicht generierten) Zonen-GA, nicht die
    # über die Raum-Szenen-GA erreichbaren
    assert receivers == {}


def test_detection_skips_element_scene_inputs_in_planned_projects(gewerk_catalog):
    """Geplant: "LDA_… SZENE" der DALI-Gruppen sind Szenen-Eingänge, keine
    Szenen – "Szenen erkennen" übernimmt sie nicht (importiert schon)."""
    from knix_arranger.services.scene_detection_service import detect_scenes
    project, wohnen, _kueche, _apt = _project(gewerk_catalog)
    wohnen.gewerk_assignments.append(GewerkAssignment(gewerk_code="LDA", count=1))
    RecalcService().recalc_actors_and_addresses(project)
    element_inputs = [g for g in project.group_addresses.all_addresses()
                      if g.gewerk_code == "LDA" and g.function_name == "SZENE"]
    assert element_inputs
    for ga in element_inputs:
        ga.datapoint_type = "DPST-18-1"
    assert not any(s.source_ga_addresses[0] in {g.address for g in element_inputs}
                   for s in detect_scenes(project))
    project.topology.is_imported = True
    assert any(s.source_ga_addresses[0] in {g.address for g in element_inputs}
               for s in detect_scenes(project))
