"""
Dialog "Projekt neu aus ETS aufbauen" (FA-527)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QGroupBox, QCheckBox,
)

from ...services.rebuild_service import REBUILD_OPTIONS, REBUILT_FROM_ETS


class RebuildDialog(QDialog):
    """ETS-Projektdatei wählen und festlegen, was aus dem bisherigen
    Projekt behalten wird; alles andere entsteht frisch aus der ETS."""

    def __init__(self, project_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Projekt neu aus ETS aufbauen")
        self.setMinimumWidth(620)
        self._filepath = ""

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"Das Projekt «{project_name}» wird aus der ETS-Projektdatei neu "
            "aufgebaut. Anders als beim Import werden keine Planungsdaten aus "
            "dem bisherigen Stand übernommen.\n\n"
            "Der aktuelle Stand wird vorher gespeichert und im Projektordner "
            "unter «Sicherungen» abgelegt.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        file_group = QGroupBox("ETS-Projektdatei (.knxproj)")
        file_layout = QHBoxLayout(file_group)
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Pfad zur .knxproj-Datei...")
        file_layout.addWidget(self._path_edit)
        browse = QPushButton("Durchsuchen...")
        browse.clicked.connect(self._browse)
        file_layout.addWidget(browse)
        layout.addWidget(file_group)

        keep_group = QGroupBox("Aus dem bisherigen Projekt behalten")
        keep_layout = QVBoxLayout(keep_group)
        self._checks: dict[str, QCheckBox] = {}
        for option in REBUILD_OPTIONS:
            check = QCheckBox(f"{option.label} – {option.detail}")
            check.setChecked(option.default)
            keep_layout.addWidget(check)
            self._checks[option.key] = check
        layout.addWidget(keep_group)

        fresh = QLabel("Neu aus der ETS: " + ", ".join(REBUILT_FROM_ETS) + ".")
        fresh.setWordWrap(True)
        fresh.setStyleSheet("color: #666666; padding: 4px;")
        layout.addWidget(fresh)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._btn_ok = QPushButton("Neu aufbauen")
        self._btn_ok.setEnabled(False)
        self._btn_ok.clicked.connect(self.accept)
        buttons.addWidget(self._btn_ok)
        layout.addLayout(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "ETS-Projektdatei öffnen", "",
            "ETS6-Projekt (*.knxproj);;Alle Dateien (*.*)",
        )
        if path:
            self._filepath = path
            self._path_edit.setText(path)
            self._btn_ok.setEnabled(True)

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def keep(self) -> set[str]:
        return {key for key, check in self._checks.items() if check.isChecked()}
