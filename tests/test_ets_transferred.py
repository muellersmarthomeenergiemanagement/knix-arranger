"""
Projektstatus "in ETS uebertragen": ab dann stehen die Adressen fest.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.project import KnxProject
from knix_arranger.services.renumber_service import can_renumber, mark_ets_transferred


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def test_roundtrip_and_fixed():
    project = KnxProject(name="T")
    assert not project.addresses_fixed and can_renumber(project)
    mark_ets_transferred(project, True)
    assert project.ets_transferred and project.addresses_fixed
    assert not can_renumber(project)
    assert KnxProject.from_dict(project.to_dict()).ets_transferred == project.ets_transferred
    assert project.changelog[-1].category == "Projekt"

    first = project.ets_transferred
    mark_ets_transferred(project, True)          # Datum bleibt
    assert project.ets_transferred == first and len(project.changelog) == 1
    mark_ets_transferred(project, False)
    assert project.ets_transferred == "" and can_renumber(project)
    assert "zurückgesetzt" in project.changelog[-1].message


def test_imported_is_fixed_too():
    project = KnxProject(name="T")
    project.topology.is_imported = True
    assert project.addresses_fixed and not can_renumber(project)


def test_offer_after_export():
    from knix_arranger.ui.dialogs.project_properties_dialog import offer_ets_transferred
    project = KnxProject(name="T")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        assert not offer_ets_transferred(None, project)
    assert not project.ets_transferred
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as ask:
        assert offer_ets_transferred(None, project)
        assert project.ets_transferred
        # bereits übertragen: keine Frage mehr
        assert not offer_ets_transferred(None, project)
        assert ask.call_count == 1


def test_properties_dialog_checkbox():
    from knix_arranger.ui.dialogs.project_properties_dialog import ProjectPropertiesDialog
    project = KnxProject(name="T")
    dlg = ProjectPropertiesDialog(project)
    dlg._ets_check.setChecked(True)
    dlg._apply()
    assert project.ets_transferred

    dlg = ProjectPropertiesDialog(project)
    assert "seit" in dlg._ets_check.text()
    dlg._ets_check.setChecked(False)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        dlg._apply()                              # Rückfrage verneint
    assert project.ets_transferred
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        dlg._apply()
    assert not project.ets_transferred

    imported = KnxProject(name="I")
    imported.topology.is_imported = True
    assert ProjectPropertiesDialog(imported)._ets_check is None


def test_renumber_action_explains_transferred():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from knix_arranger.ui import main_window
    project = KnxProject(name="T")
    mark_ets_transferred(project, True)
    fake = SimpleNamespace(_project=project, _bus=MagicMock(), _status_bar=MagicMock(),
                           _backup_project=MagicMock())
    with patch.object(main_window.QMessageBox, "information") as info:
        main_window.MainWindow._renumber_addresses(fake)
    assert "in die ETS übertragen" in info.call_args[0][2]
    fake._bus.begin_change.assert_not_called()
