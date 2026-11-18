"""
Wert auf eine GA senden (FA-3102b): GA, Datenpunkttyp und Wert eingeben, die
Telegrammdaten sehen und ausdrücklich bestätigen. Bei Alarm, Wetterstation,
Tor und Türe fragt KNiX ein zweites Mal nach.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QVBoxLayout,
)

from ...services.bus_access import BusSendError, MonitorContext, group_address_raw
from ...services.dpt_values import dpt_parts, encode_value, size_text, value_suggestions
from ..styles import TEXT_MUTED

_ERROR = "#C62828"


def dpt_label(dpt: str) -> str:
    """"DPST-9-1" -> "9.001", "DPT-1" -> "1"; sonst unverändert."""
    main, sub = dpt_parts(dpt)
    if not main:
        return dpt or ""
    return f"{main}.{sub:03d}" if sub else str(main)


class BusSendDialog(QDialog):
    def __init__(self, context: MonitorContext | None, address: str = "",
                 connection_label: str = "", parent=None):
        super().__init__(parent)
        self._context = context
        self.values: tuple[str, str, int, str] | None = None   # GA, Hex, Länge, Wert
        self.setWindowTitle("Wert senden")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Das Telegramm geht sofort auf den Bus und wirkt wie ein Tastendruck"
            + (f" (über {connection_label})." if connection_label else "."))
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        form = QFormLayout()
        self._address = QLineEdit(address)
        self._address.setPlaceholderText("z.B. 1/0/1")
        self._address.textChanged.connect(self._address_changed)
        form.addRow("Gruppenadresse:", self._address)
        self._designation = QLabel()
        self._designation.setWordWrap(True)
        form.addRow("Bezeichnung:", self._designation)
        self._dpt = QLineEdit()
        self._dpt.setPlaceholderText("z.B. 1.001, 5.001, 9.001")
        self._dpt.textChanged.connect(self._dpt_changed)
        form.addRow("Datenpunkttyp:", self._dpt)
        self._value = QComboBox()
        self._value.setEditable(True)
        self._value.setInsertPolicy(QComboBox.NoInsert)
        self._value.editTextChanged.connect(self._update_preview)
        form.addRow("Wert:", self._value)
        self._preview = QLabel()
        self._preview.setWordWrap(True)
        form.addRow("Telegramm:", self._preview)
        layout.addLayout(form)

        self._caution = QLabel()
        self._caution.setWordWrap(True)
        self._caution.setStyleSheet(f"color: {_ERROR};")
        self._caution.hide()
        layout.addWidget(self._caution)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._send_btn = buttons.button(QDialogButtonBox.Ok)
        self._send_btn.setText("Senden")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._send)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._address_changed()
        (self._value if address else self._address).setFocus()

    # ── Eingaben ─────────────────────────────────────────────────────────

    def _ga(self):
        if self._context is None:
            return None
        return self._context.gas.get(self._address.text().strip())

    def _address_changed(self) -> None:
        ga = self._ga()
        if ga is not None:
            self._designation.setText(" ".join((ga.designation or "").split()) or "–")
            self._designation.setStyleSheet("")
            self._dpt.setText(dpt_label(ga.datapoint_type or ""))
        else:
            known = not self._address.text().strip()
            self._designation.setText("" if known else "GA nicht im Projekt")
            self._designation.setStyleSheet(f"color: {TEXT_MUTED};")
        caution = self._context.caution(self._address.text().strip()) if self._context else ""
        self._caution.setText(caution)
        self._caution.setVisible(bool(caution))
        self._update_preview()

    def _dpt_changed(self) -> None:
        current = self._value.currentText()
        self._value.blockSignals(True)
        self._value.clear()
        self._value.addItems(value_suggestions(self._dpt.text()))
        self._value.setEditText(current)
        self._value.blockSignals(False)
        self._update_preview()

    def _encoded(self) -> tuple[str, int]:
        """(Hex, Länge) oder ValueError/BusSendError mit Meldung."""
        group_address_raw(self._address.text())
        return encode_value(self._dpt.text(), self._value.currentText())

    def _update_preview(self) -> None:
        try:
            payload, size = self._encoded()
        except (ValueError, BusSendError) as exc:
            entered = bool(self._value.currentText().strip())
            self._preview.setText(str(exc) if entered else "Wert eingeben")
            self._preview.setStyleSheet(f"color: {_ERROR if entered else TEXT_MUTED};")
            self._send_btn.setEnabled(False)
            return
        self._preview.setText(f"Schreiben auf {self._address.text().strip()}: Daten "
                              f"{payload} ({size_text(size)})")
        self._preview.setStyleSheet("")
        self._send_btn.setEnabled(True)

    # ── Senden ───────────────────────────────────────────────────────────

    def _send(self) -> None:
        try:
            payload, size = self._encoded()
        except (ValueError, BusSendError) as exc:
            QMessageBox.warning(self, "Wert senden", str(exc))
            return
        address = self._address.text().strip()
        if self._caution.text():
            answer = QMessageBox.warning(
                self, "Wert senden – Vorsicht",
                f"{self._caution.text()}\n\nTrotzdem «{self._value.currentText().strip()}» "
                f"auf {address} senden?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self.values = (address, payload, size, self._value.currentText().strip())
        self.accept()
