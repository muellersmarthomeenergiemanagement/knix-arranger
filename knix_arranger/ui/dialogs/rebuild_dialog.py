"""
Dialog "Projekt neu aus ETS aufbauen" (FA-527, FA-527a)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QGroupBox, QCheckBox,
)

from ...services.rebuild_service import REBUILD_OPTIONS, REBUILT_FROM_ETS

REBUILD, RECONCILE = "rebuild", "reconcile"


def _option_text(option, project) -> str:
    text = f"{option.label} – {option.detail}"
    if option.key == "bus_recordings" and project is not None:
        names = [r.get("file", "") for r in getattr(project, "bus_recordings", [])]
        if names:
            shown = ", ".join(names[:3]) + (", …" if len(names) > 3 else "")
            text += f" ({len(names)}: {shown})"
        else:
            text += " (keine)"
    return text


class RebuildDialog(QDialog):
    """ETS-Projektdatei wählen und festlegen, was aus dem bisherigen
    Projekt behalten wird; alles andere entsteht frisch aus der ETS.

    Mit ``filepath`` (Aufruf aus dem ETS6 Import, FA-527a) ist die Datei
    vorgegeben; mit ``offer_reconcile`` wählt «Nur abgleichen» stattdessen
    den Re-Import (``choice == RECONCILE``)."""

    def __init__(self, project_name: str, parent=None, *, filepath: str = "",
                 project=None, offer_reconcile: bool = False, start_dir: str = ""):
        super().__init__(parent)
        self._start_dir = start_dir
        self.setWindowTitle("Projekt neu aus ETS aufbauen")
        self.setMinimumWidth(620)
        self._filepath = filepath
        self.choice = REBUILD

        layout = QVBoxLayout(self)
        if offer_reconcile:
            text = (
                f"«{project_name}» ist aus der ETS importiert – die ETS ist "
                "massgebend. Das Projekt wird deshalb aus der gewählten Datei neu "
                "aufgebaut; Fehler aus früheren Ständen werden nicht mitgenommen.\n\n"
                "«Nur abgleichen» übernimmt stattdessen Gewerke, Produkte und "
                "Bedienelemente aus dem bisherigen Stand.\n\n"
                "Der aktuelle Stand wird vorher im Projektordner unter "
                "«Sicherungen» abgelegt.")
        else:
            text = (
                f"Das Projekt «{project_name}» wird aus der ETS-Projektdatei neu "
                "aufgebaut. Anders als beim Import werden keine Planungsdaten aus "
                "dem bisherigen Stand übernommen.\n\n"
                "Der aktuelle Stand wird vorher gespeichert und im Projektordner "
                "unter «Sicherungen» abgelegt.")
        intro = QLabel(text)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        file_group = QGroupBox("ETS-Projektdatei (.knxproj)")
        file_layout = QHBoxLayout(file_group)
        self._path_edit = QLineEdit(filepath)
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Pfad zur .knxproj-Datei...")
        file_layout.addWidget(self._path_edit)
        if not filepath:
            browse = QPushButton("Durchsuchen...")
            browse.clicked.connect(self._browse)
            file_layout.addWidget(browse)
        layout.addWidget(file_group)

        keep_group = QGroupBox("Aus dem bisherigen Projekt behalten")
        keep_layout = QVBoxLayout(keep_group)
        self._checks: dict[str, QCheckBox] = {}
        for option in REBUILD_OPTIONS:
            check = QCheckBox(_option_text(option, project))
            check.setChecked(option.default)
            keep_layout.addWidget(check)
            self._checks[option.key] = check
        layout.addWidget(keep_group)

        fresh = QLabel("Neu aus der ETS: " + ", ".join(REBUILT_FROM_ETS) + ".")
        fresh.setWordWrap(True)
        fresh.setStyleSheet("color: #666666; padding: 4px;")
        layout.addWidget(fresh)

        buttons = QHBoxLayout()
        if offer_reconcile:
            self._btn_reconcile = QPushButton("Nur abgleichen")
            self._btn_reconcile.setObjectName("secondary")
            self._btn_reconcile.clicked.connect(self._reconcile)
            buttons.addWidget(self._btn_reconcile)
        buttons.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._btn_ok = QPushButton("Neu aufbauen")
        self._btn_ok.setEnabled(bool(filepath))
        self._btn_ok.setDefault(True)
        self._btn_ok.clicked.connect(self.accept)
        buttons.addWidget(self._btn_ok)
        layout.addLayout(buttons)

    def _reconcile(self):
        self.choice = RECONCILE
        self.accept()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "ETS-Projektdatei öffnen", self._start_dir,
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
