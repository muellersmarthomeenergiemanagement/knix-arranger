"""
Flags eines Kommunikationsobjekts bearbeiten (Topologie, geplante Projekte).

Die Produktdaten liefern bei Objekten, deren Funktion erst die Parametrierung
festlegt, alle Flags (Feller EDIZIOdue «Object 2»: K L S Ü A). Der Integrator
trägt hier ein, wie er das Objekt in der ETS parametriert -- die Prüfungen
FA-627/628/634 rechnen danach mit diesen Flags.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
)

from ...services.ko_links import (
    COMMUNICATE, INIT, READ, TRANSMIT, UPDATE, WRITE, parse_flags,
)

# Reihenfolge und Texte wie in der ETS
_FLAGS = (
    (COMMUNICATE, "K  Kommunikation"),
    (READ, "L  Lesen – beantwortet Leseanfragen"),
    (WRITE, "S  Schreiben – empfängt"),
    (TRANSMIT, "Ü  Übertragen – sendet"),
    (UPDATE, "A  Aktualisieren"),
    (INIT, "I  Lesen bei Init"),
)


class KoFlagsDialog(QDialog):
    def __init__(self, device, co, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flags bearbeiten")
        layout = QVBoxLayout(self)
        name = co.name or co.object_function
        title = QLabel(f"<b>{device.physical_address} KO {co.object_number}</b> «{name}»")
        layout.addWidget(title)
        gas = ", ".join(co.connected_gas) if co.connected_gas else ""
        hint = QLabel("Wie in der ETS parametriert. Gilt für alle GAs dieses KOs"
                      + (f" ({gas})." if gas else "."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        present = parse_flags(co.flags)
        self._boxes = {}
        for flag, text in _FLAGS:
            box = QCheckBox(text)
            box.setChecked(flag in present)
            layout.addWidget(box)
            self._boxes[flag] = box
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def flags_text(self) -> str:
        """Schreibweise des ETS-Reports, z.B. "K-SÜA-" (ko_links.parse_flags)."""
        return "".join(flag if self._boxes[flag].isChecked() else "-"
                       for flag, _t in _FLAGS)
