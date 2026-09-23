"""
Wizard Schritt 12: Tastenbelegung prüfen

Nur-Lese-Übersicht Taste → Gruppenadresse als Kontrolle vor dem Export.
Bearbeitet wird die Zuordnung in Schritt 11 (Funktionszuordnung).
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton, QAbstractItemView, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ...models.project import KnxProject
from ...services.sensor_service import SensorService
from ...services.belegungsplan_service import _split_button_channel
from ..column_utils import fit_columns
from .recompute_guard import RecomputeGuard, KEY_FUNCTIONS

_ROLE_LABELS = {
    "befehl": "Befehl",
    "rueckmeldung": "Rückmeld.",
    "fremdsteuerung": "Fremdsteuerung",
}


class Step09Functions(QWidget):
    """Prüfansicht Sensortasten -> GA (FA-1500)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        # Vom WizardController durch eine gemeinsame Instanz ersetzt
        self._guard = RecomputeGuard()

        layout = QVBoxLayout(self)

        info = QLabel(
            "Prüfen Sie die Tastenbelegung vor dem Export: pro Taste die zugeordnete "
            "Gruppenadresse mit Befehl und Rückmeldung.\n"
            "Änderungen nehmen Sie in Schritt 11 (Funktionszuordnung) vor – "
            "diese Ansicht ist nur zur Kontrolle."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._import_banner = QLabel(
            "Dieses Projekt wurde aus einem ETS-Projekt importiert. Funktionszuordnungen\n"
            "werden NICHT automatisch neu berechnet. 'Funktionen automatisch zuordnen'\n"
            "bleibt bei Bedarf manuell verfügbar (mit Warnhinweis)."
        )
        self._import_banner.setWordWrap(True)
        self._import_banner.setStyleSheet(
            "background-color: #FFF3CD; color: #856404; padding: 8px; border-radius: 4px;"
        )
        self._import_banner.hide()
        layout.addWidget(self._import_banner)

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
            "Bitte zuerst in Schritt 10 die Gruppenadressen berechnen."
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
            "kann im Menü 'Berichte' als Excel-Datei generiert werden."
        )
        hint.setStyleSheet("color: #808080; padding: 10px;")
        layout.addWidget(hint)

    def on_enter(self):
        self._import_banner.setVisible(self._project.topology.is_imported)

        # Importierte Verknüpfungen (XLSX/knxproj) bleiben unverändert
        # (FA-ImportGuard) – nur anzeigen, keine automatische Neuzuordnung.
        if self._project.topology.is_imported:
            self._refresh()
            return

        all_rooms = self._project.all_rooms
        has_gewerke = any(r.gewerk_assignments for r in all_rooms)
        has_gas = bool(self._project.group_addresses.all_addresses())
        # Die Zuordnung läuft bereits in Schritt 11 – hier nur nachholen, wenn
        # sich Gewerke, Geräte oder GAs seither geändert haben.
        if (has_gewerke and has_gas
                and self._guard.is_stale(self._project, KEY_FUNCTIONS)):
            self._auto_assign()
        else:
            self._refresh()

    def _auto_assign(self):
        if self._project.topology.is_imported:
            reply = QMessageBox.question(
                self,
                "Importierte Verknüpfungen überschreiben?",
                "Dieses Projekt wurde aus einem ETS-Projekt importiert.\n"
                "Die automatische Zuordnung erstellt Funktionszuordnungen anhand von\n"
                "Heuristiken (Raum/Gewerk) und kann bestehende, manuell geprüfte\n"
                "Verknüpfungen überschreiben.\n\n"
                "Trotzdem fortfahren?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

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
        self._guard.mark_done(self._project, KEY_FUNCTIONS)

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
            active_bes = [be for be in room.bedienelemente if not be.suppressed]
            if not active_bes:
                continue

            rooms_with_assignments += 1
            room_fas = sum(
                len(be.function_assignments) for be in active_bes
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

            for be in active_bes:
                ch_label = f"{be.channels}-Kanal"
                pn_str = be.participant_number if be.participant_number else "–"
                # Bedienelement-Knoten
                sensor_item = QTreeWidgetItem(room_item, [
                    f"{be.element_type} [{pn_str}]",
                    f"{ch_label}, {len(be.function_assignments)} Funktionen",
                    "", "", "", "", "",
                ])
                sensor_item.setFont(0, bold_font)

                # Physischer Kanal (Taste bzw. geräteweite Fremdsteuerung):
                # alle FunctionAssignments derselben SensorFunktion (sf_id)
                # gehören zusammen (Befehl + Rückmeldung, oder eine
                # Fremdsteuerungs-GA) -- siehe SensorFunktion-Docstring.
                channel_groups: dict[str, list] = {}
                for fa in be.function_assignments:
                    channel_groups.setdefault(fa.sf_id or fa.button_channel, []).append(fa)

                for group_fas in channel_groups.values():
                    is_fremdsteuerung = all(fa.role == "fremdsteuerung" for fa in group_fas)
                    if is_fremdsteuerung:
                        taste, kanal = "Fremdsteuerung", group_fas[0].button_channel
                    else:
                        taste, kanal = _split_button_channel(group_fas[0].button_channel)

                    channel_item = QTreeWidgetItem(sensor_item, [
                        "", taste, kanal, "", "", "", "",
                    ])

                    for fa in group_fas:
                        action_label = _ROLE_LABELS.get(fa.role, fa.action_type)
                        if fa.role == "befehl" and fa.action_type:
                            action_label = fa.action_type
                        addr = ga_address.get(fa.function_ga, "–")
                        QTreeWidgetItem(channel_item, [
                            "",
                            "",
                            "",
                            action_label,
                            addr,
                            fa.function_ga,
                            fa.description,
                        ])

                    channel_item.setExpanded(True)

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

