"""
Dialog zur Eingabe des ETS6-Projektpassworts fuer verschluesselte .knxproj-Dateien.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon


class KnxprojPasswordDialog(QDialog):
    """Fragt das ETS6-Projektpasswort ab und bietet Speichern an."""

    def __init__(self, project_id: str, filename: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ETS6-Projektpasswort")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Info-Text
        info = QLabel(
            f"Das Projekt <b>{filename}</b> ist passwortgeschützt.\n"
            "Bitte geben Sie das ETS6-Projektpasswort ein:"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Passwort-Eingabe
        pw_layout = QHBoxLayout()
        pw_label = QLabel("Passwort:")
        pw_label.setFixedWidth(80)
        pw_layout.addWidget(pw_label)

        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_edit.setPlaceholderText("ETS6-Projektpasswort …")
        self._pw_edit.returnPressed.connect(self._on_ok)
        pw_layout.addWidget(self._pw_edit)

        self._show_pw_btn = QPushButton("👁")
        self._show_pw_btn.setFixedWidth(32)
        self._show_pw_btn.setCheckable(True)
        self._show_pw_btn.setToolTip("Passwort anzeigen")
        self._show_pw_btn.toggled.connect(self._toggle_visibility)
        pw_layout.addWidget(self._show_pw_btn)

        layout.addLayout(pw_layout)

        # Fehlermeldung (initial unsichtbar)
        self._error_label = QLabel("Falsches Passwort – bitte erneut versuchen.")
        self._error_label.setStyleSheet("color: #c62828;")
        self._error_label.setVisible(False)
        layout.addWidget(self._error_label)

        # Passwort merken
        self._save_cb = QCheckBox("Passwort für dieses Projekt speichern")
        self._save_cb.setChecked(True)
        layout.addWidget(self._save_cb)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        self._btn_ok = QPushButton("Importieren")
        self._btn_ok.setDefault(True)
        self._btn_ok.clicked.connect(self._on_ok)
        btn_layout.addWidget(self._btn_ok)
        layout.addLayout(btn_layout)

        self._pw_edit.setFocus()

    # ------------------------------------------------------------------

    def _toggle_visibility(self, checked: bool):
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self._pw_edit.setEchoMode(mode)

    def _on_ok(self):
        if self._pw_edit.text():
            self.accept()

    def show_wrong_password(self):
        """Zeigt Fehlermeldung bei falschem Passwort und leert das Feld."""
        self._error_label.setVisible(True)
        self._pw_edit.clear()
        self._pw_edit.setFocus()

    @property
    def password(self) -> str:
        return self._pw_edit.text()

    @property
    def save_password(self) -> bool:
        return self._save_cb.isChecked()
