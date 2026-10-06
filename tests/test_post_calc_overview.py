"""
Projektuebergreifende Nachkalkulation (FA-2205, FA-2206).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.models.project import KnxProject
from knix_arranger.models.quotation import CustomerQuote
from knix_arranger.models.topology import Area, Device, Line
from knix_arranger.services.post_calc_overview import (
    apply_guide_values, build_overview, find_project_files, load_results,
    project_results, suggest_guide_values,
)


def _project(name: str, date: str, devices: int = 20, prog_actual: float = 10.0,
             material_actual: float = 9000.0, status: str = "Akzeptiert") -> KnxProject:
    project = KnxProject(name=name)
    project.topology.areas = [Area(lines=[Line(devices=[
        Device(device_type="actor") for _ in range(devices)] + [
        Device(device_type="power_supply")])])]
    project.customer_quotes = [CustomerQuote(
        quote_number=f"OF-{name}", date_created=date, status=status,
        material_total=8000.0, material_markup_percent=25.0,
        labor_mounting_hours=10, labor_programming_hours=8,
        labor_commissioning_hours=6, labor_documentation_hours=2,
        hourly_rate_mounting=100, hourly_rate_programming=100,
        hourly_rate_commissioning=100, hourly_rate_documentation=100,
        actual_material_cost=material_actual, actual_mounting_hours=10,
        actual_programming_hours=prog_actual, actual_commissioning_hours=7,
        actual_documentation_hours=2,
    )]
    return project


def test_project_results_only_accepted_with_actuals():
    assert project_results(_project("A", "2026-01-10", status="Entwurf")) == []
    empty = _project("B", "2026-01-10")
    q = empty.customer_quotes[0]
    q.actual_material_cost = q.actual_mounting_hours = q.actual_programming_hours = 0
    q.actual_commissioning_hours = q.actual_documentation_hours = 0
    assert project_results(empty) == []

    (r,) = project_results(_project("C", "2026-01-10"))
    assert r.devices == 20                       # ohne Spannungsversorgung
    # Offertbetrag: 8000 * 1.25 + 26 h * 100 = 12'600
    assert r.revenue == pytest.approx(12600)
    assert r.planned_margin == pytest.approx(12600 - 8000 - 2600)
    assert r.actual_margin == pytest.approx(12600 - 9000 - 2900)
    assert r.deviation_percent("programming") == pytest.approx(25.0)
    assert r.deviation_percent("material") == pytest.approx(12.5)


def test_overview_margin_deviations_trend():
    results = [r for p in (
        _project("P1", "2026-01-10", material_actual=8000),
        _project("P2", "2026-03-10", material_actual=8000),
        _project("P3", "2026-06-10", material_actual=9500),
        _project("P4", "2026-09-10", material_actual=9500),
    ) for r in project_results(p)]
    overview = build_overview(results)
    assert overview.planned_margin_percent == pytest.approx(2000 / 12600 * 100)
    first = overview.deviations[0]
    assert first.label in ("Programmierung", "Inbetriebnahme", "Material")
    assert first.deviating >= 2
    assert "gesunken" in overview.trend


def test_trend_needs_four_projects():
    results = project_results(_project("P1", "2026-01-10"))
    assert "mindestens vier" in build_overview(results).trend


def test_guide_value_suggestion_and_apply():
    profile = CompanyProfile(minutes_programming_per_device=22,
                             minutes_commissioning_per_device=22,
                             commissioning_base_hours=2.0)
    results = [r for p in (_project("P1", "2026-01-10", prog_actual=10),
                           _project("P2", "2026-02-10", prog_actual=12))
               for r in project_results(p)]
    suggestions = {s.attr: s for s in suggest_guide_values(results, profile)}
    # Programmierung: (10 h + 12 h) / 2 * 60 / 20 Geräte = 33 Min.
    assert suggestions["minutes_programming_per_device"].suggested == 33.0
    assert suggestions["minutes_programming_per_device"].based_on == 2
    # Inbetriebnahme: (7 h - 2 h Sockel) * 60 / 20 = 15 Min.
    assert suggestions["minutes_commissioning_per_device"].suggested == 15.0
    apply_guide_values(profile, list(suggestions.values()))
    assert profile.minutes_programming_per_device == 33.0
    # nur ein Projekt: kein Vorschlag
    assert suggest_guide_values(results[:1], profile) == []


def test_find_and_load_project_files(tmp_path):
    for name, date in (("Alpha", "2026-01-10"), ("Beta", "2026-02-10")):
        folder = tmp_path / name
        folder.mkdir()
        _project(name, date).save(str(folder / f"{name}.knxarr"))
    (tmp_path / "Alpha" / "Sicherungen").mkdir()
    _project("Alt", "2025-01-01").save(str(tmp_path / "Alpha" / "Sicherungen" / "Alpha_alt.knxarr"))
    (tmp_path / "kaputt.knxarr").write_text("kein json")

    files = find_project_files(str(tmp_path), [str(tmp_path / "Beta" / "Beta.knxarr")])
    assert [os.path.basename(f) for f in files] == ["Alpha.knxarr", "Beta.knxarr", "kaputt.knxarr"]

    # Das geöffnete Projekt zählt im aktuellen Stand, nicht doppelt aus der Datei
    current = KnxProject.load(str(tmp_path / "Beta" / "Beta.knxarr"))
    current._file_path = str(tmp_path / "Beta" / "Beta.knxarr")
    current.customer_quotes[0].actual_programming_hours = 20
    results = load_results(files, current=current)
    assert [r.project for r in results] == ["Alpha", "Beta"]
    assert results[1].actual["programming"] == 20


def test_dialog(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.post_calc_overview_dialog import PostCalcOverviewDialog
    results = [r for p in (_project("P1", "2026-01-10"), _project("P2", "2026-02-10"))
               for r in project_results(p)]
    saved = []
    profile = CompanyProfile()
    dlg = PostCalcOverviewDialog(results, profile, saved.append)
    from unittest.mock import patch
    from PySide6.QtWidgets import QMessageBox
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        dlg._apply()
    assert saved == [profile]
    assert profile.minutes_programming_per_device == 30.0
    # ohne Ergebnisse: nur Hinweis
    PostCalcOverviewDialog([], CompanyProfile(), saved.append)
