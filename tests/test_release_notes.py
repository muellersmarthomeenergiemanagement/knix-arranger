"""
Tests fuer die Release-Notes ("Was ist neu"): Datei-Konsistenz, Auswahl
uebersprungener Versionen, CLI fuer CI/release.py und Startlogik nach Update.
"""
from __future__ import annotations
import json
import os
import re
import sys
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger import __version__
from knix_arranger.services import release_notes_service as rns
from knix_arranger.services.release_notes_service import (
    CATEGORIES, RELEASE_NOTES_PATH, load_release_notes, notes_for, notes_since,
    parse_version,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestReleaseNotesFile:
    def _raw_versions(self):
        return json.loads(RELEASE_NOTES_PATH.read_text(encoding="utf-8"))["versions"]

    def test_current_version_has_entry(self):
        """Ohne Eintrag bricht CI das Release ab – hier schon früher auffallen."""
        assert notes_for(__version__) is not None, (
            f"release_notes.json enthält keinen Eintrag für {__version__}"
        )

    def test_entries_are_well_formed(self):
        allowed = {"version", "date"} | {key for key, _ in CATEGORIES}
        for entry in self._raw_versions():
            assert re.fullmatch(r"\d+\.\d+\.\d+", entry["version"])
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry.get("date", ""))
            assert set(entry) <= allowed, set(entry) - allowed
            assert any(entry.get(key) for key, _ in CATEGORIES), entry["version"]

    def test_newest_entry_first_and_unique(self):
        versions = [parse_version(e["version"]) for e in self._raw_versions()]
        assert versions == sorted(versions, reverse=True)
        assert len(versions) == len(set(versions))


class TestNotesSelection:
    def test_skipped_versions_are_included(self, tmp_path):
        path = tmp_path / "notes.json"
        path.write_text(json.dumps({"versions": [
            {"version": v, "date": "2026-01-01", "neu": [f"Punkt {v}"]}
            for v in ["1.2.0", "1.1.10", "1.1.9", "1.1.2"]
        ]}), encoding="utf-8")

        result = notes_since("1.1.2", "1.1.10", path)

        # numerisch, nicht alphabetisch (1.1.10 > 1.1.9)
        assert [n.version for n in result] == ["1.1.10", "1.1.9"]

    def test_markdown_and_html_contain_items(self):
        notes = load_release_notes()[0]
        first_item = next(v[0] for v in notes.items.values() if v)
        assert first_item in notes.to_markdown()
        assert notes.version in notes.to_html()


class TestCli:
    def test_missing_version_fails(self, capsys):
        assert rns.main(["99.0.0"]) == 1

    def test_writes_markdown(self, tmp_path):
        out = tmp_path / "notes.md"
        assert rns.main([f"v{__version__}", "--output", str(out)]) == 0
        assert out.read_text(encoding="utf-8").startswith("### ")


class _FakeWindow:
    """Minimaler Ersatz für MainWindow – nur die App-Settings-Methoden."""

    def __init__(self, settings: dict):
        self.settings = dict(settings)

    def _load_app_settings(self):
        return dict(self.settings)

    def _save_app_setting(self, key, value):
        self.settings[key] = value


class TestStartupDialog:
    def _run(self, settings: dict, current="1.1.16"):
        from knix_arranger.ui import main_window
        fake = _FakeWindow(settings)
        with patch.object(main_window, "__version__", current), \
             patch("knix_arranger.ui.dialogs.whats_new_dialog.WhatsNewDialog") as dlg:
            main_window.MainWindow._show_whats_new_after_update(fake)
        return fake, dlg

    def test_fresh_install_shows_nothing(self):
        fake, dlg = self._run({})
        dlg.assert_not_called()
        assert fake.settings["last_seen_version"] == "1.1.16"

    def test_update_shows_all_versions_since_last_seen(self):
        fake, dlg = self._run({"last_seen_version": "1.1.13"})
        shown = [n.version for n in dlg.call_args.args[0]]
        assert shown == ["1.1.16", "1.1.15", "1.1.14"]
        assert fake.settings["last_seen_version"] == "1.1.16"

    def test_existing_user_without_last_seen_sees_current_version(self):
        fake, dlg = self._run({"workspace_root_path": "C:/Projekte"})
        assert [n.version for n in dlg.call_args.args[0]] == ["1.1.16"]

    def test_same_version_shows_nothing(self):
        _, dlg = self._run({"last_seen_version": "1.1.16"})
        dlg.assert_not_called()


def test_whats_new_dialog_builds():
    from knix_arranger.ui.dialogs.whats_new_dialog import WhatsNewDialog
    dlg = WhatsNewDialog(load_release_notes(), "Was ist neu")
    assert dlg.windowTitle().startswith("Was ist neu")
