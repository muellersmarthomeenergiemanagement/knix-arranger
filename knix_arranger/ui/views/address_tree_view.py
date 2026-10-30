"""
GA-Baumansicht: HG > MG > UG mit Farbmarkierung (FA-821)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QMenu, QPushButton, QAbstractItemView, QMessageBox,
    QStyledItemDelegate, QLineEdit, QInputDialog,
)
from PySide6.QtGui import QColor, QBrush, QKeySequence, QShortcut
from PySide6.QtCore import Signal, Qt, QTimer
from ..widgets.search_filter_bar import SearchFilterBar
from ..dialogs.ga_edit_dialog import GaEditDialog, dpt_combo, function_combo
from ..dialogs.ga_bulk_edit_dialog import GaBulkEditDialog
from ..dialogs.ga_scene_dialog import GaSceneDialog
from ..styles import GEWERK_COLORS
from ...models.group_address import GroupAddressStructure, GroupAddress
from ..column_utils import fit_columns
from ..topology_jump import add_topology_menu
from ..widgets.drag_drop import DragDropTree
from ..tree_select import select_tree_item
from ...services.ets_corrections import gewerk_display
from ...services.ga_move import (
    can_move_to_middle_group, can_reorder, can_swap, is_draggable,
    move_to_middle_group, swap_addresses,
)
from ...services.time_program_service import timed_label
from ...services.ga_delete import (
    DELETABLE, GENERATED, classify, delete_gas, omitted_function_of, restore_function,
)
from ...services import ga_functions
from ...services.ga_edit import (
    PROFILE_LABELS, apply_changes, can_set_profile, editable_fields, element_of,
    is_reworked, reset_to_plan, set_element_profile,
)

# Spalten
COL_ADDRESS, COL_DESIGNATION, COL_DESCRIPTION, COL_FUNCTION, COL_DPT, COL_GEWERK, COL_ROOM = range(7)
_COLUMNS = 7
# In der Zelle bearbeitbar (F2): Spalte -> GA-Feld
_INLINE_FIELDS = {COL_DESCRIPTION: "description", COL_FUNCTION: "function_name",
                  COL_DPT: "datapoint_type"}
# Kennzeichen nachbearbeiteter Funktionen (FA-1003b)
REWORKED_MARK = "✎"


class _InlineDelegate(QStyledItemDelegate):
    """Editor für Beschreibung, Funktion und DPT; der Wert geht über die
    Ansicht an alle markierten GAs (services/ga_edit), nicht ins Item."""

    def __init__(self, view: "AddressTreeView"):
        super().__init__(view._tree)
        self._view = view

    def _ga(self, index):
        item = self._view._tree.itemFromIndex(index)
        return item, (item.data(0, AddressTreeView.GA_OBJECT_ROLE) if item else None)

    def createEditor(self, parent, option, index):
        item, ga = self._ga(index)
        field = _INLINE_FIELDS.get(index.column())
        if not isinstance(ga, GroupAddress) or not field or not self._view._can_edit(ga, field):
            return None
        if field == "function_name":
            editor = function_combo(ga.function_name)
        elif field == "datapoint_type":
            editor = dpt_combo(ga.datapoint_type)
        else:
            editor = QLineEdit(ga.description)
        editor.setParent(parent)
        return editor

    def setEditorData(self, editor, index):
        pass    # Startwert setzt createEditor

    def setModelData(self, editor, model, index):
        item, _ga = self._ga(index)
        field = _INLINE_FIELDS[index.column()]
        value = editor.text() if isinstance(editor, QLineEdit) else editor.currentText().strip()
        self._view._commit_inline(item, field, value)


class AddressTreeView(QWidget):
    """GA-Baumansicht: Hauptgruppe > Mittelgruppe > Untergruppe."""

    address_selected = Signal(str)  # GA-Adresse z.B. "2/0/0"
    ga_modified = Signal()  # Emitted when a GA was edited
    # Gewerk für die markierten GAs festlegen (Korrekturschicht, MainWindow)
    gewerk_change_requested = Signal(list)
    # Gerät in der Topologie anwählen: (Device, GA-Adresse), FA-1011a
    device_requested = Signal(object, str)
    # Adresse -> [(Device, Text)], von MainWindow gesetzt (FA-1011a)
    linked_devices = None

    # Qt.UserRole für Adress-String, UserRole+1 für GA-Objekt,
    # UserRole+2 für (HG, MG) eines Mittelgruppen-Knotens
    GA_OBJECT_ROLE = Qt.UserRole + 1
    MG_ROLE = Qt.UserRole + 2

    # Gewerk-Codes je Filterkategorie
    _CATEGORY_CODES: dict[str, set[str]] = {
        "licht":    {"L", "LD", "LDA", "LC", "LCT", "LCW", "DMX", "S", "SD"},
        "jalousie": {"J", "R", "M", "T", "DF"},
        "heizung":  {"H", "WP", "TF"},
        "lueftung": {"LU", "KL", "V"},
        "energie":  {"EV", "PV", "SP", "E"},
        "alarm":    {"A", "RK", "FK", "TK"},
        "allgemein": {"G", "BW", "BL", "P", "SF", "W", "MM", "GS", "TE", "TVL", "LW", "FG",
                      "F", "U"},
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._structure: GroupAddressStructure | None = None
        self._project = None   # für Umsortieren per Ziehen (FA-1015 d)
        self._active_category: str = ""
        self._bus = None

        layout = QVBoxLayout(self)

        title = QLabel("Gruppenadressen - Baumansicht")
        title.setObjectName("title")
        layout.addWidget(title)

        # Toolbar
        toolbar = QHBoxLayout()
        self._btn_expand_all = QPushButton("Alle aufklappen")
        self._btn_expand_all.setToolTip("Alle Haupt- und Mittelgruppen aufklappen")
        self._btn_expand_all.clicked.connect(self._expand_all)
        self._btn_collapse_all = QPushButton("Alle zuklappen")
        self._btn_collapse_all.setToolTip("Alle Haupt- und Mittelgruppen zuklappen")
        self._btn_collapse_all.clicked.connect(self._collapse_all)
        toolbar.addWidget(self._btn_expand_all)
        toolbar.addWidget(self._btn_collapse_all)
        toolbar.addStretch()
        hint = QLabel("Doppelklick oder Rechtsklick auf eine GA zum Bearbeiten  ·  "
                      "F2: Zelle bearbeiten")
        hint.setStyleSheet("color: #666666; font-style: italic;")
        self._hint = hint
        toolbar.addWidget(hint)
        layout.addLayout(toolbar)

        # Suchleiste
        self._search_bar = SearchFilterBar(
            filters=[
                ("licht", "Licht"), ("jalousie", "Jalousie"),
                ("heizung", "Heizung"), ("lueftung", "Lüftung/Klima"),
                ("energie", "Energie"), ("alarm", "Alarm"),
                ("allgemein", "Allgemein"),
            ]
        )
        self._search_bar.search_changed.connect(self._apply_filter)
        self._search_bar.filter_changed.connect(self._on_category_changed)
        layout.addWidget(self._search_bar)

        # Baum; in geplanten Projekten GAs per Ziehen tauschen oder in eine
        # andere Mittelgruppe verschieben (FA-1015 d)
        self._tree = DragDropTree()
        self._tree.drag_data = self._drag_data
        self._tree.target_data = self._drop_target
        self._tree.can_drop = self._can_drop
        self._tree.on_drop = self._on_drop
        # Spaltenbreiten beim Aufklappen von Hand; beim Aufbau einmal am Ende
        # (sonst je Mittelgruppe einmal, Projekt_23: 0,5 s)
        self._building = False
        self._tree.itemExpanded.connect(
            lambda _: None if self._building else fit_columns(self._tree, stretch_to_fit=False)
        )
        self._tree.setHeaderLabels([
            "Adresse", "Bezeichnung", "Beschreibung", "Funktion", "DPT", "Gewerk", "Raum",
        ])
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # F2: Beschreibung, Funktion, DPT direkt in der Zelle, für alle markierten
        self._tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self._tree.setItemDelegate(_InlineDelegate(self))
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        # Entf: markierte GAs löschen
        delete_shortcut = QShortcut(QKeySequence.Delete, self._tree)
        delete_shortcut.setContext(Qt.WidgetShortcut)
        delete_shortcut.activated.connect(self._delete_selected)
        layout.addWidget(self._tree)

    def showEvent(self, event):
        """Spaltenbreiten neu berechnen, wenn diese Ansicht sichtbar wird.

        set_structure() läuft oft, während dieser Tab noch gar nicht sichtbar
        ist -- main_window.py hält alle Ansichten dauerhaft in einem
        QStackedWidget vor, statt sie neu zu erzeugen. resizeColumnToContents()
        (in fit_columns()) liefert auf einem verborgenen Widget teils falsche
        (zu schmale) Breiten. Beim ersten Einblenden hier korrekt nachziehen.
        """
        super().showEvent(event)
        fit_columns(self._tree, stretch_to_fit=False)

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus."""
        self._bus = bus

    # Uhr-Symbol statt Buchstabenkürzel: "[T]" wäre mit dem Gewerk T
    # (Tagesvorhang, in ETS-Projekten auch Tor) verwechselbar
    TIMED_MARK = "⏱"

    def set_timed_gas(self, programs: dict[str, list[str]]) -> None:
        """GAs, die ein aktives Zeitprogramm schaltet (GA-id -> Programmnamen):
        Uhr-Symbol vor der Beschreibung, Programmnamen im Tooltip (FA-3306d).
        Wirkt beim nächsten set_structure."""
        self._timed = dict(programs)

    def set_structure(self, structure: GroupAddressStructure):
        """Setzt die anzuzeigende GA-Struktur."""
        self._structure = structure
        self._refresh_tree()

    def set_project(self, project) -> None:
        """Projekt für das Umsortieren per Ziehen (nur geplante Projekte)."""
        self._project = project
        reorder = project is not None and can_reorder(project)
        self._hint.setText(
            "Doppelklick oder Rechtsklick auf eine GA zum Bearbeiten  ·  F2: Zelle bearbeiten"
            "  ·  Entf: markierte löschen"
            + ("  ·  Ziehen auf eine GA: tauschen, auf eine Mittelgruppe: verschieben"
               if reorder else ""))

    # ── Ziehen und Ablegen (FA-1015 d) ──

    def select_address(self, address: str) -> bool:
        """GA anwählen (Sprung aus der Validierung, FA-615a); ein Suchtext,
        der sie ausblendet, wird gelöscht."""
        def match(item):
            return item.data(0, Qt.UserRole) == address
        found = select_tree_item(self._tree, match)
        if found is not None and (self._search_bar.search_text or self._active_category):
            self._search_bar.clear()
            found = select_tree_item(self._tree, match)
        if found is None:
            # Adresse gibt es nicht (z.B. Lücke im Block): ihre Mittelgruppe
            parts = address.split("/")
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                group = (int(parts[0]), int(parts[1]))
                found = select_tree_item(
                    self._tree, lambda item: item.data(0, self.MG_ROLE) == group)
        return found is not None

    def _drag_data(self, item: QTreeWidgetItem):
        ga = item.data(0, self.GA_OBJECT_ROLE)
        if (not isinstance(ga, GroupAddress) or self._project is None
                or not can_reorder(self._project) or not is_draggable(ga)):
            return None
        return ga

    def _drop_target(self, item: QTreeWidgetItem):
        ga = item.data(0, self.GA_OBJECT_ROLE)
        if isinstance(ga, GroupAddress):
            return ("ga", ga)
        mg = item.data(0, self.MG_ROLE)
        return ("mg", mg) if mg else None

    @staticmethod
    def _can_drop(gas: list, target) -> bool:
        kind, value = target
        if kind == "ga":
            return len(gas) == 1 and can_swap(gas[0], value)
        return can_move_to_middle_group(gas, *value)

    def _on_drop(self, gas: list, target) -> None:
        if self._project is None or not self._can_drop(gas, target):
            return
        kind, value = target
        if self._bus:
            if kind == "ga":
                self._bus.begin_change(f"GA {gas[0].address} und {value.address} tauschen")
            else:
                self._bus.begin_change(
                    f"{len(gas)} GA nach Mittelgruppe {value[0]}/{value[1]} verschieben")
        if kind == "ga":
            changed = swap_addresses(self._project, gas[0], value)
        else:
            changed = move_to_middle_group(self._project, gas, *value)
        if not changed:
            return
        self._refresh_tree()
        self.ga_modified.emit()

    def _refresh_tree(self):
        self._building = True
        try:
            self._build_tree()
        finally:
            self._building = False
        fit_columns(self._tree, stretch_to_fit=False)

    def _build_tree(self):
        self._tree.clear()
        if not self._structure:
            return

        for hg in sorted(self._structure.main_groups, key=lambda m: m.number):
            hg_text = f"HG {hg.number} - {hg.name}"
            hg_item = QTreeWidgetItem(self._tree, [hg_text] + [""] * (_COLUMNS - 1))
            hg_item.setExpanded(True)
            hg_item.setData(0, Qt.UserRole, None)

            for mg in sorted(hg.middle_groups, key=lambda m: m.number):
                ga_count = len(mg.group_addresses)
                mg_text = f"MG {mg.number} - {mg.name}"
                mg_item = QTreeWidgetItem(
                    hg_item, [mg_text, f"{ga_count} Adressen"] + [""] * (_COLUMNS - 2)
                )
                mg_item.setExpanded(True)
                mg_item.setData(0, Qt.UserRole, None)
                mg_item.setData(0, self.MG_ROLE, (hg.number, mg.number))

                for ga in sorted(mg.group_addresses, key=lambda g: g.sub_group):
                    if ga.is_placeholder:
                        designation = "(Reserve)"
                    else:
                        # Sub → Description → Fallback, damit immer ein Text erscheint
                        designation = ga.designation or ga.description or "(keine Bezeichnung)"
                    timed = getattr(self, "_timed", {}).get(ga.id, [])
                    reworked = is_reworked(ga)
                    ga_item = QTreeWidgetItem(mg_item, [
                        ga.address,
                        designation,
                        " ".join(p for p in (self.TIMED_MARK if timed else "",
                                             ga.description) if p),
                        " ".join(p for p in (REWORKED_MARK if reworked else "",
                                             ga.function_name) if p),
                        ga.datapoint_type,
                        gewerk_display(ga),
                        ga.room_number,
                    ])
                    ga_item.setData(0, Qt.UserRole, ga.address)
                    ga_item.setData(0, self.GA_OBJECT_ROLE, ga)
                    ga_item.setFlags(ga_item.flags() | Qt.ItemIsEditable)
                    role = ga_functions.role_label(ga.function_name)
                    tip = f"Rolle: {role}" if role else ""
                    if reworked:
                        tip = "\n".join(p for p in (
                            tip, f"Nachbearbeitet – geplant war {ga.plan_function}") if p)
                    if tip:
                        ga_item.setToolTip(COL_FUNCTION, tip)
                    if timed:
                        ga_item.setToolTip(2, timed_label(timed))

                    # Farbmarkierung nach Gewerk-Kategorie
                    color = self._get_gewerk_color(ga.gewerk_code)
                    if color:
                        for col in range(_COLUMNS):
                            ga_item.setBackground(col, QBrush(QColor(color)))

                    if ga.is_placeholder:
                        for col in range(_COLUMNS):
                            ga_item.setForeground(col, QBrush(QColor("#757575")))

    def _get_gewerk_color(self, gewerk_code: str) -> str | None:
        """Gibt die Farbe basierend auf Gewerk-Kategorie zurück."""
        category_map = {
            "L": "licht", "LD": "licht", "LDA": "licht",
            "LC": "licht", "LCT": "licht", "LCW": "licht", "DMX": "licht",
            "S": "licht", "SD": "licht",
            "J": "jalousie", "R": "jalousie", "M": "jalousie", "T": "jalousie", "DF": "jalousie",
            "H": "heizung", "WP": "heizung",
            "LU": "lueftung", "KL": "lueftung", "V": "lueftung",
            "EV": "energie", "PV": "energie", "SP": "energie", "E": "energie",
            "A": "alarm", "RK": "alarm", "FK": "alarm", "TK": "alarm",
        }
        category = category_map.get(gewerk_code, "")
        return GEWERK_COLORS.get(category)

    def _expand_all(self):
        self._tree.expandAll()
        fit_columns(self._tree, stretch_to_fit=False)

    def _collapse_all(self):
        """Nur MG zuklappen – HG-Ebene bleibt sichtbar."""
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            hg_item = root.child(i)
            hg_item.setExpanded(True)
            for j in range(hg_item.childCount()):
                hg_item.child(j).setExpanded(False)
        fit_columns(self._tree, stretch_to_fit=False)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        address = item.data(0, Qt.UserRole)
        if address:
            self.address_selected.emit(address)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Oeffnet den Bearbeitungsdialog per Doppelklick auf eine GA."""
        ga = item.data(0, self.GA_OBJECT_ROLE)
        if isinstance(ga, GroupAddress):
            self._edit_ga(ga)

    def _show_context_menu(self, pos):
        """Kontextmenue mit Bearbeiten-Option."""
        item = self._tree.itemAt(pos)
        if not item:
            return
        global_pos = self._tree.viewport().mapToGlobal(pos)
        ga = item.data(0, self.GA_OBJECT_ROLE)
        menu = QMenu(self)
        if isinstance(ga, GroupAddress):
            selected_gas = self._selected_gas()
            if ga not in selected_gas:
                selected_gas = [ga]
            selected = [g.address for g in selected_gas]
            edit_action = menu.addAction(
                f"Bearbeiten… ({len(selected)} GA)" if len(selected) > 1 else "Bearbeiten…")
            reworked = [g for g in selected_gas if is_reworked(g)]
            reset_action = None
            if reworked and self._project is not None:
                reset_action = menu.addAction(
                    f"Auf Planung zurücksetzen ({len(reworked)} GA)" if len(reworked) > 1
                    else f"Auf Planung zurücksetzen ({reworked[0].plan_function})")
            profile_action = None
            if self._project is not None and can_set_profile(self._project, ga):
                profile_action = menu.addAction("Funktionsumfang des Elements…")
            scene_action = None
            if (self._project is not None and not ga.is_placeholder
                    and ga.function_name != "SZENE"):
                scene_action = menu.addAction("Zur Szene hinzufügen…")
            gewerk_action = menu.addAction(
                f"Gewerk zuordnen… ({len(selected)} GA)" if len(selected) > 1
                else "Gewerk zuordnen…")
            if not ga.is_placeholder:
                add_topology_menu(menu, ga.address, self.linked_devices,
                                  self.device_requested.emit)
            restore_action = None
            function = omitted_function_of(ga)
            if function and self._project is not None:
                restore_action = menu.addAction(f"Funktion «{function}» wieder einschalten")
            menu.addSeparator()
            delete_action = menu.addAction(
                f"Löschen… ({len(selected)} GA)" if len(selected) > 1 else "Löschen…")
            delete_action.setEnabled(self._project is not None)
            action = menu.exec(global_pos)
            if action == edit_action:
                if len(selected_gas) > 1 and self._project is not None:
                    self._edit_many(selected_gas)
                else:
                    self._edit_ga(ga)
            elif reset_action is not None and action == reset_action:
                self._reset_to_plan(reworked)
            elif profile_action is not None and action == profile_action:
                self._choose_profile(ga)
            elif scene_action is not None and action == scene_action:
                self._edit_scenes(ga)
            elif action == gewerk_action:
                self.gewerk_change_requested.emit(selected)
            elif restore_action is not None and action == restore_action:
                self._restore_function(ga, function)
            elif action == delete_action:
                self._delete_selected(fallback=ga)
        else:
            # HG- oder MG-Knoten: Auf-/Zuklappen anbieten
            expand_act  = menu.addAction("Aufklappen")
            collapse_act = menu.addAction("Zuklappen")
            action = menu.exec(global_pos)
            if action == expand_act:
                item.setExpanded(True)
                fit_columns(self._tree, stretch_to_fit=False)
            elif action == collapse_act:
                item.setExpanded(False)

    def _selected_gas(self) -> list[GroupAddress]:
        return [i.data(0, self.GA_OBJECT_ROLE) for i in self._tree.selectedItems()
                if isinstance(i.data(0, self.GA_OBJECT_ROLE), GroupAddress)]

    def _delete_selected(self, fallback: GroupAddress | None = None) -> None:
        """Markierte GAs löschen: generierte werden zur Reserve (Funktion
        weggelassen), manuelle und importierte entfernt – mit Rückfrage."""
        if self._project is None:
            return
        gas = self._selected_gas()
        if fallback is not None and fallback not in gas:
            gas = [fallback]
        if not gas:
            return
        kinds = [classify(self._project, ga) for ga in gas]
        n_generated = sum(1 for kind, _r in kinds if kind == GENERATED)
        n_deleted = sum(1 for kind, _r in kinds if kind == DELETABLE)
        kept = [(ga, reason) for ga, (kind, reason) in zip(gas, kinds)
                if kind not in (GENERATED, DELETABLE)]
        if not n_generated and not n_deleted:
            QMessageBox.information(
                self, "Löschen",
                "Nichts zu löschen:\n\n" + "\n".join(
                    f"{ga.address}: {reason}" for ga, reason in kept[:10]))
            return
        lines = []
        if n_deleted:
            text = (f"{n_deleted} GA werden entfernt, ebenso ihre Verknüpfungen "
                    f"(Tasten, Szenen, DALI, Zeitprogramme, Kommunikationsobjekte).")
            if self._project.topology.is_imported:
                text += " Die ETS bleibt massgebend: ein erneuter Import bringt sie zurück."
            lines.append(text)
        if n_generated:
            lines.append(f"{n_generated} GA entstehen aus einem Gewerk: ihre Funktion wird "
                         f"für das Element weggelassen, die Adresse bleibt als Reserve «--» "
                         f"frei, die übrigen Adressen verschieben sich nicht.")
        if kept:
            lines.append(f"{len(kept)} GA bleiben ({kept[0][1]}).")
        first = gas[0]
        title = (f"GA {first.address} »{first.designation}« löschen?" if len(gas) == 1
                 else f"{len(gas)} GA löschen?")
        if QMessageBox.question(
                self, "GA löschen", title + "\n\n" + "\n\n".join(lines),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if self._bus:
            self._bus.begin_change(title.rstrip("?"))
        delete_gas(self._project, gas)
        self._structure = self._project.group_addresses
        self._refresh_tree()
        self.ga_modified.emit()

    def _restore_function(self, ga: GroupAddress, function: str) -> None:
        if self._bus:
            self._bus.begin_change(f"Funktion {function} auf {ga.address} wieder einschalten")
        if restore_function(self._project, ga):
            self._structure = self._project.group_addresses
            self._refresh_tree()
            self.ga_modified.emit()

    def _edit_ga(self, ga: GroupAddress):
        """Oeffnet den GA-Bearbeitungsdialog."""
        if self._bus:
            self._bus.begin_change(f"GA {ga.address} »{ga.designation}« bearbeiten")
        dialog = GaEditDialog(ga, parent=self, project=self._project)
        if dialog.exec() == GaEditDialog.Accepted:
            self._after_edit(dialog.result_info)

    def _edit_many(self, gas: list[GroupAddress]) -> None:
        """Sammeldialog für mehrere markierte GAs (FA-1003b)."""
        if self._bus:
            self._bus.begin_change(f"{len(gas)} GA bearbeiten")
        dialog = GaBulkEditDialog(self._project, gas, parent=self)
        if dialog.exec() == GaBulkEditDialog.Accepted:
            self._after_edit(dialog.result_info)

    def _can_edit(self, ga: GroupAddress, field: str) -> bool:
        return self._project is not None and field in editable_fields(self._project, ga)

    def _commit_inline(self, item: QTreeWidgetItem, field: str, value) -> None:
        """Wert aus der Zelle für die bearbeitete GA und alle mit ihr markierten."""
        ga = item.data(0, self.GA_OBJECT_ROLE) if item else None
        if not isinstance(ga, GroupAddress) or self._project is None:
            return
        gas = self._selected_gas()
        if ga not in gas:
            gas = [ga]
        targets = [g for g in gas if getattr(g, field) != value
                   and field in editable_fields(self._project, g)]
        if not targets:
            return
        if self._bus:
            label = {"function_name": "Funktion", "datapoint_type": "DPT",
                     "description": "Beschreibung"}[field]
            self._bus.begin_change(
                f"{label} von {len(targets)} GA setzen" if len(targets) > 1
                else f"{label} von GA {ga.address} setzen")
        result = apply_changes(self._project, targets, {field: value})
        # Baum erst neu aufbauen, wenn der Editor geschlossen ist
        QTimer.singleShot(0, lambda: self._after_edit(result))

    def _edit_scenes(self, ga: GroupAddress) -> None:
        """GA in Szenen aufnehmen, mit Wert je Szene (FA-1816)."""
        dialog = GaSceneDialog(self._project, ga, parent=self)
        if dialog.exec() != GaSceneDialog.Accepted:
            return
        if self._bus:
            self._bus.begin_change(f"GA {ga.address} in Szenen")
        from ...services.scene_membership import set_scene_values
        if set_scene_values(self._project, ga, dialog.values()) and self._bus:
            self._bus.any_change.emit("scenes")

    def _choose_profile(self, ga: GroupAddress) -> None:
        """Funktionsumfang des Elements wählen (FA-1003d), z.B. Heizung nur Ein/Aus."""
        assignment, nr = element_of(self._project, ga)
        if assignment is None:
            return
        keys = list(PROFILE_LABELS)
        current = assignment.element_profiles.get(nr, "")
        name = ga.designation.split(" ", 1)[0]
        label, ok = QInputDialog.getItem(
            self, "Funktionsumfang",
            f"Element {name}:\n\nDie Adressen bleiben. Nicht benötigte Funktionen werden "
            f"Reserve. Bei Schalten bekommt das Element einen Schaltaktor-Kanal.",
            [PROFILE_LABELS[k] for k in keys], keys.index(current), False)
        if not ok:
            return
        profile = keys[[PROFILE_LABELS[k] for k in keys].index(label)]
        if profile == current:
            return
        if self._bus:
            self._bus.begin_change(f"Funktionsumfang {name}: {label}")
        if set_element_profile(self._project, ga, profile):
            self._after_edit()

    def _reset_to_plan(self, gas: list[GroupAddress]) -> None:
        if self._bus:
            self._bus.begin_change(f"{len(gas)} GA auf Planung zurücksetzen")
        if reset_to_plan(self._project, gas):
            self._after_edit()

    def _after_edit(self, result=None) -> None:
        if self._project is not None:
            self._structure = self._project.group_addresses
        self._refresh_tree()
        self.ga_modified.emit()
        if result is not None and result.skipped:
            QMessageBox.information(
                self, "GA bearbeiten",
                f"{len(result.skipped)} GA nicht geändert:\n\n" + "\n".join(
                    f"{address}: {reason}" for address, reason in result.skipped[:10]))

    def _on_category_changed(self, category: str):
        self._active_category = category
        self._apply_filter()

    def _apply_filter(self, _text=None):
        search = self._search_bar.search_text.lower()
        allowed_codes = self._CATEGORY_CODES.get(self._active_category) if self._active_category else None
        self._filter_tree_items(self._tree.invisibleRootItem(), search, allowed_codes)

    def _filter_tree_items(self, parent: QTreeWidgetItem, search: str, allowed_codes: set | None):
        for i in range(parent.childCount()):
            item = parent.child(i)
            # Rekursiv filtern
            self._filter_tree_items(item, search, allowed_codes)
            has_visible_children = any(
                not item.child(j).isHidden() for j in range(item.childCount())
            )

            if item.childCount() == 0:
                # Blatt-Element (GA): Text- und Kategorie-Prüfung kombinieren
                text_ok = (not search) or any(
                    search in item.text(col).lower() for col in range(_COLUMNS)
                )
                cat_ok = (allowed_codes is None) or (item.text(COL_GEWERK) in allowed_codes)
                item.setHidden(not (text_ok and cat_ok))
            else:
                # HG / MG: sichtbar wenn mindestens ein Kind sichtbar ist
                item.setHidden(not has_visible_children)
