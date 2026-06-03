"""
Lizenzdialog (NFA-098)
Import und Anzeige der .knxlic-Lizenzdatei.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout, QFileDialog,
)
from PySide6.QtCore import Qt
from ..styles import KNX_GREEN, KNX_DARK_GREEN
from ...services.license_service import LicenseService


class LicenseDialog(QDialog):
    """Dialog zur Lizenz-Verwaltung (Import und Statusanzeige)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._service = LicenseService()
        self.setWindowTitle("Lizenz")
        self.setMinimumSize(480, 340)

        layout = QVBoxLayout(self)

        title = QLabel("KNiX Arranger Lizenz")
        title.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {KNX_DARK_GREEN}; padding: 10px;"
        )
        layout.addWidget(title)

        # Status
        status_group = QGroupBox("Aktueller Lizenzstatus")
        grid = QGridLayout()
        self._status_label = QLabel()
        self._customer_label = QLabel()
        self._type_label = QLabel()
        self._expiry_label = QLabel()

        grid.addWidget(QLabel("Status:"), 0, 0)
        grid.addWidget(self._status_label, 0, 1)
        grid.addWidget(QLabel("Kunde:"), 1, 0)
        grid.addWidget(self._customer_label, 1, 1)
        grid.addWidget(QLabel("Typ:"), 2, 0)
        grid.addWidget(self._type_label, 2, 1)
        grid.addWidget(QLabel("Gültig bis:"), 3, 0)
        grid.addWidget(self._expiry_label, 3, 1)

        status_group.setLayout(grid)
        layout.addWidget(status_group)

        # Import
        import_group = QGroupBox("Lizenzdatei importieren")
        import_layout = QVBoxLayout()

        hint = QLabel(
            "Sie haben eine Lizenzdatei (.knxlic) per E-Mail erhalten.\n"
            "Klicken Sie auf «Datei auswählen» um diese zu importieren."
        )
        hint.setStyleSheet("color: #555; font-size: 11px;")
        hint.setWordWrap(True)
        import_layout.addWidget(hint)

        btn_row = QHBoxLayout()
        import_btn = QPushButton("Lizenzdatei auswählen…")
        import_btn.setStyleSheet(
            f"background-color: {KNX_GREEN}; color: white; "
            f"font-weight: bold; padding: 6px 20px;"
        )
        import_btn.clicked.connect(self._import_license)
        btn_row.addWidget(import_btn)
        btn_row.addStretch()
        import_layout.addLayout(btn_row)

        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        import_layout.addWidget(self._result_label)

        import_group.setLayout(import_layout)
        layout.addWidget(import_group)

        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._refresh_status()

    def _refresh_status(self):
        info = self._service.check_license()
        if info.is_valid:
            self._status_label.setText("Gültig")
            self._status_label.setStyleSheet(f"color: {KNX_GREEN}; font-weight: bold;")
        else:
            self._status_label.setText(info.message or "Keine Lizenz")
            self._status_label.setStyleSheet("color: red; font-weight: bold;")

        type_names = {"single": "Einzellizenz", "annual": "Jahreslizenz", "trial": "Testlizenz"}
        self._customer_label.setText(info.customer or "-")
        self._type_label.setText(type_names.get(info.license_type, "-"))
        self._expiry_label.setText(info.expiry_date or "-")

    def _import_license(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Lizenzdatei auswählen", "", "KNiX Lizenz (*.knxlic)"
        )
        if not path:
            return

        info = self._service.import_license(path)
        if info.is_valid:
            self._result_label.setText(f"Lizenz erfolgreich importiert. {info.message}")
            self._result_label.setStyleSheet(f"color: {KNX_GREEN}; font-weight: bold;")
            self._refresh_status()
        else:
            self._result_label.setText(f"Fehler: {info.message}")
            self._result_label.setStyleSheet("color: red;")
