"""
Ansicht "ETS-Funktionen" (FA-529): die in der ETS je Raum angelegten
Funktionen mit ihren Gruppenadressen und Hinweisen (FA-636).
"""
from __future__ import annotations

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
)

from ...models.project import KnxProject
from ...services.ets_function_service import overview_rows
from ..styles import COLOR_WARNING

_COLUMNS = ["Raum / Funktion", "Rolle", "Adresse", "Name in der ETS", "DPT", "Hinweis"]


class EtsFunctionsView(QWidget):
    """Übersicht Raum > Funktion > GA."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("ETS-Funktionen")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: #666;")
        layout.addWidget(self._summary)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(_COLUMNS)
        self._tree.setRootIsDecorated(True)
        layout.addWidget(self._tree, 1)

    def set_project(self, project: KnxProject | None) -> None:
        self._project = project
        rows = overview_rows(project) if project else []
        functions = {(r.floor, r.room, r.function) for r in rows}
        with_hints = sum(1 for r in rows if r.hints)
        if not rows:
            text = ("Das Projekt enthält keine ETS-Funktionen. Sie werden beim "
                    "Import einer .knxproj eingelesen.")
        else:
            text = (f"{len(functions)} Funktion(en) in "
                    f"{len({(r.floor, r.room) for r in rows})} Raum/Räumen, "
                    f"{with_hints} GA(s) mit Hinweis. Die GAs neuer Funktionen "
                    "legt die ETS in HG 12 an.")
        self._summary.setText(text)
        self._fill(rows)

    def _fill(self, rows) -> None:
        self._tree.clear()
        rooms: dict[tuple[str, str], QTreeWidgetItem] = {}
        functions: dict[tuple[str, str, str], QTreeWidgetItem] = {}
        warn = QBrush(QColor(COLOR_WARNING))
        for row in rows:
            room_key = (row.floor, row.room)
            room_item = rooms.get(room_key)
            if room_item is None:
                room_item = QTreeWidgetItem([f"{row.floor} › {row.room}"])
                self._tree.addTopLevelItem(room_item)
                rooms[room_key] = room_item
            fn_key = (row.floor, row.room, row.function)
            fn_item = functions.get(fn_key)
            if fn_item is None:
                fn_item = QTreeWidgetItem([f"{row.function} ({row.type_label})"])
                room_item.addChild(fn_item)
                functions[fn_key] = fn_item
            if not row.address and not row.role:
                # Funktion ohne GA
                if row.hints:
                    fn_item.setText(5, "; ".join(row.hints))
                    fn_item.setForeground(5, warn)
                continue
            item = QTreeWidgetItem(["", row.role, row.address, row.ga_name,
                                    row.datapoint_type, "; ".join(row.hints)])
            if row.hints:
                item.setForeground(5, warn)
            fn_item.addChild(item)
        self._tree.expandAll()
        for col in range(len(_COLUMNS)):
            self._tree.resizeColumnToContents(col)
