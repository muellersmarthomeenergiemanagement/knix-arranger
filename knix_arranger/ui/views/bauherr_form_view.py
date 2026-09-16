"""
Interaktive Bauherren-Beratungsansicht (Option B)

Zeigt die Tastenbelegung aller Räume als anklickbare Taster-Widgets.
Jeder Slot ist ein eigenständiger Taster – keine Wippen-Metapher.

Jede Taste ist jederzeit umstellbar (keine schreibgeschützten Slots mehr):
Auswahl zwischen den tatsächlich geplanten Gewerk-Instanzen aller Räume
(jeweils mit Raumnamen beschriftet), den benannten Szenen des Projekts oder
einem freien Wunsch. Gewerk-/Szenen-Auswahl verknüpft sofort die passende
Gruppenadresse, ganz ohne Umweg über die Verknüpfungsmatrix.

Änderungen werden sofort in die SensorFunktionen des Projekts geschrieben.
"""
from __future__ import annotations
import math
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QScrollArea, QFrame, QComboBox, QLineEdit,
    QSplitter, QSizePolicy, QGridLayout, QTextEdit, QSpinBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ...models.project import KnxProject
from ...models.building import Room, Bedienelement, SensorFunktion
from ...services.bauherr_form_service import _DROPDOWN_OPTIONS, BauherrFormService
from ...services.sensor_service import GEWERK_PRIMARY_FUNCTIONS
from ...services.scene_addressing import (
    scene_group_key, scene_channel_designation, build_scope_label_lookup,
)
from ..styles import KNX_BLUE, KNX_DARK_GREEN

# ── Farben (identisch zum Excel-Formular) ────────────────────────────────────
_C_HEADER   = "#1A5276"
_C_ASSIGNED = "#E8F5E9"
_C_WISH     = "#FFF8E1"

_FONT_FN     = "#1B5E20"
_FONT_WISH   = "#E65100"
_FONT_HEADER = "#FFFFFF"

# Obergrenze fuer die manuelle Tastenanzahl-Anpassung -- deckt auch groessere
# Glas-/Rocker-Tastereinheiten ab, die ueber die feste Auswahl (1/2/4/6) im
# Funktionszuordnungs-Dialog (Schritt 8) hinausgehen.
_MAX_CHANNELS = 12


class _SlotWidget(QWidget):
    """
    Einzelner Taster-Slot -- immer eine QComboBox, nie schreibgeschützt.

    Jeder Slot laesst sich jederzeit auf ein anderes Gewerk (aus diesem oder
    einem anderen Raum, jeweils mit Raumnamen beschriftet), eine Szene oder
    einen freien Wunsch umstellen -- so laesst sich waehrend der Beratung
    direkt auf Aenderungswuensche des Bauherrn reagieren, ohne zuerst in
    Schritt 8 etwas entfernen zu muessen. Grün = bereits ein Wert gesetzt,
    Gelb = noch offen.
    """

    changed = Signal()

    def __init__(self, be: Bedienelement, sf_idx: int,
                 service: BauherrFormService, slot_number: int,
                 room: Room, parent=None):
        super().__init__(parent)
        self._be      = be
        self._sf_idx  = sf_idx
        self._service = service
        self._room    = room

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(0)

        sf = be.funktionen[sf_idx] if sf_idx < len(be.funktionen) else None

        # Taster-Nummer (klein, grau)
        num_lbl = QLabel(f"T{slot_number}")
        num_lbl.setStyleSheet(
            "color: #9E9E9E; font-size: 8px; padding: 0; margin: 0;"
        )
        num_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(num_lbl)

        self._combo = QComboBox()
        self._combo.addItem("– Funktion wählen –", None)
        self._populate_combo()
        has_value = self._select_current(sf)
        self._apply_style(has_value)
        self._combo.currentIndexChanged.connect(self._on_changed)
        layout.addWidget(self._combo)

        self.setMinimumHeight(56)
        self.setStyleSheet(
            "QWidget { border: 1px solid #CFD8DC; border-radius: 3px; "
            "background-color: #FAFAFA; }"
        )

    def _populate_combo(self):
        """Befuellt den Combo mit den tatsaechlich geplanten Gewerken aller
        Raeume (eigener Raum zuerst, jeweils mit Raumnamen beschriftet -- vorher
        war nicht ersichtlich, welches Gewerk aus welchem Raum ausgewaehlt
        wird) und den benannten Szenen des Projekts -- direkt auswaehlbar,
        inklusive GA-Verknuepfung, ohne Umweg ueber die Verknuepfungsmatrix.
        Generische Freitext-Wuensche bleiben als Fallback fuer alles, was
        (noch) keinem Gewerk entspricht."""
        project = self._service.project
        rooms_ordered = [self._room] + [
            r for r in project.all_rooms if r.id != self._room.id
        ]
        seen: set[tuple[str, str, int]] = set()
        for room in rooms_ordered:
            for assignment in room.gewerk_assignments:
                code = assignment.gewerk_code
                if code not in GEWERK_PRIMARY_FUNCTIONS:
                    continue
                for elem_nr in range(1, assignment.count + 1):
                    key = (room.id, code, elem_nr)
                    if key in seen:
                        continue
                    seen.add(key)
                    first_desc = GEWERK_PRIMARY_FUNCTIONS[code][0][2]
                    display = f"{code} – {first_desc}"
                    if assignment.count > 1:
                        display += f" #{elem_nr}"
                    display += f"   ·   {room.number} {room.name}"
                    self._combo.addItem(display, ("gewerk", code, elem_nr, room.id))

        label_lookup = build_scope_label_lookup(project.areal)
        for scene in project.scenes:
            if not scene.name or scene.is_detected:
                continue
            designation = scene_channel_designation(
                scene_group_key(scene), label_lookup
            )
            self._combo.addItem(
                f"Szene: {scene.name}   ·   {designation}",
                ("scene", scene.id, designation, scene.name),
            )

        for opt in _DROPDOWN_OPTIONS:
            self._combo.addItem(opt, ("wish", opt))

    def _select_current(self, sf: SensorFunktion | None) -> bool:
        """Waehlt die Combo-Option, die dem aktuellen Zustand von sf
        entspricht, und gibt zurueck ob ueberhaupt ein Wert gesetzt ist.
        Passt der Zustand zu keiner gelisteten Option (z.B. eine "Direkte
        GA"-Zuweisung aus Schritt 8), wird ein synthetischer Eintrag mit den
        Originalwerten ergaenzt -- sonst wuerde das blosse Anzeigen dieses
        Slots eine bestehende Zuweisung stillschweigend verwerfen."""
        if sf is None:
            self._combo.setCurrentIndex(0)
            return False

        target = None
        if sf.scene_id:
            target = ("scene", sf.scene_id)
        elif sf.gewerk_code:
            target = ("gewerk", sf.gewerk_code, sf.element_number,
                      sf.source_room_id or self._room.id)
        elif sf.ga_designation:
            target = None  # Direkte GA (Schritt 8) -- unten als Sonderfall behandelt
        elif sf.label:
            idx = self._combo.findText(sf.label)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
                return True

        if target is not None:
            for i in range(self._combo.count()):
                data = self._combo.itemData(i)
                if not data:
                    continue
                if data[0] == target[0] and data[1:len(target)] == target[1:]:
                    self._combo.setCurrentIndex(i)
                    return True

        current_label = self._service._button_label(sf)
        if not current_label:
            self._combo.setCurrentIndex(0)
            return False

        current_fields = dict(
            label=sf.label, gewerk_code=sf.gewerk_code,
            element_number=sf.element_number, source_room_id=sf.source_room_id,
            ga_designation=sf.ga_designation, action_type=sf.action_type,
            bedienart=sf.bedienart, scene_id=sf.scene_id,
        )
        self._combo.insertItem(1, current_label, ("current", current_fields))
        self._combo.setCurrentIndex(1)
        return True

    def _apply_style(self, has_value: bool):
        if has_value:
            self._combo.setStyleSheet(
                f"background-color: {_C_ASSIGNED}; color: {_FONT_FN}; "
                f"font-size: 10px; font-weight: bold; "
                f"border: 1px solid #A5D6A7; border-radius: 2px; padding: 2px;"
            )
        else:
            self._combo.setStyleSheet(
                f"background-color: {_C_WISH}; color: {_FONT_WISH}; "
                f"font-size: 10px; border: 1px solid #E0C870; "
                f"border-radius: 2px; padding: 2px;"
            )

    @staticmethod
    def _fields_for(data) -> dict:
        """SensorFunktion-Felder fuer die gewaehlte Combo-Option. Leeres Dict
        fuer den Platzhalter (setzt den Slot wieder auf leer zurueck)."""
        if not data:
            return {}
        kind = data[0]
        if kind == "gewerk":
            _, code, elem_nr, room_id = data
            return dict(gewerk_code=code, element_number=elem_nr, source_room_id=room_id)
        if kind == "scene":
            _, scene_id, designation, scene_name = data
            return dict(
                label=scene_name, ga_designation=designation,
                action_type="kurz", bedienart="Szene abrufen", scene_id=scene_id,
            )
        if kind == "current":
            # Unveraendert uebernommener Ausgangszustand (z.B. Direkte-GA-
            # Zuweisung aus Schritt 8) -- source_room_id wird unten je nach
            # eigenem/fremdem Raum wieder korrekt aufgeloest.
            return dict(data[1])
        # "wish": reiner Freitext-Wunsch, keine GA bekannt -- muss spaeter ueber
        # die Verknuepfungsmatrix (FA-2503) aufgeloest werden.
        _, text = data
        return dict(label=text)

    def _apply_fields(self, fields: dict):
        be, sf_idx = self._be, self._sf_idx
        # source_room_id="" bedeutet "eigener Raum" (siehe SensorFunktion) --
        # das Gewerk-Item liefert dafuer bewusst die eigene Raum-Id (fuer den
        # Vergleich in _select_current), hier auf "" normalisiert.
        source_room_id = fields.get("source_room_id", "")
        if source_room_id == self._room.id:
            source_room_id = ""

        if sf_idx < len(be.funktionen):
            sf = be.funktionen[sf_idx]
        else:
            while len(be.funktionen) < sf_idx:
                be.funktionen.append(SensorFunktion())
            sf = SensorFunktion()
            be.funktionen.append(sf)

        sf.label          = fields.get("label", "")
        sf.gewerk_code     = fields.get("gewerk_code", "")
        sf.element_number  = fields.get("element_number", 1)
        sf.source_room_id  = source_room_id
        sf.ga_designation  = fields.get("ga_designation", "")
        sf.action_type     = fields.get("action_type", "")
        sf.bedienart       = fields.get("bedienart", "")
        sf.scene_id        = fields.get("scene_id", "")

    def _on_changed(self, index: int):
        data = self._combo.itemData(index)
        fields = self._fields_for(data)
        self._apply_fields(fields)

        if data:
            # Wahl markiert das Bedienelement als manuell konfiguriert, damit
            # auto_assign_functions die Funktionsliste bei der nachfolgenden
            # Neuberechnung nicht verwirft (FA-1410: is_auto=False wird erhalten).
            self._be.is_auto = False

        self._apply_style(bool(data))
        self.changed.emit()


class _TasterWidget(QFrame):
    """
    Grafische Darstellung eines Bedienelements als Raster einzelner Taster.
    2-spaltiges Grid, kein Wippen-Konzept.
    """

    changed = Signal()
    notes_changed = Signal()
    # Tastenanzahl (be.channels) wurde geaendert -- Grid muss mit neuer
    # Slot-Zahl komplett neu aufgebaut werden (siehe BauherrFormView._load_room).
    structure_changed = Signal()

    def __init__(self, be: Bedienelement, service: BauherrFormService,
                 room: Room, parent=None):
        super().__init__(parent)
        self._be = be
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 2px solid #263238; border-radius: 4px; "
            "background-color: white; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Geräte-Header ─────────────────────────────────────────────────
        pn   = be.participant_number or "–"
        name = service._device_product_name(be)
        mode = "Auto" if be.is_auto else "Manuell"
        te_idx = getattr(be, "taster_index", 1)
        te_label = (f"  Tastereinheit {te_idx}  –  " if be.element_type == "Tastereinheit" else "  ")
        hdr = QLabel(f"{te_label}{name}  [{pn}]  {mode}")
        hdr.setFixedHeight(24)
        hdr.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        hdr.setStyleSheet(
            f"background-color: {_C_HEADER}; color: {_FONT_HEADER}; "
            f"font-size: 10px; font-weight: bold; border: none;"
        )
        layout.addWidget(hdr)

        # ── Tastenanzahl anpassen ────────────────────────────────────────────
        # Nur bei Tastereinheiten sinnvoll (Kanalzahl = Anzahl physischer
        # Tasten); ein Raumthermostat o.ä. hat kein editierbares "channels".
        # Untergrenze = bereits definierte Funktionen, damit eine Verkleinerung
        # nicht stillschweigend eine schon zugewiesene Funktion verwirft.
        if be.element_type == "Tastereinheit":
            count_bar = QWidget()
            count_bar.setStyleSheet(
                "QWidget { background-color: #ECEFF1; border: none; }"
            )
            count_layout = QHBoxLayout(count_bar)
            count_layout.setContentsMargins(6, 2, 6, 2)
            count_layout.setSpacing(4)

            count_lbl = QLabel("Anzahl Tasten:")
            count_lbl.setStyleSheet(
                "color: #546E7A; font-size: 9px; border: none;"
            )
            count_layout.addWidget(count_lbl)

            self._channels_spin = QSpinBox()
            self._channels_spin.setMinimum(max(1, len(be.funktionen)))
            self._channels_spin.setMaximum(_MAX_CHANNELS)
            self._channels_spin.setValue(be.channels)
            self._channels_spin.setFixedWidth(48)
            self._channels_spin.setToolTip(
                "Physische Tastenzahl dieser Tastereinheit. Zusätzliche "
                "Tasten erscheinen als leere Wunsch-Felder unten."
            )
            self._channels_spin.valueChanged.connect(self._on_channels_changed)
            count_layout.addWidget(self._channels_spin)
            count_layout.addStretch()

            layout.addWidget(count_bar)

        # ── Taster-Raster ──────────────────────────────────────────────────
        n_buttons = be.channels
        n_slots   = max(n_buttons, len(be.funktionen))

        grid_widget = QWidget()
        grid_widget.setStyleSheet("QWidget { border: none; background: white; }")
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(5)

        for slot_idx in range(n_slots):
            grid_row = slot_idx // 2
            grid_col = slot_idx  % 2

            slot = _SlotWidget(be, slot_idx, service, slot_number=slot_idx + 1, room=room)
            slot.changed.connect(self.changed)
            grid.addWidget(slot, grid_row, grid_col)

        # Gleichmässige Spaltenbreiten
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        layout.addWidget(grid_widget)

        # ── Anmerkungszeile ────────────────────────────────────────────────
        ann_bar = QWidget()
        ann_bar.setStyleSheet(
            "QWidget { background-color: #FAFAFA; border-top: 1px solid #CFD8DC; "
            "border: none; }"
        )
        ann_layout = QHBoxLayout(ann_bar)
        ann_layout.setContentsMargins(6, 3, 6, 3)
        ann_layout.setSpacing(4)

        ann_lbl = QLabel("Anmerkung:")
        ann_lbl.setFixedWidth(72)
        ann_lbl.setStyleSheet(
            "color: #546E7A; font-size: 8px; font-style: italic; border: none;"
        )
        ann_layout.addWidget(ann_lbl)

        self._ann_edit = QLineEdit()
        self._ann_edit.setPlaceholderText("Optionale Anmerkung des Bauherrn …")
        self._ann_edit.setStyleSheet(
            "background-color: #FFFDE7; border: 1px dotted #BDBDBD; "
            "font-size: 9px; padding: 1px 4px; border-radius: 2px;"
        )
        self._ann_edit.setFixedHeight(22)
        self._ann_edit.setText(be.bauherr_annotation or "")
        self._ann_edit.textChanged.connect(self._on_annotation)
        ann_layout.addWidget(self._ann_edit)

        layout.addWidget(ann_bar)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _on_annotation(self, text: str):
        self._be.bauherr_annotation = text
        self.notes_changed.emit()

    def _on_channels_changed(self, value: int):
        if value == self._be.channels:
            return
        self._be.channels = value
        # Analog zur Wunsch-Auswahl in leeren Slots: eine manuelle Anpassung
        # hier markiert das Bedienelement als manuell konfiguriert, sonst
        # wuerde auto_assign_functions die Tastenzahl bei der naechsten
        # Neuberechnung (z.B. nach einer Gebaeudestrukturaenderung) wieder
        # verwerfen (FA-1410).
        self._be.is_auto = False
        self.structure_changed.emit()


class BauherrFormView(QWidget):
    """
    Interaktive Bauherren-Beratungsansicht.
    Links: Raumliste. Rechts: Taster-Widgets des gewählten Raums.
    """

    project_changed = Signal()
    notes_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        self._service: BauherrFormService | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Bauherren-Beratung – Tastenbelegung")
        title.setObjectName("title")
        layout.addWidget(title)

        hint = QLabel(
            "Jede Taste ist direkt umstellbar: Gewerk (mit Raumangabe), "
            "Szene oder freier Wunsch auswählen.  "
            "Gelb = noch offen.  Grün = bereits ein Wert gewählt."
        )
        hint.setObjectName("subtitle")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        # ── Linke Seite: Raumliste ─────────────────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.addWidget(QLabel("Räume:"))
        self._room_list = QListWidget()
        self._room_list.setMinimumWidth(160)
        self._room_list.setMaximumWidth(220)
        self._room_list.currentItemChanged.connect(self._on_room_selected)
        left_layout.addWidget(self._room_list)
        splitter.addWidget(left)

        # ── Rechte Seite ───────────────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self._room_title = QLabel("")
        self._room_title.setStyleSheet(
            f"background-color: {KNX_DARK_GREEN}; color: white; "
            f"font-size: 13px; font-weight: bold; padding: 6px 10px;"
        )
        self._room_title.setFixedHeight(32)
        right_layout.addWidget(self._room_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 12, 12, 12)
        self._content_layout.setSpacing(12)
        self._content_layout.addStretch()
        scroll.setWidget(self._content)
        right_layout.addWidget(scroll, 1)

        # Raum-Anmerkungsblock
        notes_frame = QFrame()
        notes_frame.setFrameShape(QFrame.StyledPanel)
        notes_frame.setStyleSheet(
            "QFrame { background-color: #F9F9F9; "
            "border: 1px solid #546E7A; border-radius: 3px; }"
        )
        notes_layout = QVBoxLayout(notes_frame)
        notes_layout.setContentsMargins(8, 6, 8, 6)
        notes_layout.setSpacing(4)

        notes_lbl = QLabel("Anmerkungen zum Raum:")
        notes_lbl.setStyleSheet(
            f"color: {KNX_BLUE}; font-weight: bold; font-size: 10px; border: none;"
        )
        notes_layout.addWidget(notes_lbl)

        self._room_notes = QTextEdit()
        self._room_notes.setPlaceholderText(
            "Allgemeine Wünsche und Bemerkungen des Bauherrn …"
        )
        self._room_notes.setFixedHeight(70)
        self._room_notes.setStyleSheet(
            "background-color: white; border: 1px dotted #BDBDBD; font-size: 9px;"
        )
        self._room_notes.textChanged.connect(self._on_room_notes_changed)
        notes_layout.addWidget(self._room_notes)
        right_layout.addWidget(notes_frame)

        splitter.addWidget(right)
        splitter.setSizes([180, 700])

        self._current_room: Room | None = None

    # ── Projekt ────────────────────────────────────────────────────────────

    def set_project(self, project: KnxProject):
        self._project = project
        self._service = BauherrFormService(project)
        self._refresh_room_list()

    def refresh(self):
        if self._project:
            self._refresh_room_list()

    def _refresh_room_list(self):
        self._room_list.clear()
        if not self._project:
            return
        for room in self._project.all_rooms:
            if not any(not be.suppressed for be in room.bedienelemente):
                continue
            item = QListWidgetItem(f"{room.number}  {room.name}")
            item.setData(Qt.UserRole, room)
            self._room_list.addItem(item)
        if self._room_list.count():
            self._room_list.setCurrentRow(0)

    # ── Raum-Auswahl ───────────────────────────────────────────────────────

    def _on_room_selected(self, current: QListWidgetItem, _previous):
        if current is None:
            return
        self._load_room(current.data(Qt.UserRole))

    def _load_room(self, room: Room):
        self._current_room = room
        self._room_title.setText(f"  Raum {room.number}  –  {room.name}")

        self._room_notes.blockSignals(True)
        self._room_notes.setPlainText(room.bauherr_notes or "")
        self._room_notes.blockSignals(False)

        # Alte Widgets entfernen
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Taster-Widgets aufbauen
        for be in room.bedienelemente:
            if be.suppressed:
                continue
            taster = _TasterWidget(be, self._service, room=room)
            taster.changed.connect(self.project_changed)
            taster.notes_changed.connect(self.notes_changed)
            taster.structure_changed.connect(self._on_structure_changed)
            self._content_layout.insertWidget(
                self._content_layout.count() - 1, taster
            )

    def _on_structure_changed(self):
        """Tastenanzahl eines Bedienelements wurde geaendert -- Raum komplett
        neu aufbauen, damit das Grid mit der neuen Slot-Zahl neu entsteht
        (_TasterWidget legt die Slots nur einmal bei der Konstruktion an)."""
        if self._current_room is not None:
            self._load_room(self._current_room)
        self.project_changed.emit()

    def _on_room_notes_changed(self):
        if self._current_room is None:
            return
        self._current_room.bauherr_notes = self._room_notes.toPlainText()
        self.notes_changed.emit()
