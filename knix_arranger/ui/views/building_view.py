"""
Gebäudestruktur-Baumansicht (FA-101 bis FA-107)
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLabel, QMenu, QInputDialog, QMessageBox, QDialog,
    QFormLayout, QLineEdit, QComboBox, QDialogButtonBox,
)
from PySide6.QtCore import Signal, Qt
from ...models.building import Areal, Building, Wing, Floor, Apartment, Room, Verteiler, STANDARD_FLOOR_NAMES
from ...models.topology import Topology
from ...services.building_service import BuildingService
from ..column_utils import fit_columns

_DEVICE_TYPE_LABELS: dict[str, str] = {
    "actor":         "Aktor",
    "sensor":        "Sensor",
    "coupler":       "Koppler",
    "power_supply":  "Spannungsversorgung",
    "other":         "Sonstiges",
}


class BuildingView(QWidget):
    """Gebäudestruktur als Baum mit Bearbeitungsfunktionen."""

    structure_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._areal: Areal | None = None
        self._topology: Topology | None = None

        layout = QVBoxLayout(self)

        # Titel
        title = QLabel("Gebäudestruktur")
        title.setObjectName("title")
        layout.addWidget(title)

        # Toolbar – Zeile 1: Hinzufügen
        toolbar1 = QHBoxLayout()
        self._btn_add_building  = QPushButton("+ Gebäude")
        self._btn_add_wing      = QPushButton("+ Flügel")
        self._btn_add_floor     = QPushButton("+ Stockwerk")
        self._btn_add_apartment = QPushButton("+ Wohnung/Zone")
        self._btn_add_room      = QPushButton("+ Raum")
        self._btn_add_verteiler = QPushButton("+ Verteiler")

        self._btn_add_building.clicked.connect(self._add_building)
        self._btn_add_wing.clicked.connect(self._add_wing)
        self._btn_add_floor.clicked.connect(self._add_floor)
        self._btn_add_apartment.clicked.connect(self._add_apartment)
        self._btn_add_room.clicked.connect(self._add_room)
        self._btn_add_verteiler.clicked.connect(self._add_verteiler)

        toolbar1.addWidget(self._btn_add_building)
        toolbar1.addWidget(self._btn_add_wing)
        toolbar1.addWidget(self._btn_add_floor)
        toolbar1.addWidget(self._btn_add_apartment)
        toolbar1.addWidget(self._btn_add_room)
        toolbar1.addWidget(self._btn_add_verteiler)
        toolbar1.addStretch()
        layout.addLayout(toolbar1)

        # Toolbar – Zeile 2: Bearbeiten / Löschen
        toolbar2 = QHBoxLayout()
        self._btn_rename = QPushButton("Umbenennen")
        self._btn_rename.clicked.connect(self._rename_selected)
        self._btn_delete = QPushButton("Entfernen")
        self._btn_delete.setObjectName("danger")
        self._btn_delete.clicked.connect(self._delete_selected)

        toolbar2.addWidget(self._btn_rename)
        toolbar2.addStretch()
        toolbar2.addWidget(self._btn_delete)
        layout.addLayout(toolbar2)

        # Baum
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels(["Element", "Typ", "Details"])
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def showEvent(self, event):
        """Baut den Baum beim Einblenden neu auf, damit Änderungen (z.B. neue
        function_assignments nach GA-Neugenerierung) sofort sichtbar sind."""
        super().showEvent(event)
        self._refresh_tree()

    def set_bus(self, bus):
        """Verbindet die View mit dem zentralen ProjectBus (für Phase B: manuelle Bearbeitung)."""
        self._bus = bus

    def set_areal(self, areal: Areal):
        """Setzt die anzuzeigende Gebäudestruktur."""
        self._areal = areal
        self._refresh_tree()

    def set_topology(self, topology: Topology):
        """Setzt die Topologie für die Gerätezahl-Anzeige."""
        self._topology = topology
        self._refresh_tree()

    # ------------------------------------------------------------------
    # Geräte-Hilfsmethoden
    # ------------------------------------------------------------------

    def _devices_for_building(self, building: Building) -> int:
        if not self._topology:
            return 0
        room_ids = {r.id for r in building.all_rooms}
        count = 0
        for area in self._topology.areas:
            for line in area.lines:
                if any(rid in room_ids for rid in line.assigned_room_ids):
                    count += line.device_count
        return count

    def _devices_for_room(self, room) -> list:
        """Geräte mit direkter room_id-Zuweisung (Sensoren, manuell, Import)."""
        if not self._topology:
            return []
        return [
            device
            for area in self._topology.areas
            for line in area.lines
            for device in line.devices
            if device.room_id == room.id
        ]

    @staticmethod
    def _loc_matches_vt(loc: str, vt_names: set[str]) -> bool:
        """Prüft ob eine installation_location zu einem Verteiler gehört.

        Erlaubt Abweichungen wie 'HV' vs 'HV Technik': Es reicht, wenn
        einer der Werte ein Präfix des anderen ist (case-insensitiv).
        """
        loc = loc.strip().lower()
        if not loc:
            return False
        for name in vt_names:
            if not name:
                continue
            if loc == name or loc.startswith(name) or name.startswith(loc):
                return True
        return False

    def _devices_for_verteiler(self, room, vt) -> list:
        """Geräte auf Linien, die diesen Raum bedienen und deren
        installation_location mit dem Verteiler-Namen übereinstimmt
        (Aktoren, Spannungsversorgungen)."""
        if not self._topology:
            return []
        vt_names = {n.strip().lower() for n in [vt.name, vt.verteiler_type] if n}
        result = []
        seen: set[str] = set()
        for area in self._topology.areas:
            for line in area.lines:
                if room.id not in line.assigned_room_ids:
                    continue
                for device in line.devices:
                    if device.id in seen:
                        continue
                    if self._loc_matches_vt(device.installation_location, vt_names):
                        result.append(device)
                        seen.add(device.id)
        return result

    # ------------------------------------------------------------------
    # Baumdarstellung
    # ------------------------------------------------------------------

    def _refresh_tree(self):
        self._tree.clear()
        if not self._areal:
            return

        areal_item = QTreeWidgetItem(self._tree, [self._areal.name or "Areal", "Areal", ""])
        areal_item.setData(0, Qt.UserRole, ("areal", self._areal))
        areal_item.setExpanded(True)

        for building in self._areal.buildings:
            bld_devices = self._devices_for_building(building)
            bld_item = QTreeWidgetItem(
                areal_item,
                [building.name, "Gebäude", f"{bld_devices} Geräte"],
            )
            bld_item.setData(0, Qt.UserRole, ("building", building))
            bld_item.setExpanded(True)

            for wing in building.wings:
                wing_item = QTreeWidgetItem(bld_item, [wing.name, "Flügel", ""])
                wing_item.setData(0, Qt.UserRole, ("wing", wing))
                wing_item.setExpanded(True)

                for floor in wing.floors:
                    devices = floor.total_devices()
                    detail = f"HG {floor.main_group_number}, {devices} Geräte"
                    floor_item = QTreeWidgetItem(
                        wing_item,
                        [f"{floor.short_code} – {floor.name}", "Stockwerk", detail],
                    )
                    floor_item.setData(0, Qt.UserRole, ("floor", floor))
                    floor_item.setExpanded(True)

                    for apt in floor.apartments:
                        apt_item = QTreeWidgetItem(
                            floor_item,
                            [apt.name, "Wohnung/Zone", f"{len(apt.rooms)} Räume"],
                        )
                        apt_item.setData(0, Qt.UserRole, ("apartment", apt))
                        apt_item.setExpanded(True)

                        for room in apt.rooms:
                            # Geräte nach Typ getrennt sammeln
                            room_devices = self._devices_for_room(room)
                            vt_dev_map: dict[str, list] = {}
                            shown_ids: set[str] = set()
                            for vt in room.verteiler:
                                vd = self._devices_for_verteiler(room, vt)
                                vt_dev_map[vt.id] = vd
                                for d in vd:
                                    shown_ids.add(d.id)

                            topo_total = len(room_devices) + len(shown_ids)
                            sensor_count = len(room.bedienelemente)
                            dev_count    = topo_total if topo_total else room.total_devices()
                            gewerke      = len(room.gewerk_assignments)
                            room_label   = room.name if not room.number else f"{room.number} – {room.name}"
                            parts = [f"{gewerke} Gewerke", f"{dev_count} Geräte"]
                            if sensor_count:
                                parts.append(f"{sensor_count} Bedienelemente")
                            room_item = QTreeWidgetItem(
                                apt_item,
                                [room_label, "Raum", ", ".join(parts)],
                            )
                            room_item.setData(0, Qt.UserRole, ("room", room))

                            # Verteiler als Kindknoten + zugehörige Topologie-Geräte
                            for vt in room.verteiler:
                                vd = vt_dev_map.get(vt.id, [])
                                if vd:
                                    vt_detail = f"{len(vd)} Geräte"
                                else:
                                    vt_detail = (
                                        f"{len(vt.actor_assignments)} Aktoren"
                                        f", {len(vt.line_couplers)} Koppler"
                                        f", {len(vt.power_supplies)} Speisungen"
                                        f", {len(vt.interfaces)} Schnittst."
                                    )
                                vt_item = QTreeWidgetItem(
                                    room_item,
                                    [vt.name or vt.verteiler_type, vt.verteiler_type, vt_detail],
                                )
                                vt_item.setData(0, Qt.UserRole, ("verteiler", vt))
                                vt_item.setExpanded(True)
                                for device in vd:
                                    label = device.product_name or device.product or device.device_type
                                    addr  = device.physical_address or "–"
                                    dtype = _DEVICE_TYPE_LABELS.get(device.device_type, device.device_type)
                                    QTreeWidgetItem(vt_item, [label, addr, dtype])

                            # Bedienelemente aus Wizard-Funktionsdefinition
                            for be in room.bedienelemente:
                                ch_info = f"{be.channels}-Kanal"
                                pn = f"  [{be.participant_number}]" if be.participant_number else ""
                                be_item = QTreeWidgetItem(
                                    room_item,
                                    [f"{be.element_type}{pn}", "Bedienelement",
                                     f"{ch_info}, {len(be.function_assignments)} Funktionen"],
                                )
                                for fa in be.function_assignments:
                                    QTreeWidgetItem(
                                        be_item,
                                        [fa.button_channel, fa.function_ga, fa.description],
                                    )

                            # Raumgebundene Topologie-Geräte (Sensoren, manuell, Import)
                            for device in room_devices:
                                if device.id in shown_ids:
                                    continue
                                label = device.product_name or device.product or device.device_type
                                addr  = device.physical_address or "–"
                                dtype = _DEVICE_TYPE_LABELS.get(device.device_type, device.device_type)
                                QTreeWidgetItem(room_item, [label, addr, dtype])

        fit_columns(self._tree)

    # ------------------------------------------------------------------
    # Selektion
    # ------------------------------------------------------------------

    def _get_selected_data(self) -> tuple[str, object] | None:
        item = self._tree.currentItem()
        if item:
            return item.data(0, Qt.UserRole)
        return None

    # ------------------------------------------------------------------
    # Hinzufügen
    # ------------------------------------------------------------------

    def _add_building(self):
        if not self._areal:
            return
        name, ok = QInputDialog.getText(self, "Gebäude hinzufügen", "Gebäudename:")
        if ok and name:
            building = Building(name=name)
            wing = Wing(name="Hauptgebäude")
            building.wings.append(wing)
            self._areal.buildings.append(building)
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_wing(self):
        data = self._get_selected_data()
        if not data or data[0] != "building":
            QMessageBox.information(self, "Hinweis", "Bitte ein Gebäude auswählen.")
            return
        building = data[1]
        name, ok = QInputDialog.getText(self, "Flügel hinzufügen", "Flügelname:")
        if ok and name:
            building.wings.append(Wing(name=name))
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_floor(self):
        data = self._get_selected_data()
        if not data or data[0] != "wing":
            QMessageBox.information(self, "Hinweis", "Bitte einen Flügel auswählen.")
            return
        wing = data[1]
        code, ok = QInputDialog.getText(self, "Stockwerk hinzufügen", "Kürzel (z.B. EG, 1.OG, UG):")
        if not (ok and code):
            return
        default_name = STANDARD_FLOOR_NAMES.get(code.upper(), code)
        name, ok2 = QInputDialog.getText(self, "Stockwerk", "Name:", text=default_name)
        if ok2 and name:
            # BuildingService legt automatisch eine Standard-Wohnung an
            BuildingService.add_floor(wing, name=name, short_code=code)
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_apartment(self):
        data = self._get_selected_data()
        if not data or data[0] != "floor":
            QMessageBox.information(self, "Hinweis", "Bitte ein Stockwerk auswählen.")
            return
        floor = data[1]
        name, ok = QInputDialog.getText(self, "Wohnung/Zone hinzufügen", "Name:")
        if ok and name:
            floor.apartments.append(Apartment(name=name))
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_room(self):
        data = self._get_selected_data()
        if not data or data[0] != "apartment":
            QMessageBox.information(self, "Hinweis", "Bitte eine Wohnung/Zone auswählen.")
            return
        apt = data[1]
        number, ok = QInputDialog.getText(self, "Raum hinzufügen", "Raumnummer (z.B. E01):")
        if not (ok and number):
            return
        name, ok2 = QInputDialog.getText(self, "Raum", "Raumname:")
        if ok2 and name:
            apt.rooms.append(Room(number=number, name=name))
            self._refresh_tree()
            self.structure_changed.emit()

    def _add_verteiler(self):
        data = self._get_selected_data()
        if not data or data[0] != "room":
            QMessageBox.information(self, "Hinweis", "Bitte einen Raum auswählen.")
            return
        room = data[1]

        dlg = QDialog(self)
        dlg.setWindowTitle("Verteiler hinzufügen")
        form = QFormLayout(dlg)

        name_edit        = QLineEdit()
        name_edit.setPlaceholderText("z.B. UV Küche, HV")
        type_combo       = QComboBox()
        type_combo.addItems(["HV", "UV", "NV", "TV"])
        designation_edit = QLineEdit()

        form.addRow("Name:", name_edit)
        form.addRow("Typ:", type_combo)
        form.addRow("Bezeichnung:", designation_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.Accepted:
            vt = Verteiler(
                name=name_edit.text().strip() or type_combo.currentText(),
                verteiler_type=type_combo.currentText(),
                designation=designation_edit.text().strip(),
            )
            room.verteiler.append(vt)
            self._refresh_tree()
            self.structure_changed.emit()

    # ------------------------------------------------------------------
    # Umbenennen
    # ------------------------------------------------------------------

    def _on_double_click(self, _item: QTreeWidgetItem, _column: int):
        self._rename_selected()

    def _rename_selected(self):
        data = self._get_selected_data()
        if not data:
            return
        kind, obj = data

        titles = {
            "areal":     "Areal umbenennen",
            "building":  "Gebäude umbenennen",
            "wing":      "Flügel umbenennen",
            "floor":     "Stockwerk umbenennen",
            "apartment": "Wohnung/Zone umbenennen",
            "room":      "Raum umbenennen",
            "verteiler": "Verteiler umbenennen",
        }
        title = titles.get(kind)
        if not title:
            return

        new_name, ok = QInputDialog.getText(self, title, "Name:", text=getattr(obj, "name", ""))
        if not (ok and new_name):
            return
        obj.name = new_name

        if kind == "floor":
            code, ok2 = QInputDialog.getText(self, "Stockwerk", "Kürzel:", text=obj.short_code)
            if ok2 and code:
                obj.short_code = code

        self._refresh_tree()
        self.structure_changed.emit()

    # ------------------------------------------------------------------
    # Löschen
    # ------------------------------------------------------------------

    def _delete_selected(self):
        data = self._get_selected_data()
        if not data:
            return
        kind, obj = data
        reply = QMessageBox.question(
            self, "Löschen",
            f"'{getattr(obj, 'name', kind)}' wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._remove_from_structure(kind, obj)
            self._refresh_tree()
            self.structure_changed.emit()

    def _remove_from_structure(self, kind: str, obj):
        if not self._areal:
            return
        if kind == "building":
            if obj in self._areal.buildings:
                self._areal.buildings.remove(obj)
        elif kind == "wing":
            for b in self._areal.buildings:
                if obj in b.wings:
                    b.wings.remove(obj)
                    return
        elif kind == "floor":
            for b in self._areal.buildings:
                for w in b.wings:
                    if obj in w.floors:
                        w.floors.remove(obj)
                        return
        elif kind == "apartment":
            for f in self._areal.all_floors:
                if obj in f.apartments:
                    f.apartments.remove(obj)
                    return
        elif kind == "room":
            for f in self._areal.all_floors:
                for a in f.apartments:
                    if obj in a.rooms:
                        a.rooms.remove(obj)
                        return
        elif kind == "verteiler":
            for f in self._areal.all_floors:
                for a in f.apartments:
                    for r in a.rooms:
                        if obj in r.verteiler:
                            r.verteiler.remove(obj)
                            return

    # ------------------------------------------------------------------
    # Kontextmenü
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return

        menu = QMenu(self)
        kind = data[0]

        if kind == "areal":
            menu.addAction("Gebäude hinzufügen", self._add_building)
            menu.addAction("Umbenennen",          self._rename_selected)
        elif kind == "building":
            menu.addAction("Flügel hinzufügen",   self._add_wing)
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "wing":
            menu.addAction("Stockwerk hinzufügen", self._add_floor)
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "floor":
            menu.addAction("Wohnung/Zone hinzufügen", self._add_apartment)
            menu.addAction("Umbenennen",              self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",                 self._delete_selected)
        elif kind == "apartment":
            menu.addAction("Raum hinzufügen",      self._add_room)
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "room":
            menu.addAction("Verteiler hinzufügen", self._add_verteiler)
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)
        elif kind == "verteiler":
            menu.addAction("Umbenennen",           self._rename_selected)
            menu.addSeparator()
            menu.addAction("Löschen",              self._delete_selected)

        menu.exec(self._tree.viewport().mapToGlobal(pos))
