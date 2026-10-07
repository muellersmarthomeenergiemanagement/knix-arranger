"""
Ziehen und Ablegen für Bäume und Tabellen (FA-1015 a-d).

Die Ansicht entscheidet über drei Rückrufe, was geschieht:

- drag_data(item) -> object | None: Nutzdaten eines Eintrags, None = nicht ziehbar
- can_drop(payload, target) -> bool: darf hier abgelegt werden?
- on_drop(payload, target): Ablegen ausführen

payload ist die Liste der Nutzdaten aller gezogenen Einträge, target die
Nutzdaten (target_data) des Eintrags unter der Maus. Gezogen werden kann auch
zwischen zwei Widgets der App (z.B. Gewerk-Katalog → Raumtabelle); Qt bewegt
dabei selbst nichts. on_drop läuft nach dem Ziehen, damit Rückfragen und das
Neuaufbauen der Ansicht nicht innerhalb der Drag-Schleife stattfinden.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView, QListWidget, QTableWidget, QTreeWidget,
)

_MIME = "application/x-knix-drag"
_HIGHLIGHT = QColor("#D6EAF8")   # helles Blau, Schrift bleibt lesbar

# Nutzdaten des laufenden Ziehens (nur innerhalb der App)
_current_payload: list = []


class _DragDropMixin:
    """Gemeinsame Logik; die Klassen unten verbinden sie mit dem Qt-Widget."""

    def _init_drag_drop(self) -> None:
        self.drag_data: Callable | None = None
        self.target_data: Callable = self._default_target_data
        self.can_drop: Callable | None = None
        self.on_drop: Callable | None = None
        self._hover = None
        self._hover_brushes: list = []
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDropIndicatorShown(False)

    @staticmethod
    def _default_target_data(item):
        return item.data(0, Qt.UserRole) if hasattr(item, "columnCount") else item.data(Qt.UserRole)

    # -- Ziehen -------------------------------------------------------------

    def startDrag(self, _actions):
        global _current_payload
        if self.drag_data is None:
            return
        payload, seen = [], set()
        for item in self.selectedItems() or [self.currentItem()]:
            if item is None:
                continue
            data = self.drag_data(item)
            # Zeilen einer Tabelle liefern je Zelle dieselben Nutzdaten
            key = tuple(map(id, data)) if isinstance(data, tuple) else id(data)
            if data is None or key in seen:
                continue
            seen.add(key)
            payload.append(data)
        if not payload:
            return
        _current_payload = payload
        mime = QMimeData()
        mime.setData(_MIME, b"1")
        drag = QDrag(self)
        drag.setMimeData(mime)
        try:
            drag.exec(Qt.MoveAction | Qt.CopyAction)
        finally:
            _current_payload = []

    # -- Ablegen ------------------------------------------------------------

    def _target_at(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is None or self.can_drop is None or not _current_payload:
            return None, None
        target = self.target_data(item)
        if target is None or not self.can_drop(_current_payload, target):
            return None, None
        return item, target

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_MIME) and _current_payload:
            self.setState(QAbstractItemView.DraggingState)   # Scrollen am Rand
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat(_MIME):
            event.ignore()
            return
        super().dragMoveEvent(event)   # automatisches Scrollen am Rand
        item, _target = self._target_at(event)
        self._set_hover(item)
        if item is None:
            event.ignore()
        else:
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._set_hover(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        item, target = self._target_at(event)
        self._set_hover(None)
        self.setState(QAbstractItemView.NoState)
        if item is None:
            event.ignore()
            return
        payload = list(_current_payload)
        event.setDropAction(Qt.CopyAction)   # Qt soll nichts entfernen
        event.accept()
        handler = self.on_drop
        QTimer.singleShot(0, lambda: handler(payload, target))

    # -- Hervorhebung des Ziels -----------------------------------------------

    def _cells(self, item):
        if hasattr(item, "columnCount"):   # QTreeWidgetItem
            return [(item, c) for c in range(item.columnCount())]
        if isinstance(self, QTableWidget):
            row = item.row()
            return [(self.item(row, c), None) for c in range(self.columnCount())
                    if self.item(row, c) is not None]
        return [(item, None)]

    def _set_hover(self, item) -> None:
        if item is self._hover:
            return
        for (cell, col), brush in zip(self._cells_of_hover(), self._hover_brushes):
            try:
                _set_background(cell, col, brush)
            except RuntimeError:   # Eintrag inzwischen gelöscht
                pass
        self._hover, self._hover_brushes = item, []
        if item is None:
            return
        for cell, col in self._cells(item):
            self._hover_brushes.append(
                cell.background(col) if col is not None else cell.background())
            _set_background(cell, col, QBrush(_HIGHLIGHT))

    def _cells_of_hover(self):
        if self._hover is None:
            return []
        try:
            return self._cells(self._hover)
        except RuntimeError:
            return []


def _set_background(cell, col, brush) -> None:
    if col is None:
        cell.setBackground(brush)
    else:
        cell.setBackground(col, brush)


class DragDropTree(_DragDropMixin, QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_drag_drop()


class DragDropTable(_DragDropMixin, QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_drag_drop()


class DragSourceList(_DragDropMixin, QListWidget):
    """Liste, aus der nur gezogen wird (z.B. Gewerk-Katalog)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_drag_drop()
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.DragOnly)
