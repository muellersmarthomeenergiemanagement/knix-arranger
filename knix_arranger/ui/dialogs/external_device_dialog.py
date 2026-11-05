"""
Externes Gerät erfassen bzw. bearbeiten (FA-609b).

Ein Gerät am Bus, das nicht im ETS-Projekt steht, z.B. die TP-Schnittstelle
eines Visualisierungsservers (Chalet: Z-Server 1.1.200). Es belegt eine
physikalische Adresse, zählt bei Teilnehmern und Busstrom der Linie und
bleibt beim Re-Import erhalten.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
    QLineEdit, QMessageBox, QSpinBox, QVBoxLayout,
)

from ...models.topology import Device

# (Anzeige, device_type)
KINDS = [
    ("Visualisierung / Server", "other"),
    ("Schnittstelle (USB/IP)", "other"),
    ("Fremdgerät", "other"),
]


class ExternalDeviceDialog(QDialog):
    def __init__(self, area_number: int, line, device: Device | None = None, parent=None):
        super().__init__(parent)
        self._line = line
        self._prefix = f"{area_number}.{line.line_number}."
        self._device = device
        self.setWindowTitle("Externes Gerät bearbeiten" if device else "Externes Gerät erfassen")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        info = QLabel(
            "Gerät am Bus, das nicht im ETS-Projekt steht, z.B. die Schnittstelle "
            "einer Visualisierung. Es zählt bei Teilnehmern und Busstrom der Linie "
            "und bleibt beim Re-Import erhalten.")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self._name = QLineEdit(device.product if device else "")
        self._name.setPlaceholderText("z.B. Z-Server Visualisierung")
        form.addRow("Bezeichnung:", self._name)

        self._kind = QComboBox()
        for label, _code in KINDS:
            self._kind.addItem(label)
        if device:
            # Art steht im Applikationsfeld, sonst nach Gerätetyp
            labels = [label for label, _code in KINDS]
            codes = [code for _label, code in KINDS]
            self._kind.setCurrentIndex(
                labels.index(device.application_program)
                if device.application_program in labels
                else codes.index(device.device_type) if device.device_type in codes else 0)
        form.addRow("Art:", self._kind)

        self._participant = QSpinBox()
        self._participant.setRange(1, 255)
        self._participant.setPrefix(self._prefix)
        self._participant.setValue(self._current_participant() or self._free_participant())
        form.addRow("Physikalische Adresse:", self._participant)

        self._location = QLineEdit(device.installation_location if device else "")
        self._location.setPlaceholderText("z.B. HV")
        form.addRow("Einbauort:", self._location)

        self._current = QDoubleSpinBox()
        self._current.setRange(0, 500)
        self._current.setDecimals(0)
        self._current.setSuffix(" mA")
        self._current.setSpecialValueText("unbekannt (10 mA angenommen)")
        self._current.setValue(device.bus_current if device else 0)
        form.addRow("Busstrom:", self._current)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _current_participant(self) -> int:
        if self._device and self._device.physical_address.startswith(self._prefix):
            tail = self._device.physical_address[len(self._prefix):]
            return int(tail) if tail.isdigit() else 0
        return 0

    def _used(self) -> set[str]:
        return self._line.used_addresses(exclude=self._device)

    def _free_participant(self) -> int:
        used = self._used()
        # Schnittstellen und Server oft am Ende des Adressbereichs (1.1.200)
        return next((n for n in range(200, 256) if f"{self._prefix}{n}" not in used),
                    next((n for n in range(1, 256) if f"{self._prefix}{n}" not in used), 255))

    @property
    def physical_address(self) -> str:
        return f"{self._prefix}{self._participant.value()}"

    def _accept(self) -> None:
        if not self._name.text().strip():
            QMessageBox.warning(self, "Bezeichnung fehlt", "Bitte eine Bezeichnung eingeben.")
            return
        if self.physical_address in self._used():
            QMessageBox.warning(self, "Adresse vergeben",
                                f"Die Adresse {self.physical_address} ist auf dieser Linie "
                                "bereits vergeben.")
            return
        self.accept()

    def apply(self, device: Device | None = None) -> Device:
        """Werte in das Gerät schreiben (neues Gerät, wenn keines übergeben)."""
        device = device or Device(external=True, manually_added=True)
        label, code = KINDS[self._kind.currentIndex()]
        device.product = self._name.text().strip()
        device.device_type = code
        device.application_program = label
        device.physical_address = self.physical_address
        device.installation_location = self._location.text().strip()
        device.bus_current = float(self._current.value())
        device.external = True
        return device
