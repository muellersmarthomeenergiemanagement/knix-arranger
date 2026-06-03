"""
Wizard Schritt 3: Räume anlegen

Baum-Struktur: Zone → Stockwerk → Räume
Jeder Raum bekommt eine floor_id (physisches Stockwerk) und gehört zu
einer Zone (Apartment).  Bei EFH (eine Zone) wird stockwerkbasiert
nummeriert (E01, O01), bei MFH zonenbasiert (W1-01, W2-03).
"""
from __future__ import annotations
import copy
import re
import uuid
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QPushButton,
    QLineEdit, QFormLayout, QGroupBox, QDialog, QDialogButtonBox,
    QTextEdit, QMessageBox,
)
from PySide6.QtCore import Qt, QEvent
from ...models.project import KnxProject
from ...models.building import Room, Wing, Floor, Apartment
from ..column_utils import fit_columns


# UserRole-Schlüssel für Tree-Items
_KIND_ZONE       = "zone"        # (zone_name,)
_KIND_ZONE_FLOOR = "zone_floor"  # (apartment, floor)
_KIND_ROOM       = "room"        # (room, apartment, floor)


class Step03Rooms(QWidget):
    """Räume pro Zone und Stockwerk anlegen."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        # Clipboard: {"type": "floor", "rooms": [...]}
        #         oder {"type": "zone", "floors": [{"rooms": [...]}, ...]}
        self._room_clipboard: dict | None = None
        self._item_index: dict = {}  # (kind_key, id_or_name) → QTreeWidgetItem

        layout = QVBoxLayout(self)
        info = QLabel(
            "Legen Sie Räume pro Zone (Wohnung) und Stockwerk an.\n"
            "EFH: Raumnummern nach Stockwerk (E01, O01).  "
            "MFH: Raumnummern nach Zone (W1-01, W2-01)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        content = QHBoxLayout()

        # ── Baum ──────────────────────────────────────────────────────────
        tree_layout = QVBoxLayout()
        self._tree = QTreeWidget()
        self._tree.itemExpanded.connect(lambda _: fit_columns(self._tree))
        self._tree.setHeaderLabels(["Zone / Stockwerk / Raum", "Raumnr.", "Geräte"])
        self._tree.currentItemChanged.connect(self._on_selection)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.installEventFilter(self)
        tree_layout.addWidget(self._tree)

        btn_layout = QHBoxLayout()
        self._btn_add    = QPushButton("+ Raum")
        self._btn_remove = QPushButton("Entfernen")
        self._btn_remove.setObjectName("danger")
        self._btn_remove.setToolTip("Raum entfernen (Entf)  ·  F2: Name bearbeiten")
        self._btn_clone  = QPushButton("Klonen")
        self._btn_clone.setToolTip("Raum duplizieren – Nummer wird inkrementiert")
        self._btn_bulk   = QPushButton("Massenerfassung…")
        self._btn_bulk.setToolTip(
            "Mehrere Räume auf einmal anlegen (eine Zeile = ein Raum: 'E01 Wohnzimmer')"
        )
        self._btn_copy_floor = QPushButton("Stockwerk kop.")
        self._btn_copy_floor.setToolTip(
            "Alle Räume des gewählten Stockwerks kopieren"
        )
        self._btn_copy_zone  = QPushButton("Zone kop.")
        self._btn_copy_zone.setToolTip(
            "Alle Stockwerke der gewählten Zone kopieren"
        )
        self._btn_paste  = QPushButton("Einfügen")
        self._btn_paste.setToolTip("Kopierte Räume einfügen")
        self._btn_paste.setEnabled(False)

        self._btn_add.clicked.connect(self._add_room)
        self._btn_remove.clicked.connect(self._remove_room)
        self._btn_clone.clicked.connect(self._clone_room)
        self._btn_bulk.clicked.connect(self._bulk_add_rooms)
        self._btn_copy_floor.clicked.connect(self._copy_floor)
        self._btn_copy_zone.clicked.connect(self._copy_zone)
        self._btn_paste.clicked.connect(self._paste)

        for btn in (self._btn_add, self._btn_remove, self._btn_clone,
                    self._btn_bulk, self._btn_copy_floor, self._btn_copy_zone,
                    self._btn_paste):
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        tree_layout.addLayout(btn_layout)
        content.addLayout(tree_layout, 2)

        # ── Details ────────────────────────────────────────────────────────
        detail = QGroupBox("Raum-Details")
        form = QFormLayout()
        self._room_number = QLineEdit()
        self._room_number.setPlaceholderText("z.B. E01")
        self._room_name   = QLineEdit()
        self._room_name.setPlaceholderText("z.B. Schlafzimmer")
        form.addRow("Raumnummer:", self._room_number)
        form.addRow("Name:", self._room_name)

        self._btn_apply = QPushButton("Übernehmen")
        self._btn_apply.clicked.connect(self._apply_changes)
        self._room_number.returnPressed.connect(self._apply_changes)
        self._room_name.returnPressed.connect(self._apply_changes)
        form.addRow("", self._btn_apply)

        detail.setLayout(form)
        content.addWidget(detail, 1)
        layout.addLayout(content)

    def eventFilter(self, obj, event):
        if obj is self._tree and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Delete:
                self._remove_room()
                return True
            if key == Qt.Key.Key_F2:
                # F2: Raumnamen-Feld fokussieren (wie Doppelklick)
                item = self._tree.currentItem()
                if item and item.data(0, Qt.UserRole) and \
                        item.data(0, Qt.UserRole)[0] == _KIND_ROOM:
                    self._room_name.setFocus()
                    self._room_name.selectAll()
                    return True
        return super().eventFilter(obj, event)

    # ── Hilfsmethoden ──────────────────────────────────────────────────────

    def _get_wing(self) -> Wing | None:
        b = self._project.areal.buildings
        if not b or not b[0].wings:
            return None
        return b[0].wings[0]

    def _all_zone_names(self) -> list[str]:
        wing = self._get_wing()
        if not wing:
            return []
        return sorted({apt.name for floor in wing.floors for apt in floor.apartments})

    def _is_efh(self) -> bool:
        """EFH-Modus: genau eine Zone über alle Stockwerke."""
        return len(self._all_zone_names()) <= 1

    def _floor_by_id(self) -> dict[str, Floor]:
        wing = self._get_wing()
        if not wing:
            return {}
        return {f.id: f for f in wing.floors}

    def _suggest_room_number(self, apt: Apartment, floor: Floor) -> str:
        """Schlägt die nächste Raumnummer vor: Stockwerkkürzel + laufende Nummer."""
        existing = len(apt.rooms)
        return f"{floor.short_code}{existing + 1:02d}"

    # ── Refresh ────────────────────────────────────────────────────────────

    def on_enter(self):
        self._refresh()

    def _refresh(self):
        self._tree.clear()
        self._item_index = {}
        wing = self._get_wing()
        if not wing:
            return

        zone_names = self._all_zone_names()
        for zone_name in zone_names:
            # Alle Apartments mit diesem Namen über alle Stockwerke
            zone_floor_pairs: list[tuple[Apartment, Floor]] = [
                (apt, floor)
                for floor in wing.floors
                for apt in floor.apartments
                if apt.name == zone_name
            ]
            total_rooms = sum(len(apt.rooms) for apt, _ in zone_floor_pairs)

            zone_item = QTreeWidgetItem(self._tree, [
                f"Zone: {zone_name}", f"{total_rooms} Räume", "",
            ])
            zone_item.setData(0, Qt.UserRole, (_KIND_ZONE, zone_name, zone_floor_pairs))
            zone_item.setExpanded(True)
            self._item_index[(_KIND_ZONE, zone_name)] = zone_item

            for apt, floor in zone_floor_pairs:
                floor_label = f"{floor.short_code} – {floor.name}" if floor.name else floor.short_code
                floor_item = QTreeWidgetItem(zone_item, [
                    floor_label, f"{len(apt.rooms)} Räume", "",
                ])
                floor_item.setData(0, Qt.UserRole, (_KIND_ZONE_FLOOR, apt, floor))
                floor_item.setExpanded(True)
                self._item_index[(_KIND_ZONE_FLOOR, id(apt))] = floor_item

                for room in apt.rooms:
                    room_item = QTreeWidgetItem(floor_item, [
                        room.name, room.number, str(room.total_devices()),
                    ])
                    room_item.setData(0, Qt.UserRole, (_KIND_ROOM, room, apt, floor))
                    self._item_index[(_KIND_ROOM, id(room))] = room_item

        fit_columns(self._tree)

    # ── Selektion ──────────────────────────────────────────────────────────

    def _on_selection(self, current, _previous):
        if not current:
            return
        kind = current.data(0, Qt.UserRole)
        if kind and kind[0] == _KIND_ROOM:
            room = kind[1]
            self._room_number.setText(room.number)
            self._room_name.setText(room.name)

    def _on_double_click(self, item, _column):
        kind = item.data(0, Qt.UserRole)
        if kind and kind[0] == _KIND_ROOM:
            self._room_number.setFocus()
            self._room_number.selectAll()

    # ── Kontextauflösung ───────────────────────────────────────────────────

    def _resolve_zone_floor(self) -> tuple[Apartment, Floor] | None:
        """
        Gibt (apartment, floor) für das aktuell selektierte Item zurück.
        Beim Zone-Item nur wenn genau ein Stockwerk vorhanden.
        """
        item = self._tree.currentItem()
        if not item:
            return None
        kind = item.data(0, Qt.UserRole)
        if not kind:
            return None

        if kind[0] == _KIND_ZONE_FLOOR:
            return kind[1], kind[2]
        if kind[0] == _KIND_ROOM:
            return kind[2], kind[3]
        if kind[0] == _KIND_ZONE:
            pairs = kind[2]
            if len(pairs) == 1:
                return pairs[0]
            # Mehrere Stockwerke → kein eindeutiger Kontext
            return None
        return None

    # ── Raum hinzufügen ────────────────────────────────────────────────────

    def _add_room(self):
        ctx = self._resolve_zone_floor()
        if ctx is None:
            item = self._tree.currentItem()
            if item and item.data(0, Qt.UserRole) and item.data(0, Qt.UserRole)[0] == _KIND_ZONE:
                QMessageBox.information(
                    self, "Stockwerk wählen",
                    "Diese Zone umfasst mehrere Stockwerke.\n"
                    "Wählen Sie ein Stockwerk in der Zone aus, um einen Raum hinzuzufügen.",
                )
            return
        apt, floor = ctx
        number = self._suggest_room_number(apt, floor)
        room = Room(number=number, name="Raum", floor_id=floor.id)
        apt.rooms.append(room)
        self._refresh()
        self._select_by_data(_KIND_ROOM, room)

    # ── Raum entfernen ─────────────────────────────────────────────────────

    def _remove_room(self):
        item = self._tree.currentItem()
        if not item:
            return
        kind = item.data(0, Qt.UserRole)
        if not kind or kind[0] != _KIND_ROOM:
            return
        room, apt, _floor = kind[1], kind[2], kind[3]
        reply = QMessageBox.question(
            self,
            "Raum entfernen",
            f'Raum "{room.name}" (Nr. {room.number}) wirklich entfernen?\n'
            "Alle Gewerke und Konfigurationen dieses Raums gehen verloren.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        apt.rooms.remove(room)
        self._refresh()

    # ── Raum klonen ────────────────────────────────────────────────────────

    def _clone_room(self):
        item = self._tree.currentItem()
        if not item:
            return
        kind = item.data(0, Qt.UserRole)
        if not kind or kind[0] != _KIND_ROOM:
            return
        room, apt, floor = kind[1], kind[2], kind[3]

        new_dict = copy.deepcopy(room.to_dict())
        new_dict["id"] = str(uuid.uuid4())
        new_dict["number"] = _increment_room_number(room.number)
        new_room = Room.from_dict(new_dict)
        new_room.floor_id = floor.id

        idx = apt.rooms.index(room)
        apt.rooms.insert(idx + 1, new_room)
        self._refresh()
        self._select_by_data(_KIND_ROOM, new_room)

    # ── Massenerfassung ────────────────────────────────────────────────────

    def _bulk_add_rooms(self):
        ctx = self._resolve_zone_floor()
        if ctx is None:
            QMessageBox.information(
                self, "Stockwerk wählen",
                "Wählen Sie ein Stockwerk innerhalb einer Zone aus.",
            )
            return
        apt, floor = ctx

        dlg = QDialog(self)
        dlg.setWindowTitle("Massenerfassung Räume")
        dlg.resize(400, 300)
        dlg_layout = QVBoxLayout(dlg)
        floor_label = f"{floor.short_code} – {floor.name}" if floor.name else floor.short_code
        dlg_layout.addWidget(QLabel(
            f"Räume für Zone '{apt.name}' / {floor_label}:\n"
            "Format: NUMMER Name  (z.B. E01 Wohnzimmer)"
        ))
        editor = QTextEdit()
        editor.setPlaceholderText("E01 Wohnzimmer\nE02 Schlafzimmer\nE03 Bad")
        dlg_layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        dlg_layout.addWidget(buttons)

        if dlg.exec() != QDialog.Accepted:
            return

        lines = [ln.strip() for ln in editor.toPlainText().splitlines() if ln.strip()]
        if not lines:
            return

        if apt.rooms:
            reply = QMessageBox.question(
                self, "Vorhandene Räume ersetzen?",
                f"'{apt.name}' / {floor_label} hat bereits {len(apt.rooms)} Raum/Räume.\n"
                "Diese werden ersetzt. Fortfahren?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        apt.rooms = []
        for line in lines:
            parts = line.split(None, 1)
            number = parts[0]
            name   = parts[1] if len(parts) > 1 else parts[0]
            apt.rooms.append(Room(
                id=str(uuid.uuid4()), number=number, name=name, floor_id=floor.id,
            ))

        self._refresh()
        self._select_by_data(_KIND_ZONE_FLOOR, apt)

    # ── Kopieren / Einfügen ────────────────────────────────────────────────

    @staticmethod
    def _rooms_to_dicts(apt: Apartment) -> list[dict]:
        return [copy.deepcopy(r.to_dict()) for r in apt.rooms]

    def _copy_floor(self):
        """Kopiert die Räume eines einzelnen Stockwerks."""
        ctx = self._resolve_zone_floor()
        if ctx is None:
            QMessageBox.information(
                self, "Stockwerk wählen",
                "Bitte ein konkretes Stockwerk innerhalb einer Zone auswählen.",
            )
            return
        apt, _floor = ctx
        if not apt.rooms:
            QMessageBox.information(
                self, "Keine Räume",
                f"Zone '{apt.name}' hat auf diesem Stockwerk noch keine Räume.",
            )
            return
        self._room_clipboard = {
            "type": "floor",
            "rooms": self._rooms_to_dicts(apt),
        }
        self._btn_paste.setEnabled(True)
        self._btn_paste.setToolTip(
            f"Stockwerk: {len(apt.rooms)} Räume aus '{apt.name}' kopiert"
        )

    def _copy_zone(self):
        """Kopiert alle Stockwerke einer Zone (index-basiert)."""
        item = self._tree.currentItem()
        if not item:
            QMessageBox.information(self, "Zone wählen", "Bitte eine Zone auswählen.")
            return
        kind = item.data(0, Qt.UserRole)
        if not kind:
            return

        # Zone-Item oder Zone-Floor-Item → Zone ermitteln
        if kind[0] == _KIND_ZONE:
            zone_floor_pairs = kind[2]
        elif kind[0] == _KIND_ZONE_FLOOR:
            # Eltern-Zone ermitteln
            parent = item.parent()
            if not parent:
                return
            kind = parent.data(0, Qt.UserRole)
            if not kind or kind[0] != _KIND_ZONE:
                return
            zone_floor_pairs = kind[2]
        elif kind[0] == _KIND_ROOM:
            parent = item.parent()
            if not parent:
                return
            grandparent = parent.parent()
            if not grandparent:
                return
            kind = grandparent.data(0, Qt.UserRole)
            if not kind or kind[0] != _KIND_ZONE:
                return
            zone_floor_pairs = kind[2]
        else:
            return

        floors_data = [
            {"rooms": self._rooms_to_dicts(apt)}
            for apt, _floor in zone_floor_pairs
        ]
        total = sum(len(f["rooms"]) for f in floors_data)
        if total == 0:
            QMessageBox.information(
                self, "Keine Räume", "Die gewählte Zone hat noch keine Räume.",
            )
            return

        self._room_clipboard = {"type": "zone", "floors": floors_data}
        self._btn_paste.setEnabled(True)
        n_floors = len(floors_data)
        self._btn_paste.setToolTip(
            f"Zone: {n_floors} Stockwerk(e), {total} Räume kopiert"
        )

    def _paste(self):
        if not self._room_clipboard:
            return
        if self._room_clipboard["type"] == "floor":
            self._paste_floor()
        else:
            self._paste_zone()

    def _paste_floor(self):
        ctx = self._resolve_zone_floor()
        if ctx is None:
            QMessageBox.information(
                self, "Stockwerk wählen",
                "Bitte das Ziel-Stockwerk innerhalb einer Zone auswählen.",
            )
            return
        apt, floor = ctx
        apt.rooms = []
        for room_dict in self._room_clipboard["rooms"]:
            new_dict = copy.deepcopy(room_dict)
            new_dict["id"] = str(uuid.uuid4())
            new_dict["floor_id"] = floor.id
            for g in new_dict.get("gewerk_assignments", []):
                g["id"] = str(uuid.uuid4())
            for b in new_dict.get("bedienelemente", []):
                b["id"] = str(uuid.uuid4())
            apt.rooms.append(Room.from_dict(new_dict))
        self._refresh()
        self._select_by_data(_KIND_ZONE_FLOOR, apt)

    def _paste_zone(self):
        """Fügt eine kopierte Zone index-basiert in die Ziel-Zone ein."""
        item = self._tree.currentItem()
        if not item:
            QMessageBox.information(self, "Zone wählen", "Bitte eine Ziel-Zone auswählen.")
            return
        kind = item.data(0, Qt.UserRole)
        if not kind:
            return

        # Ziel-Zone ermitteln (Zone-, Floor- oder Room-Item)
        if kind[0] == _KIND_ZONE:
            zone_floor_pairs = kind[2]
        elif kind[0] == _KIND_ZONE_FLOOR:
            parent = item.parent()
            kind = parent.data(0, Qt.UserRole) if parent else None
            if not kind or kind[0] != _KIND_ZONE:
                return
            zone_floor_pairs = kind[2]
        elif kind[0] == _KIND_ROOM:
            parent = item.parent()
            grandparent = parent.parent() if parent else None
            kind = grandparent.data(0, Qt.UserRole) if grandparent else None
            if not kind or kind[0] != _KIND_ZONE:
                return
            zone_floor_pairs = kind[2]
        else:
            return

        src_floors = self._room_clipboard["floors"]
        n_src = len(src_floors)
        n_dst = len(zone_floor_pairs)
        n_paste = min(n_src, n_dst)

        first_apt = None
        for i in range(n_paste):
            apt, floor = zone_floor_pairs[i]
            apt.rooms = []
            for room_dict in src_floors[i]["rooms"]:
                new_dict = copy.deepcopy(room_dict)
                new_dict["id"] = str(uuid.uuid4())
                new_dict["floor_id"] = floor.id
                for g in new_dict.get("gewerk_assignments", []):
                    g["id"] = str(uuid.uuid4())
                for b in new_dict.get("bedienelemente", []):
                    b["id"] = str(uuid.uuid4())
                apt.rooms.append(Room.from_dict(new_dict))
            if first_apt is None:
                first_apt = apt

        self._refresh()
        if first_apt:
            self._select_by_data(_KIND_ZONE_FLOOR, first_apt)

        if n_src != n_dst:
            QMessageBox.information(
                self, "Hinweis",
                f"{n_paste} von {n_src} Stockwerk(en) eingefügt "
                f"(Ziel hat {n_dst} Stockwerk(e)).",
            )

    # ── Details übernehmen ─────────────────────────────────────────────────

    def _apply_changes(self):
        item = self._tree.currentItem()
        if not item:
            return
        kind = item.data(0, Qt.UserRole)
        if not kind or kind[0] != _KIND_ROOM:
            return
        room = kind[1]
        room.number = self._room_number.text()
        room.name   = self._room_name.text()
        self._refresh()
        self._select_by_data(_KIND_ROOM, room)

    # ── Tree-Navigation ────────────────────────────────────────────────────

    def _select_by_data(self, kind_key: str, obj):
        """Selektiert Item anhand von kind_key und Objekt-Identität (O(1) via Index)."""
        key = (_KIND_ZONE, obj) if kind_key == _KIND_ZONE else (kind_key, id(obj))
        item = self._item_index.get(key)
        if item:
            self._tree.setCurrentItem(item)


# ── Hilfsfunktion ──────────────────────────────────────────────────────────

def _increment_room_number(number: str) -> str:
    """Inkrementiert den numerischen Teil einer Raumnummer (z.B. E01 → E02)."""
    m = re.match(r'^(.*?)(\d+)$', number)
    if m:
        prefix, digits = m.group(1), m.group(2)
        return f"{prefix}{int(digits) + 1:0{len(digits)}d}"
    return number + "_2"
