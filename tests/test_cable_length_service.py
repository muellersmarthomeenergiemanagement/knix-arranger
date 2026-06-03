"""
Tests fuer CableLengthService (FA-2602).
"""
from __future__ import annotations
import pytest
from dataclasses import dataclass, field
from knix_arranger.services.cable_length_service import CableLengthService


# ── Minimale Stub-Klassen ──────────────────────────────────────────────

@dataclass
class _Line:
    id: str = "line-1"
    line_number: int = 1
    name: str = "Testlinie"
    topology_form: str = "Linie"
    trunk_length: float = 0.0
    branch_lengths: list[float] = field(default_factory=list)


@dataclass
class _Area:
    area_number: int = 1
    name: str = "Bereich 1"
    lines: list = field(default_factory=list)


@dataclass
class _Topology:
    areas: list = field(default_factory=list)


@dataclass
class _Project:
    topology: _Topology = field(default_factory=_Topology)


# ── Tests ──────────────────────────────────────────────────────────────

svc = CableLengthService()


def test_empty_line_is_ok():
    line = _Line(trunk_length=0.0, branch_lengths=[])
    result = svc.validate_line(line)
    assert result.status == "OK"
    assert result.total_length == 0.0


def test_normal_values_ok():
    line = _Line(trunk_length=200.0, branch_lengths=[5.0, 3.0])
    result = svc.validate_line(line)
    assert result.status == "OK"
    assert result.total_length == pytest.approx(208.0)
    assert result.max_branch == pytest.approx(5.0)
    assert result.branch_count == 2


def test_trunk_warning():
    line = _Line(trunk_length=600.0)
    result = svc.validate_line(line)
    assert result.status == "Warnung"
    assert any("Stammleitung" in m for m in result.messages)


def test_trunk_error():
    line = _Line(trunk_length=750.0)
    result = svc.validate_line(line)
    assert result.status == "Fehler"


def test_total_warning():
    # trunk 401 m + 80 Stichleitungen a 5 m = 801 m > 800 (Warnung)
    # kein trunk-Fehler (401 < 700), kein Stich-Fehler (5 < 10)
    line = _Line(trunk_length=401.0, branch_lengths=[5.0] * 80)
    result = svc.validate_line(line)
    assert result.total_length == pytest.approx(801.0)
    assert result.status == "Warnung"


def test_total_error():
    line = _Line(trunk_length=600.0, branch_lengths=[250.0, 200.0])
    result = svc.validate_line(line)
    assert result.total_length == pytest.approx(1050.0)
    assert result.status == "Fehler"


def test_branch_warning():
    line = _Line(trunk_length=0.0, branch_lengths=[9.0])
    result = svc.validate_line(line)
    assert result.status == "Warnung"
    assert any("Stichleitung 1" in m for m in result.messages)


def test_branch_error():
    line = _Line(trunk_length=0.0, branch_lengths=[5.0, 11.0])
    result = svc.validate_line(line)
    assert result.status == "Fehler"


def test_validate_project():
    project = _Project(
        topology=_Topology(areas=[
            _Area(lines=[
                _Line(id="l1", trunk_length=100.0),
                _Line(id="l2", trunk_length=800.0),  # > 700 → Fehler
            ])
        ])
    )
    results = svc.validate_project(project)
    assert len(results) == 2
    assert results[0].status == "OK"
    assert results[1].status == "Fehler"


def test_highest_severity_wins():
    """Wenn Stamm Warnung und Gesamtlaenge Fehler → Status Fehler."""
    line = _Line(trunk_length=580.0, branch_lengths=[150.0, 300.0])
    result = svc.validate_line(line)
    assert result.status == "Fehler"
