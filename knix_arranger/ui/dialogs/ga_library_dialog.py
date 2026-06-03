"""
GA-Vorlagen-Bibliothek Dialog (FA-435)
Zeigt gespeicherte GA-Vorlagen und erlaubt Auswahl zum Einfügen oder Löschen.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QAbstractItemView, QMessageBox,
)
from PySide6.QtCore import Qt

from ...services import ga_library_service


class GALibraryDialog(QDialog):
    """Dialog zum Auswählen und Verwalten von GA-Vorlagen."""

    def __init__(self, entries: list[dict], parent=None):
        super().__init__(parent)
        self.selected_entries: list[dict] = []
        self._entries = list(entries)  # lokale Kopie
        self.setWindowTitle("GA-Vorlagen-Bibliothek")
        self.setMinimumWidth(560)
        self.setMinimumHeight(380)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Vorlagen auswählen und einfügen. "
            "Mehrfachauswahl mit Strg/Shift möglich."
        ))

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list.itemDoubleClicked.connect(self._insert)
        self._refresh_list()
        layout.addWidget(self._list)

        # Buttons
        btn_layout = QHBoxLayout()

        self._btn_delete = QPushButton("Vorlage löschen")
        self._btn_delete.setObjectName("secondary")
        self._btn_delete.clicked.connect(self._delete_selected)
        btn_layout.addWidget(self._btn_delete)

        btn_layout.addStretch()

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        insert_btn = QPushButton("Einfügen")
        insert_btn.setDefault(True)
        insert_btn.clicked.connect(self._insert)
        btn_layout.addWidget(insert_btn)

        layout.addLayout(btn_layout)

    def _refresh_list(self):
        self._list.clear()
        for entry in self._entries:
            addr = (
                f"{entry.get('main_group', 0)}/"
                f"{entry.get('middle_group', 0)}/"
                f"{entry.get('sub_group', 0)}"
            )
            label = f"{entry.get('name', '?')}  [{addr}]  {entry.get('designation', '')}"
            self._list.addItem(QListWidgetItem(label))

    def _delete_selected(self):
        rows = sorted(
            [self._list.row(item) for item in self._list.selectedItems()],
            reverse=True,
        )
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._entries):
                ga_library_service.remove_entry(row)
                self._entries.pop(row)
        self._refresh_list()

    def _insert(self):
        rows = [self._list.row(item) for item in self._list.selectedItems()]
        if not rows:
            QMessageBox.information(
                self, "Hinweis", "Bitte mindestens eine Vorlage auswählen."
            )
            return
        self.selected_entries = [
            self._entries[r] for r in rows if 0 <= r < len(self._entries)
        ]
        self.accept()
