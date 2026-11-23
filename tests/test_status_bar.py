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


def test_show_message_lands_in_status_field():
    """Live-Monitor rief showMessage auf: Qt zeichnete die Meldung über die
    anderen Felder. Jetzt landet sie im Meldungsfeld."""
    bar = KnxStatusBar()
    bar.showMessage("1/1/5 gelesen – Ein", 15000)
    assert bar._status_label.text() == "1/1/5 gelesen – Ein"
    assert bar.currentMessage() == ""


def test_long_message_full_text_in_tooltip():
    bar = KnxStatusBar()
    long_text = "KNXPROJ importiert: " + "sehr lange Meldung " * 20
    bar.set_status(long_text)
    assert bar._status_label.text() == long_text
    assert bar._status_label.toolTip() == long_text


def test_separators_only_with_content():
    bar = KnxStatusBar()
    assert not bar._variant_separator.isVisibleTo(bar)
    bar.set_variant("B")
    bar.set_ga_count(12)
    assert bar._variant_separator.isVisibleTo(bar) and bar._ga_separator.isVisibleTo(bar)
