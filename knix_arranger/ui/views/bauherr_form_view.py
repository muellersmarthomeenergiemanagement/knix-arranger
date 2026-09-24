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
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QScrollArea, QFrame, QComboBox, QLineEdit,
    QSplitter, QSizePolicy, QGridLayout, QTextEdit, QSpinBox,
    QPushButton, QDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from ...models.project import KnxProject
from ...models.building import Room, Bedienelement, SensorFunktion, SensorFunktionGa
from ...services.bauherr_form_service import _DROPDOWN_OPTIONS, BauherrFormService
from ...services.sensor_service import GEWERK_PRIMARY_FUNCTIONS
from ...services.scene_addressing import (
    scene_group_key, scene_channel_designation, build_scope_label_lookup,
    scene_target_designation, is_callable_scene,
)
from ..dialogs.ga_picker_dialog import GaPickerDialog
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
    # Diese Taste wurde geloescht (SensorFunktion aus be.funktionen entfernt)
    # -- Positionen aller nachfolgenden Slots verschieben sich, daher muss
    # der komplette Taster-Raster neu aufgebaut werden (siehe _TasterWidget).
    removed = Signal()

    def __init__(self, be: Bedienelement, sf: SensorFunktion | None,
                 service: BauherrFormService, slot_label: str,
                 room: Room, parent=None):
        super().__init__(parent)
        self._be      = be
        self._sf      = sf
        self._service = service
        self._room    = room

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
        self._rebuild_extra_row()

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
            if count > 1:
                display += f" #{elem_nr}"
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

        if data and data[0] == "gewerk" and not self._service.gewerk_lookup_available():
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

        self._apply_fields(fields, keep_extra_gas=bool(data and data[0] == "current"))

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
        if not is_direct_ga:
            return

        for extra in list(sf.extra_gas):
            chip = QPushButton(f"{self._service._label_from_ga(extra.ga_designation)}  ✕")
            chip.setToolTip("Klicken zum Entfernen")
            chip.setStyleSheet(
                "QPushButton { font-size: 12px; color: #37474F; background: #ECEFF1; "
                "border: 1px solid #CFD8DC; border-radius: 8px; padding: 1px 6px; } "
                "QPushButton:hover { background: #FFCDD2; }"
            )
            chip.clicked.connect(lambda _checked=False, e=extra: self._on_remove_extra(e))
            self._extra_row.addWidget(chip)
        self._extra_row.addStretch()

    def _on_add_ga(self):
        dlg = GaPickerDialog(self._service.project, self._room, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_ga is not None:
            if self._sf is None:
                return
            self._sf.extra_gas.append(SensorFunktionGa(
                ga_designation=self._ga_text(dlg.selected_ga), role="befehl",
                description=dlg.selected_ga.designation,
            ))
            self._be.is_auto = False
            self._rebuild_extra_row()
            self.changed.emit()

    def _on_remove_extra(self, extra: SensorFunktionGa):
        if self._sf is not None and extra in self._sf.extra_gas:
            self._sf.extra_gas.remove(extra)
            self._be.is_auto = False
            self._rebuild_extra_row()
            self.changed.emit()

    def _on_delete(self):
        if self._sf is None:
            return
        if self._sf in self._be.funktionen:
            self._be.funktionen.remove(self._sf)
        self._be.is_auto = False
        self.removed.emit()


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
            f"font-size: 12px; font-weight: bold; border: none;"
        )
        layout.addWidget(hdr)

        # Geräteinterne Funktionen ohne physische Taste (z.B. Nachtabsenkung
        # LED, role="fremdsteuerung" -- FA-1410d) sind kein bedienbarer
        # Taster-Slot fuer den Bauherrn und werden hier ausgeblendet (be.
        # funktionen selbst bleibt unangetastet, nur die Anzeige filtert).
        real_funktionen = [
            sf for sf in be.funktionen if sf.primary_role != "fremdsteuerung"
        ]

        # ── Tastenanzahl anpassen ────────────────────────────────────────────
        # Nur bei Tastereinheiten sinnvoll (Kanalzahl = Anzahl physischer
        # Tasten); ein Raumthermostat o.ä. hat kein editierbares "channels".
        # Untergrenze = bereits definierte Funktionen, damit eine Verkleinerung
        # nicht stillschweigend eine schon zugewiesene Funktion verwirft --
        # eine einzelne Taste wirklich entfernen geht ueber den ✕-Button am
        # Slot (echtes Loeschen aus be.funktionen), nicht ueber dieses Feld.
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
                slot_label = f"T{seq_num}"

            slot = _SlotWidget(be, sf, service, slot_label=slot_label, room=room)
            slot.changed.connect(self.changed)
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
