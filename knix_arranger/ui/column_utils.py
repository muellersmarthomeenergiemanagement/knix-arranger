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


def fit_columns(widget, min_col_width: int = 50, stretch_to_fit: bool = True,
                flex: int | None = None) -> None:
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
    if flex is not None and 0 <= flex < n:
        # Eine Spalte (langer Freitext, z.B. «Details») nimmt den Rest der
        # Breite: sie füllt den freien Platz bzw. gibt bei Platzmangel als
        # einzige nach -- Namen und Adressen bleiben ganz lesbar.
        header = widget.header() if hasattr(widget, "header") else widget.horizontalHeader()
        others = total - widget.columnWidth(flex)
        minimum = max(min_col_width, header.sectionSizeHint(flex) + 16, vp_width // 4)
        if others + minimum <= vp_width:
            widget.setColumnWidth(flex, vp_width - others)
            return
    if total <= vp_width:
        return  # Alles passt → fertig

    # Schritt 3: Proportional skalieren, Minimum einhalten. Das Minimum ist
    # mindestens die Breite der Spaltenüberschrift -- sonst werden Köpfe wie
    # "Hersteller" oder "Total (CHF)" abgeschnitten. Passt es dann nicht mehr,
    # scrollt die Tabelle horizontal.
    header = widget.header() if hasattr(widget, "header") else widget.horizontalHeader()
    scale = vp_width / total
    for i in range(n):
        # +16: sectionSizeHint rechnet mit normaler Schrift, die Köpfe sind fett
        min_w = max(min_col_width, header.sectionSizeHint(i) + 16)
        new_w = max(min_w, int(widget.columnWidth(i) * scale))
        widget.setColumnWidth(i, new_w)


def scrollable(widget):
    """Widget in einen Rollbereich legen, der es nie unter seine
    Wunschgrösse staucht: bei kleinem Fenster (1280 x 720) rollen statt
    Felder zu überlappen und Knöpfe abzuschneiden."""
    from PySide6.QtWidgets import QFrame, QScrollArea
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    # nur die Höhe halten: in der Breite passt sich der Inhalt an
    widget.setMinimumHeight(widget.sizeHint().height())
    area.setWidget(widget)
    plain_background(area)
    return area


def plain_background(area) -> None:
    """Rollbereich ohne eigenen (grauen) Hintergrund -- wie die übrigen
    Ansichten auf dem Hintergrund des Fensters."""
    area.setStyleSheet("QScrollArea { background: transparent; }")
    area.viewport().setAutoFillBackground(False)
    if area.widget() is not None:
        area.widget().setAutoFillBackground(False)


def widen_popup(combo) -> None:
    """Auswahlliste so breit wie ihr längster Eintrag, auch wenn das Feld
    selbst schmaler ist (lange Einträge wurden abgeschnitten)."""
    metrics = combo.fontMetrics()
    widest = max((metrics.horizontalAdvance(combo.itemText(i))
                  for i in range(combo.count())), default=0)
    combo.view().setMinimumWidth(widest + 40)


class EmptyHint:
    """Hinweistext in einer leeren Tabelle oder Liste («Noch keine …»),
    mittig im Anzeigebereich; verschwindet mit der ersten Zeile."""

    def __init__(self, view, text: str):
        from PySide6.QtCore import QEvent, QObject, Qt
        from PySide6.QtWidgets import QLabel

        self._view = view
        self._label = QLabel(text, view.viewport())
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("color: #757575; background: transparent; padding: 24px;")
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        model = view.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.modelReset,
                       model.layoutChanged):
            signal.connect(self.update)

        hint = self

        class _Resize(QObject):
            def eventFilter(self, _obj, event):
                if event.type() in (QEvent.Resize, QEvent.Show):
                    hint.update()
                return False
        self._filter = _Resize(view)
        view.viewport().installEventFilter(self._filter)
        self.update()

    def update(self, *_args) -> None:
        self._label.setGeometry(self._view.viewport().rect())
        self._label.setVisible(self._view.model().rowCount() == 0)

    def visible(self) -> bool:
        return self._view.model().rowCount() == 0

