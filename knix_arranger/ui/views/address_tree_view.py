"""
GA-Baumansicht: HG > MG > UG mit Farbmarkierung (FA-821)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QMenu, QPushButton,
)
from PySide6.QtGui import QColor, QBrush
from PySide6.QtCore import Signal, Qt
from ..widgets.search_filter_bar import SearchFilterBar
from ..dialogs.ga_edit_dialog import GaEditDialog
from ..styles import GEWERK_COLORS
from ...models.group_address import GroupAddressStructure, GroupAddress
from ..column_utils import fit_columns


class AddressTreeView(QWidget):
    """GA-Baumansicht: Hauptgruppe > Mittelgruppe > Untergruppe."""

    address_selected = Signal(str)  # GA-Adresse z.B. "2/0/0"
    ga_modified = Signal()  # Emitted when a GA was edited

    # Qt.UserRole für Adress-String, UserRole+1 für GA-Objekt
    GA_OBJECT_ROLE = Qt.UserRole + 1

    # Gewerk-Codes je Filterkategorie
    _CATEGORY_CODES: dict[str, set[str]] = {
        "licht":    {"L", "LD", "LDA", "LC", "LCT", "LCW", "DMX", "S", "SD"},
        "jalousie": {"J", "R", "M", "T", "DF"},
        "heizung":  {"H", "WP", "TF"},
        "lueftung": {"LU", "KL", "V"},
        "energie":  {"EV", "PV", "SP", "E"},
        "alarm":    {"A", "RK", "FK", "TK"},
        "allgemein": {"G", "BW", "BL", "P", "W", "MM", "GS", "TE", "TVL", "LW", "FG", "F", "U"},
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._structure: GroupAddressStructure | None = None
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
        hint = QLabel("Doppelklick oder Rechtsklick auf eine GA zum Bearbeiten")
        hint.setStyleSheet("color: #808080; font-style: italic;")
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

        # Baum
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels([
            "Adresse", "Bezeichnung", "DPT", "Gewerk", "Raum",
        ])
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree)

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus."""
        self._bus = bus

    def set_structure(self, structure: GroupAddressStructure):
        """Setzt die anzuzeigende GA-Struktur."""
        self._structure = structure
        self._refresh_tree()

    def _refresh_tree(self):
        self._tree.clear()
        if not self._structure:
            return

        for hg in sorted(self._structure.main_groups, key=lambda m: m.number):
            hg_text = f"HG {hg.number} - {hg.name}"
            hg_item = QTreeWidgetItem(self._tree, [hg_text, "", "", "", ""])
            hg_item.setExpanded(True)
            hg_item.setData(0, Qt.UserRole, None)

            for mg in sorted(hg.middle_groups, key=lambda m: m.number):
                ga_count = len(mg.group_addresses)
                mg_text = f"MG {mg.number} - {mg.name}"
                mg_item = QTreeWidgetItem(
                    hg_item, [mg_text, f"{ga_count} Adressen", "", "", ""]
                )
                mg_item.setExpanded(True)
                mg_item.setData(0, Qt.UserRole, None)

                for ga in sorted(mg.group_addresses, key=lambda g: g.sub_group):
                    if ga.is_placeholder:
                        designation = "(Reserve)"
                    else:
                        # Sub → Description → Fallback, damit immer ein Text erscheint
                        designation = ga.designation or ga.description or "(keine Bezeichnung)"
                    ga_item = QTreeWidgetItem(mg_item, [
                        ga.address,
                        designation,
                        ga.datapoint_type,
                        ga.gewerk_code,
                        ga.room_number,
                    ])
                    ga_item.setData(0, Qt.UserRole, ga.address)
                    ga_item.setData(0, self.GA_OBJECT_ROLE, ga)

                    # Farbmarkierung nach Gewerk-Kategorie
                    color = self._get_gewerk_color(ga.gewerk_code)
                    if color:
                        for col in range(5):
                            ga_item.setBackground(col, QBrush(QColor(color)))

                    if ga.is_placeholder:
                        for col in range(5):
                            ga_item.setForeground(col, QBrush(QColor("#808080")))

        fit_columns(self._tree)

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
        fit_columns(self._tree)

    def _collapse_all(self):
        """Nur MG zuklappen – HG-Ebene bleibt sichtbar."""
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            hg_item = root.child(i)
            hg_item.setExpanded(True)
            for j in range(hg_item.childCount()):
                hg_item.child(j).setExpanded(False)
        fit_columns(self._tree)

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
            edit_action = menu.addAction("Bearbeiten…")
            action = menu.exec(global_pos)
            if action == edit_action:
                self._edit_ga(ga)
        else:
            # HG- oder MG-Knoten: Auf-/Zuklappen anbieten
            expand_act  = menu.addAction("Aufklappen")
            collapse_act = menu.addAction("Zuklappen")
            action = menu.exec(global_pos)
            if action == expand_act:
                item.setExpanded(True)
                fit_columns(self._tree)
            elif action == collapse_act:
                item.setExpanded(False)

    def _edit_ga(self, ga: GroupAddress):
        """Oeffnet den GA-Bearbeitungsdialog."""
        if self._bus:
            self._bus.begin_change(f"GA {ga.address} »{ga.designation}« bearbeiten")
        dialog = GaEditDialog(ga, parent=self)
        if dialog.exec() == GaEditDialog.Accepted:
            self._refresh_tree()
            self.ga_modified.emit()

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
                    search in item.text(col).lower() for col in range(5)
                )
                cat_ok = (allowed_codes is None) or (item.text(3) in allowed_codes)
                item.setHidden(not (text_ok and cat_ok))
            else:
                # HG / MG: sichtbar wenn mindestens ein Kind sichtbar ist
                item.setHidden(not has_visible_children)
