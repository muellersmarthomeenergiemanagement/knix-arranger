"""
Tests fuer das checkpoint-basierte Aenderungsprotokoll (ChangelogEntry, KnxProject.changelog).
"""
from __future__ import annotations
from knix_arranger.models.project import KnxProject, ChangelogEntry


def test_add_changelog_entry_appends():
    project = KnxProject(name="Test")
    assert project.changelog == []
    project.add_changelog_entry("Notiz", "Erste Notiz")
    project.add_changelog_entry("Import", "ETS-Projekt importiert")
    assert len(project.changelog) == 2
    assert project.changelog[0].category == "Notiz"
    assert project.changelog[0].message == "Erste Notiz"
    assert project.changelog[1].category == "Import"


def test_changelog_entry_has_timestamp():
    entry = ChangelogEntry(category="Notiz", message="x")
    assert entry.timestamp  # nicht leer


def test_changelog_roundtrip_to_dict_from_dict():
    project = KnxProject(name="Test")
    project.add_changelog_entry("Re-Import", "3 Geräte / 2 Räume wiedererkannt")

    data = project.to_dict()
    restored = KnxProject.from_dict(data)

    assert len(restored.changelog) == 1
    assert restored.changelog[0].category == "Re-Import"
    assert restored.changelog[0].message == "3 Geräte / 2 Räume wiedererkannt"
    assert restored.changelog[0].timestamp == project.changelog[0].timestamp


def test_changelog_entry_dict_roundtrip():
    entry = ChangelogEntry(timestamp="2026-01-01 10:00", category="Revision", message="Revisionspaket erstellt")
    data = entry.to_dict()
    restored = ChangelogEntry.from_dict(data)
    assert restored.timestamp == entry.timestamp
    assert restored.category == entry.category
    assert restored.message == entry.message
