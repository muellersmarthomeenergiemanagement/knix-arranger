"""
ETS-Arbeitsliste in KNiX (FA-618, Sprünge FA-1011l): offene Aufgaben nach
Priorität; Doppelklick springt zum Gerät oder zur GA, Rechtsklick zeigt alle
Ziele. Speichern als PDF oder Excel wie bisher.

Nicht modal: der Integrator springt in die Ansichten und arbeitet die Liste
nebenher ab.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QMenu, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from ...services import ets_worklist
from ...services.validation_targets import worklist_targets
from ..column_utils import fit_columns

_ITEM_ROLE = Qt.UserRole


class EtsWorklistDialog(QDialog):
    """on_jump(Target) springt, on_export() speichert als PDF/Excel."""

    def __init__(self, project, on_jump, on_export, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ETS-Arbeitsliste")
        self.resize(900, 560)
        self._project = project
        self._on_jump = on_jump

        layout = QVBoxLayout(self)
        hint = QLabel(ets_worklist.HOW_TO_USE + "  ·  Doppelklick: zum Gerät bzw. zur GA, "
                      "Rechtsklick: weitere Ziele.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Nr.", "Ort in der ETS", "Aufgabe", "Status"])
        self._tree.setWordWrap(True)
        self._tree.itemDoubleClicked.connect(lambda item, _c: self._jump(item))
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        save = QPushButton("Als PDF/Excel speichern…")
        save.clicked.connect(on_export)
        buttons.addButton(save, QDialogButtonBox.ActionRole)
        refresh = QPushButton("Aktualisieren")
        refresh.clicked.connect(self.refresh)
        buttons.addButton(refresh, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        """Liste zum aktuellen Projektstand (verändert das Projekt nicht)."""
        self._tree.clear()
        worklist = ets_worklist.build_worklist(self._project)
        for prio, rows in ets_worklist._numbered(worklist):
            if not rows:
                continue
            title, _explain = ets_worklist.PRIORITIES[prio]
            group = QTreeWidgetItem(self._tree, [f"{title} ({len(rows)})", "", "", ""])
            group.setFirstColumnSpanned(True)
            group.setExpanded(True)
            for n, item in rows:
                row = QTreeWidgetItem(group, [str(n), item.where,
                                              ets_worklist._task_text(item), item.status])
                row.setData(0, _ITEM_ROLE, item)
        if not worklist.items:
            QTreeWidgetItem(self._tree, ["", "", "Keine offenen Aufgaben.", ""])
        fit_columns(self._tree)

    def _targets(self, row) -> list:
        item = row.data(0, _ITEM_ROLE) if row is not None else None
        return worklist_targets(item, self._project) if item is not None else []

    def _jump(self, row) -> None:
        targets = self._targets(row)
        if targets:
            self._on_jump(targets[0])

    def _show_context_menu(self, pos) -> None:
        targets = self._targets(self._tree.itemAt(pos))
        if not targets:
            return
        menu = QMenu(self)
        for target in targets:
            menu.addAction(target.label, lambda t=target: self._on_jump(t))
        menu.setDefaultAction(menu.actions()[0])
        menu.exec(self._tree.viewport().mapToGlobal(pos))
