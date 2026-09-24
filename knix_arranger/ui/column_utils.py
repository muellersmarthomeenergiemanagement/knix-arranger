"""
Spaltenbreiten-Hilfsfunktionen für QTableWidget und QTreeWidget.

Kernfunktion fit_columns():
  1. Passt jede Spalte an ihren Inhalt an (resizeColumnToContents).
  2. Standardmäßig (stretch_to_fit=True): wenn alle Spalten zusammen breiter
     als der Viewport wären, werden sie proportional gestaucht – so bleiben
     alle Spalten ohne Scrollen sichtbar, aber ggf. schmaler als ihr Inhalt.
     Mit stretch_to_fit=False bleibt jede Spalte bei ihrer inhaltsbasierten
     Breite; die Ansicht scrollt stattdessen horizontal, wenn nötig (siehe
     Verknüpfungsmatrix-Fix -- bei vielen/breiten Spalten schrumpft sonst
     jede auf eine kaum noch lesbare Breite).
"""
from __future__ import annotations


def fit_columns(widget, min_col_width: int = 50, stretch_to_fit: bool = True) -> None:
    """
    Passt Spaltenbreiten an den Inhalt an.

    Funktioniert mit QTableWidget und QTreeWidget.

    Args:
        widget:         Das Table- oder Tree-Widget.
        min_col_width:  Mindestbreite einer Spalte in Pixeln (Standardwert 50,
                         nur relevant wenn stretch_to_fit=True).
        stretch_to_fit: True (Standard) staucht alle Spalten bei Bedarf
                         proportional, damit sie ohne Scrollen in den Viewport
                         passen. False belässt jede Spalte bei ihrer
                         inhaltsbasierten Breite -- die Ansicht scrollt dann
                         bei Bedarf horizontal statt Spalten zu schrumpfen.
    """
    n = widget.columnCount()
    if n == 0:
        return

    # Schritt 1: Jede Spalte auf Inhaltsbreite setzen
    for i in range(n):
        widget.resizeColumnToContents(i)

    if not stretch_to_fit:
        return

    # Schritt 2: Prüfen ob alle Spalten in den Viewport passen
    vp_width = widget.viewport().width()
    if vp_width <= 0:
        return  # Widget noch nicht dargestellt – nichts tun

    total = sum(widget.columnWidth(i) for i in range(n))
    if total <= vp_width:
        return  # Alles passt → fertig

    # Schritt 3: Proportional skalieren, Minimum einhalten. Das Minimum ist
    # mindestens die Breite der Spaltenüberschrift -- sonst werden Köpfe wie
    # "Hersteller" oder "Total (CHF)" abgeschnitten. Passt es dann nicht mehr,
    # scrollt die Tabelle horizontal.
    header = widget.header() if hasattr(widget, "header") else widget.horizontalHeader()
    scale = vp_width / total
    for i in range(n):
        min_w = max(min_col_width, header.sectionSizeHint(i))
        new_w = max(min_w, int(widget.columnWidth(i) * scale))
        widget.setColumnWidth(i, new_w)
