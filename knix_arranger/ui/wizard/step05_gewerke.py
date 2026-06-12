"""
Wizard Schritt 5: Gewerke pro Raum zuweisen
"""
from __future__ import annotations
import copy
import uuid
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QComboBox, QSpinBox,
    QGroupBox, QAbstractItemView, QHeaderView, QMessageBox, QLineEdit,
    QDialog,
)
from PySide6.QtCore import Qt, QTimer
from ...models.project import KnxProject
from ...models.building import GewerkAssignment
from ...models.group_address import GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup
from ...models.device import GEWERK_TO_SENSOR_TYPE
from ...services.gewerk_service import GewerkService
from ...services.address_generator import AddressGenerator
from ..dialogs.gewerk_template_dialog import GewerkTemplateDialog
from ..dialogs.extra_ga_dialog import ExtraGaDialog
from ..dialogs.product_select_dialog import ProductSelectDialog
from ..column_utils import fit_columns

# Spalten-Indizes
_COL_FLOOR   = 0
_COL_APT     = 1
_COL_ROOM    = 2
_COL_NUMBER  = 3
_COL_GCODE   = 4
_COL_GNAME   = 5
_COL_COUNT   = 6   # Anzahl (Taster / Kanäle) dieser Funktion
_COL_EXTRA   = 7   # Anzahl Extra-GAs (Info-Spalte)
_COL_ACTION  = 8
_NUM_COLS    = 9


def _fresh_ga(ga_dict: dict) -> GewerkAssignment:
    """Erstellt GewerkAssignment aus Dict mit neuer UUID."""
    d = copy.deepcopy(ga_dict)
    d["id"] = str(uuid.uuid4())
    return GewerkAssignment.from_dict(d)


class Step05Gewerke(QWidget):
    """Gewerke pro Raum zuweisen (FA-300)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        # Zwischenablage: None oder {"level": "room"|"apartment"|"floor", "data": ...}
        self._clipboard: dict | None = None
        # Verhindert dass itemChanged während _refresh_table ausgelöst wird
        self._refreshing = False

        layout = QVBoxLayout(self)

        info = QLabel(
            "Weisen Sie jedem Raum die benötigten Gewerke zu.\n"
            "Sie können auch Vorlagen verwenden (Wohnzimmer, Schlafzimmer, etc.)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Banner: importierte Topologie ohne Gewerke (FA-ImportGuard)
        self._import_banner = QLabel(
            "Hinweis: Die Topologie wurde aus einer ETS-Datei importiert. "
            "Ohne Gewerk-Zuweisungen bleibt die importierte Topologie unverändert erhalten.\n"
            "Weisen Sie hier Gewerke zu, damit der Wizard in Schritt 6 die Topologie "
            "ergänzen und validieren kann."
        )
        self._import_banner.setWordWrap(True)
        self._import_banner.setStyleSheet(
            "background: #FFF3E0; border: 1px solid #FF9800; "
            "border-radius: 4px; padding: 6px; color: #E65100;"
        )
        self._import_banner.hide()
        layout.addWidget(self._import_banner)

        # ── Vorlagen-Bereich ──
        template_group = QGroupBox("Vorlagen")
        template_layout = QVBoxLayout()

        apply_layout = QHBoxLayout()
        apply_layout.addWidget(QLabel("Vorlage:"))
        self._template_combo = QComboBox()
        self._template_combo.addItem("-- Vorlage wählen --", "")
        self._template_combo.currentIndexChanged.connect(
            lambda _: self._update_template_buttons()
        )
        apply_layout.addWidget(self._template_combo, 1)

        self._btn_apply_template = QPushButton("Auf Raum anwenden")
        self._btn_apply_template.setToolTip(
            "Gewerke der gewählten Vorlage auf alle selektierten Räume anwenden.\n"
            "Bereits vorhandene Gewerke bleiben erhalten (additive Zuweisung)."
        )
        self._btn_apply_template.clicked.connect(self._apply_template)
        apply_layout.addWidget(self._btn_apply_template)
        template_layout.addLayout(apply_layout)

        mgmt_layout = QHBoxLayout()
        self._btn_new_template = QPushButton("Neue Vorlage...")
        self._btn_new_template.setToolTip(
            "Neue leere Vorlage erstellen und Gewerke manuell zusammenstellen.\n"
            "Vorlagen können für Wohnzimmer, Schlafzimmer, Küche usw. erstellt werden."
        )
        self._btn_new_template.clicked.connect(self._new_template)
        mgmt_layout.addWidget(self._btn_new_template)

        self._btn_from_room = QPushButton("Aus Raum erstellen...")
        self._btn_from_room.setToolTip(
            "Gewerke des aktuell selektierten Raums als neue Vorlage speichern.\n"
            "Ideal um einen gut konfigurierten Raum als Basis für andere Räume zu nutzen."
        )
        self._btn_from_room.clicked.connect(self._template_from_room)
        mgmt_layout.addWidget(self._btn_from_room)

        self._btn_edit_template = QPushButton("Bearbeiten...")
        self._btn_edit_template.setToolTip("Gewerke der gewählten Vorlage anpassen")
        self._btn_edit_template.clicked.connect(self._edit_template)
        mgmt_layout.addWidget(self._btn_edit_template)

        self._btn_delete_template = QPushButton("Löschen")
        self._btn_delete_template.setObjectName("danger")
        self._btn_delete_template.setToolTip("Gewählte Vorlage dauerhaft löschen")
        self._btn_delete_template.clicked.connect(self._delete_template)
        mgmt_layout.addWidget(self._btn_delete_template)

        mgmt_layout.addStretch()
        template_layout.addLayout(mgmt_layout)
        template_group.setLayout(template_layout)
        layout.addWidget(template_group)

        # ── Kopieren / Einfügen ──
        cp_group = QGroupBox("Kopieren / Einfügen")
        cp_layout = QHBoxLayout()

        self._btn_copy_room = QPushButton("Raum kopieren")
        self._btn_copy_room.setToolTip(
            "Gewerke des gewählten Raums in die Zwischenablage kopieren"
        )
        self._btn_copy_room.clicked.connect(self._copy_room)
        cp_layout.addWidget(self._btn_copy_room)

        self._btn_copy_apt = QPushButton("Wohnung/Zone kopieren")
        self._btn_copy_apt.setToolTip(
            "Gewerke aller Räume der gewählten Wohnung/Zone kopieren"
        )
        self._btn_copy_apt.clicked.connect(self._copy_apartment)
        cp_layout.addWidget(self._btn_copy_apt)

        self._btn_copy_floor = QPushButton("Stockwerk kopieren")
        self._btn_copy_floor.setToolTip(
            "Gewerke aller Räume des gewählten Stockwerks kopieren"
        )
        self._btn_copy_floor.clicked.connect(self._copy_floor)
        cp_layout.addWidget(self._btn_copy_floor)

        self._btn_paste = QPushButton("Einfügen")
        self._btn_paste.setToolTip("Zwischenablage in gewählen Raum / Wohnung / Stockwerk einfügen")
        self._btn_paste.clicked.connect(self._paste)
        self._btn_paste.setEnabled(False)
        cp_layout.addWidget(self._btn_paste)

        self._clipboard_label = QLabel("Zwischenablage: leer")
        cp_layout.addWidget(self._clipboard_label)
        cp_layout.addStretch()

        cp_group.setLayout(cp_layout)
        layout.addWidget(cp_group)

        # ── Filter-Leiste ──
        filter_group = QGroupBox("Filter")
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(4)

        self._filters: list[tuple[int, QLineEdit]] = []
        filter_defs = [
            (_COL_FLOOR,  "Stockwerk"),
            (_COL_APT,    "Wohnung/Zone"),
            (_COL_ROOM,   "Raum"),
            (_COL_NUMBER, "Raumnr."),
            (_COL_GCODE,  "Gewerk"),
            (_COL_GNAME,  "Name"),
        ]

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(self._apply_filter)

        for col, label in filter_defs:
            le = QLineEdit()
            le.setPlaceholderText(label + " …")
            le.setClearButtonEnabled(True)
            le.textChanged.connect(self._filter_timer.start)
            filter_layout.addWidget(le)
            self._filters.append((col, le))

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # ── Tabelle ──
        self._table = QTableWidget()
        self._table.setColumnCount(_NUM_COLS)
        self._table.setHorizontalHeaderLabels([
            "Stockwerk", "Wohnung/Zone", "Raum", "Raumnr.",
            "Gewerk", "Name", "Anzahl", "+GAs", "Aktion",
        ])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemChanged.connect(self._on_count_changed)
        layout.addWidget(self._table)

        # ── Gewerk hinzufügen ──
        add_group = QGroupBox("Gewerk hinzufügen")
        add_layout = QHBoxLayout()

        self._gewerk_combo = QComboBox()
        add_layout.addWidget(QLabel("Gewerk:"))
        add_layout.addWidget(self._gewerk_combo)

        self._count_spin = QSpinBox()
        self._count_spin.setRange(1, 20)
        self._count_spin.setValue(1)
        add_layout.addWidget(QLabel("Anzahl:"))
        add_layout.addWidget(self._count_spin)

        self._btn_add = QPushButton("Hinzufügen")
        self._btn_add.setToolTip(
            "Gewerk mit der gewählten Anzahl zu allen selektierten Räumen hinzufügen.\n"
            "Tipp: Mehrere Räume mit Strg+Klick gleichzeitig auswählen."
        )
        self._btn_add.clicked.connect(self._add_gewerk)
        add_layout.addWidget(self._btn_add)

        self._btn_apply_all = QPushButton("Auf alle gleichen Räume anwenden")
        self._btn_apply_all.setToolTip(
            "Gewerk-Zuweisungen der selektierten Räume auf alle Räume\n"
            "mit demselben Namen im gesamten Projekt übertragen."
        )
        self._btn_apply_all.clicked.connect(self._apply_to_same_rooms)
        add_layout.addWidget(self._btn_apply_all)

        add_group.setLayout(add_layout)
        layout.addWidget(add_group)

        # ── Schnell-Buttons häufige Gewerke ──
        quick_group = QGroupBox("Schnell-Buttons (Gewerk zu selektierten Räumen hinzufügen)")
        quick_layout = QHBoxLayout()
        quick_layout.addWidget(QLabel("Schnell:"))
        for code, label in [("L", "L Licht"), ("LD", "LD Dimmen"), ("J", "J Jalousie"),
                             ("H", "H Heizung"), ("S", "S Szenen"), ("V", "V Sonstiges")]:
            btn = QPushButton(label)
            btn.setToolTip(f"Gewerk {code} zu allen selektierten Räumen hinzufügen")
            btn.clicked.connect(lambda checked, c=code: self._quick_add_gewerk(c))
            quick_layout.addWidget(btn)
        quick_layout.addStretch()
        quick_group.setLayout(quick_layout)
        layout.addWidget(quick_group)

    # ── Lifecycle ──

    def on_leave(self):
        """GAs beim Verlassen sofort aktualisieren.

        Stellt sicher, dass Schritt 8 (Sensoren) und Schritt 9 (Funktionen)
        aktuelle GAs vorfinden – auch wenn der User Schritt 7 überspringt.
        Manuelle GAs (is_manual=True) bleiben erhalten.
        """
        has_gewerke = any(r.gewerk_assignments for r in self._project.all_rooms)
        if not has_gewerke:
            return
        catalog = self._project.gewerk_catalog
        manual_gas = [
            ga for ga in self._project.group_addresses.all_addresses()
            if ga.is_manual
        ]
        gen = AddressGenerator(catalog, variant=self._project.config.mg_variant)
        structure = gen.generate(self._project.areal)
        self._project.group_addresses = structure
        for ga in manual_gas:
            self._insert_manual_ga(ga)

    def _insert_manual_ga(self, ga: GroupAddress) -> None:
        """Fügt eine manuelle GA in die Struktur ein."""
        structure = self._project.group_addresses
        hg = next((h for h in structure.main_groups if h.number == ga.main_group), None)
        if not hg:
            hg = MainGroup(number=ga.main_group, name=f"HG {ga.main_group}")
            structure.main_groups.append(hg)
            structure.main_groups.sort(key=lambda h: h.number)
        mg = next((m for m in hg.middle_groups if m.number == ga.middle_group), None)
        if not mg:
            mg = MiddleGroup(number=ga.middle_group, name=f"MG {ga.middle_group}")
            hg.middle_groups.append(mg)
            hg.middle_groups.sort(key=lambda m: m.number)
        mg.group_addresses.append(ga)

    def on_enter(self):
        catalog = self._project.gewerk_catalog
        self._gewerk_combo.clear()
        for code in catalog.all_codes():
            g = catalog.get(code)
            self._gewerk_combo.addItem(f"{code} - {g.name}", code)
        self._refresh_template_combo()
        self._refresh_table()

        # Banner anzeigen, wenn importierte Topologie vorhanden und noch keine Gewerke
        has_gewerke = any(r.gewerk_assignments for r in self._project.all_rooms)
        if self._project.topology.is_imported and not has_gewerke:
            self._import_banner.show()
        else:
            self._import_banner.hide()

    # ── Kontext-Lookup ──

    def _context_from_row(self, row: int):
        """Gibt (floor, apt, room) der gewählten Tabellenzeile zurück."""
        if row < 0:
            return None, None, None
        item = self._table.item(row, _COL_FLOOR)
        if not item:
            return None, None, None
        return item.data(Qt.UserRole)  # (floor, apt, room)

    def _selected_rooms(self) -> list:
        """Gibt die eindeutigen Room-Objekte aller selektierten Tabellenzeilen zurück."""
        seen_ids = set()
        rooms = []
        for idx in self._table.selectionModel().selectedRows():
            row = idx.row()
            if self._table.isRowHidden(row):
                continue
            _, _, room = self._context_from_row(row)
            if room and id(room) not in seen_ids:
                seen_ids.add(id(room))
                rooms.append(room)
        return rooms

    # ── Vorlagen-Combo ──

    def _refresh_template_combo(self):
        self._template_combo.clear()
        self._template_combo.addItem("-- Vorlage wählen --", "")

        service = GewerkService(self._project.gewerk_catalog)
        templates = service.get_all_template_names(
            self._project.custom_gewerk_templates
        )

        has_system = False
        has_custom = False
        for key, name, is_system in templates:
            if is_system:
                if not has_system:
                    has_system = True
                self._template_combo.addItem(name, key)
            else:
                if not has_custom:
                    self._template_combo.insertSeparator(self._template_combo.count())
                    has_custom = True
                self._template_combo.addItem(f"\u2605 {name}", key)

        self._update_template_buttons()

    def _update_template_buttons(self):
        key = self._template_combo.currentData()
        service = GewerkService(self._project.gewerk_catalog)
        is_custom = key and not service.is_system_template(key)
        self._btn_edit_template.setEnabled(bool(is_custom))
        self._btn_delete_template.setEnabled(bool(is_custom))

    # ── Tabelle befuellen ──

    def _refresh_table(self):
        self._refreshing = True
        try:
            self._refresh_table_impl()
        finally:
            self._refreshing = False

    def _refresh_table_impl(self):
        _ro = Qt.ItemIsSelectable | Qt.ItemIsEnabled  # read-only flags

        rows = []
        for floor in self._project.all_floors:
            for apt in floor.apartments:
                for room in apt.rooms:
                    if room.gewerk_assignments:
                        for ga in room.gewerk_assignments:
                            gewerk = self._project.gewerk_catalog.get(ga.gewerk_code)
                            rows.append((floor, apt, room, ga, gewerk))
                    else:
                        rows.append((floor, apt, room, None, None))

        self._table.setRowCount(len(rows))
        for i, (floor, apt, room, ga, gewerk) in enumerate(rows):
            floor_item = QTableWidgetItem(floor.short_code)
            floor_item.setFlags(_ro)
            floor_item.setData(Qt.UserRole, (floor, apt, room))
            self._table.setItem(i, _COL_FLOOR, floor_item)

            for col, text in [
                (_COL_APT,    apt.name),
                (_COL_ROOM,   room.name),
                (_COL_NUMBER, room.number),
            ]:
                it = QTableWidgetItem(text)
                it.setFlags(_ro)
                self._table.setItem(i, col, it)

            if ga:
                for col, text in [
                    (_COL_GCODE, ga.gewerk_code),
                    (_COL_GNAME, gewerk.name if gewerk else "?"),
                ]:
                    it = QTableWidgetItem(text)
                    it.setFlags(_ro)
                    self._table.setItem(i, col, it)

                # Anzahl – editierbar: wie viele Kanäle / Elemente dieser Funktion
                count_item = QTableWidgetItem(str(ga.count))
                count_item.setData(Qt.UserRole, ga)
                count_item.setTextAlignment(Qt.AlignCenter)
                count_item.setToolTip(
                    "Anzahl der Funktionskanäle (1–20).\n"
                    "Beispiel: J×2 = 2 Jalousie-Kanäle im Raum.\n"
                    "Doppelklick zum Bearbeiten."
                )
                self._table.setItem(i, _COL_COUNT, count_item)

                # Extra-GAs Anzahl anzeigen
                extra_count = len(ga.extra_entries)
                extra_item = QTableWidgetItem(f"+{extra_count}" if extra_count else "")
                extra_item.setFlags(_ro)
                extra_item.setToolTip(
                    f"{extra_count} zusätzliche GA(s) definiert"
                    if extra_count else "Keine zusätzlichen GAs"
                )
                extra_item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(i, _COL_EXTRA, extra_item)

                # Aktions-Widget: Extra-GAs Button + Entfernen-Button
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(2, 1, 2, 1)
                action_layout.setSpacing(3)

                block_size = gewerk.block_size if gewerk else 5
                btn_extra = QPushButton("+ GAs…")
                btn_extra.setToolTip("Zusätzliche Gruppenadressen für diese Zuweisung definieren")
                btn_extra.setFixedWidth(58)
                btn_extra.clicked.connect(
                    lambda checked, g=ga, bs=block_size: self._edit_extra_gas(g, bs)
                )
                action_layout.addWidget(btn_extra)

                btn_product = QPushButton("✓ Produkt" if ga.linked_product else "Produkt…")
                if ga.linked_product:
                    lp = ga.linked_product
                    btn_product.setToolTip(
                        f"Verknüpft: {lp.get('manufacturer', '')} "
                        f"{lp.get('order_number', '')} – {lp.get('product_name', '')}\n"
                        "Klicken um Produkt zu ändern."
                    )
                else:
                    btn_product.setToolTip(
                        "Produkt aus Katalog/KNXPROD zuweisen – generiert die GAs "
                        "dieser Zuweisung aus den ComObjects des Produkts und fügt "
                        "es der Materialliste hinzu."
                    )
                btn_product.setFixedWidth(70)
                btn_product.clicked.connect(
                    lambda checked, r=room, g=ga: self._select_product(r, g)
                )
                action_layout.addWidget(btn_product)

                btn_del = QPushButton("X")
                btn_del.setFixedWidth(26)
                btn_del.setObjectName("danger")
                btn_del.clicked.connect(lambda checked, r=room, g=ga: self._remove_gewerk(r, g))
                action_layout.addWidget(btn_del)

                self._table.setCellWidget(i, _COL_ACTION, action_widget)
            else:
                for col, text in [
                    (_COL_GCODE,  ""),
                    (_COL_GNAME,  "(keine Gewerke)"),
                    (_COL_COUNT,  ""),
                    (_COL_EXTRA,  ""),
                ]:
                    it = QTableWidgetItem(text)
                    it.setFlags(_ro)
                    self._table.setItem(i, col, it)

        fit_columns(self._table)
        self._apply_filter()

    def _on_count_changed(self, item: QTableWidgetItem):
        """Speichert Anzahl direkt ins Modell."""
        if self._refreshing or item.column() != _COL_COUNT:
            return
        ga = item.data(Qt.UserRole)
        if not isinstance(ga, GewerkAssignment):
            return
        try:
            val = int(item.text())
        except ValueError:
            val = -1

        if item.column() == _COL_COUNT:
            if 1 <= val <= 20:
                ga.count = val
                self._sync_material_quantity(ga)
            else:
                self._refreshing = True
                item.setText(str(ga.count))
                self._refreshing = False

    def _sync_material_quantity(self, ga: GewerkAssignment):
        """Hält die Menge des verknüpften Materialliste-Eintrags synchron mit ga.count."""
        if not ga.linked_product:
            return
        entry_id = ga.linked_product.get("material_entry_id")
        if not entry_id:
            return
        for entry in self._project.material_list.entries:
            if entry.id == entry_id:
                entry.quantity = ga.count
                break

    # ── Filter ──

    def _apply_filter(self):
        texts = [(col, le.text().strip().lower()) for col, le in self._filters]
        for row in range(self._table.rowCount()):
            hide = False
            for col, text in texts:
                if text:
                    item = self._table.item(row, col)
                    cell = (item.text() if item else "").lower()
                    if text not in cell:
                        hide = True
                        break
            self._table.setRowHidden(row, hide)

    # ── Kopieren ──

    def _copy_room(self):
        floor, apt, room = self._context_from_row(self._table.currentRow())
        if not room:
            return
        self._clipboard = {
            "level": "room",
            "data": [copy.deepcopy(ga.to_dict()) for ga in room.gewerk_assignments],
        }
        self._btn_paste.setEnabled(True)
        n = len(self._clipboard["data"])
        self._clipboard_label.setText(
            f"Zwischenablage: Raum \"{room.name}\" ({n} Gewerk{'e' if n != 1 else ''})"
        )

    def _copy_apartment(self):
        floor, apt, room = self._context_from_row(self._table.currentRow())
        if not apt:
            return
        rooms_data = [
            (r.name, [copy.deepcopy(ga.to_dict()) for ga in r.gewerk_assignments])
            for r in apt.rooms
        ]
        self._clipboard = {"level": "apartment", "data": rooms_data}
        self._btn_paste.setEnabled(True)
        total = sum(len(gws) for _, gws in rooms_data)
        self._clipboard_label.setText(
            f"Zwischenablage: Wohnung \"{apt.name}\" "
            f"({len(rooms_data)} Räume, {total} Gewerke)"
        )

    def _copy_floor(self):
        floor, apt, room = self._context_from_row(self._table.currentRow())
        if not floor:
            return
        apts_data = [
            (
                a.name,
                [
                    (r.name, [copy.deepcopy(ga.to_dict()) for ga in r.gewerk_assignments])
                    for r in a.rooms
                ],
            )
            for a in floor.apartments
        ]
        self._clipboard = {"level": "floor", "data": apts_data}
        self._btn_paste.setEnabled(True)
        total_rooms = sum(len(rms) for _, rms in apts_data)
        self._clipboard_label.setText(
            f"Zwischenablage: Stockwerk \"{floor.short_code}\" "
            f"({len(apts_data)} Wohnungen, {total_rooms} Räume)"
        )

    # ── Einfügen ──

    def _paste(self):
        if not self._clipboard:
            return
        floor, apt, room = self._context_from_row(self._table.currentRow())
        level = self._clipboard["level"]
        data  = self._clipboard["data"]

        if level == "room":
            if not room:
                QMessageBox.information(
                    self, "Raum wählen",
                    "Bitte eine Zeile in der Tabelle auswählen.",
                )
                return
            room.gewerk_assignments = [_fresh_ga(d) for d in data]

        elif level == "apartment":
            if not apt:
                QMessageBox.information(
                    self, "Raum wählen",
                    "Bitte eine Zeile in der Tabelle auswählen.",
                )
                return
            room_map = {r.name: r for r in apt.rooms}
            matched = 0
            skipped = 0
            for room_name, ga_dicts in data:
                target = room_map.get(room_name)
                if target is None:
                    skipped += 1
                    continue
                target.gewerk_assignments = [_fresh_ga(d) for d in ga_dicts]
                matched += 1
            if skipped:
                QMessageBox.information(
                    self, "Hinweis",
                    f"{matched} Raum/Räume übertragen, "
                    f"{skipped} nicht gefunden (abweichende Raumnamen).",
                )

        elif level == "floor":
            if not floor:
                QMessageBox.information(
                    self, "Raum wählen",
                    "Bitte eine Zeile in der Tabelle auswählen.",
                )
                return
            n_src = len(data)
            n_dst = len(floor.apartments)
            # Positions-basiert: 1. Wohnung → 1. Wohnung, unabhaengig vom Namen
            for i, (_, rooms_data) in enumerate(data):
                if i >= n_dst:
                    break
                target_apt = floor.apartments[i]
                n_src_rooms = len(rooms_data)
                n_dst_rooms = len(target_apt.rooms)
                for j, (_, ga_dicts) in enumerate(rooms_data):
                    if j >= n_dst_rooms:
                        break
                    target_apt.rooms[j].gewerk_assignments = [
                        _fresh_ga(d) for d in ga_dicts
                    ]
                if n_src_rooms != n_dst_rooms:
                    QMessageBox.information(
                        self, "Hinweis",
                        f"Wohnung '{target_apt.name}': "
                        f"{min(n_src_rooms, n_dst_rooms)} von {n_src_rooms} "
                        f"Raum/Räumen eingefügt (Ziel hat {n_dst_rooms}).",
                    )
            if n_src != n_dst:
                QMessageBox.information(
                    self, "Hinweis",
                    f"{min(n_src, n_dst)} von {n_src} Wohnung(en) eingefügt "
                    f"(Ziel-Stockwerk hat {n_dst} Wohnung(en)).",
                )

        self._refresh_table()

    # ── Gewerk hinzufügen/entfernen ──

    def _add_gewerk(self):
        rooms = self._selected_rooms()
        if not rooms:
            floor, apt, room = self._context_from_row(self._table.currentRow())
            if room:
                rooms = [room]
        if not rooms:
            QMessageBox.warning(
                self, "Kein Raum ausgewählt",
                "Bitte wählen Sie zuerst einen oder mehrere Räume in der Tabelle aus.",
            )
            return
        code = self._gewerk_combo.currentData()
        count = self._count_spin.value()
        if not code:
            return
        added = 0
        already_present = 0
        for room in rooms:
            if not any(ga.gewerk_code == code for ga in room.gewerk_assignments):
                room.gewerk_assignments.append(GewerkAssignment(gewerk_code=code, count=count))
                added += 1
            else:
                already_present += 1
        self._refresh_table()
        if added == 0 and already_present > 0:
            gewerk = self._project.gewerk_catalog.get(code)
            name = gewerk.name if gewerk else code
            QMessageBox.information(
                self, "Gewerk bereits vorhanden",
                f"Das Gewerk \"{code} – {name}\" ist bereits in allen gewählten Räumen vorhanden.",
            )

    def _quick_add_gewerk(self, code: str):
        """Schnell-Button: Gewerk zu allen selektierten Räumen hinzufügen (FA-3209)."""
        rooms = self._selected_rooms()
        if not rooms:
            floor, apt, room = self._context_from_row(self._table.currentRow())
            if room:
                rooms = [room]
        if not rooms:
            QMessageBox.warning(
                self, "Kein Raum ausgewählt",
                "Bitte wählen Sie zuerst einen oder mehrere Räume in der Tabelle aus.",
            )
            return
        added = 0
        for room in rooms:
            if not any(ga.gewerk_code == code for ga in room.gewerk_assignments):
                room.gewerk_assignments.append(GewerkAssignment(gewerk_code=code, count=1))
                added += 1
        self._refresh_table()
        if added == 0:
            gewerk = self._project.gewerk_catalog.get(code)
            name = gewerk.name if gewerk else code
            QMessageBox.information(
                self, "Gewerk bereits vorhanden",
                f"Das Gewerk \"{code} – {name}\" ist bereits in allen gewählten Räumen vorhanden.",
            )

    def _apply_to_same_rooms(self):
        """Gewerk-Zuweisungen der selektierten Räume auf alle gleichen Räume übertragen (FA-3208)."""
        rooms = self._selected_rooms()
        if not rooms:
            return

        all_rooms = list(self._project.all_rooms)
        affected = 0
        for src_room in rooms:
            for target in all_rooms:
                if target is src_room:
                    continue
                if target.name == src_room.name:
                    target.gewerk_assignments = [
                        _fresh_ga(ga.to_dict()) for ga in src_room.gewerk_assignments
                    ]
                    affected += 1

        if affected:
            self._refresh_table()
            QMessageBox.information(
                self, "Fertig",
                f"Gewerke auf {affected} weiteren Raum/Räumen mit gleichem Namen übertragen.",
            )
        else:
            QMessageBox.information(
                self, "Keine gleichen Räume",
                "Es wurden keine anderen Räume mit denselben Namen gefunden.",
            )

    def _edit_extra_gas(self, ga: GewerkAssignment, block_size: int):
        """Öffnet den Extra-GA-Dialog für eine GewerkAssignment-Instanz."""
        dlg = ExtraGaDialog(
            gewerk_code=ga.gewerk_code,
            block_size=block_size,
            extra_entries=ga.extra_entries,
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            ga.extra_entries = dlg.get_extra_entries()
            self._refresh_table()

    def _remove_gewerk(self, room, ga):
        if ga.linked_product:
            entry_id = ga.linked_product.get("material_entry_id")
            if entry_id:
                self._project.material_list.remove(entry_id)
        if ga in room.gewerk_assignments:
            room.gewerk_assignments.remove(ga)
        self._refresh_table()

    def _select_product(self, room, ga: GewerkAssignment):
        """Öffnet die Produktauswahl und verknüpft das gewählte Produkt mit der Zuweisung.

        Der GA-Block dieser Zuweisung wird danach aus den ComObjects des
        Produkts generiert (siehe AddressGenerator._build_product_schema)
        und das Produkt wird der Materialliste hinzugefügt.
        """
        dlg = ProductSelectDialog(parent=self)
        if dlg.exec() != QDialog.Accepted:
            return

        prod = dlg.selected_product
        if not prod:
            return

        if not prod.com_objects:
            QMessageBox.information(
                self, "Keine ComObject-Daten",
                "Dieses Produkt enthält keine ComObject-Daten (kein KNXPROD-Import).\n"
                "Das GA-Schema dieser Zuweisung bleibt unverändert – das Produkt "
                "wird nur der Materialliste hinzugefügt.",
            )

        entry = dlg.get_material_entry()
        if entry is None:
            return
        entry.quantity = ga.count

        # Alten Materialliste-Eintrag entfernen, falls bereits ein Produkt verknüpft war
        if ga.linked_product:
            old_entry_id = ga.linked_product.get("material_entry_id")
            if old_entry_id:
                self._project.material_list.remove(old_entry_id)

        self._project.material_list.add_or_update(entry)

        ga.linked_product = {
            "manufacturer": prod.manufacturer,
            "order_number": prod.order_number,
            "product_name": prod.product_name,
            "com_objects": prod.com_objects,
            "material_entry_id": entry.id,
        }
        self._refresh_table()

    # ── Vorlage anwenden ──

    def _apply_template(self):
        template_key = self._template_combo.currentData()
        if not template_key:
            return
        rooms = self._selected_rooms()
        if not rooms:
            floor, apt, room = self._context_from_row(self._table.currentRow())
            if room:
                rooms = [room]
        if not rooms:
            return
        service = GewerkService(self._project.gewerk_catalog)
        for room in rooms:
            service.apply_template(room, template_key, self._project.custom_gewerk_templates)
        self._refresh_table()

    # ── Vorlagen-Verwaltung ──

    def _new_template(self):
        dialog = GewerkTemplateDialog(self._project.gewerk_catalog, parent=self)
        if dialog.exec() == GewerkTemplateDialog.Accepted:
            result = dialog.get_template()
            if result:
                name, gewerke = result
                key = GewerkService.generate_template_key(
                    name, set(self._project.custom_gewerk_templates.keys()),
                )
                GewerkService.add_custom_template(
                    self._project.custom_gewerk_templates, key, name, gewerke,
                )
                self._refresh_template_combo()

    def _template_from_room(self):
        floor, apt, room = self._context_from_row(self._table.currentRow())
        if not room:
            return
        if not room.gewerk_assignments:
            QMessageBox.information(
                self, "Keine Gewerke",
                "Der ausgewählte Raum hat keine Gewerke zugewiesen.",
            )
            return
        suggested_name, gewerke = GewerkService.create_template_from_room(room)
        dialog = GewerkTemplateDialog(
            self._project.gewerk_catalog,
            name=suggested_name,
            gewerke=gewerke,
            parent=self,
        )
        if dialog.exec() == GewerkTemplateDialog.Accepted:
            result = dialog.get_template()
            if result:
                name, gewerke = result
                key = GewerkService.generate_template_key(
                    name, set(self._project.custom_gewerk_templates.keys()),
                )
                GewerkService.add_custom_template(
                    self._project.custom_gewerk_templates, key, name, gewerke,
                )
                self._refresh_template_combo()

    def _edit_template(self):
        key = self._template_combo.currentData()
        if not key:
            return
        service = GewerkService(self._project.gewerk_catalog)
        if service.is_system_template(key):
            return
        template = self._project.custom_gewerk_templates.get(key)
        if not template:
            return
        dialog = GewerkTemplateDialog(
            self._project.gewerk_catalog,
            name=template["name"],
            gewerke=list(template["gewerke"]),
            parent=self,
        )
        if dialog.exec() == GewerkTemplateDialog.Accepted:
            result = dialog.get_template()
            if result:
                name, gewerke = result
                GewerkService.update_custom_template(
                    self._project.custom_gewerk_templates, key, name, gewerke,
                )
                self._refresh_template_combo()

    def _delete_template(self):
        key = self._template_combo.currentData()
        if not key:
            return
        service = GewerkService(self._project.gewerk_catalog)
        if service.is_system_template(key):
            return
        template = self._project.custom_gewerk_templates.get(key)
        if not template:
            return
        reply = QMessageBox.question(
            self, "Vorlage löschen",
            f"Soll die Vorlage '{template['name']}' wirklich gelöscht werden?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            GewerkService.remove_custom_template(
                self._project.custom_gewerk_templates, key,
            )
            self._refresh_template_combo()
