"""
Spaltenfilter für Bäume: je Spalte ein Eingabefeld über dem Spaltenkopf.

Ein Eintrag passt, wenn jede ausgefüllte Spalte den Text enthält (Gross-/
Kleinschreibung egal). Passende Einträge bleiben samt Unterknoten sichtbar,
ihre übergeordneten Knoten als Zusammenhang und aufgeklappt.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLineEdit, QTreeWidget, QTreeWidgetItem, QWidget


class TreeColumnFilter(QWidget):
    """Filterzeile für ein QTreeWidget; Feldbreiten folgen den Spalten."""

    changed = Signal()

    def __init__(self, tree: QTreeWidget, parent=None):
        super().__init__(parent)
        self._tree = tree
        self._edits: list[QLineEdit] = []
        header = tree.header()
        for col in range(tree.columnCount()):
            # Ohne Layout: die Felder liegen genau über den Spalten und
            # scrollen mit, ohne dem Fenster eine Mindestbreite aufzuzwingen
            edit = QLineEdit(self)
            edit.setPlaceholderText(f"Filter {tree.headerItem().text(col)}")
            edit.setClearButtonEnabled(True)
            edit.textChanged.connect(self.apply)
            self._edits.append(edit)
        self.setFixedHeight(self._edits[0].sizeHint().height() if self._edits else 0)
        header.sectionResized.connect(lambda *_: self._sync_widths())
        tree.horizontalScrollBar().valueChanged.connect(lambda *_: self._sync_widths())
        QTimer.singleShot(0, self._sync_widths)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_widths()

    def _sync_widths(self) -> None:
        header = self._tree.header()
        # Rahmen des Baums: Felder bündig mit den Spaltenköpfen
        left = self._tree.frameWidth()
        for col, edit in enumerate(self._edits):
            width = header.sectionSize(col)
            edit.setGeometry(left + header.sectionViewportPosition(col), 0,
                             width, self.height())
            edit.setVisible(width > 0 and not header.isSectionHidden(col))

    def texts(self) -> list[str]:
        return [e.text().strip().lower() for e in self._edits]

    def set_text(self, column: int, text: str) -> None:
        self._edits[column].setText(text)

    def is_active(self) -> bool:
        return any(self.texts())

    def clear(self) -> None:
        for edit in self._edits:
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
        self.apply()

    def apply(self) -> None:
        """Filter auf den aktuellen Bauminhalt anwenden (auch nach Neuaufbau)."""
        texts = self.texts()
        active = any(texts)
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            self._filter_item(root.child(i), texts, active)
        self.changed.emit()

    def _filter_item(self, item: QTreeWidgetItem, texts: list[str], active: bool) -> bool:
        if not active or self._matches(item, texts):
            self._show_subtree(item)
            return True
        visible = False
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), texts, active):
                visible = True
        item.setHidden(not visible)
        if visible:
            item.setExpanded(True)
        return visible

    @staticmethod
    def _matches(item: QTreeWidgetItem, texts: list[str]) -> bool:
        return all(not t or t in item.text(col).lower() for col, t in enumerate(texts))

    def _show_subtree(self, item: QTreeWidgetItem) -> None:
        item.setHidden(False)
        for i in range(item.childCount()):
            self._show_subtree(item.child(i))
