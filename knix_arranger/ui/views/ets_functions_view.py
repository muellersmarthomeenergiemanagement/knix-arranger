"""
Ansicht "ETS-Funktionen": die in der ETS je Raum angelegten Funktionen
(FA-529, Hinweise FA-636) und die in KNiX geplanten (FA-530) mit ihren GAs,
Elementen und dem Stand in der ETS (FA-637).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QPushButton, QMessageBox,
)

from ...models.project import KnxProject
from ...services.ets_function_service import overview_rows, type_label
from ...services import ets_function_plan as plan
from ..styles import COLOR_WARNING

_COLUMNS = ["Raum / Funktion", "Rolle", "Adresse", "Name in der ETS", "DPT", "Hinweis"]
_PLAN_COLUMNS = ["Ort / Funktion", "Funktionspunkt", "Adresse", "Bezeichnung",
                 "Stand in der ETS / Aktorkanal"]
_STATE_TEXT = {"anlegen": "in der ETS anlegen", "ergänzen": "GAs zuordnen", "ok": "vorhanden"}


class EtsFunctionsView(QWidget):
    """Übersicht Raum > Funktion > GA, eingelesen und geplant."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        self._bus = None
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

        self._tabs = QTabWidget()
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(_COLUMNS)

        plan_page = QWidget()
        plan_layout = QVBoxLayout(plan_page)
        plan_layout.setContentsMargins(0, 4, 0, 0)
        buttons = QHBoxLayout()
        self._btn_new = QPushButton("Neue Funktion…")
        self._btn_new.setToolTip("Mehrere Elemente eines Raums oder einer Zone gemeinsam "
                                 "bedienen, z.B. «Fensterfront» für drei Jalousien")
        self._btn_new.clicked.connect(self._new_function)
        self._btn_edit = QPushButton("Bearbeiten…")
        self._btn_edit.clicked.connect(self._edit_function)
        self._btn_delete = QPushButton("Löschen")
        self._btn_delete.clicked.connect(self._delete_function)
        self._btn_groups = QPushButton("Gruppen erkennen…")
        self._btn_groups.setToolTip(
            "Importierte Projekte: GAs, die mehrere Aktorkanäle desselben Gewerks "
            "belegen, als Funktion übernehmen (z.B. «Licht Zentral» eines Raums)")
        self._btn_groups.clicked.connect(self._detect_groups)
        for btn in (self._btn_new, self._btn_edit, self._btn_delete, self._btn_groups):
            buttons.addWidget(btn)
        buttons.addStretch()
        plan_layout.addLayout(buttons)
        self._plan_tree = QTreeWidget()
        self._plan_tree.setHeaderLabels(_PLAN_COLUMNS)
        self._plan_tree.itemDoubleClicked.connect(lambda _i, _c: self._edit_function())
        self._plan_tree.currentItemChanged.connect(lambda *_a: self._update_buttons())
        plan_layout.addWidget(self._plan_tree, 1)

        self._tabs.addTab(self._tree, "In der ETS")
        self._tabs.addTab(plan_page, "Geplant")
        layout.addWidget(self._tabs, 1)
        self._update_buttons()

    def set_bus(self, bus) -> None:
        self._bus = bus

    def set_project(self, project: KnxProject | None) -> None:
        self._project = project
        rows = overview_rows(project) if project else []
        statuses = plan.compare_plan(project) if project else []
        self._summary.setText(self._summary_text(rows, statuses))
        self._fill(rows)
        self._fill_plan(statuses)
        self._update_buttons()

    def _summary_text(self, rows, statuses) -> str:
        if rows:
            functions = {(r.floor, r.room, r.function) for r in rows}
            text = (f"In der ETS: {len(functions)} Funktion(en) in "
                    f"{len({(r.floor, r.room) for r in rows})} Raum/Räumen, "
                    f"{sum(1 for r in rows if r.hints)} GA(s) mit Hinweis.")
        else:
            text = ("In der ETS: keine Funktionen eingelesen (beim Import einer "
                    ".knxproj).")
        if statuses:
            todo = sum(1 for s in statuses if s.state != "ok")
            text += f" Geplant: {len(statuses)} Funktion(en)"
            text += f", davon {todo} in der ETS anzulegen oder zu ergänzen." if rows else "."
        return text

    # ── Eingelesen ────────────────────────────────────────────────────────

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

    # ── Geplant ───────────────────────────────────────────────────────────

    def _fill_plan(self, statuses) -> None:
        self._plan_tree.clear()
        project = self._project
        places: dict[str, QTreeWidgetItem] = {}
        warn = QBrush(QColor(COLOR_WARNING))
        ets_read = bool(project) and any(r.ets_functions for r in project.all_rooms)
        channels = self._actor_channels(project) if statuses else {}
        for status in statuses:
            function = status.function
            location = status.location
            key = function.room_id or function.zone_id
            place = places.get(key)
            if place is None:
                floor = (location.floor.name or location.floor.short_code) if location else ""
                text = f"{floor} › {location.label}" if location else "Ort fehlt"
                place = QTreeWidgetItem([text])
                self._plan_tree.addTopLevelItem(place)
                places[key] = place
            state = _STATE_TEXT[status.state] if ets_read else ""
            if function.ets_gas and status.ets is None:
                state = "aus der ETS übernommen"
            if status.ets is not None and status.ets.name != function.name:
                state += f" («{status.ets.name}»)"
            if status.other_room:
                state += ", anderer Raum"
            fn_item = QTreeWidgetItem([f"{function.name} ({plan.plan_type_label(function.function_type)})",
                                       "", "", "", state])
            fn_item.setData(0, Qt.UserRole, function.id)
            if ets_read and (status.state != "ok" or status.other_room):
                fn_item.setForeground(4, warn)
            place.addChild(fn_item)
            missing = {ga.address for ga in status.missing}
            gas = list(plan.function_ga_map(project, function).items())
            gas_node = QTreeWidgetItem([f"Funktions-GAs ({len(gas)})"])
            gas_node.setToolTip(0, "Eigene Befehls-GAs der Funktion; sie kommen zusätzlich "
                                   "auf die Aktorkanäle der bedienten Elemente")
            gas_node.setData(0, Qt.UserRole, function.id)
            fn_item.addChild(gas_node)
            for point, ga in gas:
                ga_state = "" if not ets_read or status.ets is None else (
                    "fehlt" if ga.address in missing else "zugeordnet")
                if ga.function_id != function.id:
                    ga_state = ", ".join(p for p in ("bestehende GA", ga_state) if p)
                item = QTreeWidgetItem(["", plan._point_label(function.function_type, point),
                                        ga.address, ga.designation, ga_state])
                item.setData(0, Qt.UserRole, function.id)
                if ga_state == "fehlt":
                    item.setForeground(4, warn)
                gas_node.addChild(item)
            # Aktorkanal je Element: über seine eigene GA im Belegungsplan
            own_gas = {}
            for member, _fga, own in plan.member_links(project, function):
                if own is not None:
                    own_gas.setdefault((member.assignment.id, member.element_number), own)
            members = plan.resolve_members(project, function)
            members_node = QTreeWidgetItem([f"Bediente Elemente ({len(members)})"])
            members_node.setToolTip(0, "Elemente der Gewerke, die die Funktion gemeinsam "
                                       "bedient")
            members_node.setData(0, Qt.UserRole, function.id)
            fn_item.addChild(members_node)
            for member in members:
                if member is None:
                    item = QTreeWidgetItem(["", "Element entfernt"])
                    item.setForeground(1, warn)
                else:
                    own = own_gas.get((member.assignment.id, member.element_number))
                    channel = channels.get(own.address, "") if own else ""
                    item = QTreeWidgetItem(["", member.label, "", "",
                                            channel or "noch kein Aktorkanal"])
                item.setData(0, Qt.UserRole, function.id)
                members_node.addChild(item)
        self._finish(self._plan_tree, len(_PLAN_COLUMNS))

    @staticmethod
    def _actor_channels(project) -> dict[str, str]:
        """GA des Elements -> "Aktor 1.1.3, Kanal 1" aus dem Belegungsplan."""
        if project is None or not project.topology.areas:
            return {}
        try:
            from ...services.belegungsplan_service import BelegungsplanService
            rows = BelegungsplanService().generate(project).actor_rows
        except Exception:
            return {}
        result = {}
        for row in rows:
            if row.ga_address and row.physical_address:
                text = f"Aktor {row.physical_address}"
                label = row.channel_label
                if label:
                    text += f", Kanal {label}" if label.isdigit() else f", {label}"
                result.setdefault(row.ga_address, text)
        return result

    def _selected_function(self):
        item = self._plan_tree.currentItem()
        if item is None or self._project is None:
            return None
        fid = item.data(0, Qt.UserRole)
        return next((f for f in self._project.functions if f.id == fid), None)

    def _selected_location(self) -> tuple[str, str]:
        function = self._selected_function()
        return (function.room_id, function.zone_id) if function else ("", "")

    def _update_buttons(self) -> None:
        has = self._selected_function() is not None
        self._btn_new.setEnabled(self._project is not None)
        self._btn_edit.setEnabled(has)
        self._btn_delete.setEnabled(has)
        self._btn_groups.setVisible(
            self._project is not None and self._project.topology.is_imported)

    def _new_function(self) -> None:
        from ..dialogs.function_edit_dialog import FunctionEditDialog
        if self._project is None:
            return
        dialog = FunctionEditDialog(self._project, None, self._selected_location(), self)
        if dialog.exec():
            function = dialog.result_function()
            self._begin(f"Funktion «{function.name}» anlegen")
            self._project.functions.append(function)
            self._apply()

    def _edit_function(self) -> None:
        from ..dialogs.function_edit_dialog import FunctionEditDialog
        function = self._selected_function()
        if function is None:
            return
        dialog = FunctionEditDialog(self._project, function, parent=self)
        if dialog.exec():
            self._begin(f"Funktion «{function.name}» bearbeiten")
            index = self._project.functions.index(function)
            self._project.functions[index] = dialog.result_function()
            self._apply()

    def _detect_groups(self) -> None:
        """FA-531: Gruppenbedienungen des Imports als Funktionen übernehmen."""
        from ...services.group_function_detection import adopt, suggest_group_functions
        from ..dialogs.group_suggestion_dialog import GroupSuggestionDialog
        if self._project is None:
            return
        suggestions = suggest_group_functions(self._project)
        if not suggestions:
            QMessageBox.information(
                self, "Gruppen erkennen",
                "Keine weiteren Gruppenbedienungen gefunden: keine Befehls-GA belegt "
                "mehrere Aktorkanäle desselben Gewerks, die nicht schon zu einer "
                "Funktion gehört.")
            return
        dialog = GroupSuggestionDialog(suggestions, self)
        if not dialog.exec():
            return
        chosen = dialog.selected()
        if not chosen:
            return
        self._begin(f"{len(chosen)} Gruppe(n) als Funktion übernehmen")
        for suggestion, name in chosen:
            adopt(self._project, suggestion, name)
        self._apply()

    def _delete_function(self) -> None:
        function = self._selected_function()
        if function is None:
            return
        answer = QMessageBox.question(
            self, "Funktion löschen",
            f"Funktion «{function.name}» mit ihren GAs löschen?")
        if answer != QMessageBox.Yes:
            return
        self._begin(f"Funktion «{function.name}» löschen")
        self._project.functions.remove(function)
        self._apply()

    def _begin(self, description: str) -> None:
        if self._bus is not None:
            self._bus.begin_change(description)

    def _apply(self) -> None:
        warnings = plan.sync_function_gas(self._project)
        if not self._project.topology.is_imported:
            plan.unlink_removed_gas(self._project)
        self.set_project(self._project)
        if warnings:
            QMessageBox.warning(self, "Funktionen", "\n".join(warnings))
        self.changed.emit()

    @staticmethod
    def _finish(tree: QTreeWidget, columns: int) -> None:
        tree.expandAll()
        for col in range(columns):
            tree.resizeColumnToContents(col)
