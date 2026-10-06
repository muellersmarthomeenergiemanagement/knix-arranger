"""
Fehlerbehandlung im laufenden Betrieb (NFA-041, NFA-143, NFA-146) und
Einstellungen-Dialog (NFA-114).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.utils import logging_setup


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_setup, "get_log_dir", lambda: str(tmp_path))
    return tmp_path


def _raise():
    try:
        raise ValueError("Testfehler")
    except ValueError as e:
        return e


def test_crash_report_contents(log_dir):
    logging_setup.set_last_action("Ansicht «topology»")
    path = logging_setup.create_crash_report(_raise())
    text = open(path, encoding="utf-8").read()
    for part in ("ValueError: Testfehler", "Software-Version", "Arbeitsspeicher:",
                 "Bildschirm:", "Letzte Aktion: Ansicht «topology»", "_raise"):
        assert part in text


def test_unexpected_error_shows_message_and_writes_report(log_dir):
    with patch.object(QMessageBox, "exec", return_value=0) as shown:
        path = logging_setup.handle_unexpected_error(_raise())
    assert shown.call_count == 1
    assert os.path.exists(path) and os.path.dirname(path) == str(log_dir)


def test_exception_hook_installed(log_dir, monkeypatch):
    import threading
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    logging_setup.install_exception_hook()
    err = _raise()
    with patch.object(QMessageBox, "exec", return_value=0) as shown:
        sys.excepthook(type(err), err, err.__traceback__)
    assert shown.call_count == 1
    assert list(log_dir.glob("crash_report_*.txt"))


def test_settings_dialog_update_flag():
    from knix_arranger.ui.dialogs.settings_dialog import SettingsDialog
    dlg = SettingsDialog(auto_update_check=False)
    assert dlg.auto_update_check is False
    dlg._auto_update_check.setChecked(True)
    assert dlg.auto_update_check is True
    # Keine wirkungslosen Projektstandards mehr
    assert not hasattr(dlg, "_language_combo")
    assert not hasattr(dlg, "_variant_combo")


def test_help_menu_has_log_folder():
    from knix_arranger.ui import main_window
    source = open(main_window.__file__, encoding="utf-8").read()
    assert "Logdateien öffnen" in source and "_open_log_folder" in source
