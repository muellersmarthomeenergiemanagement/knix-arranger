"""Lesemodus ohne gültige Lizenz (NFA-066): ansehen ja, speichern und exportieren nein."""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from knix_arranger.ui import license_gate


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def reset_gate():
    license_gate.set_read_only(False)
    yield
    license_gate.set_read_only(False)


def _invalid():
    return SimpleNamespace(is_valid=False, message="Lizenz abgelaufen.", warning=None)


def _valid():
    return SimpleNamespace(is_valid=True, message="Gültig", warning=None)


def test_licensed_dialogs_pass_through():
    with patch.object(QFileDialog, "getSaveFileName", return_value=("C:/x.pdf", "PDF")) as dlg:
        assert license_gate.get_save_file_name(None, "Titel") == ("C:/x.pdf", "PDF")
    dlg.assert_called_once()
    assert license_gate.export_allowed(None)
    assert license_gate.save_allowed(None)


def test_read_only_blocks_export_without_file_dialog():
    license_gate.set_read_only(True)
    with patch.object(QMessageBox, "exec", return_value=0), \
         patch.object(QFileDialog, "getSaveFileName") as save_dlg, \
         patch.object(QFileDialog, "getExistingDirectory") as dir_dlg:
        assert license_gate.get_save_file_name(None, "Titel") == ("", "")
        assert license_gate.get_existing_directory(None, "Ordner") == ""
        assert not license_gate.save_allowed(None)
    save_dlg.assert_not_called()
    dir_dlg.assert_not_called()


def test_license_entered_ends_read_only():
    license_gate.set_read_only(True)

    def click_license(box):
        # Knopf "Lizenz…" ist der erste hinzugefügte
        box.clickedButton = lambda: box.buttons()[0]
        return 0

    with patch.object(QMessageBox, "exec", click_license), \
         patch("knix_arranger.ui.dialogs.license_dialog.LicenseDialog") as dialog, \
         patch("knix_arranger.services.license_service.LicenseService.check_license",
               return_value=_valid()):
        assert license_gate.export_allowed(None)
    dialog.return_value.exec.assert_called_once()
    assert not license_gate.is_read_only()


def test_listener_gets_change_and_dead_listeners_are_dropped():
    class Window:
        def __init__(self):
            self.seen = []

        def on_change(self, read_only):
            self.seen.append(read_only)

    w = Window()
    license_gate.add_listener(w.on_change)
    license_gate.set_read_only(True)
    license_gate.set_read_only(False)
    assert w.seen == [True, False]
    del w
    license_gate.set_read_only(True)  # darf nicht an toter Referenz scheitern


def test_start_without_license_is_read_only_not_exit():
    from knix_arranger import app as app_module
    fake = SimpleNamespace(license_service=MagicMock())
    fake.license_service.check_license.return_value = _invalid()
    with patch("knix_arranger.ui.dialogs.license_dialog.LicenseDialog") as dialog:
        app_module.KnixApplication._check_license(fake)  # kein SystemExit
    dialog.return_value.exec.assert_called_once()
    assert license_gate.is_read_only()
    assert "Lesemodus" in fake._pending_license_warning


def test_start_with_license_stays_writable():
    from knix_arranger import app as app_module
    fake = SimpleNamespace(license_service=MagicMock())
    fake.license_service.check_license.return_value = _valid()
    app_module.KnixApplication._check_license(fake)
    assert not license_gate.is_read_only()
    assert fake._pending_license_warning is None


def test_save_and_autosave_blocked_in_read_only():
    from knix_arranger.ui import main_window
    project = MagicMock()
    project._file_path = "C:/Projekt/Projekt.knxarr"
    fake = SimpleNamespace(_project=project, _status_bar=MagicMock())
    license_gate.set_read_only(True)
    with patch.object(license_gate, "_ask_for_license", return_value=False) as ask:
        assert main_window.MainWindow._save_project(fake) is False
        assert main_window.MainWindow._save_project_as(fake) is False
    assert ask.call_count == 2
    main_window.MainWindow._autosave(fake)
    project.save.assert_not_called()
