"""
Inbetriebnahme-Checklisten-View (FA-1901/1904).

Erlaubt das Erfassen von Prüfergebnissen direkt in der Software.
Resultate werden in project.checklists persistiert und beim Excel-Export
als ausgefüllte Zellen ausgegeben.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QComboBox, QLineEdit, QSplitter, QGroupBox, QProgressBar,
    QMessageBox, QAbstractItemView, QHeaderView, QFileDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush

from ...models.project import KnxProject
from ...models.documentation import (
    CommissioningChecklist, ChecklistItem,
    ITEM_KIND_DEVICE, ITEM_KIND_FUNCTION,
    RESULT_OK, RESULT_DEFECT, RESULT_NA, RESULT_OPEN, RESULT_CHOICES,
)
from ...services.documentation_service import DocumentationService

# Ergebnis-Anzeige
_RESULT_DISPLAY = {
    RESULT_OPEN:   "—",
    RESULT_OK:     "✓ OK",
    RESULT_DEFECT: "⚠ Mangel",
    RESULT_NA:     "n/a",
}

# Farben je Ergebnis
_RESULT_COLORS = {
    RESULT_OK:     "#1B5E20",
    RESULT_DEFECT: "#B71C1C",
    RESULT_NA:     "#757575",
    RESULT_OPEN:   "",
}

# Tabellenkolumnen
_COL_KIND  = 0
_COL_CHECK = 1
_COL_DESC  = 2
_COL_GA    = 3
_COL_RES   = 4
_COL_NOTES = 5
_NUM_COLS  = 6

_TYPE_ROOM = "room"
_TYPE_BE   = "be"


class CommissioningView(QWidget):
    """Hauptansicht für Inbetriebnahme-Checklisten (FA-1901)."""

    checklist_changed = Signal()

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._current_cl: CommissioningChecklist | None = None
        self._current_be_id: str | None = None
        self._populating = False   # verhindert Signalschleifen beim Befüllen

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 6, 8, 4)
        title = QLabel("<b>Inbetriebnahme-Checkliste</b>")
        title.setStyleSheet("font-size: 14px;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._btn_init = QPushButton("Checkliste erstellen")
        self._btn_init.setToolTip(
            "Generiert Prüfpunkte aus aktuellem Projektstand.\n"
            "Nur beim ersten Mal – danach werden Ergebnisse nie überschrieben."
        )
        self._btn_init.clicked.connect(self._init_checklists)
        hdr.addWidget(self._btn_init)

        self._btn_sync = QPushButton("Abgleichen")
        self._btn_sync.setToolTip(
            "Neue Räume/BEs/GAs werden hinzugefügt.\n"
            "Bestehende Items mit Ergebnissen bleiben unverändert."
        )
        self._btn_sync.clicked.connect(self._sync_checklists)
        hdr.addWidget(self._btn_sync)

        self._btn_export = QPushButton("Excel exportieren…")
        self._btn_export.clicked.connect(self._export_excel)
        hdr.addWidget(self._btn_export)

        layout.addLayout(hdr)

        # ── Fortschrittsleiste ────────────────────────────────────────────────
        prog_box = QGroupBox()
        prog_box.setStyleSheet("QGroupBox { margin: 0; padding: 4px; }")
        prog_layout = QHBoxLayout(prog_box)
        prog_layout.setContentsMargins(8, 4, 8, 4)

        self._lbl_stats = QLabel()
        prog_layout.addWidget(self._lbl_stats)

        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.setMinimumWidth(200)
        prog_layout.addWidget(self._progress, 1)

        layout.addWidget(prog_box)

        # ── Splitter: Baum | Tabelle ──────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)

        # Raum-/BE-Baum
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(200)
        self._tree.setMaximumWidth(320)
        self._tree.currentItemChanged.connect(self._on_tree_selection)
        splitter.addWidget(self._tree)

        # Rechte Seite: Label + Bulk-Toolbar + Tabelle
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Kontext-Label (welcher Raum / welches BE)
        self._be_label = QLabel()
        self._be_label.setStyleSheet(
            "font-weight: bold; font-size: 12px; padding: 5px 10px;"
            "background: #E8F5E9; border-bottom: 1px solid #C8E6C9;"
        )
        right_layout.addWidget(self._be_label)

        # Bulk-Toolbar
        bulk_bar = QWidget()
        bulk_bar.setStyleSheet("background: #F5F5F5; border-bottom: 1px solid #E0E0E0;")
        bulk_layout = QHBoxLayout(bulk_bar)
        bulk_layout.setContentsMargins(8, 4, 8, 4)
        bulk_layout.setSpacing(6)

        bulk_layout.addWidget(QLabel("Auswahl setzen:"))

        self._bulk_combo = QComboBox()
        for r in RESULT_CHOICES:
            self._bulk_combo.addItem(_RESULT_DISPLAY[r], userData=r)
        self._bulk_combo.setFixedWidth(110)
        bulk_layout.addWidget(self._bulk_combo)

        btn_apply_sel = QPushButton("Markierte Zeilen")
        btn_apply_sel.setToolTip("Ergebnis auf alle markierten Zeilen anwenden")
        btn_apply_sel.clicked.connect(self._bulk_apply_selected)
        bulk_layout.addWidget(btn_apply_sel)

        btn_apply_all = QPushButton("Alle sichtbaren")
        btn_apply_all.setToolTip("Ergebnis auf alle aktuell angezeigten Zeilen anwenden")
        btn_apply_all.clicked.connect(self._bulk_apply_all)
        bulk_layout.addWidget(btn_apply_all)

        bulk_layout.addStretch()

        lbl_hint = QLabel("Notiz: direkt in Zelle tippen")
        lbl_hint.setStyleSheet("color: #888; font-size: 10px;")
        bulk_layout.addWidget(lbl_hint)

        right_layout.addWidget(bulk_bar)

        # Tabelle
        self._table = QTableWidget()
        self._table.setColumnCount(_NUM_COLS)
        self._table.setHorizontalHeaderLabels([
            "Art", "Prüfpunkt / Kanal", "Beschreibung / Funktion",
            "GA-Bezeichnung", "Ergebnis", "Notiz",
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Nur Notiz-Spalte editierbar
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.AnyKeyPressed)
        self._table.setColumnWidth(_COL_KIND,  36)
        self._table.setColumnWidth(_COL_CHECK, 130)
        self._table.setColumnWidth(_COL_DESC,  200)
        self._table.setColumnWidth(_COL_GA,    170)
        self._table.setColumnWidth(_COL_RES,   110)
        self._table.itemChanged.connect(self._on_notes_edited)

        right_layout.addWidget(self._table, 1)
        splitter.addWidget(right)
        splitter.setSizes([240, 820])
        layout.addWidget(splitter, 1)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def set_project(self, project: KnxProject):
        self._project = project
        self.refresh()

    def refresh(self):
        self._current_cl = None
        self._current_be_id = None
        self._rebuild_tree()
        self._update_progress()
        self._table.setRowCount(0)
        self._be_label.setText(
            "Kein Projekt geladen" if not self._project.checklists
            else "← Raum oder Bedienelement auswählen"
        )

    # ── Baum ─────────────────────────────────────────────────────────────────

    def _rebuild_tree(self):
        self._tree.blockSignals(True)
        self._tree.clear()
        for cl in self._project.checklists:
            room_node = QTreeWidgetItem([cl.room_name])
            room_node.setData(0, Qt.UserRole, (_TYPE_ROOM, cl.room_id))
            self._tree.addTopLevelItem(room_node)

            # Stabiler Schlüssel: (be_type, be_number) — be_id ändert sich bei Rebuild
            seen_be: dict[tuple, QTreeWidgetItem] = {}
            for item in cl.items:
                if not item.be_type and not item.be_number:
                    continue
                key = (item.be_type, item.be_number)
                if key not in seen_be:
                    label = self._be_label_for(item)
                    be_node = QTreeWidgetItem([label])
                    be_node.setData(0, Qt.UserRole, (_TYPE_BE, cl.room_id, item.be_type, item.be_number))
                    room_node.addChild(be_node)
                    seen_be[key] = be_node

            self._recolor_room_node(room_node, cl)

        self._tree.expandAll()
        self._tree.blockSignals(False)

    @staticmethod
    def _be_label_for(first_item: ChecklistItem) -> str:
        """Stabiles Label aus be_type + be_number."""
        label = first_item.be_type or "BE"
        if first_item.be_number:
            label += f"  [{first_item.be_number}]"
        return label

    def _recolor_room_node(self, room_node: QTreeWidgetItem,
                           cl: CommissioningChecklist):
        for j in range(room_node.childCount()):
            be_node = room_node.child(j)
            be_data = be_node.data(0, Qt.UserRole)
            if be_data and len(be_data) == 4:
                be_type, be_number = be_data[2], be_data[3]
                be_items = [i for i in cl.items
                            if i.be_type == be_type and i.be_number == be_number]
                self._color_node(be_node, be_items)
        self._color_node(room_node, cl.items)

    @staticmethod
    def _color_node(node: QTreeWidgetItem, items: list[ChecklistItem]):
        results = {i.result for i in items if i.result}
        if not results:
            color = "#888"
        elif RESULT_DEFECT in results:
            color = "#B71C1C"
        elif all(r in (RESULT_OK, RESULT_NA) for r in results):
            color = "#1B5E20"
        else:
            color = "#E65100"
        node.setForeground(0, QBrush(QColor(color)))

    def _on_tree_selection(self, current: QTreeWidgetItem, _prev):
        if not current:
            return
        data = current.data(0, Qt.UserRole)
        if not data:
            return

        if data[0] == _TYPE_ROOM:
            cl = self._cl_by_room(data[1])
            if not cl:
                return
            self._current_cl = cl
            self._current_be_id = None
            self._be_label.setText(cl.room_name)
            self._populate_table(cl.items)

        elif data[0] == _TYPE_BE:
            cl = self._cl_by_room(data[1])
            if not cl:
                return
            be_type, be_number = data[2], data[3]
            be_items = [i for i in cl.items
                        if i.be_type == be_type and i.be_number == be_number]
            self._current_cl = cl
            self._current_be_id = None
            label = self._be_label_for(be_items[0]) if be_items else f"{be_type} [{be_number}]"
            self._be_label.setText(f"{cl.room_name}  ▸  {label}")
            self._populate_table(be_items)

    def _cl_by_room(self, room_id: str) -> CommissioningChecklist | None:
        return next((c for c in self._project.checklists if c.room_id == room_id), None)

    # ── Tabelle ───────────────────────────────────────────────────────────────

    def _populate_table(self, items: list[ChecklistItem]):
        self._populating = True
        self._table.setRowCount(0)
        self._table.setRowCount(len(items))

        for row, item in enumerate(items):
            # Spalten A–D: nur lesen
            kind_icon = "⚙" if item.item_kind == ITEM_KIND_DEVICE else "⚡"
            for col, text in [
                (_COL_KIND,  kind_icon),
                (_COL_CHECK, item.check_type),
                (_COL_DESC,  item.description),
                (_COL_GA,    item.function_ga),
            ]:
                cell = QTableWidgetItem(text)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                if col == _COL_KIND:
                    cell.setData(Qt.UserRole, item.id)   # Anker für Zeilen-Lookup
                self._table.setItem(row, col, cell)

            # Spalte E: Ergebnis — Inline-ComboBox
            combo = QComboBox()
            for r in RESULT_CHOICES:
                combo.addItem(_RESULT_DISPLAY[r], userData=r)
            idx = combo.findData(item.result)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._apply_combo_color(combo, item.result)
            combo.currentIndexChanged.connect(
                lambda _i, it=item, cb=combo: self._on_combo_changed(it, cb)
            )
            self._table.setCellWidget(row, _COL_RES, combo)

            # Spalte F: Notiz — direkt editierbar
            notes_cell = QTableWidgetItem(item.notes)
            notes_cell.setData(Qt.UserRole, item.id)
            self._table.setItem(row, _COL_NOTES, notes_cell)

        self._table.resizeRowsToContents()
        self._populating = False

    @staticmethod
    def _apply_combo_color(combo: QComboBox, result: str):
        color = _RESULT_COLORS.get(result, "")
        combo.setStyleSheet(
            f"QComboBox {{ color: {color}; font-weight: bold; }}" if color
            else "QComboBox { color: #333; }"
        )

    # ── Ergebnis erfassen ─────────────────────────────────────────────────────

    def _on_combo_changed(self, cl_item: ChecklistItem, combo: QComboBox):
        if self._populating:
            return
        new_result = combo.currentData()
        cl_item.result = new_result
        self._apply_combo_color(combo, new_result)
        self._update_progress()
        self._refresh_current_tree_node()
        self.checklist_changed.emit()

    def _on_notes_edited(self, cell: QTableWidgetItem):
        if self._populating or cell.column() != _COL_NOTES:
            return
        item_id = cell.data(Qt.UserRole)
        if not item_id:
            return
        cl_item = self._find_item(item_id)
        if cl_item:
            cl_item.notes = cell.text()
            self.checklist_changed.emit()

    # ── Bulk-Aktionen ─────────────────────────────────────────────────────────

    def _bulk_apply_selected(self):
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        if not rows:
            QMessageBox.information(self, "Keine Auswahl",
                                    "Bitte zuerst Zeilen markieren (Klick / Shift+Klick).")
            return
        self._apply_bulk(sorted(rows))

    def _bulk_apply_all(self):
        self._apply_bulk(list(range(self._table.rowCount())))

    def _apply_bulk(self, rows: list[int]):
        result = self._bulk_combo.currentData()
        for row in rows:
            kind_cell = self._table.item(row, _COL_KIND)
            if not kind_cell:
                continue
            item_id = kind_cell.data(Qt.UserRole)
            cl_item = self._find_item(item_id)
            if cl_item is None:
                continue
            cl_item.result = result
            combo = self._table.cellWidget(row, _COL_RES)
            if isinstance(combo, QComboBox):
                idx = combo.findData(result)
                self._populating = True
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                self._populating = False
                self._apply_combo_color(combo, result)

        self._update_progress()
        self._refresh_current_tree_node()
        self.checklist_changed.emit()

    # ── Hilfsmethoden ─────────────────────────────────────────────────────────

    def _find_item(self, item_id: str) -> ChecklistItem | None:
        for cl in self._project.checklists:
            for item in cl.items:
                if item.id == item_id:
                    return item
        return None

    def _refresh_current_tree_node(self):
        node = self._tree.currentItem()
        if not node:
            return
        data = node.data(0, Qt.UserRole)
        if not data or len(data) < 2:
            return
        cl = self._cl_by_room(data[1])
        if not cl:
            return
        room_node = node.parent() if node.parent() else node
        self._recolor_room_node(room_node, cl)

    # ── Fortschritt ───────────────────────────────────────────────────────────

    def _update_progress(self):
        all_items = [i for cl in self._project.checklists for i in cl.items]
        total  = len(all_items)
        ok     = sum(1 for i in all_items if i.result == RESULT_OK)
        defect = sum(1 for i in all_items if i.result == RESULT_DEFECT)
        na     = sum(1 for i in all_items if i.result == RESULT_NA)
        done   = ok + defect + na

        self._progress.setMaximum(max(total, 1))
        self._progress.setValue(done)
        self._progress.setFormat(f"{done} / {total}")

        color = "#1B5E20" if defect == 0 and done == total and total > 0 else \
                "#B71C1C" if defect > 0 else "#1565C0"
        self._progress.setStyleSheet(
            f"QProgressBar::chunk {{ background: {color}; }}"
        )
        self._lbl_stats.setText(
            f"<span style='color:#1B5E20'>✓ {ok} OK</span>  "
            f"<span style='color:#B71C1C'>⚠ {defect} Mangel</span>  "
            f"<span style='color:#555'>– {na} n/a</span>  "
            f"<span style='color:#888'>○ {total - done} offen</span>   "
        )

    # ── Aktionen ──────────────────────────────────────────────────────────────

    def _init_checklists(self):
        if self._project.checklists:
            if QMessageBox.question(
                self, "Checkliste vorhanden",
                "Es sind bereits Checklisten gespeichert.\n\n"
                "Möchten Sie stattdessen 'Abgleichen' verwenden,\n"
                "um nur neue Punkte hinzuzufügen?",
                QMessageBox.Yes | QMessageBox.No,
            ) == QMessageBox.Yes:
                self._sync_checklists()
                return

        svc = DocumentationService(self._project)
        n = svc.init_project_checklists()
        self.refresh()
        QMessageBox.information(
            self, "Checkliste erstellt",
            f"{n} Prüfpunkte aus aktuellem Projektstand generiert."
        )
        self.checklist_changed.emit()

    def _sync_checklists(self):
        svc = DocumentationService(self._project)
        added, total = svc.sync_project_checklists()
        self.refresh()
        QMessageBox.information(
            self, "Abgleich abgeschlossen",
            f"{added} neue Prüfpunkte hinzugefügt.\n"
            f"Gesamt: {total} Prüfpunkte.\n\n"
            "Bestehende Ergebnisse wurden nicht verändert."
        )
        self.checklist_changed.emit()

    def _export_excel(self):
        if not self._project.checklists:
            QMessageBox.information(self, "Keine Checkliste",
                                    "Erstellen Sie zuerst eine Checkliste.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Checkliste exportieren",
            f"{self._project.name}_Checklisten.xlsx",
            "Excel-Dateien (*.xlsx)",
        )
        if not path:
            return
        DocumentationService(self._project).export_checklists_excel(path)
        QMessageBox.information(self, "Exportiert", f"Gespeichert: {path}")
