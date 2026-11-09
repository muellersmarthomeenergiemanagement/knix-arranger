"""
Lange Texte in einem QTreeWidget umbrechen.

QTreeView bricht mit setWordWrap um, berechnet die Zeilenhöhe aber nicht aus
der aktuellen Spaltenbreite -- der Text wird abgeschnitten ("nic..."). Der
Delegate rechnet die Höhe aus der Spaltenbreite (in Spalte 0 abzüglich der
Einrückung); ändert sich die Breite, werden die Zeilen neu angeordnet.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtWidgets import QStyledItemDelegate

_PADDING = 10


class WrapDelegate(QStyledItemDelegate):
    def __init__(self, tree):
        super().__init__(tree)
        self._tree = tree

    def _indent(self, index) -> int:
        if index.column() != 0:
            return 0
        depth, parent = 0, index.parent()
        while parent.isValid():
            depth += 1
            parent = parent.parent()
        tree = self._tree
        return (depth + (1 if tree.rootIsDecorated() else 0)) * tree.indentation()

    def text_width(self, index) -> int:
        return self._tree.columnWidth(index.column()) - self._indent(index) - _PADDING

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        text = index.data(Qt.DisplayRole)
        width = self.text_width(index)
        if not text or width <= 40:
            return size
        rect = option.fontMetrics.boundingRect(
            QRect(0, 0, width, 100000), Qt.TextWordWrap, str(text))
        return QSize(size.width(), max(size.height(), rect.height() + 6))


def enable_word_wrap(tree) -> WrapDelegate:
    """Umbruch einschalten; Zeilenhöhen folgen der Spaltenbreite."""
    tree.setWordWrap(True)
    tree.setUniformRowHeights(False)
    tree.setTextElideMode(Qt.ElideNone)
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    delegate = WrapDelegate(tree)
    tree.setItemDelegate(delegate)
    timer = QTimer(tree)
    timer.setSingleShot(True)
    timer.setInterval(50)
    timer.timeout.connect(tree.doItemsLayout)
    tree.header().sectionResized.connect(lambda *_a: timer.start())
    return delegate
