"""
Statusleiste (NFA-023): Meldungen nur im festen Feld rechts.

Regression: set_status() zeigte die Meldung zusätzlich als temporäre
Qt-Meldung, die über "Projekt: …" links gezeichnet wurde – die Texte lagen
drei Sekunden übereinander.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.ui.widgets.status_bar import KnxStatusBar


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def test_status_only_in_permanent_label():
    bar = KnxStatusBar()
    bar.set_project_name("Chalet")
    bar.set_status("Projekt 'Chalet' geladen.")
    assert bar._status_label.text() == "Projekt 'Chalet' geladen."
    assert bar.currentMessage() == ""
    assert bar._project_label.text() == "Projekt: Chalet"
