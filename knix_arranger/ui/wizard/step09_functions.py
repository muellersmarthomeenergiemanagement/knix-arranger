"""
Wizard Schritt 9: Funktionsdefinition (Bauherr-Formular)
Automatische Zuordnung Sensor-Tasten -> Gruppenadressen
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ...models.project import KnxProject
from ...services.sensor_service import SensorService
from ...services.belegungsplan_service import _split_button_channel
from ..column_utils import fit_columns


class Step09Functions(QWidget):
    """Funktionszuordnung Sensortasten -> GA (FA-1500)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project

        layout = QVBoxLayout(self)

        info = QLabel(
            "Ordnen Sie Sensortasten den Gruppenadressen zu.\n"
            "Die automatische Zuordnung verknuepft Sensoren mit den\n"
            "offensichtlich logischen Funktionen im selben Raum."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        self._btn_auto = QPushButton("Funktionen automatisch zuordnen")
        self._btn_auto.clicked.connect(self._auto_assign)
        btn_layout.addWidget(self._btn_auto)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self._summary = QLabel("")
        self._summary.setObjectName("subtitle")
        layout.addWidget(self._summary)

        self._no_ga_hint = QLabel(
            "Hinweis: Keine Gruppenadressen vorhanden. "
            "Bitte zuerst in Schritt 7 die Gruppenadressen berechnen."
        )
        self._no_ga_hint.setStyleSheet("color: #E67E22; font-weight: bold;")
        self._no_ga_hint.setWordWrap(True)
        self._no_ga_hint.setVisible(False)
        layout.addWidget(self._no_ga_hint)

        # Baum: Raum > Sensor > Funktionszuordnungen
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels([
            "Raum / Sensor", "Taste", "Kanal", "Aktion", "Adresse", "Bezeichnung", "Beschreibung",
        ])
        self._tree.setAlternatingRowColors(True)
        self._tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tree.setRootIsDecorated(True)
        layout.addWidget(self._tree)

        # Hinweis
        hint = QLabel(
            "Hinweis: Das detaillierte Funktionsdefinitions-Formular für den Bauherrn\n"
            "kann im Menue 'Berichte' als Excel-Datei generiert werden."
        )
        hint.setStyleSheet("color: #808080; padding: 10px;")
        layout.addWidget(hint)

    def on_enter(self):
        all_rooms = self._project.all_rooms
        has_gewerke = any(r.gewerk_assignments for r in all_rooms)
        has_gas = bool(self._project.group_addresses.all_addresses())
        if has_gewerke and has_gas:
            # Immer neu zuweisen – Gewerke, GAs oder funktionen können sich geändert haben
            self._auto_assign()
        else:
            self._refresh()

    def _auto_assign(self):
        gas = self._project.group_addresses

        if not gas.all_addresses():
            self._no_ga_hint.setVisible(True)
            self._summary.setText("")
            self._tree.clear()
            return

        self._no_ga_hint.setVisible(False)

        service = SensorService()
        all_rooms = self._project.all_rooms

        # Basis-Zuweisung aus Gewerken (auto_assign_functions)
        count = service.auto_assign_functions(all_rooms, gas)

        # auto_assign_functions behandelt bereits sowohl Auto- als auch Manual-BEs
        # (FA-1410: SensorFunktionen werden expandiert, function_assignments befüllt).

        self._refresh()
        self._summary.setText(
            f"{count} Funktionszuordnungen automatisch erstellt"
        )

    def _refresh(self):
        self._tree.clear()
        bold_font = QFont()
        bold_font.setBold(True)

        # Lookup: Bezeichnung → "x/x/x"-Adresse
        ga_address: dict[str, str] = {
            ga.designation: f"{ga.main_group}/{ga.middle_group}/{ga.sub_group}"
            for ga in self._project.group_addresses.all_addresses()
            if not ga.is_placeholder
        }

        all_rooms = self._project.all_rooms
        total_assignments = 0
        rooms_with_assignments = 0

        for room in all_rooms:
            if not room.bedienelemente:
                continue

            rooms_with_assignments += 1
            room_fas = sum(
                len(be.function_assignments) for be in room.bedienelemente
            )
            total_assignments += room_fas

            # Raum-Knoten
            room_item = QTreeWidgetItem(self._tree, [
                f"{room.number} {room.name}",
                f"{room_fas} Zuordnungen",
                "", "", "", "", "",
            ])
            room_item.setFont(0, bold_font)
            room_item.setData(0, Qt.UserRole, room)
            room_item.setExpanded(True)

            for be in room.bedienelemente:
                ch_label = f"{be.channels}-Kanal"
                pn_str = be.participant_number if be.participant_number else "–"
                # Bedienelement-Knoten
                sensor_item = QTreeWidgetItem(room_item, [
                    f"{be.element_type} [{pn_str}]",
                    f"{ch_label}, {len(be.function_assignments)} Funktionen",
                    "", "", "", "", "",
                ])
                sensor_item.setFont(0, bold_font)

                for fa in be.function_assignments:
                    taste, kanal = _split_button_channel(fa.button_channel)
                    action_label = "Rückmeld." if fa.is_feedback else fa.action_type
                    addr = ga_address.get(fa.function_ga, "–")
                    QTreeWidgetItem(sensor_item, [
                        "",
                        taste,
                        kanal,
                        action_label,
                        addr,
                        fa.function_ga,
                        fa.description,
                    ])

                sensor_item.setExpanded(True)

        fit_columns(self._tree)

        if total_assignments == 0:
            self._summary.setText(
                "Noch keine Funktionszuordnungen vorhanden."
            )
        elif not self._summary.text():
            self._summary.setText(
                f"{rooms_with_assignments} Räume, "
                f"{total_assignments} Zuordnungen"
            )

