"""
Spaltenbreiten-Hilfsfunktionen für QTableWidget und QTreeWidget.

Kernfunktion fit_columns():
  1. Passt jede Spalte an ihren Inhalt an (resizeColumnToContents).
  2. Wenn alle Spalten zusammen breiter als der Viewport wären, werden sie
     proportional gestaucht – so bleiben alle Spalten ohne Scrollen sichtbar.
"""
from __future__ import annotations


def fit_columns(widget, min_col_width: int = 50) -> None:
    """
    Passt Spaltenbreiten an den Inhalt an; alle Spalten bleiben sichtbar.

    Funktioniert mit QTableWidget und QTreeWidget.

    Args:
        widget:        Das Table- oder Tree-Widget.
        min_col_width: Mindestbreite einer Spalte in Pixeln (Standardwert 50).
    """
    n = widget.columnCount()
    if n == 0:
        return

    # Schritt 1: Jede Spalte auf Inhaltsbreite setzen
    for i in range(n):
        widget.resizeColumnToContents(i)

    # Schritt 2: Prüfen ob alle Spalten in den Viewport passen
    vp_width = widget.viewport().width()
    if vp_width <= 0:
        return  # Widget noch nicht dargestellt – nichts tun

    total = sum(widget.columnWidth(i) for i in range(n))
    if total <= vp_width:
        return  # Alles passt → fertig

    # Schritt 3: Proportional skalieren, Minimum einhalten
    scale = vp_width / total
    for i in range(n):
        new_w = max(min_col_width, int(widget.columnWidth(i) * scale))
        widget.setColumnWidth(i, new_w)
