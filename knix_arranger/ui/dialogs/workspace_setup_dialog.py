"""
Ersteinrichtung des Arbeitsverzeichnisses (Workspace).

Wird beim allerersten Start gezeigt: Neue Projekte werden künftig verbindlich
in diesem Ordner angelegt (einheitliche Struktur für Projekte und Berichte).
"""
from __future__ import annotations
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QGroupBox,
)
from PySide6.QtCore import Qt, QStandardPaths
from ..styles import KNX_GREEN, KNX_DARK_GREEN


def suggested_workspace_path() -> str:
    """Liefert einen sinnvollen Vorschlag für das Arbeitsverzeichnis."""
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    base = docs or os.path.expanduser("~")
    return os.path.join(base, "KNX-Projekte")


class WorkspaceSetupDialog(QDialog):
    """Fragt einmalig den Wurzelordner für das Projekt-Arbeitsverzeichnis ab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Arbeitsverzeichnis einrichten")
        self.setMinimumSize(520, 260)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._path = suggested_workspace_path()

        layout = QVBoxLayout(self)

        intro = QLabel(
            "<b>Arbeitsverzeichnis für Projekte</b><br><br>"
            "Neue Projekte werden künftig in diesem Ordner angelegt – jeweils in "
            "einem eigenen Unterordner mit einheitlicher Struktur "
            "(Projektdatei, Revisionen, Berichte). So bleiben Projekte und "
            "Dokumentationen übersichtlich an einem Ort."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        path_group = QGroupBox("Speicherort")
        path_layout = QHBoxLayout()
        self._path_edit = QLineEdit(self._path)
        self._path_edit.setReadOnly(True)
        path_layout.addWidget(self._path_edit, 1)

        btn_choose = QPushButton("Ordner wählen…")
        btn_choose.clicked.connect(self._choose_folder)
        path_layout.addWidget(btn_choose)
        path_group.setLayout(path_layout)
        layout.addWidget(path_group)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_use = QPushButton("Verwenden")
        btn_use.setStyleSheet(
            f"QPushButton {{ background-color: {KNX_GREEN}; color: white; "
            f"font-weight: bold; border-radius: 4px; border: none; "
            f"padding: 8px 24px; }}"
            f"QPushButton:hover {{ background-color: {KNX_DARK_GREEN}; }}"
        )
        btn_use.clicked.connect(self._confirm)
        btn_row.addWidget(btn_use)
        layout.addLayout(btn_row)

    def _choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Arbeitsverzeichnis wählen", self._path
        )
        if chosen:
            self._path = chosen
            self._path_edit.setText(chosen)

    def _confirm(self):
        os.makedirs(self._path, exist_ok=True)
        self.accept()

    @property
    def workspace_path(self) -> str:
        return self._path
