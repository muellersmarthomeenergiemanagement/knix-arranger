"""
Review-Dialog fuer automatisch erkannte Gewerk-Vorschlaege (FA-521g).

Zeigt alle von `services.gewerk_suggestion_service.suggest_gewerk_assignments()`
gefundenen Raum+Gewerk-Kombinationen als anhak-/abwaehlbare Liste, mit
Moeglichkeit den erkannten Gewerk-Code pro Zeile umzuschalten (loest eine
Neuberechnung der zugeordneten Funktionen aus). Erst nach Bestaetigung
("Übernehmen") werden `GewerkAssignment`s angelegt und die betroffenen
Gruppenadressen verknuepft -- kein Blind-Automatismus, siehe Plan FA-521g.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QAbstractItemView, QDialogButtonBox,
)
from PySide6.QtCore import Qt

from ...models.building import GewerkAssignment
from ...services.address_generator import AddressGenerator
from ...services.gewerk_channel_matching import (
    group_channels_by_name, match_channel_to_schema,
)
from ...services.gewerk_suggestion_service import (
    GewerkSuggestion, _MATCHABLE_CODES, find_reusable_assignment,
)
from ..column_utils import fit_columns

_COL_CHECK = 0
_COL_ROOM = 1
_COL_DEVICE = 2
_COL_CHANNEL = 3
_COL_GEWERK = 4
_COL_FUNCTIONS = 5


class GewerkSuggestionReviewDialog(QDialog):
    """Review/Korrektur-Liste fuer automatisch erkannte Gewerk-Vorschlaege.

    Nach Accepted: `self.applied_count` = Anzahl tatsaechlich angelegter
    GewerkAssignments (fuer die Erfolgsmeldung im Aufrufer)."""

    def __init__(self, project, suggestions: list[GewerkSuggestion], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gewerke aus Topologie -- Vorschläge prüfen")
        self.setMinimumSize(820, 480)
        self._project = project
        self.applied_count = 0

        self._gen = AddressGenerator(project.gewerk_catalog, variant=project.config.mg_variant)
        self._ga_by_address = {
            ga.address: ga for ga in project.group_addresses.all_addresses()
        }
        # Ein Eintrag pro Zeile: die urspruengliche Suggestion plus
        # veraenderlichen Zustand (Gewerk-Code kann umgeschaltet werden,
        # matched wird dann neu berechnet).
        self._rows: list[dict] = [
            {
                "suggestion": s, "code": s.gewerk_code, "matched": s.matched,
                "existing_assignment": s.existing_assignment,
            }
            for s in suggestions
        ]

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Automatisch erkannte Zuordnungen -- bitte prüfen. Abgewählte "
            "Zeilen werden nicht übernommen; das Gewerk pro Zeile kann "
            "umgestellt werden (berechnet die Funktionen neu)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        toggle_row = QHBoxLayout()
        btn_all = QPushButton("Alle auswählen")
        btn_all.clicked.connect(lambda: self._set_all_checked(True))
        toggle_row.addWidget(btn_all)
        btn_none = QPushButton("Keine auswählen")
        btn_none.clicked.connect(lambda: self._set_all_checked(False))
        toggle_row.addWidget(btn_none)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["", "Raum", "Gerät", "Kanal", "Gewerk", "Funktionen"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self._table, 1)

        row = QHBoxLayout()
        row.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Übernehmen")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)

        self._refresh_table()

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for r in range(self._table.rowCount()):
            self._table.item(r, _COL_CHECK).setCheckState(state)

    def _refresh_table(self):
        self._table.setRowCount(len(self._rows))
        for i, entry in enumerate(self._rows):
            s: GewerkSuggestion = entry["suggestion"]

            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check_item.setCheckState(Qt.Checked)
            self._table.setItem(i, _COL_CHECK, check_item)

            room_text = f"{s.room.number} {s.room.name}".strip()
            self._table.setItem(i, _COL_ROOM, QTableWidgetItem(room_text))

            device_text = f"{s.device.physical_address} ({s.device.manufacturer} {s.device.product})".strip()
            self._table.setItem(i, _COL_DEVICE, QTableWidgetItem(device_text))
            self._table.setItem(i, _COL_CHANNEL, QTableWidgetItem(s.channel_name))

            combo = QComboBox()
            for code in _MATCHABLE_CODES:
                gewerk = self._project.gewerk_catalog.get(code)
                name = gewerk.name if gewerk else code
                combo.addItem(f"{code} – {name}", code)
            idx = combo.findData(entry["code"])
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(
                lambda _idx, row=i, cb=combo: self._on_gewerk_changed(row, cb.currentData())
            )
            self._table.setCellWidget(i, _COL_GEWERK, combo)

            self._set_functions_cell(i, entry)

        fit_columns(self._table)

    def _set_functions_cell(self, row: int, entry: dict):
        matched = entry["matched"]
        s: GewerkSuggestion = entry["suggestion"]
        text = f"{len(matched)}/{s.schema_function_count} erkannt: " + ", ".join(sorted(matched.keys()))
        if entry["existing_assignment"]:
            text += "  (ergänzt bestehende Zuweisung)"
        self._table.setItem(row, _COL_FUNCTIONS, QTableWidgetItem(text))

    def _on_gewerk_changed(self, row: int, code: str):
        if not code:
            return
        entry = self._rows[row]
        s: GewerkSuggestion = entry["suggestion"]
        gewerk = self._project.gewerk_catalog.get(code)
        if not gewerk:
            return
        schema = self._gen._get_block_schema(gewerk, assignment=None, is_feedback=False)
        if not schema:
            entry["code"] = code
            entry["matched"] = {}
            self._set_functions_cell(row, entry)
            return

        cos = group_channels_by_name(s.device).get(s.channel_name, [])
        matched_cos = match_channel_to_schema(cos, schema)
        matched_gas = {
            function: self._ga_by_address[co.connected_gas[0]]
            for function, co in matched_cos.items()
            if co.connected_gas and co.connected_gas[0] in self._ga_by_address
        }
        entry["code"] = code
        entry["matched"] = matched_gas
        entry["schema_function_count"] = sum(
            1 for e in schema.entries if not e.is_reserve and e.function
        )
        s.schema_function_count = entry["schema_function_count"]
        entry["existing_assignment"] = find_reusable_assignment(s.room, code)
        self._set_functions_cell(row, entry)

    def _on_accept(self):
        for i, entry in enumerate(self._rows):
            if self._table.item(i, _COL_CHECK).checkState() != Qt.Checked:
                continue
            s: GewerkSuggestion = entry["suggestion"]
            code = entry["code"]
            matched = entry["matched"]
            if not matched:
                continue

            # Bereits vorhandene, unverknuepfte Zuweisung desselben Codes
            # (z.B. aus der Bezeichnungs-basierten Ableitung beim Import,
            # FA-519b) wiederverwenden statt eine zweite, doppelte Zeile
            # fuer dasselbe Gewerk im selben Raum anzulegen. Erneut prüfen
            # statt nur den beim Öffnen gecachten Wert zu nehmen, falls
            # zwischenzeitlich (durch eine andere Zeile) bereits verbraucht.
            assignment = find_reusable_assignment(s.room, code)
            if not assignment:
                assignment = GewerkAssignment(gewerk_code=code, count=1)
                s.room.gewerk_assignments.append(assignment)
            assignment.linked_ga_ids.update(
                {function: ga.id for function, ga in matched.items()}
            )
            for function, ga in matched.items():
                ga.is_manual = True
                ga.assignment_id = ""
                ga.gewerk_code = code
                ga.room_number = s.room.number
                ga.room_id = s.room.id
                ga.element_number = 1
                ga.function_name = function
            self.applied_count += 1

        self.accept()
