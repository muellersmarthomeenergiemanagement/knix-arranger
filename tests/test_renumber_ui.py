"""
Oberflaechen-Pfade von "Adressen neu ordnen" (Hauptfenster) und der
Vollstaendigkeits-Rueckfrage vor dem Revisionspaket (Berichte-Dialog).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.project import KnxProject
from knix_arranger.ui import main_window
from knix_arranger.ui.dialogs.reports_dialog import ReportsDialog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_renumber_service import _project, _grow_wohnen, _by_designation  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _fake_window(project):
    return SimpleNamespace(
        _project=project, _bus=MagicMock(), _status_bar=MagicMock(),
        _backup_project=MagicMock(return_value=""))


def _dialog_returning(accepted: bool):
    """Ersatz für den Vorschau-Dialog (das Ersatz-Fenster ist kein QWidget)."""
    dialog_cls = MagicMock()
    dialog_cls.Accepted = 1
    dialog_cls.return_value.exec.return_value = 1 if accepted else 0
    return dialog_cls


class TestRenumberAction:
    def test_imported_project_only_informs(self):
        project = _project()
        project.topology.is_imported = True
        fake = _fake_window(project)
        with patch.object(main_window.QMessageBox, "information") as info:
            main_window.MainWindow._renumber_addresses(fake)
        info.assert_called_once()
        fake._bus.begin_change.assert_not_called()

    def test_accepted_preview_renumbers_with_backup_and_undo(self):
        project = _project()
        _grow_wohnen(project)
        fake = _fake_window(project)
        with patch("knix_arranger.ui.dialogs.renumber_dialog.RenumberDialog",
                   _dialog_returning(True)):
            main_window.MainWindow._renumber_addresses(fake)
        fake._backup_project.assert_called_once()
        fake._bus.begin_change.assert_called_once()
        fake._bus.emit_addresses_changed.assert_called_once()
        assert _by_designation(project, "LD_E01_01 E/A (Wohnen)").address == "2/0/0"

    def test_cancelled_preview_changes_nothing(self):
        project = _project()
        _grow_wohnen(project)
        fake = _fake_window(project)
        with patch("knix_arranger.ui.dialogs.renumber_dialog.RenumberDialog",
                   _dialog_returning(False)):
            main_window.MainWindow._renumber_addresses(fake)
        fake._bus.begin_change.assert_not_called()
        assert _by_designation(project, "LD_E01_01 E/A (Wohnen)").address == "2/0/10"


class TestRevisionConfirm:
    def test_open_points_are_shown_and_cancel_stops(self):
        dlg = ReportsDialog(KnxProject(name="Leer"))
        shown = {}

        def fake_exec(box):
            shown["text"] = box.informativeText()
            return 0
        with patch.object(QMessageBox, "exec", fake_exec), \
             patch.object(QMessageBox, "clickedButton", return_value=None):
            assert dlg._confirm_revision_completeness() is False
        assert "• Abnahmeprotokoll: Abnahmeprotokoll fehlt noch" in shown["text"]
        assert "\n" in shown["text"]
