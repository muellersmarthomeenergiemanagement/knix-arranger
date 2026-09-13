"""
Tests fuer SettingsDialog (FA-851-857, FA-1707 Aufwandsschaetzung).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.ui.dialogs.settings_dialog import SettingsDialog


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestEffortFactorsRoundTrip:
    """Aufwands-Richtwerte (FA-1707) werden korrekt geladen und gespeichert."""

    def test_populates_from_profile(self):
        profile = CompanyProfile(
            minutes_programming_per_device=30.0,
            minutes_commissioning_per_device=15.0,
            commissioning_base_hours=3.5,
            minutes_documentation_per_device=9.0,
            documentation_base_hours=1.5,
            hourly_rate_documentation=110.0,
        )
        dlg = SettingsDialog(profile=profile)
        assert dlg._minutes_programming.value() == 30.0
        assert dlg._minutes_commissioning.value() == 15.0
        assert dlg._commissioning_base.value() == 3.5
        assert dlg._minutes_documentation.value() == 9.0
        assert dlg._documentation_base.value() == 1.5
        assert dlg._rate_documentation.value() == 110.0

    def test_get_profile_returns_edited_values(self):
        dlg = SettingsDialog(profile=CompanyProfile())
        dlg._minutes_programming.setValue(25.0)
        dlg._minutes_commissioning.setValue(12.5)
        dlg._commissioning_base.setValue(1.0)
        dlg._minutes_documentation.setValue(7.0)
        dlg._documentation_base.setValue(0.5)
        dlg._rate_documentation.setValue(115.0)

        result = dlg.get_profile()
        assert result.minutes_programming_per_device == 25.0
        assert result.minutes_commissioning_per_device == 12.5
        assert result.commissioning_base_hours == 1.0
        assert result.minutes_documentation_per_device == 7.0
        assert result.documentation_base_hours == 0.5
        assert result.hourly_rate_documentation == 115.0

    def test_default_profile_uses_zveh_derived_defaults(self):
        dlg = SettingsDialog()
        assert dlg._minutes_programming.value() == 22.0
        assert dlg._minutes_commissioning.value() == 22.0
        assert dlg._commissioning_base.value() == 2.0
        assert dlg._minutes_documentation.value() == 5.0
        assert dlg._documentation_base.value() == 1.0
        assert dlg._rate_documentation.value() == 125.0
