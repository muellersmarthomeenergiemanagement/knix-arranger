"""
Ansicht "ETS-Funktionen": die in der ETS je Raum angelegten Funktionen
(FA-529, Hinweise FA-636) und die in KNiX geplanten (FA-530) mit ihren GAs,
Elementen, ihren Gewerken (FA-530c) und dem Stand in der ETS (FA-637).
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
    QTabWidget, QPushButton, QMessageBox, QMenu, QLineEdit, QCheckBox,
    QTreeWidgetItemIterator,
)

from ...models.project import KnxProject
from ...services.ets_function_service import (
    EtsFunctionMembers, function_key, function_operators, function_text, iter_functions,
    overview_rows,
    shared_function_gas, type_label,
)
from ...services import ets_function_plan as plan
from ...services.function_gewerke import EtsGewerke, GewerkCell, gewerk_cell
from ..styles import COLOR_WARNING

_COLUMNS = ["Raum / Funktion", "Gewerk", "Rolle", "Adresse", "Name in der ETS", "DPT", "Hinweis"]
_PLAN_COLUMNS = ["Ort / Funktion", "Gewerk", "Funktionspunkt", "Adresse", "Bezeichnung",
                 "Stand in der ETS / Aktorkanal"]
_STATE_TEXT = {"anlegen": "in der ETS anlegen", "ergänzen": "GAs zuordnen", "ok": "vorhanden"}
# Funktionszeile und "etwas zu tun" (Hinweis, anlegen/ergänzen): für das
# Aufklappen beim Öffnen und den Filter "Nur mit Hinweis"
_KIND = Qt.UserRole + 1
_ATTENTION = Qt.UserRole + 2
_COUNT_RE = re.compile(r" \(\d+\)$")


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

        filters = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Suchen: Funktion, Raum, Adresse, GA-Name, Gerät, Taste …")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _t: self._apply_filters())
        filters.addWidget(self._search, 1)
        self._only_open = QCheckBox("Nur mit Hinweis")
        self._only_open.toggled.connect(lambda _c: self._apply_filters())
        filters.addWidget(self._only_open)
        btn_expand = QPushButton("Alle aufklappen")
        btn_expand.clicked.connect(lambda: self._current_tree().expandAll())
        btn_collapse = QPushButton("Alle zuklappen")
        btn_collapse.clicked.connect(lambda: _collapse(self._current_tree()))
        filters.addWidget(btn_expand)
        filters.addWidget(btn_collapse)
        layout.addLayout(filters)
        # Aufklappzustand vor dem Filtern, je Baum (None = kein Filter aktiv)
        self._restore: dict[int, set | None] = {}

        self._tabs = QTabWidget()
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(_COLUMNS)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(
            lambda pos: self._show_ga_menu(self._tree, pos))

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
        self._plan_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._plan_tree.customContextMenuRequested.connect(
            lambda pos: self._show_ga_menu(self._plan_tree, pos))
        self._plan_tree.itemDoubleClicked.connect(lambda _i, _c: self._edit_function())
        self._plan_tree.currentItemChanged.connect(lambda *_a: self._update_buttons())
        plan_layout.addWidget(self._plan_tree, 1)

        self._tabs.addTab(self._tree, "In der ETS")
        self._tabs.addTab(plan_page, "Geplant")
        layout.addWidget(self._tabs, 1)
        self._tabs.currentChanged.connect(self._update_filter_label)
        self._update_buttons()

    def set_bus(self, bus) -> None:
        self._bus = bus

    # Sprünge in andere Ansichten (ViewJumps), von MainWindow gesetzt (FA-1011g)
    jumps = None

    def select_function(self, key, address: str = "") -> bool:
        """Funktion anwählen, mit address deren GA-Zeile (Sprung aus den
        Gruppenadressen, FA-1011g). key: Funktion-id (Geplant) oder
        ("ets", Stockwerk, Raum, Funktion) (In der ETS)."""
        from ..tree_select import select_tree_item
        self._clear_filters()
        ets = isinstance(key, tuple)
        tree = self._tree if ets else self._plan_tree
        self._tabs.setCurrentIndex(0 if ets else 1)
        if address and select_tree_item(tree, lambda item: (
                item.data(0, Qt.UserRole) == key and item.text(3) == address)) is not None:
            return True
        return select_tree_item(
            tree, lambda item: item.data(0, Qt.UserRole) == key) is not None

    def _show_ga_menu(self, tree: QTreeWidget, pos) -> None:
        """GA-Zeile: zur GA springen (FA-1011g)."""
        item = tree.itemAt(pos)
        address = item.text(3) if item is not None else ""
        if self.jumps is None or "/" not in address:
            return
        menu = QMenu(self)
        act = menu.addAction(f"Zur Gruppenadresse {address} springen")
        if menu.exec(tree.viewport().mapToGlobal(pos)) == act:
            self.jumps.ga(address)

    def set_project(self, project: KnxProject | None) -> None:
        self._project = project
        rows = overview_rows(project) if project else []
        statuses = plan.compare_plan(project) if project else []
        self._summary.setText(self._summary_text(rows, statuses))
        trees = (self._tree, self._plan_tree)
        # geöffnete Knoten bleiben offen (z.B. nach dem Speichern)
        states = {id(t): self._restore.get(id(t)) if self._filter_active()
                  else (_expanded_paths(t) if t.topLevelItemCount() else None)
                  for t in trees}
        self._fill(rows)
        self._fill_plan(statuses)
        for tree in trees:
            state = states[id(tree)]
            if state is None:
                _default_expand(tree)
            else:
                _restore_paths(tree, state)
            self._restore[id(tree)] = None
        self._apply_filters()
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
        ga_nodes: dict[tuple[str, str, str], QTreeWidgetItem] = {}
        addresses: dict[tuple[str, str, str], list[str]] = {}
        gewerke = EtsGewerke(self._project) if rows else None
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
                fn_item.setData(0, Qt.UserRole, ("ets", *fn_key))
                fn_item.setData(0, _KIND, "function")
                room_item.addChild(fn_item)
                functions[fn_key] = fn_item
            if row.hints:
                fn_item.setData(0, _ATTENTION, True)
            if not row.address and not row.role:
                # Funktion ohne GA
                if row.hints:
                    fn_item.setText(6, "; ".join(row.hints))
                    fn_item.setForeground(6, warn)
                continue
            ga_node = ga_nodes.get(fn_key)
            if ga_node is None:
                ga_node = QTreeWidgetItem(["GAs"])
                ga_node.setData(0, Qt.UserRole, ("ets", *fn_key))
                fn_item.addChild(ga_node)
                ga_nodes[fn_key] = ga_node
            item = QTreeWidgetItem(["", "", row.role, row.address, row.ga_name,
                                    row.datapoint_type, "; ".join(row.hints)])
            item.setData(0, Qt.UserRole, ("ets", *fn_key))
            if row.address:
                _set_gewerk(item, gewerke.cell(row.address))
                addresses.setdefault(fn_key, []).append(row.address)
            if row.hints:
                item.setForeground(6, warn)
            ga_node.addChild(item)
        for fn_key, ga_node in ga_nodes.items():
            ga_node.setText(0, f"GAs ({ga_node.childCount()})")
            # zugeklappt: die Funktionszeile sagt, dass darunter etwas ist
            hinted = sum(1 for i in range(ga_node.childCount()) if ga_node.child(i).text(6))
            fn_item = functions[fn_key]
            if hinted and not fn_item.text(6):
                fn_item.setText(6, f"{hinted} GA(s) mit Hinweis")
                fn_item.setForeground(6, warn)
        for fn_key, fn_item in functions.items():
            _set_gewerk(fn_item, gewerke.function_cell(addresses.get(fn_key, [])))
        if rows:
            self._add_members(functions)
        self._finish(self._tree, len(_COLUMNS))

    def _add_members(self, functions: dict) -> None:
        """Je Funktion «Bediente Elemente» aus den KO-Verknüpfungen der Aktoren
        (FA-529b) und der Hinweis auf GAs anderer Funktionen (FA-636b)."""
        project = self._project
        members = EtsFunctionMembers(project)
        shared = shared_function_gas(project)
        warn = QBrush(QColor(COLOR_WARNING))
        for floor, room, function in iter_functions(project):
            fn_item = functions.get(function_key(floor, room, function))
            if fn_item is None:
                continue
            others = []
            for ref in function.refs:
                for _fl, other_room, other in shared.get(ref.address, []):
                    text = function_text(other_room, other)
                    if other is not function and text not in others:
                        others.append(text)
            if others:
                fn_item.setText(6, "; ".join(t for t in (
                    fn_item.text(6), f"GAs auch in {', '.join(others)}") if t))
                fn_item.setForeground(6, warn)
                fn_item.setData(0, _ATTENTION, True)
            found = members.members(function)
            node = QTreeWidgetItem([f"Bediente Elemente ({len(found)})"])
            node.setToolTip(0, "Elemente der Gewerke, deren Aktorkanal eine GA der Funktion "
                               "hat (aus den KO-Verknüpfungen der ETS)")
            node.setData(0, Qt.UserRole, fn_item.data(0, Qt.UserRole))
            _set_gewerk(node, gewerk_cell(project, [m.code for m in found]))
            fn_item.addChild(node)
            for member in found:
                item = QTreeWidgetItem(["", "", member.place, member.address,
                                        " ".join(member.designation.split()), "",
                                        f"Aktor {member.channel}"])
                item.setData(0, Qt.UserRole, fn_item.data(0, Qt.UserRole))
                _set_gewerk(item, gewerk_cell(project, [member.code]))
                node.addChild(item)
            if not found:
                node.addChild(QTreeWidgetItem(["", "", "kein Aktorkanal verknüpft"]))
            operators = function_operators(project, [r.address for r in function.refs
                                                     if r.address])
            node = QTreeWidgetItem([f"Bedienende Elemente ({len(operators)})"])
            node.setToolTip(0, "Taster, Sensoren und Visualisierungen, die auf eine GA der "
                               "Funktion senden (aus den KO-Verknüpfungen der ETS)")
            node.setData(0, Qt.UserRole, fn_item.data(0, Qt.UserRole))
            fn_item.addChild(node)
            for operator in operators:
                item = QTreeWidgetItem(["", "", operator.place, operator.address,
                                        operator.text, "", operator.device])
                item.setData(0, Qt.UserRole, fn_item.data(0, Qt.UserRole))
                node.addChild(item)
            if not operators:
                node.addChild(QTreeWidgetItem(["", "", "kein Taster oder Sensor verknüpft"]))

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
                                       "", "", "", "", state])
            fn_item.setData(0, Qt.UserRole, function.id)
            fn_item.setData(0, _KIND, "function")
            if ets_read and (status.state != "ok" or status.other_room):
                fn_item.setForeground(5, warn)
                # übernommen: die GAs gibt es in der ETS, nichts anzulegen
                if not (function.ets_gas and status.ets is None):
                    fn_item.setData(0, _ATTENTION, True)
            place.addChild(fn_item)
            members = plan.resolve_members(project, function)
            codes = [m.assignment.gewerk_code for m in members if m is not None]
            if codes:
                _set_gewerk(fn_item, gewerk_cell(project, codes))
            else:
                # ohne Elemente: Gewerk der GA-Bezeichnung
                _set_gewerk(fn_item, gewerk_cell(project, [plan.gewerk_code(project, function)]),
                            grey=True)
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
                item = QTreeWidgetItem(["", "", plan._point_label(function.function_type, point),
                                        ga.address, ga.designation, ga_state])
                item.setData(0, Qt.UserRole, function.id)
                if ga_state == "fehlt":
                    item.setForeground(5, warn)
                gas_node.addChild(item)
            # Status über den Leitkanal: Rückmeldung des ersten Elements
            for point, ga in plan.status_gas(project, function).items():
                ga_state = "" if not ets_read or status.ets is None else (
                    "fehlt" if ga.address in missing else "zugeordnet")
                ga_state = ", ".join(p for p in ("Leitkanal", ga_state) if p)
                item = QTreeWidgetItem(["", "", plan._point_label(function.function_type, point),
                                        ga.address, ga.designation, ga_state])
                item.setToolTip(5, "Status der Funktion: Rückmeldung ihres ersten Elements, "
                                   "keine eigene GA")
                item.setData(0, Qt.UserRole, function.id)
                if "fehlt" in ga_state:
                    item.setForeground(5, warn)
                gas_node.addChild(item)
            # Aktorkanal je Element: über seine eigene GA im Belegungsplan
            own_gas = {}
            for member, _fga, own in plan.member_links(project, function):
                if own is not None:
                    own_gas.setdefault((member.assignment.id, member.element_number), own)
            members_node = QTreeWidgetItem([f"Bediente Elemente ({len(members)})"])
            members_node.setToolTip(0, "Elemente der Gewerke, die die Funktion gemeinsam "
                                       "bedient")
            members_node.setData(0, Qt.UserRole, function.id)
            fn_item.addChild(members_node)
            for member in members:
                if member is None:
                    item = QTreeWidgetItem(["", "", "Element entfernt"])
                    item.setForeground(2, warn)
                    fn_item.setData(0, _ATTENTION, True)
                else:
                    own = own_gas.get((member.assignment.id, member.element_number))
                    channel = channels.get(own.address, "") if own else ""
                    item = QTreeWidgetItem(["", "", member.label, "", "",
                                            channel or "noch kein Aktorkanal"])
                    _set_gewerk(item, gewerk_cell(project, [member.assignment.gewerk_code]))
                item.setData(0, Qt.UserRole, function.id)
                members_node.addChild(item)
            # Geplante Bedienung (Sensorfunktionen) und Taster aus der ETS
            planned = plan.planned_operators(project, function)
            sending = function_operators(project, [ga.address for _p, ga in gas])
            # in der ETS schon verknüpft: dort steht er mit KO
            sent_by = {o.physical_address for o in sending}
            planned = [(label, where) for label, where in planned
                       if not where or where.split()[0] not in sent_by]
            operators_node = QTreeWidgetItem(
                [f"Bedienende Elemente ({len(planned) + len(sending)})"])
            operators_node.setToolTip(0, "Taster und Sensoren, die die Funktion bedienen: "
                                         "geplant und aus den KO-Verknüpfungen der ETS")
            operators_node.setData(0, Qt.UserRole, function.id)
            fn_item.addChild(operators_node)
            for label, where in planned:
                item = QTreeWidgetItem(["", "", label, "", "", where or "geplant"])
                item.setData(0, Qt.UserRole, function.id)
                operators_node.addChild(item)
            for operator in sending:
                item = QTreeWidgetItem(["", "", operator.place, operator.address,
                                        operator.text, f"{operator.device} (ETS)"])
                item.setData(0, Qt.UserRole, function.id)
                operators_node.addChild(item)
            if not planned and not sending:
                item = QTreeWidgetItem(["", "", "noch kein Taster oder Sensor"])
                item.setData(0, Qt.UserRole, function.id)
                operators_node.addChild(item)
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
        # Spaltenbreite über alle Zeilen, auch die danach zugeklappten
        tree.expandAll()
        for col in range(columns):
            tree.resizeColumnToContents(col)
        _collapse(tree)

    # ── Suche und Filter ──────────────────────────────────────────────────

    def _current_tree(self) -> QTreeWidget:
        return self._tree if self._tabs.currentIndex() == 0 else self._plan_tree

    def _update_filter_label(self, index: int) -> None:
        self._only_open.setText("Nur mit Hinweis" if index == 0 else "Nur offene")
        self._only_open.setToolTip(
            "Nur Funktionen mit Hinweis" if index == 0 else
            "Nur Funktionen, die in der ETS anzulegen oder zu ergänzen sind")

    def _filter_active(self) -> bool:
        return bool(self._search.text().strip()) or self._only_open.isChecked()

    def _clear_filters(self) -> None:
        for widget in (self._search, self._only_open):
            widget.blockSignals(True)
        self._search.clear()
        self._only_open.setChecked(False)
        for widget in (self._search, self._only_open):
            widget.blockSignals(False)
        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self._search.text().strip().lower()
        only_open = self._only_open.isChecked()
        for tree in (self._tree, self._plan_tree):
            key = id(tree)
            if self._filter_active():
                if self._restore.get(key) is None:
                    self._restore[key] = _expanded_paths(tree)
                for i in range(tree.topLevelItemCount()):
                    top = tree.topLevelItem(i)
                    _filter_item(top, query, only_open, False, tree.columnCount())
                    # Raum/Ort nur mit sichtbaren Funktionen
                    top.setHidden(all(top.child(c).isHidden()
                                      for c in range(top.childCount())))
            else:
                _show_all(tree)
                state = self._restore.get(key)
                if state is not None:
                    _restore_paths(tree, state)
                self._restore[key] = None


def _path(item: QTreeWidgetItem) -> tuple[str, ...]:
    """Pfad eines Knotens ohne Anzahl ("GAs (5)" -> "GAs")."""
    parts = []
    while item is not None:
        parts.append(_COUNT_RE.sub("", item.text(0)))
        item = item.parent()
    return tuple(reversed(parts))


def _items(tree: QTreeWidget):
    it = QTreeWidgetItemIterator(tree)
    while it.value():
        yield it.value()
        it += 1


def _expanded_paths(tree: QTreeWidget) -> set[tuple[str, ...]]:
    return {_path(item) for item in _items(tree) if item.isExpanded()}


def _restore_paths(tree: QTreeWidget, paths: set) -> None:
    for item in _items(tree):
        item.setExpanded(_path(item) in paths)


def _collapse(tree: QTreeWidget) -> None:
    """Alles zu, nur die Räume/Orte offen: man sieht die Funktionen."""
    tree.collapseAll()
    for i in range(tree.topLevelItemCount()):
        tree.topLevelItem(i).setExpanded(True)


def _default_expand(tree: QTreeWidget) -> None:
    """Beim Öffnen: nur Raum › Funktion; was zu tun ist, steht in der
    Funktionszeile ("2 GA(s) mit Hinweis", "in der ETS anlegen")."""
    _collapse(tree)


def _show_all(tree: QTreeWidget) -> None:
    for item in _items(tree):
        item.setHidden(False)


def _filter_item(item: QTreeWidgetItem, query: str, only_open: bool, inherited: bool,
                 columns: int) -> tuple[bool, bool]:
    """(sichtbar, Treffer darunter). Trifft ein Knoten, bleibt alles
    darunter sichtbar; Knoten mit Treffern darunter klappen auf."""
    if only_open and item.data(0, _KIND) == "function" and not item.data(0, _ATTENTION):
        item.setHidden(True)
        return False, False
    own = bool(query) and any(query in item.text(c).lower() for c in range(columns))
    matched = inherited or own or not query
    any_visible = hit_below = False
    for c in range(item.childCount()):
        visible, hit = _filter_item(item.child(c), query, only_open, matched, columns)
        any_visible |= visible
        hit_below |= hit
    if query and hit_below:
        item.setExpanded(True)
    visible = matched or any_visible
    item.setHidden(not visible)
    return visible, own or hit_below


def _set_gewerk(item: QTreeWidgetItem, cell: GewerkCell, grey: bool = False) -> None:
    """Spalte "Gewerk": abgeleitet kursiv, Namen mehrerer Gewerke im Tooltip."""
    item.setText(1, cell.text)
    if cell.tooltip:
        item.setToolTip(1, cell.tooltip)
    if cell.derived:
        font = QFont(item.font(1))
        font.setItalic(True)
        item.setFont(1, font)
    if grey:
        item.setForeground(1, QBrush(QColor("#888")))
