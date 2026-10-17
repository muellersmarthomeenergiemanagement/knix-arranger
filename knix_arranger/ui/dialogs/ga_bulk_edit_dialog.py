"""
Mehrere markierte Gruppenadressen gemeinsam bearbeiten (FA-1003b).

Gleiche Werte aller GAs sind vorbelegt, unterschiedliche zeigen
«– unterschiedlich –». Übernommen wird nur, was man ändert; je GA nur, was
nach ihrer Herkunft bearbeitbar ist (services/ga_edit).
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QGroupBox, QGridLayout,
)
from ..styles import KNX_PRIMARY
from ...services import ga_functions
from ...services.ga_edit import FIXED, FREE, GENERATED, apply_changes, edit_kind
from .ga_edit_dialog import dpt_combo, function_combo

_MIXED = "– unterschiedlich –"


def _common(gas: list, name: str):
    values = {getattr(ga, name) for ga in gas}
    return values.pop() if len(values) == 1 else None


class GaBulkEditDialog(QDialog):
    """Funktion, DPT, Beschreibung und Gewerk für mehrere GAs."""

    def __init__(self, project, gas: list, parent=None):
        super().__init__(parent)
        self._project = project
        self._gas = list(gas)
        self._touched: set[str] = set()
        self.result_info = None
        self.setWindowTitle(f"{len(gas)} GA bearbeiten")
        self.setMinimumWidth(520)

        kinds = [edit_kind(project, ga) for ga in gas]
        n_gen, n_free, n_fixed = (kinds.count(GENERATED), kinds.count(FREE),
                                  kinds.count(FIXED))

        layout = QVBoxLayout(self)
        parts = []
        if n_gen:
            parts.append(f"{n_gen} aus der Planung (Funktion, DPT, Beschreibung)")
        if n_free:
            parts.append(f"{n_free} frei bearbeitbar")
        if n_fixed:
            parts.append(f"{n_fixed} nur Beschreibung (Reserve, Zentral, Szene)")
        info = QLabel("Markiert: " + ", ".join(parts) + ".\n"
                      "Übernommen wird nur, was Sie ändern.")
        info.setWordWrap(True)
        layout.addWidget(info)

        group = QGroupBox("Eigenschaften")
        grid = QGridLayout(group)

        function = _common(gas, "function_name")
        grid.addWidget(QLabel("Funktion:"), 0, 0)
        self._function = function_combo(function or "")
        if function is None:
            self._function.setCurrentIndex(-1)
            self._function.lineEdit().setPlaceholderText(_MIXED)
        self._function.currentTextChanged.connect(self._on_function_changed)
        self._function.setEnabled(bool(n_gen or n_free))
        grid.addWidget(self._function, 0, 1)

        grid.addWidget(QLabel("Rolle:"), 1, 0)
        self._role = QLabel(ga_functions.role_label(function or "") or "–")
        grid.addWidget(self._role, 1, 1)

        dpt = _common(gas, "datapoint_type")
        grid.addWidget(QLabel("Datenpunkttyp:"), 2, 0)
        self._dpt = dpt_combo(dpt or "")
        if dpt is None:
            self._dpt.setCurrentIndex(-1)
            self._dpt.lineEdit().setPlaceholderText(_MIXED)
        self._dpt.lineEdit().textEdited.connect(lambda _t: self._touched.add("datapoint_type"))
        self._dpt.activated.connect(lambda _i: self._touched.add("datapoint_type"))
        self._dpt.setEnabled(bool(n_gen or n_free))
        grid.addWidget(self._dpt, 2, 1)

        description = _common(gas, "description")
        grid.addWidget(QLabel("Beschreibung:"), 3, 0)
        self._description = QLineEdit(description or "")
        if description is None:
            self._description.setPlaceholderText(_MIXED)
        self._description.textEdited.connect(lambda _t: self._touched.add("description"))
        grid.addWidget(self._description, 3, 1)

        gewerk = _common(gas, "gewerk_code")
        grid.addWidget(QLabel("Gewerk-Code:"), 4, 0)
        self._gewerk = QLineEdit(gewerk or "")
        self._gewerk.setMaxLength(4)
        if gewerk is None:
            self._gewerk.setPlaceholderText(_MIXED)
        self._gewerk.textEdited.connect(lambda _t: self._touched.add("gewerk_code"))
        self._gewerk.setEnabled(bool(n_free))
        if not n_free:
            self._gewerk.setToolTip("Das Gewerk kommt aus der Planung")
        grid.addWidget(self._gewerk, 4, 1)
        layout.addWidget(group)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Speichern")
        save.setStyleSheet(f"background-color: {KNX_PRIMARY}; color: white; "
                           f"font-weight: bold; padding: 6px 20px;")
        save.clicked.connect(self._save)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _on_function_changed(self, text: str) -> None:
        self._touched.add("function_name")
        self._role.setText(ga_functions.role_label(text) or "–")
        dpt = ga_functions.suggested_dpt(text)
        if dpt:
            self._dpt.setEditText(dpt)    # Vorschlag, gilt nicht als eigene Änderung

    def changes(self) -> dict:
        values = {
            "function_name": self._function.currentText().strip(),
            "datapoint_type": self._dpt.currentText().strip(),
            "description": self._description.text(),
            "gewerk_code": self._gewerk.text().strip(),
        }
        changes = {name: values[name] for name in self._touched}
        if "function_name" in changes and not changes["function_name"]:
            del changes["function_name"]
        if "datapoint_type" in changes and not changes["datapoint_type"]:
            del changes["datapoint_type"]
        return changes

    def _save(self) -> None:
        self.result_info = apply_changes(self._project, self._gas, self.changes())
        self.accept()
