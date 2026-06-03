"""
CSV Export-Dialog (FA-800)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QGroupBox, QCheckBox,
)
from PySide6.QtCore import Qt


class ExportDialog(QDialog):
    """Dialog für CSV Export."""

    def __init__(self, ga_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CSV Export")
        self.setMinimumSize(500, 260)
        self._filepath = ""

        layout = QVBoxLayout(self)

        # Info
        info = QLabel(f"{ga_count} Gruppenadressen werden exportiert.")
        info.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(info)

        # Datei
        file_group = QGroupBox("Zieldatei")
        file_layout = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Pfad für die CSV-Datei...")
        file_layout.addWidget(self._path_edit)

        btn_browse = QPushButton("Speichern unter...")
        btn_browse.clicked.connect(self._browse)
        file_layout.addWidget(btn_browse)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Optionen
        options_group = QGroupBox("Optionen")
        options_layout = QVBoxLayout()
        self._cb_overwrite = QCheckBox("Vorhandene Datei überschreiben")
        self._cb_placeholders = QCheckBox("Platzhalter/Reserve exportieren")
        self._cb_placeholders.setChecked(True)
        options_layout.addWidget(self._cb_overwrite)
        options_layout.addWidget(self._cb_placeholders)
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        self._btn_export = QPushButton("Exportieren")
        self._btn_export.setEnabled(False)
        self._btn_export.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_export)
        layout.addLayout(btn_layout)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "CSV-Datei speichern", "",
            "CSV-Dateien (*.csv);;Alle Dateien (*.*)",
        )
        if path:
            self._filepath = path
            self._path_edit.setText(path)
            self._btn_export.setEnabled(True)

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def overwrite(self) -> bool:
        return self._cb_overwrite.isChecked()
