"""
Wizard Schritt 3b: Elektroverteilungen (HV/UV/...) pro Raum anlegen
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QTreeWidgetItemIterator, QPushButton,
    QLineEdit, QFormLayout, QGroupBox, QComboBox, QListWidget,
    QListWidgetItem, QSplitter, QMessageBox, QInputDialog,
)
from PySide6.QtCore import Qt
from ...models.project import KnxProject
from ...models.building import Room, Verteiler
from ...services.xlsx_import_service import XlsxImportService
from ..column_utils import fit_columns


VERTEILER_TYPES = ["HV", "UV", "NV", "TV"]


class Step03bVerteiler(QWidget):
    """Elektroverteilungen (HV, UV, NV, TV) pro Raum anlegen."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._selected_room: Room | None = None
        self._selected_room_floor_code: str = ""
        self._selected_vt: Verteiler | None = None

        layout = QVBoxLayout(self)
        info = QLabel(
            "Legen Sie fest, welche Räume einen Elektroverteilkasten (HV, UV, NV, TV) enthalten.\n"
            "Aktoren, Linienkoppler und Speisungen werden dem Verteiler zugeordnet – nicht dem Raum direkt."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        splitter = QSplitter(Qt.Horizontal)

        # --- Linke Seite: Raumbaum ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Räume:"))
        self._room_tree = QTreeWidget()
        self._room_tree.itemExpanded.connect(lambda _: fit_columns(self._room_tree))
        self._room_tree.setHeaderLabels(["Raum", "Nr."])
        self._room_tree.currentItemChanged.connect(self._on_room_selected)
        left_layout.addWidget(self._room_tree)

        self._btn_move_to_room = QPushButton("Diesen Verteiler-Platzhalter einem Raum zuordnen…")
        self._btn_move_to_room.setToolTip(
            "Für aus dem Import abgeleitete Verteiler ohne bekannten Standort "
            "(z.B. 'HV', 'UV2') -- ordnet ihn und alle darin montierten "
            "Geräte dem tatsächlichen Raum zu. Bleibt bei künftigen "
            "Re-Importen erhalten."
        )
        self._btn_move_to_room.setEnabled(False)
        self._btn_move_to_room.setVisible(False)
        self._btn_move_to_room.clicked.connect(self._move_verteiler_to_room)
        left_layout.addWidget(self._btn_move_to_room)

        splitter.addWidget(left)

        # --- Rechte Seite: Verteiler-Liste + Editor ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Verteiler-Liste
        vt_header = QHBoxLayout()
        vt_header.addWidget(QLabel("Verteiler in diesem Raum:"))
        self._btn_add_vt = QPushButton("+ Hinzufügen")
        self._btn_add_vt.setEnabled(False)
        self._btn_add_vt.clicked.connect(self._add_verteiler)
        self._btn_remove_vt = QPushButton("Entfernen")
        self._btn_remove_vt.setObjectName("danger")
        self._btn_remove_vt.setEnabled(False)
        self._btn_remove_vt.clicked.connect(self._remove_verteiler)
        vt_header.addWidget(self._btn_add_vt)
        vt_header.addWidget(self._btn_remove_vt)
        vt_header.addStretch()
        right_layout.addLayout(vt_header)

        self._vt_list = QListWidget()
        self._vt_list.currentItemChanged.connect(self._on_vt_selected)
        right_layout.addWidget(self._vt_list)

        # Editor
        editor_box = QGroupBox("Verteiler-Details")
        editor_form = QFormLayout()

        self._edit_name = QLineEdit()
        self._edit_name.setPlaceholderText("z.B. UV Küche, HV")
        self._edit_name.returnPressed.connect(self._apply_vt)   # FA-3206
        editor_form.addRow("Name:", self._edit_name)

        self._combo_type = QComboBox()
        self._combo_type.addItems(VERTEILER_TYPES)
        editor_form.addRow("Typ:", self._combo_type)

        self._edit_designation = QLineEdit()
        self._edit_designation.setPlaceholderText("Bezeichnung / Aufschrift")
        self._edit_designation.returnPressed.connect(self._apply_vt)  # FA-3206
        editor_form.addRow("Bezeichnung:", self._edit_designation)

        self._btn_apply = QPushButton("Übernehmen")
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._apply_vt)
        editor_form.addRow("", self._btn_apply)

        editor_box.setLayout(editor_form)
        right_layout.addWidget(editor_box)

        splitter.addWidget(right)
        splitter.setSizes([350, 500])
        layout.addWidget(splitter, 1)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_enter(self):
        self._selected_room = None
        self._selected_room_floor_code = ""
        self._selected_vt = None
        self._btn_move_to_room.setVisible(False)
        self._btn_move_to_room.setEnabled(False)
        self._refresh_room_tree()
        self._refresh_vt_list()
        self._update_editor()

    # ------------------------------------------------------------------
    # Raumbaum
    # ------------------------------------------------------------------

    def _refresh_room_tree(self):
        self._room_tree.clear()
        for floor in self._project.all_floors:
            floor_item = QTreeWidgetItem(self._room_tree, [
                f"{floor.short_code} – {floor.name}", "",
            ])
            floor_item.setExpanded(True)
            floor_item.setFlags(floor_item.flags() & ~Qt.ItemIsSelectable)

            for apt in floor.apartments:
                apt_item = QTreeWidgetItem(floor_item, [apt.name, ""])
                apt_item.setExpanded(True)
                apt_item.setFlags(apt_item.flags() & ~Qt.ItemIsSelectable)

                for room in apt.rooms:
                    vt_hint = f"  [{', '.join(v.verteiler_type for v in room.verteiler)}]" \
                              if room.verteiler else ""
                    room_item = QTreeWidgetItem(apt_item, [
                        room.name + vt_hint, room.number,
                    ])
                    room_item.setData(0, Qt.UserRole, (floor.short_code, room))

        fit_columns(self._room_tree)

    @staticmethod
    def _is_verteiler_pseudo_room(room: Room | None) -> bool:
        """True für einen aus dem Einbauort abgeleiteten Verteiler-Platzhalter
        ohne echten Standort (XlsxImportService.create_verteiler_rooms):
        keine Raumnummer, aber mindestens ein Verteiler-Objekt."""
        return bool(room) and not room.number and bool(room.verteiler)

    def _on_room_selected(self, current, _previous):
        if current:
            self._selected_room_floor_code, self._selected_room = current.data(0, Qt.UserRole)
        else:
            self._selected_room_floor_code, self._selected_room = "", None
        self._selected_vt = None
        self._btn_add_vt.setEnabled(self._selected_room is not None)
        is_pseudo = self._is_verteiler_pseudo_room(self._selected_room)
        self._btn_move_to_room.setVisible(is_pseudo)
        self._btn_move_to_room.setEnabled(is_pseudo)
        self._refresh_vt_list()
        self._update_editor()

    # ------------------------------------------------------------------
    # Verteiler-Liste
    # ------------------------------------------------------------------

    def _refresh_vt_list(self):
        self._vt_list.clear()
        if not self._selected_room:
            return
        for vt in self._selected_room.verteiler:
            label = f"{vt.verteiler_type}  –  {vt.name}" if vt.name else vt.verteiler_type
            if vt.designation:
                label += f"  ({vt.designation})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, vt)
            self._vt_list.addItem(item)

    def _on_vt_selected(self, current, _previous):
        if current:
            self._selected_vt = current.data(Qt.UserRole)
        else:
            self._selected_vt = None
        self._btn_remove_vt.setEnabled(self._selected_vt is not None)
        self._btn_apply.setEnabled(self._selected_vt is not None)
        self._update_editor()

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _add_verteiler(self):
        if not self._selected_room:
            return
        vt = Verteiler(name="", verteiler_type="UV")
        self._selected_room.verteiler.append(vt)
        self._selected_vt = vt
        self._refresh_vt_list()
        self._refresh_room_tree()
        # Neuen Eintrag selektieren
        for i in range(self._vt_list.count()):
            if self._vt_list.item(i).data(Qt.UserRole) is vt:
                self._vt_list.setCurrentRow(i)
                break
        self._update_editor()

    def _move_verteiler_to_room(self):
        """Ordnet den ausgewählten Verteiler-Platzhalter (z.B. 'HV  HV') einem
        echten Raum zu -- verschiebt Verteiler-Objekt(e) und alle darin
        montierten Geräte (device.room_id / line.assigned_room_ids) dorthin
        und speichert die Zuordnung für künftige Re-Importe (FA-521b-Folgefix,
        siehe XlsxImportService.apply_verteiler_room_overrides)."""
        pseudo_room = self._selected_room
        if not self._is_verteiler_pseudo_room(pseudo_room):
            return

        key = XlsxImportService.verteiler_key(pseudo_room.name)
        if not key:
            QMessageBox.warning(
                self, "Verteiler-Typ nicht erkannt",
                "Der Name dieses Platzhalters lässt keinen Verteiler-Typ "
                "(HV/UV/NV/TV) erkennen und kann nicht automatisch "
                "zugeordnet werden.",
            )
            return

        candidates: list[tuple[str, str, Room]] = []  # (label, floor_code, room)
        for floor in self._project.all_floors:
            for apt in floor.apartments:
                for room in apt.rooms:
                    if not room.number or room is pseudo_room:
                        continue
                    candidates.append((
                        f"{floor.short_code} – {room.name} (Nr. {room.number})",
                        floor.short_code, room,
                    ))
        if not candidates:
            QMessageBox.information(
                self, "Kein Zielraum verfügbar",
                "Es sind noch keine echten Räume vorhanden, denen der "
                "Verteiler zugeordnet werden könnte.",
            )
            return

        labels = [c[0] for c in candidates]
        label, ok = QInputDialog.getItem(
            self, "Verteiler zuordnen",
            f"In welchem Raum ist \"{pseudo_room.name.strip()}\" tatsächlich montiert?",
            labels, 0, False,
        )
        if not ok:
            return
        _, target_floor_code, target_room = candidates[labels.index(label)]

        importer = XlsxImportService()
        merged = importer.apply_verteiler_room_overrides(
            self._project.topology, self._project.areal,
            {key: [target_floor_code, target_room.number]},
        )
        if not merged:
            QMessageBox.warning(
                self, "Zuordnung fehlgeschlagen",
                "Der Verteiler konnte nicht verschoben werden.",
            )
            return

        # Für künftige Re-Importe merken (siehe main_window._import_xlsx /
        # _import_ga_report_xlsx: wendet dies nach create_verteiler_rooms an).
        self._project.verteiler_room_overrides[key] = [target_floor_code, target_room.number]

        self._selected_room = None
        self._selected_room_floor_code = ""
        self._selected_vt = None
        self._refresh_room_tree()
        self._refresh_vt_list()
        self._update_editor()
        QMessageBox.information(
            self, "Verteiler zugeordnet",
            f"\"{pseudo_room.name.strip()}\" wurde {target_room.name} (Nr. {target_room.number}) "
            "zugeordnet. Diese Zuordnung bleibt bei künftigen Re-Importen erhalten.",
        )

    def _remove_verteiler(self):
        if not self._selected_room or not self._selected_vt:
            return
        vt = self._selected_vt
        name = vt.name or vt.verteiler_type
        reply = QMessageBox.question(
            self, "Verteiler entfernen",
            f"Verteiler \"{name}\" wirklich entfernen?\n"
            "Alle zugeordneten Geräte (Aktoren, Koppler, ...) gehen verloren.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._selected_room.verteiler.remove(vt)
            self._selected_vt = None
            self._refresh_vt_list()
            self._refresh_room_tree()
            self._update_editor()

    def _apply_vt(self):
        if not self._selected_vt:
            return
        self._selected_vt.name = self._edit_name.text().strip()
        self._selected_vt.verteiler_type = self._combo_type.currentText()
        self._selected_vt.designation = self._edit_designation.text().strip()
        self._refresh_vt_list()
        self._refresh_room_tree()
        # Selektion wiederherstellen
        for i in range(self._vt_list.count()):
            if self._vt_list.item(i).data(Qt.UserRole) is self._selected_vt:
                self._vt_list.setCurrentRow(i)
                break

    # ------------------------------------------------------------------
    # Editor-Zustand
    # ------------------------------------------------------------------

    def _update_editor(self):
        has_vt = self._selected_vt is not None
        self._edit_name.setEnabled(has_vt)
        self._combo_type.setEnabled(has_vt)
        self._edit_designation.setEnabled(has_vt)
        self._btn_apply.setEnabled(has_vt)

        if has_vt:
            self._edit_name.setText(self._selected_vt.name)
            idx = self._combo_type.findText(self._selected_vt.verteiler_type)
            self._combo_type.setCurrentIndex(idx if idx >= 0 else 0)
            self._edit_designation.setText(self._selected_vt.designation)
        else:
            self._edit_name.clear()
            self._combo_type.setCurrentIndex(0)
            self._edit_designation.clear()
