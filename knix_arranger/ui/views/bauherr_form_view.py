"""
Interaktive Bauherren-Beratungsansicht (Option B)

Zeigt die Tastenbelegung aller Räume als anklickbare Taster-Widgets.
Jeder Slot ist ein eigenständiger Taster – keine Wippen-Metapher.

Änderungen werden sofort in die SensorFunktionen des Projekts geschrieben.
"""
from __future__ import annotations
import math
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QScrollArea, QFrame, QComboBox, QLineEdit,
    QSplitter, QSizePolicy, QGridLayout, QTextEdit,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from ...models.project import KnxProject
from ...models.building import Room, Bedienelement, SensorFunktion
from ...services.bauherr_form_service import _DROPDOWN_OPTIONS, BauherrFormService
from ..styles import KNX_BLUE, KNX_DARK_GREEN

# ── Farben (identisch zum Excel-Formular) ────────────────────────────────────
_C_HEADER   = "#1A5276"
_C_ASSIGNED = "#E8F5E9"
_C_FOREIGN  = "#E3F2FD"
_C_GA       = "#F3E5F5"
_C_WISH     = "#FFF8E1"

_FONT_FN     = "#1B5E20"
_FONT_WISH   = "#E65100"
_FONT_HEADER = "#FFFFFF"


class _SlotWidget(QWidget):
    """
    Einzelner Taster-Slot.

    Zugewiesene Funktion → QLabel (grün, schreibgeschützt).
    Leerer Slot → QComboBox (gelb, Wunsch wählen).
    """

    changed = Signal()

    def __init__(self, be: Bedienelement, sf_idx: int,
                 service: BauherrFormService, slot_number: int,
                 parent=None):
        super().__init__(parent)
        self._be      = be
        self._sf_idx  = sf_idx
        self._service = service

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(0)

        sf = be.funktionen[sf_idx] if sf_idx < len(be.funktionen) else None
        fn_text = service._button_label(sf) if sf else ""

        # Taster-Nummer (klein, grau)
        num_lbl = QLabel(f"T{slot_number}")
        num_lbl.setStyleSheet(
            "color: #9E9E9E; font-size: 8px; padding: 0; margin: 0;"
        )
        num_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(num_lbl)

        if fn_text:
            bg = (_C_FOREIGN if (sf and sf.source_room_id) else
                  _C_GA      if (sf and sf.ga_designation)  else
                  _C_ASSIGNED)
            lbl = QLabel(fn_text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"background-color: {bg}; color: {_FONT_FN}; "
                f"font-size: 10px; font-weight: bold; "
                f"padding: 4px; border-radius: 2px;"
            )
            layout.addWidget(lbl)
            self._combo = None
        else:
            self._combo = QComboBox()
            self._combo.addItem("– Funktion wählen –", "")
            for opt in _DROPDOWN_OPTIONS:
                self._combo.addItem(opt, opt)
            if sf and sf.label:
                idx = self._combo.findText(sf.label)
                if idx >= 0:
                    self._combo.setCurrentIndex(idx)
            self._combo.setStyleSheet(
                f"background-color: {_C_WISH}; color: {_FONT_WISH}; "
                f"font-size: 10px; border: 1px solid #E0C870; "
                f"border-radius: 2px; padding: 2px;"
            )
            self._combo.currentIndexChanged.connect(self._on_changed)
            layout.addWidget(self._combo)

        self.setMinimumHeight(56)
        self.setStyleSheet(
            "QWidget { border: 1px solid #CFD8DC; border-radius: 3px; "
            "background-color: #FAFAFA; }"
        )

    def _on_changed(self, index: int):
        if self._combo is None:
            return
        val = self._combo.itemData(index) or ""
        be, sf_idx = self._be, self._sf_idx

        if sf_idx < len(be.funktionen):
            be.funktionen[sf_idx].label = val
        else:
            while len(be.funktionen) < sf_idx:
                be.funktionen.append(SensorFunktion())
            be.funktionen.append(SensorFunktion(label=val, ga_designation=val))

        if val:
            # Wunsch markiert das Bedienelement als manuell konfiguriert, damit
            # auto_assign_functions die Funktionsliste bei der nachfolgenden
            # Neuberechnung nicht verwirft (FA-1410: is_auto=False wird erhalten).
            be.is_auto = False

        if val:
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
        self.changed.emit()


class _TasterWidget(QFrame):
    """
    Grafische Darstellung eines Bedienelements als Raster einzelner Taster.
    2-spaltiges Grid, kein Wippen-Konzept.
    """

    changed = Signal()
    notes_changed = Signal()

    def __init__(self, be: Bedienelement, service: BauherrFormService,
                 parent=None):
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

            slot = _SlotWidget(be, slot_idx, service, slot_number=slot_idx + 1)
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
            "Gelbe Felder: Bauherr wählt die gewünschte Funktion.  "
            "Grüne Felder: bereits geplante Funktion (schreibgeschützt)."
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
            if not room.bedienelemente:
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
            taster = _TasterWidget(be, self._service)
            taster.changed.connect(self.project_changed)
            taster.notes_changed.connect(self.notes_changed)
            self._content_layout.insertWidget(
                self._content_layout.count() - 1, taster
            )

    def _on_room_notes_changed(self):
        if self._current_room is None:
            return
        self._current_room.bauherr_notes = self._room_notes.toPlainText()
        self.notes_changed.emit()
