"""Arbeitsablauf auf der Übersicht (workflow_status): acht Schritte mit Stand,
der erste offene ist der nächste Schritt."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.models.project import KnxProject
from knix_arranger.services.problem_monitor import ProblemMonitor
from knix_arranger.services.workflow_status import (
    DONE, NOT_NEEDED, OPEN, PARTIAL, next_step, workflow_steps,
)
from tests.test_actor_channels import _actor, project  # noqa: F401 (Fixture)


def test_leeres_projekt_beginnt_mit_dem_wizard():
    steps = workflow_steps(KnxProject(name="leer"))
    assert [s.number for s in steps] == list(range(1, 9))
    assert next_step(steps).nav_key == "wizard"
    assert steps[4].state == NOT_NEEDED                    # kein DALI-Gateway
    assert steps[5].detail == "noch nicht geprüft"


def test_nach_dem_wizard_folgt_die_beratung(project):  # noqa: F811
    steps = workflow_steps(project, errors=0, warnings=2)
    by_key = {s.nav_key: s for s in steps}
    assert by_key["wizard"].state == DONE
    assert next_step(steps).nav_key == "bauherr_form"
    assert by_key["validation"].state == PARTIAL and "2 Warnungen" in by_key["validation"].detail
    assert by_key["export"].state == OPEN
    # Eigenes Wort je Schritt statt «erledigt»
    assert by_key["wizard"].label == "vorhanden"
    assert by_key["validation"].label == ""             # Zahlen genügen
    assert by_key["export"].label == "offen"
    # Produkt nur am Aktor (Testvorlage): Materialliste begonnen
    assert _actor(project).order_number == "SA/S4.16"
    material = by_key["material_list"]
    assert material.state == PARTIAL and material.detail.startswith("1 von")
    project.ets_transferred = "2026-10-18"
    assert {s.nav_key: s for s in workflow_steps(project)}["export"].state == DONE


def test_problem_monitor_liefert_zahlen(project):  # noqa: F811
    monitor = ProblemMonitor()
    assert monitor.counts() is None
    monitor.reset(project)
    errors, warnings = monitor.counts()
    assert errors >= 0 and warnings >= 0


def test_uebersicht_zeigt_ablauf_und_navigiert(project):  # noqa: F811
    from PySide6.QtWidgets import QApplication, QPushButton
    from knix_arranger.ui.views.project_overview import ProjectOverview
    QApplication.instance() or QApplication([])
    view = ProjectOverview()
    view.update_from_project(project)
    view.set_problem_counts((0, 0))
    assert view._workflow_group.isVisibleTo(view)
    assert view._card_issues._value.text() == "0"
    keys = []
    view.navigate_requested.connect(keys.append)
    buttons = view._workflow_group.findChildren(QPushButton)
    assert len(buttons) == 8
    buttons[1].click()
    assert keys == ["bauherr_form"]
    # Importierte Projekte: kein Planungsablauf
    project.topology.is_imported = True
    view.update_from_project(project)
    assert not view._workflow_group.isVisibleTo(view)
