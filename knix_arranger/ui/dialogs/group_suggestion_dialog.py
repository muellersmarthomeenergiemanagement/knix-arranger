"""
Dialog "Gruppen erkennen" (FA-531): Gruppenbedienungen eines importierten
Projekts als Funktionen übernehmen. Der Integrator wählt und benennt, KNiX
legt nichts ohne Bestätigung an.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QAbstractItemView,
)

from ...services.ets_function_plan import MemberElement, plan_type_label
from ..column_utils import fit_columns

_COLUMNS = ["Name", "Ort", "Typ", "Elemente", "GAs", "Hinweis"]


class GroupSuggestionDialog(QDialog):
    """selected() liefert (Vorschlag, Name) der angehakten Zeilen."""

    def __init__(self, suggestions: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gruppen erkennen")
        self.setMinimumSize(900, 420)
        self._suggestions = suggestions

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Diese GAs belegen mehrere Aktorkanäle desselben Gewerks – sie bedienen eine "
            "Gruppe gemeinsam. Als Funktion übernommen erscheinen sie mit Namen in der "
            "Topologie, der Bauherrenberatung und den Berichten. Die GAs bleiben, wie sie "
            "in der ETS stehen. Zentral-GAs (HG 0), Rückmeldungen und Bewegungsmelder "
            "sind nicht dabei. Namen lassen sich hier anpassen.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        layout.addWidget(hint)

        self._table = QTableWidget(len(suggestions), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        for row, s in enumerate(suggestions):
            name = QTableWidgetItem(s.name)
            name.setFlags(name.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            name.setCheckState(Qt.Checked)
            self._table.setItem(row, 0, name)
            floor = (s.floor.name or s.floor.short_code) if s.floor else ""
            members = ", ".join(
                MemberElement(r, a, n, s.floor.short_code if s.floor else "").label.split(" (")[0]
                for r, a, n in s.members)
            gas = ", ".join(ga.address for ga in s.gas.values())
            note = (f"{s.missing_channels} Kanal/Kanäle ohne Element in KNiX"
                    if s.missing_channels else "")
            for col, text in enumerate((f"{floor} › {s.place}", plan_type_label(s.function_type),
                                        members, gas, note), start=1):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsEnabled)
                if col == 5 and note:
                    item.setToolTip("Diese Kanäle tragen kein Gewerk-Element, das KNiX "
                                    "kennt (z.B. Elementnummer über der Anzahl). Die "
                                    "Funktion umfasst nur die erkannten Elemente.")
                self._table.setItem(row, col, item)
        fit_columns(self._table)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> list[tuple[object, str]]:
        result = []
        for row, s in enumerate(self._suggestions):
            item = self._table.item(row, 0)
            if item.checkState() == Qt.Checked:
                result.append((s, item.text().strip() or s.name))
        return result
