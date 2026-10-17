"""
Eintrag in einem QTreeWidget anwählen: Eltern aufklappen, markieren, in die
Mitte scrollen (Sprung aus der Validierung, FA-615a).
"""
from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItemIterator


def select_tree_item(tree: QTreeWidget, predicate):
    """Wählt den ersten Eintrag, für den predicate(item) gilt. Gibt ihn zurück,
    None wenn keiner passt."""
    it = QTreeWidgetItemIterator(tree)
    while it.value():
        item = it.value()
        if predicate(item):
            parent = item.parent()
            while parent is not None:
                parent.setHidden(False)
                parent.setExpanded(True)
                parent = parent.parent()
            item.setHidden(False)
            tree.clearSelection()
            tree.setCurrentItem(item)
            item.setSelected(True)
            tree.scrollToItem(item, QAbstractItemView.PositionAtCenter)
            tree.setFocus()
            return item
        it += 1
    return None
