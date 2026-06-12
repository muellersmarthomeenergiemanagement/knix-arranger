"""
Kundenprofil-Dialog (projektspezifisch)
Ähnlich dem Firmenprofil, jedoch pro Projekt gespeichert.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFormLayout, QTextEdit, QFileDialog,
    QSizePolicy, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QTransform

from ...models.client_profile import ClientProfile
from ...utils.clipboard_image import save_clipboard_image


class ClientProfileDialog(QDialog):
    """Dialog zum Bearbeiten des projektspezifischen Kundenprofils."""

    def __init__(self, profile: ClientProfile | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kundenprofil bearbeiten")
        self.setMinimumSize(580, 560)

        self._profile = ClientProfile() if profile is None else profile
        self._photo_path: str = self._profile.photo_path
        self._photo_rotation: int = self._profile.photo_rotation

        layout = QVBoxLayout(self)

        # ── Kundendaten ──────────────────────────────────────────────────────
        data_group = QGroupBox("Kundendaten")
        data_form = QFormLayout()
        data_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Auftraggeber / Kundenname")
        data_form.addRow("Name:", self._name)

        self._object_address = QLineEdit()
        self._object_address.setPlaceholderText("Musterstrasse 1, 8000 Zürich")
        data_form.addRow("Objekt / Bauvorhaben:", self._object_address)

        self._contact_address = QLineEdit()
        self._contact_address.setPlaceholderText("Postadresse des Kunden")
        data_form.addRow("Postadresse:", self._contact_address)

        self._phone = QLineEdit()
        self._phone.setPlaceholderText("+41 44 000 00 00")
        data_form.addRow("Telefon:", self._phone)

        self._email = QLineEdit()
        self._email.setPlaceholderText("kunde@beispiel.ch")
        data_form.addRow("E-Mail:", self._email)

        self._website = QLineEdit()
        self._website.setPlaceholderText("www.beispiel.ch")
        data_form.addRow("Website:", self._website)

        data_group.setLayout(data_form)
        layout.addWidget(data_group)

        # ── Foto ─────────────────────────────────────────────────────────────
        photo_group = QGroupBox("Projektfoto / Objektfoto")
        photo_layout = QHBoxLayout()

        self._photo_preview = QLabel()
        self._photo_preview.setFixedSize(200, 120)
        self._photo_preview.setAlignment(Qt.AlignCenter)
        self._photo_preview.setStyleSheet(
            "border: 1px solid #ccc; background: #f0f0f0; border-radius: 4px;"
        )
        self._photo_preview.setText("Kein Foto")
        photo_layout.addWidget(self._photo_preview)

        photo_btn_col = QVBoxLayout()
        btn_photo = QPushButton("Foto auswählen…")
        btn_photo.clicked.connect(self._choose_photo)
        photo_btn_col.addWidget(btn_photo)

        btn_photo_paste = QPushButton("Aus Zwischenablage einfügen")
        btn_photo_paste.clicked.connect(self._paste_photo)
        photo_btn_col.addWidget(btn_photo_paste)

        btn_rotate = QPushButton("↻ 90° drehen")
        btn_rotate.clicked.connect(self._rotate_photo)
        photo_btn_col.addWidget(btn_rotate)

        btn_photo_clear = QPushButton("Foto entfernen")
        btn_photo_clear.setObjectName("secondary")
        btn_photo_clear.clicked.connect(self._clear_photo)
        photo_btn_col.addWidget(btn_photo_clear)
        photo_btn_col.addStretch()
        photo_layout.addLayout(photo_btn_col)
        photo_layout.addStretch()

        photo_group.setLayout(photo_layout)
        layout.addWidget(photo_group)

        # ── Notizen ──────────────────────────────────────────────────────────
        notes_group = QGroupBox("Notizen")
        notes_layout = QVBoxLayout()
        self._notes = QTextEdit()
        self._notes.setPlaceholderText("Interne Notizen zum Projekt / Kunden…")
        self._notes.setMaximumHeight(80)
        notes_layout.addWidget(self._notes)
        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        btn_ok = QPushButton("Übernehmen")
        btn_ok.clicked.connect(self._on_ok)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

        self._populate()

    # ── Befüllen / Auslesen ──────────────────────────────────────────────────

    def _populate(self):
        p = self._profile
        self._name.setText(p.name)
        self._object_address.setText(p.object_address)
        self._contact_address.setText(p.contact_address)
        self._phone.setText(p.phone)
        self._email.setText(p.email)
        self._website.setText(p.website)
        self._notes.setPlainText(p.notes)
        if p.photo_path:
            self._update_photo_preview()

    def get_profile(self) -> ClientProfile:
        p = self._profile
        p.name             = self._name.text().strip()
        p.object_address   = self._object_address.text().strip()
        p.contact_address  = self._contact_address.text().strip()
        p.phone            = self._phone.text().strip()
        p.email            = self._email.text().strip()
        p.website          = self._website.text().strip()
        p.photo_path       = self._photo_path
        p.photo_rotation   = self._photo_rotation
        p.notes            = self._notes.toPlainText().strip()
        return p

    # ── Foto ─────────────────────────────────────────────────────────────────

    def _choose_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Projektfoto auswählen", "",
            "Bilder (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;Alle Dateien (*.*)",
        )
        if path:
            self._photo_path = path
            self._photo_rotation = 0
            self._update_photo_preview()

    def _paste_photo(self):
        path = save_clipboard_image("projektfoto")
        if not path:
            QMessageBox.information(
                self, "Zwischenablage",
                "Die Zwischenablage enthält kein Bild.",
            )
            return
        self._photo_path = path
        self._photo_rotation = 0
        self._update_photo_preview()

    def _rotate_photo(self):
        if not self._photo_path:
            return
        self._photo_rotation = (self._photo_rotation + 90) % 360
        self._update_photo_preview()

    def _clear_photo(self):
        self._photo_path = ""
        self._photo_rotation = 0
        self._photo_preview.setPixmap(QPixmap())
        self._photo_preview.setText("Kein Foto")

    def _update_photo_preview(self):
        if not self._photo_path:
            return
        pix = QPixmap(self._photo_path)
        if pix.isNull():
            self._photo_preview.setText("(Ungültig)")
            return
        if self._photo_rotation:
            pix = pix.transformed(
                QTransform().rotate(self._photo_rotation),
                Qt.SmoothTransformation,
            )
        self._photo_preview.setPixmap(
            pix.scaled(200, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    # ── OK ────────────────────────────────────────────────────────────────────

    def _on_ok(self):
        self.get_profile()
        self.accept()
