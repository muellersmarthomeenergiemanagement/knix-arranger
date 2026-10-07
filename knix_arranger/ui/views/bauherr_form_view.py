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
import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QComboBox, QLineEdit,
    QSplitter, QSizePolicy, QGridLayout, QTextEdit, QSpinBox,
    QPushButton, QDialog, QMessageBox, QApplication, QMenu, QTreeWidget,
    QTreeWidgetItem,
)
from PySide6.QtCore import Qt, Signal, QTimer, QMimeData
from PySide6.QtGui import QBrush, QColor, QDrag
import json

from ...models.project import KnxProject
from ...models.building import (
    Room, Bedienelement, SensorFunktion, SensorFunktionGa, is_long_press, long_press_of,
)
from ...services.bauherr_form_service import (
    _DROPDOWN_OPTIONS, BauherrFormService,
)
from ...services.sensor_service import GEWERK_PRIMARY_FUNCTIONS, PRESENCE_SENSOR_TYPES
from ...services.scene_addressing import (
    scene_group_key, scene_channel_designation, build_scope_label_lookup,
    scene_target_designation, is_callable_scene,
)
from ..dialogs.ga_picker_dialog import GaPickerDialog
from ...services.multi_ga_check import (
    ROLE_MITHOEREN, VERDICT_AUSSERHALB, find_device, find_multi_ga, ga_address_of,
    ko_for_ga, unlink_ga,
)
from ..styles import COLOR_ERROR, COLOR_INFO, COLOR_WARNING, KNX_BLUE, KNX_DARK_GREEN
from ..widgets.function_palette import FunctionPalette, function_from_mime
from .topology_view import confirm_unlink

# ── Farben (identisch zum Excel-Formular) ────────────────────────────────────
_C_HEADER   = "#1A5276"
_C_ASSIGNED = "#E8F5E9"
_C_WISH     = "#FFF8E1"

_FONT_FN     = "#1B5E20"
_FONT_WISH   = "#E65100"
_FONT_HEADER = "#FFFFFF"

# Obergrenze fuer die manuelle Tastenanzahl-Anpassung -- deckt auch groessere
# Glas-/Rocker-Tastereinheiten ab, die ueber die feste Auswahl (1/2/4/6) im
# Funktionszuordnungs-Dialog (Schritt 11) hinausgehen.
_MAX_CHANNELS = 12

# Physische Position aus einem ETS-Import-Label wie "Taste 2, links"
# herauslesen (siehe XlsxImportService._button_key -- dieselbe Konvention).
# Reihe = Taste-Nummer, Spalte = links/rechts -- damit kann das Bauherr-Grid
# eine importierte Taste an ihrer ECHTEN Position auf der Wand platzieren
# statt an ihrer Listenposition (FA-1502c).
_TASTE_POSITION_RE = re.compile(
    r"^taste\s*(\d+)\s*,\s*(links|rechts)\b", re.IGNORECASE
)
_SIDE_TO_COL = {"links": 0, "rechts": 1}

# Melder, die selbst schalten (Licht bei Anwesenheit): erscheinen in der
# Bauherrenberatung mit Kanälen statt Tasten, damit man Leuchten verknüpft
LINKABLE_SENSOR_TYPES = PRESENCE_SENSOR_TYPES

# Hinzufügbar in der Bauherrenberatung: (Typ, Kanäle)
ADDABLE_ELEMENTS = (
    ("Tastereinheit", 4),
    ("Raumthermostat", 1),
    ("Präsenzmelder", 1),
    ("Bewegungsmelder", 1),
)


def _view_elements(room: Room, imported: bool) -> list[Bedienelement]:
    """Bedienelemente der Bauherrenberatung: was der Bauherr bedient, dazu
    Präsenz- und Bewegungsmelder, auf die man Leuchten legt."""
    return [be for be in room.bedienelemente if be.is_shown(imported)
            and (be.is_operable or be.element_type in LINKABLE_SENSOR_TYPES)]


# Gezogene Taste der Bauherrenberatung (verschieben/tauschen, FA-1015 e)
SLOT_MIME = "application/x-knix-button"

# Rolle einer Zusatz-GA an der Taste (SensorFunktionGa.role) für die Chips
_EXTRA_ROLE_LABELS = {
    "befehl": "Befehl",
    "rueckmeldung": "Rückmeldung",
    "fremdsteuerung": "Fremdsteuerung",
    ROLE_MITHOEREN: "⚠ Mithören – prüfen",
}


def _parse_taste_position(label: str) -> tuple[int, int] | None:
    """Gibt (Reihe, Spalte) 0-indiziert zurück, oder None wenn das Label
    keiner "Taste N, links/rechts"-Konvention entspricht (z.B. wizard-
    geplante oder manuell hinzugefügte Tasten -- dort bleibt es bei
    sequenzieller Nummerierung, siehe _assign_grid_positions)."""
    m = _TASTE_POSITION_RE.match((label or "").strip())
    if not m:
        return None
    return int(m.group(1)) - 1, _SIDE_TO_COL[m.group(2).lower()]


def _assign_grid_positions(
    real_funktionen: list[SensorFunktion], n_slots: int,
) -> dict[tuple[int, int], SensorFunktion | None]:
    """Ordnet jeder Taste eine (Reihe, Spalte)-Position im 2-spaltigen Grid
    zu. Tasten mit erkennbarer physischer Position (siehe
    _parse_taste_position) behalten diese; alle anderen (wizard-geplant, neu
    hinzugefügt, Platzhalter-Slots) werden zeilenweise in die verbleibenden
    freien Zellen aufgefüllt."""
    positioned: dict[tuple[int, int], SensorFunktion] = {}
    remaining: list[SensorFunktion | None] = []
    for sf in real_funktionen:
        pos = _parse_taste_position(sf.label)
        if pos is not None and pos not in positioned:
            positioned[pos] = sf
        else:
            remaining.append(sf)
    remaining.extend([None] * (n_slots - len(real_funktionen)))

    cells: dict[tuple[int, int], SensorFunktion | None] = dict(positioned)
    row = 0
    idx = 0
    while idx < len(remaining):
        for col in (0, 1):
            if idx >= len(remaining):
                break
            if (row, col) not in cells:
                cells[(row, col)] = remaining[idx]
                idx += 1
        row += 1
    return cells


class _SlotWidget(QWidget):
    """
    Einzelner Taster-Slot -- immer eine QComboBox, nie schreibgeschützt.

    Jeder Slot laesst sich jederzeit auf ein anderes Gewerk (aus diesem oder
    einem anderen Raum, jeweils mit Raumnamen beschriftet), eine Szene oder
    einen freien Wunsch umstellen -- so laesst sich waehrend der Beratung
    direkt auf Aenderungswuensche des Bauherrn reagieren, ohne zuerst in
    Schritt 11 etwas entfernen zu muessen. Grün = bereits ein Wert gesetzt,
    Gelb = noch offen.

    Eine Gewerk-Auswahl deckt automatisch ALLE Funktionen dieser Gewerk-
    Instanz ab (z.B. "LD" -> Schalten UND Dimmen auf derselben Taste, kurz/
    lang unterschieden -- siehe GEWERK_PRIMARY_FUNCTIONS/_expand_funktionen).
    Bei importierten "Direkte GA"-Zuweisungen (kein Gewerk bekannt) kann
    zusaetzlich eine weitere GA hinzugefuegt werden (z.B. Schalten- UND
    Dimmen-KO derselben physischen Taste, FA-1410d/extra_gas), da dort keine
    automatische Mehrfach-Ableitung stattfindet.
    """

    changed = Signal()
    # Bezeichnung für die Bedienungsanleitung geändert (kein Neuberechnen nötig)
    label_changed = Signal()
    # Diese Taste wurde geloescht (SensorFunktion aus be.funktionen entfernt)
    # -- Positionen aller nachfolgenden Slots verschieben sich, daher muss
    # der komplette Taster-Raster neu aufgebaut werden (siehe _TasterWidget).
    removed = Signal()

    def __init__(self, be: Bedienelement, sf: SensorFunktion | None,
                 service: BauherrFormService, slot_label: str,
                 room: Room, parent=None, begin_change=None,
                 long_of: SensorFunktion | None = None,
                 grid_pos: tuple[int, int] | None = None):
        super().__init__(parent)
        # Zelle im Raster (Reihe, Spalte) -- Position beim Verschieben in
        # importierte Tastereinheiten ("Taste 3, links")
        self._grid_pos = grid_pos
        self._press_pos = None
        self._be      = be
        self._sf      = sf
        self._service = service
        self._room    = room
        # Rückgängig-Punkt vor jeder Änderung (ProjectBus.begin_change)
        self._begin   = begin_change or (lambda _description: None)
        # Gesetzt = dieser Slot ist der lange Tastendruck der Taste long_of
        self._long_of = long_of
        # Funktion aus der Funktionsliste hierher ziehen (FA-1015 e)
        self.setAcceptDrops(True)
        self.setObjectName("bauherrSlot")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)

        head_row = QHBoxLayout()
        head_row.setSpacing(2)
        # Taster-Position (klein, grau) -- bei importierten Tasten die echte
        # physische Lage ("1 links"), sonst eine einfache Sequenznummer ("T5",
        # siehe _assign_grid_positions/FA-1502c).
        num_lbl = QLabel(slot_label)
        num_lbl.setStyleSheet(
            "color: #666666; font-size: 12px; padding: 0; margin: 0;"
        )
        num_lbl.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        head_row.addWidget(num_lbl)
        # Griff zum Verschieben/Tauschen (FA-1015 e) -- gezogen wird der
        # ganze Slot, der Griff macht es nur sichtbar
        self._grip = QLabel("≡")
        self._grip.setToolTip("Ziehen, um die Taste zu verschieben (freie Taste) "
                              "oder mit einer anderen zu tauschen (belegte Taste)")
        self._grip.setCursor(Qt.OpenHandCursor)
        self._grip.setStyleSheet("color: #78909C; font-size: 14px; padding: 0 2px;")
        self._grip.setVisible(sf is not None and long_of is None)
        head_row.addWidget(self._grip)
        head_row.addStretch()

        # Deutlich sichtbarer Hintergrund statt transparent -- ein 16px
        # transparenter Button mit nur einem kleinen "x" ging in der Praxis
        # leicht unter (Regression: Nutzer fand keine Möglichkeit, eine
        # Taste zu löschen, obwohl der Button technisch da war).
        self._btn_delete = QPushButton("✕ entfernen")
        self._btn_delete.setFixedHeight(18)
        self._btn_delete.setToolTip("Diese Taste entfernen")
        self._btn_delete.setCursor(Qt.PointingHandCursor)
        self._btn_delete.setStyleSheet(
            "QPushButton { color: #B71C1C; font-size: 12px; font-weight: bold; "
            "border: 1px solid #EF9A9A; border-radius: 2px; "
            "background: #FFEBEE; padding: 1px 6px; } "
            "QPushButton:hover { background: #FFCDD2; border-color: #B71C1C; }"
        )
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_delete.setVisible(sf is not None)
        head_row.addWidget(self._btn_delete)
        layout.addLayout(head_row)

        combo_row = QHBoxLayout()
        combo_row.setSpacing(2)
        self._combo = QComboBox()
        self._combo.addItem("– Funktion wählen –", None)
        self._populate_combo()
        has_value = self._select_current(sf)
        self._apply_style(has_value)
        self._last_index = self._combo.currentIndex()
        self._combo.currentIndexChanged.connect(self._on_changed)
        combo_row.addWidget(self._combo, 1)
        layout.addLayout(combo_row)

        # Bezeichnung für den Bauherrn (Bedienungsanleitung): Platzhalter =
        # automatische Bezeichnung, eigener Text überschreibt sie
        self._label_edit = None
        self._is_sensor = be.element_type in LINKABLE_SENSOR_TYPES
        key = (self._button_key() if (sf is not None and long_of is None
                                      and not self._is_sensor) else None)
        if key is not None:
            from ...services.user_manual import button_label_key
            self._label_key = button_label_key(be, key)
            label_row = QHBoxLayout()
            label_row.setSpacing(3)
            hint = QLabel("In der Anleitung:")
            hint.setStyleSheet("color: #607D8B; font-size: 11px; border: none;")
            label_row.addWidget(hint)
            self._label_edit = QLineEdit(
                self._project_labels().get(self._label_key, ""))
            self._label_edit.setPlaceholderText(self._auto_label(key) or "automatisch")
            self._label_edit.setToolTip(
                "Bezeichnung dieser Taste in der Bedienungsanleitung, z.B. «Hell» "
                "statt «Szene High». Leer = automatische Bezeichnung (grau).")
            self._label_edit.setStyleSheet("font-size: 11px; padding: 1px 3px;")
            self._label_edit.editingFinished.connect(self._on_label_edited)
            label_row.addWidget(self._label_edit, 1)
            layout.addLayout(label_row)

        # Gruppenadresse(n) der Taste sichtbar machen: gesendete GA klein
        # unter der Auswahl, weitere GAs als Chips (_rebuild_extra_row)
        self._ga_lbl = QLabel("")
        self._ga_lbl.setWordWrap(True)
        self._ga_lbl.setStyleSheet("color: #455A64; font-size: 11px; border: none;")
        layout.addWidget(self._ga_lbl)
        self._warn_lbl = QLabel("")
        self._warn_lbl.setWordWrap(True)
        self._warn_lbl.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 11px; font-weight: bold; border: none;")
        layout.addWidget(self._warn_lbl)

        # Zusaetzliche GAs (nur bei "Direkte GA"-Slots, FA-1410d) -- z.B.
        # Dimmen-GA zusaetzlich zur Schalten-GA derselben Taste.
        self._extra_row = QHBoxLayout()
        self._extra_row.setSpacing(3)
        layout.addLayout(self._extra_row)
        self._btn_add_ga = QPushButton("+ GA")
        self._btn_add_ga.setToolTip(
            "Zusätzliche Gruppenadresse an dieser Taste hinzufügen "
            "(z.B. Dimmen zusätzlich zu Schalten)"
        )
        self._btn_add_ga.setStyleSheet(
            "QPushButton { font-size: 12px; color: #1565C0; border: 1px dashed #90CAF9; "
            "border-radius: 2px; padding: 1px 4px; background: white; } "
            "QPushButton:hover { background: #E3F2FD; }"
        )
        self._btn_add_ga.clicked.connect(self._on_add_ga)
        layout.addWidget(self._btn_add_ga)
        self._findings: dict = {}   # GA -> MultiGaFinding dieser Taste
        self._rebuild_extra_row()

        # Langer Tastendruck dieser Taste: eigene Zeile "lang" oder "+ lang".
        # Gewerke wie Dimmer oder Jalousie belegen "lang" selbst (Dimmen,
        # Fahren) -- dort kein zweiter langer Tastendruck.
        if long_of is None and sf is not None and not self._is_sensor:
            long_sf = long_press_of(be.funktionen, sf)
            gewerk_long = ""
            if sf.gewerk_code and not sf.ga_designation:
                gewerk_long = next(
                    (fn[2] for fn in GEWERK_PRIMARY_FUNCTIONS.get(sf.gewerk_code, [])
                     if fn[3] == "lang"), "")
            if long_sf is not None:
                if gewerk_long:
                    warn = QLabel(f"⚠ «lang» ist durch das Gewerk bereits belegt "
                                  f"({gewerk_long}) – bitte einen entfernen")
                    warn.setWordWrap(True)
                    warn.setStyleSheet("color: #B71C1C; font-size: 12px; border: none;")
                    layout.addWidget(warn)
                long_slot = _SlotWidget(be, long_sf, service, "lang", room,
                                        begin_change=begin_change, long_of=sf)
                long_slot.changed.connect(self.changed)
                long_slot.label_changed.connect(self.label_changed)
                long_slot.removed.connect(self.removed)
                layout.addWidget(long_slot)
            elif gewerk_long:
                info = QLabel(f"lang: {gewerk_long} (aus Gewerk)")
                info.setStyleSheet("color: #666666; font-size: 12px; border: none;")
                layout.addWidget(info)
            else:
                btn_long = QPushButton("+ lang")
                btn_long.setToolTip(
                    "Langen Tastendruck für diese Taste ergänzen. Bei importierten "
                    "Tastern nur dokumentiert -- im Gerät in der ETS einrichten."
                )
                btn_long.setStyleSheet(self._btn_add_ga.styleSheet())
                btn_long.clicked.connect(self._on_add_long)
                layout.addWidget(btn_long)

        self.setMinimumHeight(56)
        self.setStyleSheet(
            "QWidget { border: 1px solid #CFD8DC; border-radius: 3px; "
            "background-color: #FAFAFA; }"
        )

    # ── Ziehen und Ablegen (FA-1015 e) ───────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._sf is not None and self._long_of is None:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press_pos is None or not event.buttons() & Qt.LeftButton
                or (event.position().toPoint() - self._press_pos).manhattanLength()
                < QApplication.startDragDistance()):
            return super().mouseMoveEvent(event)
        self._press_pos = None
        mime = QMimeData()
        mime.setData(SLOT_MIME, json.dumps(
            {"be_id": self._be.id, "sf_id": self._sf.id}).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab().scaledToWidth(220, Qt.SmoothTransformation))
        if drag.exec(Qt.MoveAction) == Qt.MoveAction:
            # Erst jetzt neu aufbauen: während des Ziehens läuft dieser Slot
            # noch (deleteLater aus der Drag-Schleife wäre zu früh)
            self.removed.emit()

    def mouseReleaseEvent(self, event):
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def _slot_payload(self, mime) -> dict | None:
        """Gezogene Taste {"be_id", "sf_id"}, wenn sie hier abgelegt werden darf."""
        if self._long_of is not None or not mime.hasFormat(SLOT_MIME):
            return None
        try:
            data = json.loads(bytes(mime.data(SLOT_MIME)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if self._sf is not None and data.get("sf_id") == self._sf.id:
            return None
        return data

    def dragEnterEvent(self, event):
        if (function_from_mime(event.mimeData()) is not None
                or self._slot_payload(event.mimeData()) is not None):
            self.setStyleSheet("#bauherrSlot { border: 2px dashed #1565C0; "
                               "border-radius: 3px; background: #E3F2FD; }")
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setStyleSheet("")
        payload = self._slot_payload(event.mimeData())
        if payload is not None:
            if self.apply_dropped_slot(payload):
                event.setDropAction(Qt.MoveAction)
                event.accept()
            else:
                event.ignore()
            return
        data = function_from_mime(event.mimeData())
        if data is not None and self.apply_dropped_function(data):
            event.acceptProposedAction()
        else:
            event.ignore()

    def apply_dropped_slot(self, payload: dict) -> bool:
        """Gezogene Taste hierher: auf eine freie Taste verschieben, mit einer
        belegten tauschen (nur innerhalb des Raums). Den Raster baut die
        Quelle nach dem Ziehen neu auf (removed)."""
        from ...services.button_move import has_position, move_button
        src_be = next((b for b in self._room.bedienelemente
                       if b.id == payload.get("be_id")), None)
        sf = next((f for f in src_be.funktionen if f.id == payload.get("sf_id")),
                  None) if src_be else None
        if sf is None or sf is self._sf:
            return False
        target_label = ""
        if self._sf is None and self._grid_pos is not None and any(
                has_position(f.label) for f in self._be.funktionen):
            row, col = self._grid_pos
            target_label = f"Taste {row + 1}, {'links' if col == 0 else 'rechts'}"
        self._begin("Bauherrenberatung: Taste getauscht" if self._sf is not None
                    else "Bauherrenberatung: Taste verschoben")
        move_button(src_be, sf, self._be, target=self._sf, target_label=target_label,
                    labels=self._project_labels())
        return True

    def apply_dropped_function(self, data: dict) -> bool:
        """Übernimmt eine gezogene Funktion wie eine Auswahl in der Liste der
        Taste -- mit Rückgängig-Punkt und Neuberechnung (_on_changed)."""
        target = ("gewerk", data.get("code"), data.get("element"), data.get("room_id"))
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == target:
                if i != self._combo.currentIndex():
                    self._combo.setCurrentIndex(i)
                return True
        return False

    def _populate_combo(self):
        """Befuellt den Combo mit den tatsaechlich geplanten Gewerken aller
        Raeume (eigener Raum zuerst, jeweils mit Raumnamen beschriftet -- vorher
        war nicht ersichtlich, welches Gewerk aus welchem Raum ausgewaehlt
        wird) und den benannten Szenen des Projekts -- direkt auswaehlbar,
        inklusive GA-Verknuepfung, ohne Umweg ueber die Verknuepfungsmatrix.
        Generische Freitext-Wuensche bleiben als Fallback fuer alles, was
        (noch) keinem Gewerk entspricht.

        Abschnitte sind durch nicht auswaehlbare Kopfzeilen getrennt (vorher
        eine einzige unuebersichtliche flache Liste aus Gewerken, Szenen und
        Freitext-Wuenschen)."""
        project = self._service.project

        own_items = []
        for assignment in self._room.gewerk_assignments:
            code = assignment.gewerk_code
            if code not in GEWERK_PRIMARY_FUNCTIONS:
                continue
            for elem_nr in range(1, assignment.count + 1):
                own_items.append((code, elem_nr, self._room))

        other_items = []
        seen: set[tuple[str, str, int]] = set(
            (self._room.id, code, elem_nr) for code, elem_nr, _ in own_items
        )
        for room in project.all_rooms:
            if room.id == self._room.id:
                continue
            for assignment in room.gewerk_assignments:
                code = assignment.gewerk_code
                if code not in GEWERK_PRIMARY_FUNCTIONS:
                    continue
                for elem_nr in range(1, assignment.count + 1):
                    key = (room.id, code, elem_nr)
                    if key in seen:
                        continue
                    seen.add(key)
                    other_items.append((code, elem_nr, room))

        def _gewerk_display(code: str, elem_nr: int, count: int, room: Room) -> str:
            # Alle Funktionen dieser Gewerk-Instanz nennen (z.B. "Schalten +
            # Dimmen"), nicht nur die erste -- eine Gewerk-Auswahl deckt sie
            # automatisch alle ab (siehe Klassen-Docstring).
            fn_names = " + ".join(fn[2] for fn in GEWERK_PRIMARY_FUNCTIONS[code])
            display = f"{code} – {fn_names}"
            display += room.gewerk_element_suffix(code, elem_nr, count > 1)
            display += f"   ·   {room.number} {room.name}"
            return display

        if own_items:
            self._add_header(f"── Gewerke in {self._room.name} ──")
            counts = {a.gewerk_code: a.count for a in self._room.gewerk_assignments}
            for code, elem_nr, room in own_items:
                display = _gewerk_display(code, elem_nr, counts.get(code, 1), room)
                self._combo.addItem(display, ("gewerk", code, elem_nr, room.id))

        if other_items:
            self._add_header("── Gewerke in anderen Räumen ──")
            room_counts: dict[str, dict[str, int]] = {}
            for room in project.all_rooms:
                room_counts[room.id] = {a.gewerk_code: a.count for a in room.gewerk_assignments}
            for code, elem_nr, room in other_items:
                count = room_counts.get(room.id, {}).get(code, 1)
                display = _gewerk_display(code, elem_nr, count, room)
                self._combo.addItem(display, ("gewerk", code, elem_nr, room.id))

        label_lookup = build_scope_label_lookup(project.areal)
        scene_items = [scene for scene in project.scenes if is_callable_scene(scene)]
        if scene_items:
            self._add_header("── Szenen ──")
            for scene in scene_items:
                designation = scene_target_designation(
                    scene, label_lookup, project.group_addresses
                )
                self._combo.addItem(
                    f"Szene: {scene.name}   ·   {designation}",
                    ("scene", scene.id, designation, scene.name),
                )

        self._add_header("── Freitext-Wünsche ──")
        for opt in _DROPDOWN_OPTIONS:
            self._combo.addItem(opt, ("wish", opt))

    def _add_header(self, text: str):
        """Fuegt eine nicht auswaehlbare, fett dargestellte Abschnitts-
        Kopfzeile in den Combo ein."""
        self._combo.addItem(text, ("header",))
        item = self._combo.model().item(self._combo.count() - 1)
        item.setEnabled(False)
        f = item.font()
        f.setBold(True)
        item.setFont(f)

    def _select_current(self, sf: SensorFunktion | None) -> bool:
        """Waehlt die Combo-Option, die dem aktuellen Zustand von sf
        entspricht, und gibt zurueck ob ueberhaupt ein Wert gesetzt ist.
        Passt der Zustand zu keiner gelisteten Option (z.B. eine "Direkte
        GA"-Zuweisung aus Schritt 11), wird ein synthetischer Eintrag mit den
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
            target = None  # Direkte GA (Schritt 11) -- unten als Sonderfall behandelt
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
                f"font-size: 12px; font-weight: bold; "
                f"border: 1px solid #A5D6A7; border-radius: 2px; padding: 2px;"
            )
        else:
            self._combo.setStyleSheet(
                f"background-color: {_C_WISH}; color: {_FONT_WISH}; "
                f"font-size: 12px; border: 1px solid #E0C870; "
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
            # Zuweisung aus Schritt 11) -- source_room_id wird unten je nach
            # eigenem/fremdem Raum wieder korrekt aufgeloest.
            return dict(data[1])
        # "wish": reiner Freitext-Wunsch, keine GA bekannt -- muss spaeter ueber
        # die Verknuepfungsmatrix (FA-2503) aufgeloest werden.
        _, text = data
        return dict(label=text)

    def _apply_fields(self, fields: dict, keep_extra_gas: bool = False):
        be = self._be
        # source_room_id="" bedeutet "eigener Raum" (siehe SensorFunktion) --
        # das Gewerk-Item liefert dafuer bewusst die eigene Raum-Id (fuer den
        # Vergleich in _select_current), hier auf "" normalisiert.
        source_room_id = fields.get("source_room_id", "")
        if source_room_id == self._room.id:
            source_room_id = ""

        if self._sf is None:
            self._sf = SensorFunktion()
            be.funktionen.append(self._sf)
            self._btn_delete.setVisible(True)
        sf = self._sf

        sf.label          = fields.get("label", "")
        sf.gewerk_code     = fields.get("gewerk_code", "")
        sf.element_number  = fields.get("element_number", 1)
        sf.source_room_id  = source_room_id
        sf.ga_designation  = fields.get("ga_designation", "")
        sf.action_type     = fields.get("action_type", "")
        sf.bedienart       = fields.get("bedienart", "")
        sf.scene_id        = fields.get("scene_id", "")
        # Eine echte Neuauswahl (nicht das unveraenderte "current") ersetzt das
        # Ziel dieser Taste komplett -- zusaetzliche GAs (FA-1410d) bezogen
        # sich auf das ALTE Ziel und muessen mit verworfen werden, sonst
        # haengt z.B. eine alte Dimmen-GA an einer neu gewaehlten Szene.
        if not keep_extra_gas:
            sf.extra_gas = []
            sf.primary_role = "befehl"

    def _on_changed(self, index: int):
        data = self._combo.itemData(index)
        if data and data[0] == "header":
            return  # Kopfzeilen sind deaktiviert, sollte nie ausgewaehlt werden

        # Ein langer Tastendruck braucht immer eine konkrete GA -- ein Gewerk
        # würde kurz UND lang ableiten (siehe _expand_funktionen)
        if data and data[0] == "gewerk" and (
                self._long_of is not None or not self._service.gewerk_lookup_available()):
            # Importierte Projekte (kein Schritt-7-Lauf) haben nirgends ein
            # function_name-Tag auf ihren GAs -- SensorService._expand_funktionen
            # koennte eine gewerk_code-basierte SensorFunktion NIE zu einer
            # echten GA aufloesen und wuerde sie beim naechsten Refresh
            # (z.B. Topologie/Matrix oeffnen) kommentarlos verwerfen, obwohl
            # die Auswahl hier erfolgreich aussah. Stattdessen sofort per
            # GA-Picker die echte GA festlegen (Regression: "GA wird nicht
            # uebernommen, sondern einfach geloescht").
            fields = self._resolve_gewerk_via_picker(data)
            if fields is None:
                self._combo.blockSignals(True)
                self._combo.setCurrentIndex(self._last_index)
                self._combo.blockSignals(False)
                return
        else:
            fields = self._fields_for(data)

        self._begin("Bauherrenberatung: Taste geändert")
        self._apply_fields(fields, keep_extra_gas=bool(data and data[0] == "current"))
        if self._long_of is not None:
            self._sf.press_of = self._long_of.id
            self._sf.action_type = "lang"

        if data:
            # Wahl markiert das Bedienelement als manuell konfiguriert, damit
            # auto_assign_functions die Funktionsliste bei der nachfolgenden
            # Neuberechnung nicht verwirft (FA-1410: is_auto=False wird erhalten).
            self._be.is_auto = False

        self._apply_style(bool(data))
        self._rebuild_extra_row()
        self._last_index = self._combo.currentIndex()
        self.changed.emit()

    @staticmethod
    def _ga_text(ga) -> str:
        """Adresse + Bezeichnung kombiniert (z.B. "1/0/5  L.DG.03_ea (Lavabo)"),
        dieselbe Konvention wie XlsxImportService.backfill_function_assignments
        -- sonst zeigen Gebäude-Ansicht/Schritt 12 nur den Bezeichnungstext ohne
        die eigentliche Gruppenadressnummer."""
        return f"{ga.address}  {ga.designation}".strip() if ga.designation else ga.address

    def _resolve_gewerk_via_picker(self, data) -> dict | None:
        """Loest eine Gewerk-Auswahl direkt ueber den GA-Picker auf, wenn eine
        automatische Ableitung nicht moeglich ist (siehe _on_changed). Gibt
        None bei Abbruch zurueck."""
        _, code, elem_nr, room_id = data
        room_for_pick = self._service._room_by_id(room_id) or self._room
        dlg = GaPickerDialog(self._service.project, room_for_pick,
                              gewerk_hint=code, parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected_ga is None:
            return None
        return dict(
            gewerk_code=code, element_number=elem_nr, source_room_id=room_id,
            ga_designation=self._ga_text(dlg.selected_ga),
        )

    def _rebuild_extra_row(self):
        """Zeigt zusaetzliche GAs (SensorFunktion.extra_gas, FA-1410d) als
        kleine entfernbare Chips. Massgeblich ist allein sf.ga_designation
        (nicht sf.gewerk_code): SensorService._expand_funktionen prueft
        ga_designation IMMER zuerst und behandelt die SensorFunktion dann als
        Direkte-GA, unabhaengig davon, ob zusaetzlich ein gewerk_code gesetzt
        ist (das passiert z.B. wenn eine Gewerk-Auswahl in einem Projekt ohne
        Schritt-7-Adressen ueber den GA-Picker aufgeloest wurde -- siehe
        _resolve_gewerk_via_picker -- gewerk_code bleibt dort NUR zur
        Beschriftung erhalten). Ein "echtes" Gewerk (gewerk_code gesetzt, KEIN
        ga_designation) deckt Schalten+Dimmen dagegen schon automatisch ab
        (siehe Klassen-Docstring), dafuer braucht es keine manuelle GA."""
        while self._extra_row.count():
            item = self._extra_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        sf = self._sf
        is_direct_ga = bool(sf and sf.ga_designation and not sf.scene_id)
        self._btn_add_ga.setVisible(is_direct_ga)
        primary = ga_address_of(sf.ga_designation) if sf else ""
        self._ga_lbl.setText(f"sendet {sf.ga_designation}" if primary else "")
        self._ga_lbl.setVisible(bool(primary))
        self._warn_lbl.setVisible(False)
        if not is_direct_ga:
            return

        # Pro Sensorkanal nur eine sendende GA (FA-614): nachgewiesener fremder
        # Befehl = Fehler, ohne gefundenen Sender = Warnung, Rückmeldungen
        # ausserhalb MG 6/7 = Hinweis
        extra_addrs = {ga_address_of(e.ga_designation) for e in sf.extra_gas}
        self._findings = {
            f.extra_ga: f for f in find_multi_ga(self._service.project)
            if f.physical_address == self._be.participant_number
            and f.extra_ga in extra_addrs
        }
        errors = [a for a, f in self._findings.items() if f.is_error]
        warn = [a for a, f in self._findings.items() if f.level == "warning"]
        info = [a for a, f in self._findings.items() if f.verdict == VERDICT_AUSSERHALB]
        if errors or warn:
            parts = []
            if errors:
                parts.append(f"⚠ Zweite sendende GA: {', '.join(errors)} ist der Befehl "
                             "einer anderen Bedienstelle")
            if warn:
                parts.append(f"⚠ Weitere GA {', '.join(warn)} ohne gefundenen Sender "
                             "(nicht eindeutig)")
            self._warn_lbl.setText(
                " · ".join(parts) + f" – pro Sensorkanal nur eine sendende GA "
                f"({primary}). Prüfen und ggf. trennen (✕).")
            color = COLOR_ERROR if errors else COLOR_WARNING
            self._warn_lbl.setStyleSheet(
                f"color: {color}; font-size: 11px; font-weight: bold; border: none;")
            self._warn_lbl.setVisible(True)
        elif info:
            self._warn_lbl.setText(
                f"Hinweis: Rückmeldung {', '.join(info)} liegt nicht in MG 6/7.")
            self._warn_lbl.setStyleSheet(
                f"color: {COLOR_INFO}; font-size: 11px; border: none;")
            self._warn_lbl.setVisible(True)

        for extra in list(sf.extra_gas):
            addr = ga_address_of(extra.ga_designation)
            role = _EXTRA_ROLE_LABELS.get(extra.role, "")
            text = f"{addr or self._service._label_from_ga(extra.ga_designation)}"
            if role:
                text += f" · {role}"
            chip = QPushButton(f"{text}  ✕")
            chip.setToolTip(self._chip_tooltip(extra))
            if extra.role == ROLE_MITHOEREN:
                chip.setStyleSheet(
                    f"QPushButton {{ font-size: 12px; color: {COLOR_WARNING}; "
                    "background: #FFF3E0; font-weight: bold; "
                    f"border: 1px solid {COLOR_WARNING}; border-radius: 8px; padding: 1px 6px; }} "
                    "QPushButton:hover { background: #FFCDD2; }"
                )
            else:
                chip.setStyleSheet(
                    "QPushButton { font-size: 12px; color: #37474F; background: #ECEFF1; "
                    "border: 1px solid #CFD8DC; border-radius: 8px; padding: 1px 6px; } "
                    "QPushButton:hover { background: #FFCDD2; }"
                )
            chip.clicked.connect(lambda _checked=False, e=extra: self._on_remove_extra(e))
            self._extra_row.addWidget(chip)
        self._extra_row.addStretch()

    def _device_ko(self, extra: SensorFunktionGa):
        """(Gerät, KO), an dem die Zusatz-GA in der Topologie hängt."""
        pa = self._be.participant_number
        addr = ga_address_of(extra.ga_designation)
        device = find_device(self._service.project, pa) if pa and addr else None
        co = ko_for_ga(device, addr, extra.description) if device else None
        return device, co

    def _chip_tooltip(self, extra: SensorFunktionGa) -> str:
        lines = [extra.ga_designation]
        device, co = self._device_ko(extra)
        if co is not None:
            lines.append(f"{device.physical_address} · KO {co.object_number} "
                         f"«{co.name or co.object_function}»")
        finding = self._findings.get(ga_address_of(extra.ga_designation))
        if finding is not None:
            lines.append(f"Weitere GA am Sendekanal – {finding.verdict_label}: "
                         f"{finding.reason}")
        lines.append("Klicken, um die GA von dieser Taste zu trennen")
        return "\n".join(lines)

    def _on_add_ga(self):
        dlg = GaPickerDialog(self._service.project, self._room, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_ga is not None:
            if self._sf is None:
                return
            self._begin("Bauherrenberatung: GA ergänzt")
            self._sf.extra_gas.append(SensorFunktionGa(
                ga_designation=self._ga_text(dlg.selected_ga), role="befehl",
                description=dlg.selected_ga.designation,
            ))
            self._be.is_auto = False
            self._rebuild_extra_row()
            self.changed.emit()

    # ── Bezeichnung für den Bauherrn ──
    def _button_key(self):
        from ...services.bedienelement_layout import parse_button
        channel = next((fa.button_channel for fa in self._be.function_assignments
                        if fa.sf_id == self._sf.id), "") or self._sf.label
        parsed = parse_button(channel)
        return parsed[0] if parsed else None

    def _project_labels(self) -> dict:
        return self._service.project.ets_corrections.button_labels

    def _auto_label(self, key) -> str:
        builder = getattr(self._service, "manual_builder", None)
        if builder is None:
            return ""
        try:
            lines = builder.key_lines(self._be, self._room.name, use_labels=False)
        except Exception:
            return ""
        return next((kl.label for kl in lines
                     if (kl.key.number, kl.key.side) == (key.number, key.side)), "")

    def _on_label_edited(self):
        text = self._label_edit.text().strip()
        labels = self._project_labels()
        if text == labels.get(self._label_key, ""):
            return
        self._begin(f"Bauherrenberatung: Bezeichnung «{text or 'automatisch'}»")
        if text:
            labels[self._label_key] = text
        else:
            labels.pop(self._label_key, None)
        self.label_changed.emit()

    def _on_remove_extra(self, extra: SensorFunktionGa):
        """GA von der Taste trennen -- bei importierten Geräten auch am KO
        (wie in der ETS), sonst käme sie beim nächsten Abgleich zurück."""
        if self._sf is None or extra not in self._sf.extra_gas:
            return
        device, co = self._device_ko(extra)
        addr = ga_address_of(extra.ga_designation)
        if co is not None:
            if not confirm_unlink(self, device.physical_address, co, addr):
                return
            self._begin(f"Bauherrenberatung: GA {addr} von "
                        f"{device.physical_address} KO {co.object_number} getrennt")
            unlink_ga(self._service.project, device.physical_address,
                      co.object_number, addr)
            if extra in self._sf.extra_gas:
                self._sf.extra_gas.remove(extra)
        else:
            self._begin("Bauherrenberatung: GA entfernt")
            self._sf.extra_gas.remove(extra)
        self._be.is_auto = False
        self._rebuild_extra_row()
        self.changed.emit()

    def _on_delete(self):
        if self._sf is None:
            return
        self._begin("Bauherrenberatung: Taste entfernt")
        # Eine Taste nimmt ihren langen Tastendruck mit
        long_sf = None if self._long_of else long_press_of(self._be.funktionen, self._sf)
        for sf in (self._sf, long_sf):
            if sf is not None and sf in self._be.funktionen:
                self._be.funktionen.remove(sf)
        self._be.is_auto = False
        self.removed.emit()

    def _on_add_long(self):
        """Langen Tastendruck ergänzen: leere Funktion, die zu dieser Taste
        gehört -- danach im neuen Feld "lang" auswählen."""
        if self._sf is None:
            return
        self._begin("Bauherrenberatung: langer Tastendruck ergänzt")
        self._be.funktionen.append(SensorFunktion(press_of=self._sf.id, action_type="lang"))
        self._be.is_auto = False
        self.removed.emit()   # Raster neu aufbauen


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
                 room: Room, parent=None, begin_change=None):
        super().__init__(parent)
        self._be = be
        self._begin = begin_change or (lambda _description: None)
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
            f"font-size: 12px; font-weight: bold; border: none;"
        )
        hdr_bar = QWidget()
        hdr_bar.setStyleSheet(f"QWidget {{ background-color: {_C_HEADER}; border: none; }}")
        hdr_layout = QHBoxLayout(hdr_bar)
        hdr_layout.setContentsMargins(0, 0, 4, 0)
        hdr_layout.addWidget(hdr, 1)
        # Taster, den es in Wirklichkeit nicht gibt (z.B. Licht Technik wird
        # in der Waschküche geschaltet), direkt hier entfernen -- wie in
        # Schritt 9. Importierte Geräte gibt es in der Anlage, nicht hier.
        self._room = room
        if not service.project.topology.is_imported:
            btn_remove = QPushButton("Taster entfernen" if be.element_type == "Tastereinheit"
                                     else f"{be.element_type or 'Gerät'} entfernen")
            btn_remove.setFixedHeight(20)
            btn_remove.setCursor(Qt.PointingHandCursor)
            # Wie "entfernen" an der Taste, hell auf dem dunklen Kopf
            btn_remove.setStyleSheet(
                "QPushButton { color: #B71C1C; font-size: 12px; font-weight: bold; "
                "border: 1px solid #EF9A9A; border-radius: 2px; "
                "background: #FFEBEE; padding: 1px 8px; } "
                "QPushButton:hover { background: #FFCDD2; border-color: #B71C1C; }")
            btn_remove.setToolTip("Dieses Bedienelement aus dem Raum entfernen "
                                  "(Rückgängig möglich). Seine Funktionen vorher "
                                  "auf einen anderen Taster ziehen.")
            btn_remove.clicked.connect(self._on_remove_taster)
            hdr_layout.addWidget(btn_remove)
        layout.addWidget(hdr_bar)

        # Geräteinterne Funktionen ohne physische Taste (z.B. Nachtabsenkung
        # LED, role="fremdsteuerung" -- FA-1410d) sind kein bedienbarer
        # Taster-Slot fuer den Bauherrn und werden hier ausgeblendet (be.
        # funktionen selbst bleibt unangetastet, nur die Anzeige filtert).
        # Lange Tastendrücke stehen im Slot ihrer Taste ("lang"), nicht als
        # eigene Taste
        real_funktionen = [
            sf for sf in be.funktionen
            if sf.primary_role != "fremdsteuerung" and not is_long_press(be.funktionen, sf)
        ]

        # ── Tastenanzahl anpassen ────────────────────────────────────────────
        # Nur bei Tastereinheiten sinnvoll (Kanalzahl = Anzahl physischer
        # Tasten); ein Raumthermostat o.ä. hat kein editierbares "channels".
        # Untergrenze = bereits definierte Funktionen, damit eine Verkleinerung
        # nicht stillschweigend eine schon zugewiesene Funktion verwirft --
        # eine einzelne Taste wirklich entfernen geht ueber den ✕-Button am
        # Slot (echtes Loeschen aus be.funktionen), nicht ueber dieses Feld.
        is_sensor = be.element_type in LINKABLE_SENSOR_TYPES
        if be.element_type == "Tastereinheit" or is_sensor:
            count_bar = QWidget()
            count_bar.setStyleSheet(
                "QWidget { background-color: #ECEFF1; border: none; }"
            )
            count_layout = QHBoxLayout(count_bar)
            count_layout.setContentsMargins(6, 2, 6, 2)
            count_layout.setSpacing(4)

            count_lbl = QLabel("Anzahl Kanäle:" if is_sensor else "Anzahl Tasten:")
            count_lbl.setStyleSheet(
                "color: #546E7A; font-size: 12px; border: none;"
            )
            count_layout.addWidget(count_lbl)

            self._channels_spin = QSpinBox()
            self._channels_spin.setMinimum(max(1, len(real_funktionen)))
            self._channels_spin.setMaximum(_MAX_CHANNELS)
            self._channels_spin.setValue(be.channels)
            self._channels_spin.setFixedWidth(48)
            self._channels_spin.setToolTip(
                "Physische Tastenzahl dieser Tastereinheit. Zusätzliche "
                "Tasten erscheinen als leere Wunsch-Felder unten. Um eine "
                "bereits zugewiesene Taste zu entfernen, den ✕-Button am "
                "jeweiligen Slot verwenden."
            )
            self._channels_spin.valueChanged.connect(self._on_channels_changed)
            count_layout.addWidget(self._channels_spin)
            count_layout.addStretch()

            layout.addWidget(count_bar)

        # ── Taster-Raster ──────────────────────────────────────────────────
        n_buttons = be.channels
        n_slots   = max(n_buttons, len(real_funktionen))

        grid_widget = QWidget()
        grid_widget.setStyleSheet("QWidget { border: none; background: white; }")
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(5)

        # Tasten mit erkennbarer physischer Position ("Taste N, links/
        # rechts", aus dem ETS-Import) landen an ihrer echten Stelle im
        # Grid; alle anderen fuellen zeilenweise die freien Zellen auf
        # (FA-1502c) -- vorher rein sequenziell nach Listenreihenfolge, ohne
        # Bezug zur tatsaechlichen Anordnung auf der Wand.
        cells = _assign_grid_positions(real_funktionen, n_slots)
        seq_num = 0
        for (grid_row, grid_col), sf in sorted(cells.items()):
            pos = _parse_taste_position(sf.label) if sf else None
            if pos == (grid_row, grid_col):
                side = "links" if grid_col == 0 else "rechts"
                slot_label = f"{grid_row + 1} {side}"
            else:
                seq_num += 1
                slot_label = f"{'K' if is_sensor else 'T'}{seq_num}"

            slot = _SlotWidget(be, sf, service, slot_label=slot_label, room=room,
                               begin_change=begin_change,
                               grid_pos=(grid_row, grid_col))
            slot.changed.connect(self.changed)
            slot.label_changed.connect(self.notes_changed)
            slot.removed.connect(self.structure_changed)
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
            "color: #546E7A; font-size: 12px; font-style: italic; border: none;"
        )
        ann_layout.addWidget(ann_lbl)

        self._ann_edit = QLineEdit()
        self._ann_edit.setPlaceholderText("Optionale Anmerkung des Bauherrn …")
        self._ann_edit.setStyleSheet(
            "background-color: #FFFDE7; border: 1px dotted #BDBDBD; "
            "font-size: 12px; padding: 1px 4px; border-radius: 2px;"
        )
        self._ann_edit.setFixedHeight(22)
        self._ann_edit.setText(be.bauherr_annotation or "")
        self._ann_edit.textChanged.connect(self._on_annotation)
        ann_layout.addWidget(self._ann_edit)

        layout.addWidget(ann_bar)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    @property
    def be_id(self) -> str:
        return self._be.id

    def highlight(self):
        """Hervorheben, wenn aus der Verknüpfungsmatrix hierher gesprungen."""
        self.setStyleSheet(
            "QFrame { border: 3px solid #F9A825; border-radius: 4px; "
            "background-color: white; }"
        )

    def _on_annotation(self, text: str):
        self._be.bauherr_annotation = text
        self.notes_changed.emit()

    def _on_remove_taster(self):
        from ...services.button_move import remove_bedienelement
        assigned = sum(1 for sf in self._be.funktionen if not sf.press_of
                       and (sf.gewerk_code or sf.ga_designation or sf.label))
        name = " ".join(p for p in (self._be.element_type or "Bedienelement",
                                    self._be.participant_number) if p)
        text = f"{name} entfernen?"
        if assigned:
            text += (f"\n\nSeine {assigned} belegte(n) Taste(n) gehen mit. Funktionen, die "
                     "weiterhin bedient werden sollen, vorher auf einen anderen Taster ziehen.")
        if QMessageBox.question(self, "Taster entfernen", text,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        self._begin("Bauherrenberatung: Taster entfernt")
        remove_bedienelement(self._room, self._be)
        self.structure_changed.emit()

    def _on_channels_changed(self, value: int):
        if value == self._be.channels:
            return
        self._begin("Bauherrenberatung: Tastenanzahl geändert")
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
    Links: alle Räume als Baum (Gebäude › Stockwerk › Wohnung/Zone › Raum)
    und die Funktionsliste. Rechts: Bedienelemente des gewählten Raums.
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
            "Szene oder freier Wunsch auswählen, oder eine Funktion aus der Liste "
            "links auf die Taste ziehen, auch aus einem anderen Raum.  Am Griff ≡ "
            "eine Taste auf eine andere ziehen: frei = verschieben, belegt = tauschen.  "
            "Gelb = noch offen.  Grün = bereits ein Wert gewählt.  "
            "Orange in der Liste = noch ohne Bedienung."
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
        left_split = QSplitter(Qt.Vertical)
        rooms_box = QWidget()
        rooms_layout = QVBoxLayout(rooms_box)
        rooms_layout.setContentsMargins(0, 0, 0, 0)
        rooms_layout.addWidget(QLabel("Räume:"))
        # Alle Räume des Hauses; grau = noch kein Bedienelement
        self._room_tree = QTreeWidget()
        self._room_tree.setHeaderHidden(True)
        self._room_tree.setMinimumWidth(160)
        self._room_tree.currentItemChanged.connect(self._on_room_selected)
        rooms_layout.addWidget(self._room_tree)
        left_split.addWidget(rooms_box)

        # Funktionen zum Ziehen auf eine Taste (FA-1015 e)
        functions_box = QWidget()
        functions_layout = QVBoxLayout(functions_box)
        functions_layout.setContentsMargins(0, 0, 0, 0)
        functions_layout.addWidget(QLabel("Funktionen – auf eine Taste ziehen:"))
        self._palette = FunctionPalette()
        functions_layout.addWidget(self._palette, 1)
        left_split.addWidget(functions_box)
        left_split.setSizes([200, 400])
        left.setMaximumWidth(340)
        left_layout.addWidget(left_split)
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

        add_bar = QHBoxLayout()
        add_bar.setContentsMargins(12, 6, 12, 0)
        self._btn_add_element = QPushButton("+ Bedienelement / Sensor")
        self._btn_add_element.setObjectName("secondary")
        self._btn_add_element.setToolTip(
            "Tastereinheit, Raumthermostat, Präsenz- oder Bewegungsmelder in "
            "diesen Raum setzen und danach Funktionen darauf legen")
        add_menu = QMenu(self._btn_add_element)
        for element_type, channels in ADDABLE_ELEMENTS:
            add_menu.addAction(element_type).triggered.connect(
                lambda _c=False, t=element_type, n=channels: self._add_element(t, n))
        self._btn_add_element.setMenu(add_menu)
        add_bar.addWidget(self._btn_add_element)
        self._empty_hint = QLabel("Noch kein Bedienelement in diesem Raum.")
        self._empty_hint.setObjectName("hint")
        add_bar.addWidget(self._empty_hint)
        add_bar.addStretch()
        right_layout.addLayout(add_bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._scroll = scroll
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
            f"color: {KNX_BLUE}; font-weight: bold; font-size: 12px; border: none;"
        )
        notes_layout.addWidget(notes_lbl)

        self._room_notes = QTextEdit()
        self._room_notes.setPlaceholderText(
            "Allgemeine Wünsche und Bemerkungen des Bauherrn …"
        )
        self._room_notes.setFixedHeight(70)
        self._room_notes.setStyleSheet(
            "background-color: white; border: 1px dotted #BDBDBD; font-size: 12px;"
        )
        self._room_notes.textChanged.connect(self._on_room_notes_changed)
        notes_layout.addWidget(self._room_notes)
        right_layout.addWidget(notes_frame)

        splitter.addWidget(right)
        splitter.setSizes([260, 700])

        self._current_room: Room | None = None
        self._bus = None

    def set_bus(self, bus):
        """ProjectBus für Rückgängig-Punkte vor jeder Änderung."""
        self._bus = bus

    def _begin_change(self, description: str):
        if self._bus:
            self._bus.begin_change(description)

    def show_element(self, be_id: str) -> bool:
        """Springt zum Raum des Bedienelements und zeigt dessen Taster an
        (Doppelklick in der Verknüpfungsmatrix). False, wenn es hier nicht
        vorkommt (z.B. Sensor -- die Bauherrenberatung zeigt nur, was der
        Bauherr bedient)."""
        for item in self._room_items():
            room = item.data(0, Qt.UserRole)
            if not any(be.id == be_id for be in room.bedienelemente):
                continue
            self._room_tree.setCurrentItem(item)
            for j in range(self._content_layout.count()):
                widget = self._content_layout.itemAt(j).widget()
                if isinstance(widget, _TasterWidget) and widget.be_id == be_id:
                    widget.highlight()
                    QTimer.singleShot(0, lambda w=widget: self._scroll_to(w))
                    return True
            return True
        return False

    def _scroll_to(self, widget):
        try:
            self._scroll.ensureWidgetVisible(widget)
        except RuntimeError:
            pass   # Raum inzwischen neu aufgebaut, Widget gelöscht

    # ── Projekt ────────────────────────────────────────────────────────────

    def set_project(self, project: KnxProject):
        self._project = project
        self._service = BauherrFormService(project)
        self._refresh_room_list()
        self._palette.set_project(project)

    def refresh(self):
        if self._project:
            self._refresh_room_list(
                keep_id=self._current_room.id if self._current_room else None)

    def reload(self, project: KnxProject):
        """Neu aufbauen und im selben Raum bleiben (nach Rückgängig/
        Wiederholen -- die Raum-Objekte sind dann andere, die IDs gleich)."""
        room_id = self._current_room.id if self._current_room else None
        self._project = project
        self._service = BauherrFormService(project)
        self._refresh_room_list(keep_id=room_id)
        self._palette.set_project(project)

    # ── Raumbaum ───────────────────────────────────────────────────────────

    def _room_items(self) -> list[QTreeWidgetItem]:
        """Alle Raum-Einträge des Baums in Anzeigereihenfolge."""
        items = []

        def walk(item):
            if isinstance(item.data(0, Qt.UserRole), Room):
                items.append(item)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self._room_tree.topLevelItemCount()):
            walk(self._room_tree.topLevelItem(i))
        return items

    def _select_room_row(self, index: int) -> None:
        """index-ter Raum im Baum (für Tests und Navigation)."""
        items = self._room_items()
        if 0 <= index < len(items):
            self._room_tree.setCurrentItem(items[index])

    def _select_room(self, room_id: str) -> bool:
        for item in self._room_items():
            if item.data(0, Qt.UserRole).id == room_id:
                self._room_tree.setCurrentItem(item)
                return True
        return False

    def _room_label(self, room: Room) -> tuple[str, bool]:
        count = len(_view_elements(room, self._project.topology.is_imported))
        text = f"{room.number}  {room.name}".strip()
        return (f"{text}  ({count})" if count else text), count > 0

    def _refresh_room_list(self, keep_id: str | None = None):
        """Alle Räume als Baum: Gebäude (nur bei mehreren) › Stockwerk ›
        Wohnung/Zone › Raum. Ausgewählt bleibt keep_id, sonst der erste Raum
        mit Bedienelement."""
        self._room_tree.blockSignals(True)
        self._room_tree.clear()
        self._room_tree.blockSignals(False)
        if not self._project:
            return
        buildings = self._project.areal.buildings
        muted = QBrush(QColor("#90A4AE"))
        for building in buildings:
            parent = None
            if len(buildings) > 1:
                parent = QTreeWidgetItem([building.name or "Gebäude"])
                self._room_tree.addTopLevelItem(parent)
            for wing in building.wings:
                for floor in wing.floors:
                    floor_item = QTreeWidgetItem([" ".join(
                        p for p in (floor.short_code, floor.name) if p) or "Stockwerk"])
                    for apartment in floor.apartments:
                        if not apartment.rooms:
                            continue
                        apt_item = QTreeWidgetItem([apartment.name or "Wohnung"])
                        for room in apartment.rooms:
                            text, has_elements = self._room_label(room)
                            room_item = QTreeWidgetItem([text])
                            room_item.setData(0, Qt.UserRole, room)
                            if not has_elements:
                                room_item.setForeground(0, muted)
                            apt_item.addChild(room_item)
                        floor_item.addChild(apt_item)
                    if not floor_item.childCount():
                        continue
                    if parent is not None:
                        parent.addChild(floor_item)
                    else:
                        self._room_tree.addTopLevelItem(floor_item)
        self._room_tree.expandAll()
        if keep_id and self._select_room(keep_id):
            return
        items = self._room_items()
        first = next((i for i in items if self._room_label(i.data(0, Qt.UserRole))[1]),
                     items[0] if items else None)
        if first is not None:
            self._room_tree.setCurrentItem(first)

    # ── Raum-Auswahl ───────────────────────────────────────────────────────

    def _on_room_selected(self, current: QTreeWidgetItem, _previous):
        room = current.data(0, Qt.UserRole) if current is not None else None
        if isinstance(room, Room):
            self._load_room(room)

    def _add_element(self, element_type: str, channels: int):
        """Bedienelement oder Melder in den gewählten Raum setzen -- wie in
        Schritt 9 (manuell angelegt, bleibt bei der Neuberechnung)."""
        room = self._current_room
        if room is None or self._project is None or self._project.topology.is_imported:
            return
        used = {i for a in room.gewerk_assignments for i in a.taster_indices}
        used |= {be.taster_index for be in room.bedienelemente if not be.is_auto}
        self._begin_change(f"Bauherrenberatung: {element_type} hinzugefügt")
        room.bedienelemente.append(Bedienelement(
            element_type=element_type, channels=channels, is_auto=False,
            taster_index=max(used, default=0) + 1))
        self._on_structure_changed()

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
        # Automatische Tastenbezeichnungen wie in der Bedienungsanleitung
        try:
            from ...services.user_manual import UserManualBuilder
            self._service.manual_builder = UserManualBuilder(self._project, snapshot=False)
        except Exception:
            self._service.manual_builder = None
        elements = _view_elements(room, self._project.topology.is_imported)
        self._empty_hint.setVisible(not elements)
        self._btn_add_element.setEnabled(not self._project.topology.is_imported)
        for be in elements:
            taster = _TasterWidget(be, self._service, room=room,
                                   begin_change=self._begin_change)
            taster.changed.connect(self.project_changed)
            # Markierung "ohne Bedienung" nachführen -- verzögert, ein Ablegen
            # läuft noch im Drag der Funktionsliste
            taster.changed.connect(lambda: QTimer.singleShot(0, self._palette.refresh))
            taster.notes_changed.connect(self.notes_changed)
            taster.structure_changed.connect(self._on_structure_changed)
            self._content_layout.insertWidget(
                self._content_layout.count() - 1, taster
            )

    def _on_structure_changed(self):
        """Tastenanzahl eines Bedienelements wurde geaendert -- Raum komplett
        neu aufbauen, damit das Grid mit der neuen Slot-Zahl neu entsteht
        (_TasterWidget legt die Slots nur einmal bei der Konstruktion an)."""
        room = self._current_room
        if room is not None:
            # Anzahl im Raumbaum nachführen; lädt den Raum neu
            self._refresh_room_list(keep_id=room.id)
        self._palette.refresh()
        self.project_changed.emit()

    def _on_room_notes_changed(self):
        if self._current_room is None:
            return
        self._current_room.bauherr_notes = self._room_notes.toPlainText()
        self.notes_changed.emit()
