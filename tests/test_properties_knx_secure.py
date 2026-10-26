"""
Projekteigenschaften: KNX Secure aktivieren, Modus waehlen, Archiv oeffnen.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.knx_secure import DeviceSecureInfo
from knix_arranger.models.project import KnxProject
from knix_arranger.ui.dialogs.project_properties_dialog import (
    ProjectPropertiesDialog, knx_secure_summary,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def test_enable_and_mode_applied():
    project = KnxProject(name="T")
    dlg = ProjectPropertiesDialog(project)
    assert not dlg._secure_check.isChecked()
    assert not dlg._secure_mode_combo.isEnabled()
    dlg._secure_check.setChecked(True)
    assert dlg._secure_mode_combo.isEnabled()
    dlg._secure_mode_combo.setCurrentIndex(dlg._secure_mode_combo.findData("both"))
    dlg._apply()
    assert project.knx_secure.enabled
    assert project.knx_secure.secure_mode == "both"
    assert not dlg.open_secure_archive


def test_open_archive_button_applies_and_flags():
    project = KnxProject(name="T")
    dlg = ProjectPropertiesDialog(project)
    dlg._secure_check.setChecked(True)
    dlg._open_secure_archive()
    assert dlg.open_secure_archive
    assert project.knx_secure.enabled


def test_summary_without_secrets():
    project = KnxProject(name="T")
    cfg = project.knx_secure
    assert knx_secure_summary(cfg) == "Nicht aktiviert"
    cfg.enabled = True
    cfg.device_infos["d1"] = DeviceSecureInfo(device_id="d1", secure_supported=True,
                                              fdsk="A" * 32)
    cfg.ets_project_password = "geheim"
    text = knx_secure_summary(cfg)
    assert "1 Gerät(e) secure-fähig" in text and "1 FDSK erfasst" in text
    assert "ETS6-Passwort erfasst" in text
    assert "geheim" not in text and "A" * 32 not in text
