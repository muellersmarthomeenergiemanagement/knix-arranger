"""
Dialog "Revisionspaket erstellen": Revisionsstand (FA-2106) und Auswahl der
Bestandteile (FA-2105).
"""
from __future__ import annotations
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QGroupBox, QCheckBox,
)

from ...services.revision_package import (
    REVISION_PARTS, accepted_quotes, next_revision_number,
)


class RevisionPackageDialog(QDialog):
    """Revisionsbezeichnung, Datum, Anlass und Bestandteile wählen."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Revisionspaket erstellen")
        self.setMinimumWidth(720)
        layout = QVBoxLayout(self)

        form_group = QGroupBox("Revisionsstand")
        form = QFormLayout(form_group)
        self._number = QLineEdit(next_revision_number(project))
        self._number.setMaxLength(10)
        self._number.textChanged.connect(self._update_ok)
        form.addRow("Revision:", self._number)
        self._date = QLineEdit(datetime.now().strftime("%d.%m.%Y"))
        form.addRow("Datum:", self._date)
        self._note = QLineEdit("" if project.revisions else "Erstausgabe")
        self._note.setPlaceholderText("z.B. Erweiterung Obergeschoss")
        form.addRow("Anlass:", self._note)
        if project.revisions:
            earlier = ", ".join(f"{r.number} ({r.date})" for r in project.revisions)
            hint = QLabel(f"Bisherige Revisionen: {earlier}")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #666666;")
            form.addRow("", hint)
        layout.addWidget(form_group)

        parts_group = QGroupBox("Bestandteile")
        grid = QGridLayout(parts_group)
        self._checks: dict[str, QCheckBox] = {}
        has_quote = bool(accepted_quotes(project))
        rows = (len(REVISION_PARTS) + 1) // 2
        for i, (key, label) in enumerate(REVISION_PARTS):
            check = QCheckBox(label)
            check.setChecked(True)
            if key == "offerte" and not has_quote:
                check.setChecked(False)
                check.setEnabled(False)
                check.setToolTip("Keine akzeptierte Kundenofferte im Projekt")
            grid.addWidget(check, i % rows, i // rows)
            self._checks[key] = check
        layout.addWidget(parts_group)

        info = QLabel("Bestandteile ohne Daten (z.B. keine Szenen) entfallen "
                      "automatisch. Das Paket wird im Projektordner unter "
                      "«Revisionen» in einem eigenen Ordner je Revision abgelegt.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #666666; padding: 4px;")
        layout.addWidget(info)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._btn_ok = QPushButton("Erstellen")
        self._btn_ok.clicked.connect(self.accept)
        buttons.addWidget(self._btn_ok)
        layout.addLayout(buttons)

    def _update_ok(self) -> None:
        self._btn_ok.setEnabled(bool(self.revision))

    @property
    def revision(self) -> str:
        return self._number.text().strip()

    @property
    def revision_date(self) -> str:
        return self._date.text().strip()

    @property
    def note(self) -> str:
        return self._note.text().strip()

    @property
    def parts(self) -> set[str]:
        return {key for key, check in self._checks.items() if check.isChecked()}
