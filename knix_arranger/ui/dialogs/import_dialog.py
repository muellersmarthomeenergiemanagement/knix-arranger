"""
CSV/XLSX Import-Dialog (FA-500)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QGroupBox, QTextEdit, QProgressBar,
)
from PySide6.QtCore import Qt


class ImportDialog(QDialog):
    """Dialog für CSV/XLSX Import."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CSV/XLSX Import")
        self.setMinimumSize(600, 380)
        self._filepath = ""
        self._file_type = ""  # "csv" oder "xlsx"

        layout = QVBoxLayout(self)

        # Dateiauswahl
        file_group = QGroupBox("Datei auswählen")
        file_layout = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Pfad zur ETS6 CSV- oder XLSX-Datei...")
        self._path_edit.setReadOnly(True)
        file_layout.addWidget(self._path_edit)

        btn_browse = QPushButton("Durchsuchen...")
        btn_browse.clicked.connect(self._browse)
        file_layout.addWidget(btn_browse)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Info
        info = QLabel(
            "Unterstuetzte Formate:\n"
            "- ETS6 Projekt-Datei (.knxproj) — vollstaendiger Import (empfohlen)\n"
            "- ETS6 Gruppenadress-Report (XLSX)\n"
            "- ETS6 Topologie-Report mit Objekte (XLSX)\n"
            "- UTF-8 oder ANSI Kodierung"
        )
        info.setStyleSheet("color: #808080; padding: 5px;")
        layout.addWidget(info)

        # Log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(150)
        self._log.setPlaceholderText("Import-Protokoll...")
        layout.addWidget(self._log)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_cancel = QPushButton("Abbrechen")
        self._btn_cancel.setObjectName("secondary")
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_import = QPushButton("Importieren")
        self._btn_import.setEnabled(False)
        self._btn_import.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_import)
        layout.addLayout(btn_layout)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "ETS6-Datei öffnen", "",
            "Alle unterstuetzten Formate (*.csv *.xlsx *.knxproj);;"
            "ETS6-Projekt (*.knxproj);;"
            "CSV-Dateien (*.csv);;"
            "XLSX-Dateien (*.xlsx);;"
            "Alle Dateien (*.*)",
        )
        if path:
            self._filepath = path
            lower = path.lower()
            if lower.endswith(".knxproj"):
                self._file_type = "knxproj"
            elif lower.endswith(".xlsx"):
                self._file_type = "xlsx"
            else:
                self._file_type = "csv"
            self._path_edit.setText(path)
            self._btn_import.setEnabled(True)

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def file_type(self) -> str:
        return self._file_type

    def log(self, message: str):
        self._log.append(message)
