"""
Verbindung zur Anlage (FA-3101): Art, Adresse, Secure-Angaben. Die
Einstellungen ohne Passwörter bleiben im Projekt; Passwörter nur für diese
Verbindung.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ...services.bus_access import (
    KINDS, ROUTING_SECURE, TUNNEL_SECURE, TUNNEL_UDP, ConnectionSettings, Secrets,
)
from ..styles import TEXT_MUTED


class BusConnectionDialog(QDialog):
    def __init__(self, settings: ConnectionSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mit der Anlage verbinden")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "KNiX verbindet sich über KNXnet/IP mit einer IP-Schnittstelle, einem "
            "IP-Router oder einem Fernzugang und zeigt die Gruppentelegramme. "
            "Es wird nichts gesendet. Passwörter werden nicht gespeichert.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        form = QFormLayout()
        self._kind = QComboBox()
        for key, label in KINDS:
            self._kind.addItem(label, key)
        self._kind.setCurrentIndex(max(0, self._kind.findData(settings.kind)))
        self._kind.currentIndexChanged.connect(self._update)
        form.addRow("Verbindung:", self._kind)

        self._host = QLineEdit(settings.host)
        self._host.setPlaceholderText("z.B. 192.168.1.20")
        self._host_label = QLabel("Schnittstelle:")
        form.addRow(self._host_label, self._host)
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(settings.port)
        self._port_label = QLabel("Port:")
        form.addRow(self._port_label, self._port)
        self._route_back = QCheckBox("Über NAT/VPN (Route back)")
        self._route_back.setChecked(settings.route_back)
        self._route_back.setToolTip(
            "Für Fernzugänge und VPN: die Schnittstelle antwortet an die Absenderadresse "
            "statt an die lokale Adresse des PCs.")
        form.addRow("", self._route_back)
        self._address = QLineEdit(settings.individual_address)
        self._address.setPlaceholderText("leer = Schnittstelle wählt")
        self._address.setToolTip("Tunneladresse, z.B. 1.1.72 (Tunneling 2)")
        self._address_label = QLabel("Tunneladresse:")
        form.addRow(self._address_label, self._address)

        # Secure
        self._secure_title = QLabel("<b>KNX Secure</b>")
        form.addRow(self._secure_title)
        keyring = QWidget()
        row = QHBoxLayout(keyring)
        row.setContentsMargins(0, 0, 0, 0)
        self._keyring = QLineEdit(settings.keyring_path)
        self._keyring.setPlaceholderText("Schlüsseldatei der ETS (.knxkeys), optional")
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        row.addWidget(self._keyring)
        row.addWidget(browse)
        form.addRow("Schlüsseldatei:", keyring)
        self._keyring_password = self._password()
        form.addRow("Passwort Schlüsseldatei:", self._keyring_password)
        self._user_id = QSpinBox()
        self._user_id.setRange(0, 127)
        self._user_id.setSpecialValueText("–")
        self._user_id.setValue(settings.user_id)
        self._user_id.setToolTip("Benutzer-ID des Secure-Tunnels laut ETS (meist 2 und höher)")
        self._user_id_label = QLabel("Benutzer-ID:")
        form.addRow(self._user_id_label, self._user_id)
        self._user_password = self._password()
        self._user_password_label = QLabel("Passwort des Tunnels:")
        form.addRow(self._user_password_label, self._user_password)
        self._device_password = self._password()
        self._device_password.setPlaceholderText("optional")
        self._device_password_label = QLabel("Geräte-Authentifizierung:")
        form.addRow(self._device_password_label, self._device_password)
        self._backbone = self._password()
        self._backbone_label = QLabel("Backbone-Schlüssel:")
        form.addRow(self._backbone_label, self._backbone)
        self._keyring_hint = QLabel(
            "Mit Schlüsseldatei: Tunnelpasswort und GA-Schlüssel kommen aus der Datei "
            "(ETS: Projekt › Sicherheit › Schlüssel exportieren). Ohne Secure-Verbindung "
            "dient sie nur zum Entschlüsseln gesicherter GAs (Data Secure).")
        self._keyring_hint.setWordWrap(True)
        self._keyring_hint.setStyleSheet(f"color: {TEXT_MUTED};")
        form.addRow(self._keyring_hint)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Verbinden")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update()

    @staticmethod
    def _password() -> QLineEdit:
        edit = QLineEdit()
        edit.setEchoMode(QLineEdit.Password)
        return edit

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Schlüsseldatei der ETS", self._keyring.text(),
            "KNX-Schlüsseldatei (*.knxkeys);;Alle Dateien (*)")
        if path:
            self._keyring.setText(path)

    def _update(self) -> None:
        kind = self._kind.currentData()
        routing = kind in ("routing", ROUTING_SECURE)
        for widget in (self._host, self._host_label, self._port, self._port_label,
                       self._address, self._address_label):
            widget.setVisible(not routing)
        self._route_back.setVisible(kind == TUNNEL_UDP)
        tunnel_secure = kind == TUNNEL_SECURE
        for widget in (self._user_id, self._user_id_label, self._user_password,
                       self._user_password_label, self._device_password,
                       self._device_password_label):
            widget.setVisible(tunnel_secure)
        for widget in (self._backbone, self._backbone_label):
            widget.setVisible(kind == ROUTING_SECURE)
        self.adjustSize()

    def settings(self) -> ConnectionSettings:
        return ConnectionSettings(
            kind=self._kind.currentData(), host=self._host.text().strip(),
            port=self._port.value(), route_back=self._route_back.isChecked(),
            keyring_path=self._keyring.text().strip(), user_id=self._user_id.value(),
            individual_address=self._address.text().strip())

    def secrets(self) -> Secrets:
        return Secrets(
            user_password=self._user_password.text(),
            device_authentication_password=self._device_password.text(),
            keyring_password=self._keyring_password.text(),
            backbone_key=self._backbone.text().strip())

    def _accept(self) -> None:
        problems = self.settings().problems(self.secrets())
        if problems:
            QMessageBox.warning(self, "Verbindung unvollständig", "\n".join(problems))
            return
        self.accept()
