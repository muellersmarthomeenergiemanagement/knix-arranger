"""
Tests fuer fit_columns() (column_utils.py).

Regression: fit_columns() staucht Spalten standardmaessig proportional, damit
alles ohne Scrollen in den Viewport passt -- bei vielen/breiten Spalten (z.B.
Verknuepfungsmatrix, Topologie-/Gruppenadressen-Tabellen) werden Spalten dabei
unlesbar schmal. stretch_to_fit=False muss die inhaltsbasierte Breite jeder
Spalte erhalten und stattdessen horizontales Scrollen zulassen.
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from knix_arranger.ui.column_utils import fit_columns


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _wide_table(n_cols: int = 5, text_len: int = 60) -> QTableWidget:
    table = QTableWidget(1, n_cols)
    for c in range(n_cols):
        table.setItem(0, c, QTableWidgetItem("X" * text_len))
    table.resize(200, 200)  # schmaler Viewport, erzwingt die Stauchung
    table.show()
    return table


def test_stretch_to_fit_default_shrinks_columns_below_content_width():
    table = _wide_table()
    for c in range(table.columnCount()):
        table.resizeColumnToContents(c)
    content_widths = [table.columnWidth(c) for c in range(table.columnCount())]

    fit_columns(table)  # stretch_to_fit=True (Standard)

    shrunk_widths = [table.columnWidth(c) for c in range(table.columnCount())]
    assert sum(shrunk_widths) <= sum(content_widths)
    assert any(s < c for s, c in zip(shrunk_widths, content_widths))


def test_stretch_to_fit_false_keeps_content_based_width():
    table = _wide_table()
    for c in range(table.columnCount()):
        table.resizeColumnToContents(c)
    content_widths = [table.columnWidth(c) for c in range(table.columnCount())]

    fit_columns(table, stretch_to_fit=False)

    kept_widths = [table.columnWidth(c) for c in range(table.columnCount())]
    assert kept_widths == content_widths


def test_stretch_to_fit_false_still_sizes_narrow_columns_to_content():
    """Ohne Stauchung muss fit_columns() trotzdem noch jede Spalte initial an
    ihren Inhalt anpassen (Schritt 1 bleibt aktiv) -- nur der Stauchungs-
    Schritt entfaellt."""
    table = QTableWidget(1, 2)
    table.setItem(0, 0, QTableWidgetItem("kurz"))
    table.setItem(0, 1, QTableWidgetItem("ein deutlich laengerer Zellinhalt"))
    table.resize(800, 200)

    fit_columns(table, stretch_to_fit=False)

    assert table.columnWidth(1) > table.columnWidth(0)
