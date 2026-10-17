"""
GA-Bearbeitungsdialog (FA-435, FA-1003b/c)
Ermöglicht das Bearbeiten einer einzelnen Gruppenadresse.

Mit project: nur, was nach der Herkunft der GA bearbeitbar ist (services/
ga_edit); Funktion und DPT generierter GAs bleiben als Nachbearbeitung über
Neuberechnungen erhalten. Ohne project (neue GA in Schritt 10): alle Felder
direkt ins GA-Objekt.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QGridLayout, QCheckBox, QMessageBox,
)
from PySide6.QtCore import Qt
from ..styles import KNX_GREEN, KNX_DARK_GREEN, KNX_PRIMARY
from ...models.group_address import GroupAddress
from ...services import ga_functions
from ...services.ga_edit import (
    FIELDS_FREE, GENERATED, apply_changes, edit_kind, editable_fields, move_ga,
)


# Gaengige DPT-Typen
DPT_OPTIONS = [
    "",
    "DPST-1-1",    # Schalten
    "DPST-1-7",    # Stopp
    "DPST-1-8",    # Auf/Ab
    "DPST-3-7",    # Dimmen
    "DPST-5-1",    # Prozentwert
    "DPST-9-1",    # Temperatur
    "DPST-17-1",   # Szenennummer (nur abrufen)
    "DPST-18-1",   # Szenensteuerung (abrufen und speichern)
    "DPST-20-102", # Betriebsart
]


def function_combo(current: str = "") -> QComboBox:
    """Auswahl der GA-Funktion (Liste aus ga_functions, freie Eingabe möglich)."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItem("")
    for function in ga_functions.all_functions():
        combo.addItem(function.name)
        combo.setItemData(combo.count() - 1,
                          f"{function.group} · {ga_functions.ROLE_LABELS[function.role]}"
                          f" · {function.dpt}", Qt.ToolTipRole)
    if current:
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(current)
    return combo


def dpt_combo(current: str = "") -> QComboBox:
    combo = QComboBox()
    combo.setEditable(True)
    combo.addItems(DPT_OPTIONS)
    if current:
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(current)
    return combo


class GaEditDialog(QDialog):
    """Dialog zum Bearbeiten einer Gruppenadresse."""

    def __init__(self, ga: GroupAddress, parent=None, project=None):
        super().__init__(parent)
        self._ga = ga
        self._project = project
        self.result_info = None    # ga_edit.EditResult nach dem Speichern
        self.setWindowTitle(f"GA bearbeiten: {ga.address}")
        self.setMinimumSize(500, 500)
        allowed = editable_fields(project, ga) if project is not None else FIELDS_FREE
        address_free = project is None or "designation" in allowed

        layout = QVBoxLayout(self)

        # Adresse
        addr_group = QGroupBox("Adresse")
        addr_layout = QGridLayout()

        addr_layout.addWidget(QLabel("Gruppenadresse:"), 0, 0)
        addr_label = QLabel(f"{ga.address}")
        addr_label.setStyleSheet(
            f"font-weight: bold; font-size: 16px; color: {KNX_DARK_GREEN};"
        )
        addr_layout.addWidget(addr_label, 0, 1)

        addr_layout.addWidget(QLabel("Hauptgruppe:"), 1, 0)
        self._hg_spin = QLineEdit(str(ga.main_group))
        self._hg_spin.setMaxLength(2)
        addr_layout.addWidget(self._hg_spin, 1, 1)

        addr_layout.addWidget(QLabel("Mittelgruppe:"), 2, 0)
        self._mg_spin = QLineEdit(str(ga.middle_group))
        self._mg_spin.setMaxLength(1)
        addr_layout.addWidget(self._mg_spin, 2, 1)

        addr_layout.addWidget(QLabel("Untergruppe:"), 3, 0)
        self._ug_spin = QLineEdit(str(ga.sub_group))
        self._ug_spin.setMaxLength(3)
        addr_layout.addWidget(self._ug_spin, 3, 1)
        for edit in (self._hg_spin, self._mg_spin, self._ug_spin):
            edit.setEnabled(address_free)
            if not address_free:
                edit.setToolTip("Die Adresse kommt aus der Planung – im Baum per Ziehen verschieben")

        addr_group.setLayout(addr_layout)
        layout.addWidget(addr_group)

        # Eigenschaften
        prop_group = QGroupBox("Eigenschaften")
        prop_layout = QGridLayout()

        prop_layout.addWidget(QLabel("Bezeichnung:"), 0, 0)
        self._designation = QLineEdit(ga.designation)
        prop_layout.addWidget(self._designation, 0, 1)

        prop_layout.addWidget(QLabel("Beschreibung:"), 1, 0)
        self._description = QLineEdit(ga.description)
        prop_layout.addWidget(self._description, 1, 1)

        prop_layout.addWidget(QLabel("Funktion:"), 2, 0)
        self._function = function_combo(ga.function_name)
        self._function.currentTextChanged.connect(self._on_function_changed)
        prop_layout.addWidget(self._function, 2, 1)

        prop_layout.addWidget(QLabel("Rolle:"), 3, 0)
        self._role = QLabel()
        prop_layout.addWidget(self._role, 3, 1)

        prop_layout.addWidget(QLabel("Datenpunkttyp:"), 4, 0)
        self._dpt = dpt_combo(ga.datapoint_type)
        prop_layout.addWidget(self._dpt, 4, 1)

        prop_layout.addWidget(QLabel("Gewerk-Code:"), 5, 0)
        self._gewerk = QLineEdit(ga.gewerk_code)
        self._gewerk.setMaxLength(4)
        prop_layout.addWidget(self._gewerk, 5, 1)

        prop_layout.addWidget(QLabel("Raum-Nummer:"), 6, 0)
        self._room = QLineEdit(ga.room_number)
        prop_layout.addWidget(self._room, 6, 1)

        prop_layout.addWidget(QLabel("Element-Nummer:"), 7, 0)
        self._element = QLineEdit(str(ga.element_number))
        self._element.setMaxLength(3)
        prop_layout.addWidget(self._element, 7, 1)

        # Flags
        self._central = QCheckBox("Zentraladresse")
        self._central.setChecked(ga.central == "true")
        prop_layout.addWidget(self._central, 8, 0, 1, 2)

        self._placeholder = QCheckBox("Reserve/Platzhalter")
        self._placeholder.setChecked(ga.is_placeholder)
        prop_layout.addWidget(self._placeholder, 9, 0, 1, 2)

        widgets = {
            "designation": self._designation, "description": self._description,
            "function_name": self._function, "datapoint_type": self._dpt,
            "gewerk_code": self._gewerk, "room_number": self._room,
            "element_number": self._element, "central": self._central,
            "is_placeholder": self._placeholder,
        }
        for name, widget in widgets.items():
            widget.setEnabled(name in allowed)

        if project is not None and edit_kind(project, ga) == GENERATED:
            hint = ("Aus der Planung: Funktion und DPT lassen sich nachbearbeiten, "
                    "sie bleiben bei jeder Neuberechnung erhalten, die Adresse "
                    "bleibt dieselbe. Die Bezeichnung folgt der Funktion.")
            if ga.plan_function:
                hint += f"\nGeplant war: {ga.plan_function}"
            note = QLabel(hint)
            note.setWordWrap(True)
            note.setStyleSheet("color: #666666; font-style: italic;")
            prop_layout.addWidget(note, 10, 0, 1, 2)

        prop_group.setLayout(prop_layout)
        layout.addWidget(prop_group)
        self._update_role()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Speichern")
        save_btn.setStyleSheet(
            f"background-color: {KNX_PRIMARY}; color: white; "
            f"font-weight: bold; padding: 6px 20px;"
        )
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _on_function_changed(self, text: str) -> None:
        dpt = ga_functions.suggested_dpt(text)
        if dpt and self._dpt.isEnabled():
            self._dpt.setEditText(dpt)
        self._update_role()

    def _update_role(self) -> None:
        self._role.setText(ga_functions.role_label(self._function.currentText()) or "–")

    def _values(self) -> dict:
        try:
            element = int(self._element.text())
        except ValueError:
            element = 0
        return {
            "designation": self._designation.text(),
            "description": self._description.text(),
            "datapoint_type": self._dpt.currentText(),
            "function_name": self._function.currentText().strip(),
            "gewerk_code": self._gewerk.text(),
            "room_number": self._room.text(),
            "element_number": element,
            "central": "true" if self._central.isChecked() else "",
            "is_placeholder": self._placeholder.isChecked(),
        }

    def _address(self) -> tuple[int, int, int] | None:
        try:
            return (int(self._hg_spin.text()), int(self._mg_spin.text()),
                    int(self._ug_spin.text()))
        except ValueError:
            return None

    def _save(self):
        """Speichert die Änderungen in das GA-Objekt."""
        values = self._values()
        address = self._address()
        if self._project is None:
            if address is not None:
                self._ga.main_group, self._ga.middle_group, self._ga.sub_group = address
            for name, value in values.items():
                setattr(self._ga, name, value)
            self.accept()
            return

        if address is None:
            QMessageBox.warning(self, "GA bearbeiten", "Die Adresse ist keine Zahl.")
            return
        error = move_ga(self._project, self._ga, *address)
        if error:
            QMessageBox.warning(self, "GA bearbeiten", error)
            return
        changes = {name: value for name, value in values.items()
                   if value != getattr(self._ga, name)}
        # DPT nur übernehmen, wenn er nicht bloss dem Funktionsvorschlag folgt
        if ("datapoint_type" in changes and "function_name" in changes
                and changes["datapoint_type"] == ga_functions.suggested_dpt(
                    changes["function_name"])):
            del changes["datapoint_type"]
        self.result_info = apply_changes(self._project, [self._ga], changes)
        self.accept()
