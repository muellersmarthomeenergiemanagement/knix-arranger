"""
Funktionsliste der Bauherrenberatung (FA-1015 e): Gewerk-Elemente aller
Räume zum Ziehen auf eine Taste.

Elemente ohne Bedienung (FA-619) sind orange markiert; "Nur ohne Bedienung"
blendet die übrigen aus. Gezogen wird ein JSON-Paket im eigenen MIME-Typ
FUNCTION_MIME mit {"code", "element", "room_id"}; die Taste übernimmt es wie
eine Auswahl in ihrer Liste (_SlotWidget.apply_dropped_function).
"""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QBrush, QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...services.sensor_service import GEWERK_PRIMARY_FUNCTIONS
from ..styles import COLOR_WARNING

FUNCTION_MIME = "application/x-knix-function"


def function_from_mime(mime: QMimeData) -> dict | None:
    """{"code", "element", "room_id"} aus einem Drag, sonst None."""
    if not mime.hasFormat(FUNCTION_MIME):
        return None
    try:
        data = json.loads(bytes(mime.data(FUNCTION_MIME)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("code"):
        return None
    return data


class _FunctionTree(QTreeWidget):
    def startDrag(self, _actions):
        item = self.currentItem()
        data = item.data(0, Qt.UserRole) if item else None
        if not data:
            return
        mime = QMimeData()
        mime.setData(FUNCTION_MIME, json.dumps(data).encode("utf-8"))
        mime.setText(item.text(0))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class FunctionPalette(QWidget):
    """Gewerk-Elemente aller Räume, gegliedert nach Raum."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._only_open = QCheckBox("Nur ohne Bedienung")
        self._only_open.setToolTip(
            "Nur Licht, Steckdosen und Beschattung zeigen, die noch keine Taste, "
            "kein Präsenzmelder, keine Szene und keine Zeitsteuerung bedient")
        self._only_open.toggled.connect(self.refresh)
        layout.addWidget(self._only_open)

        self._tree = _FunctionTree()
        self._tree.setHeaderHidden(True)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QAbstractItemView.DragOnly)
        self._tree.setToolTip("Funktion auf eine Taste ziehen, auch aus einem anderen Raum")
        layout.addWidget(self._tree, 1)

    def set_project(self, project) -> None:
        self._project = project
        self.refresh()

    def refresh(self) -> None:
        self._tree.clear()
        project = self._project
        if project is None:
            return
        from ...services.operation_check import unoperated_elements
        open_keys = {(u.room_id, u.gewerk_code, u.element_number)
                     for u in unoperated_elements(project)}
        floors = {}
        try:
            from ...services.bauherr_form_service import BauherrFormService
            floors = BauherrFormService(project)._floor_by_room()
        except Exception:
            pass
        catalog = project.gewerk_catalog
        warn = QBrush(QColor(COLOR_WARNING))
        only_open = self._only_open.isChecked()
        for room in project.all_rooms:
            children = []
            for assignment in room.gewerk_assignments:
                code = assignment.gewerk_code
                if code not in GEWERK_PRIMARY_FUNCTIONS:
                    continue
                gewerk = catalog.get(code)
                name = gewerk.name if gewerk else code
                for nr in range(1, assignment.count + 1):
                    is_open = (room.id, code, nr) in open_keys
                    if only_open and not is_open:
                        continue
                    text = (f"{code} – {name}"
                            f"{room.gewerk_element_suffix(code, nr, assignment.count > 1)}")
                    child = QTreeWidgetItem([text + ("   · ohne Bedienung" if is_open else "")])
                    child.setData(0, Qt.UserRole,
                                  {"code": code, "element": nr, "room_id": room.id})
                    if is_open:
                        child.setForeground(0, warn)
                    children.append(child)
            if not children:
                continue
            number = " ".join(p for p in (floors.get(room.id, ""), room.number) if p)
            parent = QTreeWidgetItem([f"{number}  {room.name}"])
            parent.setFlags(parent.flags() & ~Qt.ItemIsDragEnabled)
            parent.addChildren(children)
            self._tree.addTopLevelItem(parent)
            parent.setExpanded(True)
