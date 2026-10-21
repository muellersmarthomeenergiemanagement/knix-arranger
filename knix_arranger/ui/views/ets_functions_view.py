"""
Ansicht "ETS-Funktionen": die in der ETS je Raum angelegten Funktionen
(FA-529, Hinweise FA-636) und die in KNiX geplanten mit ihrem Stand in der
ETS (FA-530, FA-637).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QCheckBox,
)

from ...models.project import KnxProject
from ...services.ets_function_service import overview_rows, type_label
from ...services.ets_function_plan import compare_plan, point_label
from ..styles import COLOR_WARNING

_COLUMNS = ["Raum / Funktion", "Rolle", "Adresse", "Name in der ETS", "DPT", "Hinweis"]
_PLAN_COLUMNS = ["Raum / Funktion", "Funktionspunkt", "Adresse", "GA", "Stand in der ETS"]
_STATE_TEXT = {"anlegen": "in der ETS anlegen", "ergänzen": "GAs zuordnen", "ok": "vorhanden"}


class EtsFunctionsView(QWidget):
    """Übersicht Raum > Funktion > GA, eingelesen und geplant."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("ETS-Funktionen")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        self._plan_check = QCheckBox("Funktionen planen")
        self._plan_check.setToolTip(
            "Je Licht, Steckdose, Jalousie und Heizung eine Funktion mit den "
            "KNiX-GAs vorsehen; fehlende kommen in die Validierung und die "
            "ETS-Arbeitsliste")
        self._plan_check.toggled.connect(self._on_plan_toggled)
        header.addWidget(self._plan_check)
        layout.addLayout(header)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: #666;")
        layout.addWidget(self._summary)

        self._tabs = QTabWidget()
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(_COLUMNS)
        self._plan_tree = QTreeWidget()
        self._plan_tree.setHeaderLabels(_PLAN_COLUMNS)
        self._tabs.addTab(self._tree, "In der ETS")
        self._tabs.addTab(self._plan_tree, "Geplant")
        layout.addWidget(self._tabs, 1)

    def set_project(self, project: KnxProject | None) -> None:
        self._project = project
        self._plan_check.blockSignals(True)
        self._plan_check.setChecked(bool(project and project.config.plan_ets_functions))
        self._plan_check.blockSignals(False)
        rows = overview_rows(project) if project else []
        statuses = compare_plan(project) if project else []
        self._summary.setText(self._summary_text(rows, statuses))
        self._fill(rows)
        self._fill_plan(statuses)

    def _summary_text(self, rows, statuses) -> str:
        if rows:
            functions = {(r.floor, r.room, r.function) for r in rows}
            text = (f"In der ETS: {len(functions)} Funktion(en) in "
                    f"{len({(r.floor, r.room) for r in rows})} Raum/Räumen, "
                    f"{sum(1 for r in rows if r.hints)} GA(s) mit Hinweis.")
        else:
            text = ("In der ETS: keine Funktionen. Sie werden beim Import einer "
                    ".knxproj eingelesen.")
        if statuses:
            todo = sum(1 for s in statuses if s.state != "ok")
            text += (f" Geplant: {len(statuses)} Funktion(en), davon {todo} in der ETS "
                     "anzulegen oder zu ergänzen.")
        return text + " Die ETS legt die GAs neuer Funktionen in HG 12 an."

    def _on_plan_toggled(self, checked: bool) -> None:
        if self._project is None:
            return
        self._project.config.plan_ets_functions = checked
        self.changed.emit()

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
        self._finish(self._tree, len(_COLUMNS))

    def _fill_plan(self, statuses) -> None:
        self._plan_tree.clear()
        rooms: dict[int, QTreeWidgetItem] = {}
        warn = QBrush(QColor(COLOR_WARNING))
        for status in statuses:
            plan = status.planned
            room_item = rooms.get(id(plan.room))
            if room_item is None:
                floor = plan.floor.name or plan.floor.short_code
                room = " ".join(p for p in (plan.room.number, plan.room.name) if p)
                room_item = QTreeWidgetItem([f"{floor} › {room}"])
                self._plan_tree.addTopLevelItem(room_item)
                rooms[id(plan.room)] = room_item
            state = _STATE_TEXT[status.state]
            if status.ets is not None and status.ets.name != plan.name:
                state += f" («{status.ets.name}»)"
            if status.other_room:
                state += ", anderer Raum"
            fn_item = QTreeWidgetItem(
                [f"{plan.name} ({type_label(plan.function_type)})", "", "", "", state])
            if status.state != "ok" or status.other_room:
                fn_item.setForeground(4, warn)
            room_item.addChild(fn_item)
            missing = {r.address for r in status.missing}
            replaced = {new.address: old.address for new, old in status.replaced}
            for ref in plan.refs:
                if status.ets is None:
                    ref_state = ""
                elif ref.address in missing:
                    ref_state = "fehlt"
                elif ref.address in replaced:
                    ref_state = f"statt {replaced[ref.address]}"
                else:
                    ref_state = "zugeordnet"
                item = QTreeWidgetItem(["", point_label(plan.function_type, ref),
                                        ref.address, ref.ga_name, ref_state])
                if ref_state not in ("", "zugeordnet"):
                    item.setForeground(4, warn)
                fn_item.addChild(item)
        self._finish(self._plan_tree, len(_PLAN_COLUMNS))

    @staticmethod
    def _finish(tree: QTreeWidget, columns: int) -> None:
        tree.expandAll()
        for col in range(columns):
            tree.resizeColumnToContents(col)
