"""
Einstellungen-Dialog (NFA-040, FA-851–857)
Firmenprofil, Logo, Stundensätze, Projektstandards.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFormLayout, QComboBox, QTabWidget,
    QWidget, QDoubleSpinBox, QCheckBox, QFileDialog, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from ...models.company_profile import CompanyProfile


class SettingsDialog(QDialog):
    """Einstellungen und Firmenprofil (FA-851–857)."""

    def __init__(self, profile: CompanyProfile | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumSize(640, 560)

        self._profile = CompanyProfile() if profile is None else profile
        self._logo_path: str = self._profile.logo_path

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._create_general_tab(), "Allgemein")
        tabs.addTab(self._create_company_tab(), "Firmenprofil")
        tabs.addTab(self._create_rates_tab(), "Stundensätze")
        layout.addWidget(tabs)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_save = QPushButton("Speichern")
        btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

        self._populate()

    # ─── Tab: Allgemein ───────────────────────────────────────────────────────

    def _create_general_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        proj_group = QGroupBox("Projektstandards")
        proj_form = QFormLayout()

        self._variant_combo = QComboBox()
        self._variant_combo.addItems(["Variante A", "Variante B"])
        proj_form.addRow("MG-Variante:", self._variant_combo)

        self._topology_combo = QComboBox()
        self._topology_combo.addItems(["TP-256", "TP-64"])
        proj_form.addRow("Topologie-Modus:", self._topology_combo)

        self._language_combo = QComboBox()
        self._language_combo.addItems(["Deutsch", "Französisch", "Englisch"])
        proj_form.addRow("Sprache:", self._language_combo)

        proj_group.setLayout(proj_form)
        layout.addWidget(proj_group)

        update_group = QGroupBox("Updates")
        update_form = QFormLayout()
        self._auto_update_check = QCheckBox("Automatisch beim Start prüfen")
        self._auto_update_check.setChecked(True)
        update_form.addRow("Update-Prüfung:", self._auto_update_check)
        update_group.setLayout(update_form)
        layout.addWidget(update_group)

        layout.addStretch()
        return tab

    # ─── Tab: Firmenprofil ────────────────────────────────────────────────────

    def _create_company_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Logo
        logo_group = QGroupBox("Firmenlogo (FA-854)")
        logo_layout = QHBoxLayout()

        self._logo_preview = QLabel()
        self._logo_preview.setFixedSize(120, 60)
        self._logo_preview.setAlignment(Qt.AlignCenter)
        self._logo_preview.setStyleSheet(
            "border: 1px solid #ccc; background: #f5f5f5; border-radius: 4px;"
        )
        self._logo_preview.setText("Kein Logo")
        logo_layout.addWidget(self._logo_preview)

        logo_btn_col = QVBoxLayout()
        btn_logo = QPushButton("Logo auswählen…")
        btn_logo.clicked.connect(self._choose_logo)
        logo_btn_col.addWidget(btn_logo)
        btn_logo_clear = QPushButton("Logo entfernen")
        btn_logo_clear.setObjectName("secondary")
        btn_logo_clear.clicked.connect(self._clear_logo)
        logo_btn_col.addWidget(btn_logo_clear)
        logo_btn_col.addStretch()
        logo_layout.addLayout(logo_btn_col)
        logo_layout.addStretch()

        logo_group.setLayout(logo_layout)
        layout.addWidget(logo_group)

        # Firmendaten
        data_group = QGroupBox("Firmendaten (FA-851)")
        data_form = QFormLayout()

        self._company_name = QLineEdit()
        self._company_name.setPlaceholderText("Musterfirma AG")
        data_form.addRow("Firmenname:", self._company_name)

        self._company_address = QLineEdit()
        self._company_address.setPlaceholderText("Musterstrasse 1, 8000 Zürich")
        data_form.addRow("Adresse:", self._company_address)

        self._company_phone = QLineEdit()
        self._company_phone.setPlaceholderText("+41 44 000 00 00")
        data_form.addRow("Telefon:", self._company_phone)

        self._company_email = QLineEdit()
        self._company_email.setPlaceholderText("info@musterfirma.ch")
        data_form.addRow("E-Mail:", self._company_email)

        self._company_website = QLineEdit()
        self._company_website.setPlaceholderText("www.musterfirma.ch")
        data_form.addRow("Website:", self._company_website)

        data_group.setLayout(data_form)
        layout.addWidget(data_group)

        # Bearbeiter
        user_group = QGroupBox("Bearbeiter (FA-856)")
        user_form = QFormLayout()

        self._user_name = QLineEdit()
        self._user_name.setPlaceholderText("Max Muster")
        user_form.addRow("Name:", self._user_name)

        self._user_role = QLineEdit()
        self._user_role.setPlaceholderText("KNX-Systemintegrator")
        user_form.addRow("Funktion:", self._user_role)

        user_group.setLayout(user_form)
        layout.addWidget(user_group)

        layout.addStretch()
        return tab

    # ─── Tab: Stundensätze ────────────────────────────────────────────────────

    def _create_rates_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        rates_group = QGroupBox("Stundensätze (FA-1703)")
        rates_form = QFormLayout()

        self._rate_mounting = QDoubleSpinBox()
        self._rate_mounting.setRange(0, 999)
        self._rate_mounting.setPrefix("CHF ")
        self._rate_mounting.setSuffix(" / h")
        rates_form.addRow("Montage:", self._rate_mounting)

        self._rate_programming = QDoubleSpinBox()
        self._rate_programming.setRange(0, 999)
        self._rate_programming.setPrefix("CHF ")
        self._rate_programming.setSuffix(" / h")
        rates_form.addRow("Programmierung:", self._rate_programming)

        self._rate_commissioning = QDoubleSpinBox()
        self._rate_commissioning.setRange(0, 999)
        self._rate_commissioning.setPrefix("CHF ")
        self._rate_commissioning.setSuffix(" / h")
        rates_form.addRow("Inbetriebnahme:", self._rate_commissioning)

        self._markup = QDoubleSpinBox()
        self._markup.setRange(0, 100)
        self._markup.setSuffix(" %")
        rates_form.addRow("Materialaufschlag:", self._markup)

        rates_group.setLayout(rates_form)
        layout.addWidget(rates_group)
        layout.addStretch()
        return tab

    # ─── Befüllen / Auslesen ─────────────────────────────────────────────────

    def _populate(self):
        p = self._profile
        self._company_name.setText(p.company_name)
        self._company_address.setText(p.address)
        self._company_phone.setText(p.phone)
        self._company_email.setText(p.email)
        self._company_website.setText(p.website)
        self._user_name.setText(p.user_name)
        self._user_role.setText(p.role)
        self._rate_mounting.setValue(p.hourly_rate_mounting)
        self._rate_programming.setValue(p.hourly_rate_programming)
        self._rate_commissioning.setValue(p.hourly_rate_commissioning)
        self._markup.setValue(p.material_markup_percent)
        if p.logo_path:
            self._update_logo_preview(p.logo_path)

    def get_profile(self) -> CompanyProfile:
        """Gibt das aktualisierte CompanyProfile zurück."""
        p = self._profile
        p.company_name = self._company_name.text().strip()
        p.address = self._company_address.text().strip()
        p.phone = self._company_phone.text().strip()
        p.email = self._company_email.text().strip()
        p.website = self._company_website.text().strip()
        p.user_name = self._user_name.text().strip()
        p.role = self._user_role.text().strip()
        p.logo_path = self._logo_path
        p.hourly_rate_mounting = self._rate_mounting.value()
        p.hourly_rate_programming = self._rate_programming.value()
        p.hourly_rate_commissioning = self._rate_commissioning.value()
        p.material_markup_percent = self._markup.value()
        return p

    # ─── Logo ─────────────────────────────────────────────────────────────────

    def _choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Firmenlogo auswählen", "",
            "Bilder (*.png *.jpg *.jpeg *.svg *.bmp);;Alle Dateien (*.*)",
        )
        if path:
            self._logo_path = path
            self._update_logo_preview(path)

    def _clear_logo(self):
        self._logo_path = ""
        self._logo_preview.setPixmap(QPixmap())
        self._logo_preview.setText("Kein Logo")

    def _update_logo_preview(self, path: str):
        pix = QPixmap(path)
        if not pix.isNull():
            self._logo_preview.setPixmap(
                pix.scaled(120, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self._logo_preview.setText("(Ungültig)")

    # ─── Speichern ────────────────────────────────────────────────────────────

    def _on_save(self):
        self.get_profile()   # schreibt Felder → self._profile
        self.accept()
