"""
Zeitsteuerung-Ansicht (FA-3301–3308).

Zeigt Wochenprogramme, Tagesprofile, Schaltzeitpunkte, Wochenraster,
Astro-Vorschau und Standorteinstellungen.
"""
from __future__ import annotations
from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem,
    QTabWidget, QComboBox, QCheckBox, QSpinBox,
    QTimeEdit, QDateEdit, QFormLayout, QSplitter, QHeaderView, QAbstractItemView,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QLineEdit, QMessageBox,
    QInputDialog,
)
from PySide6.QtCore import Qt, QTime, QDate, QTimer
from PySide6.QtGui import QBrush, QColor, QStandardItemModel

from ...models.project import KnxProject
from ...models.time_program import (
    TimeProgram, DayProfile, SwitchPoint, WEEKDAY_NAMES, WEEKDAY_SHORT,
)
from ...services.time_program_service import (
    TimeProgramService, holiday_count, missing_target_count, switch_point_time,
)

_COL_SP_TIME     = 0
_COL_SP_DAYS     = 1
_COL_SP_ACTION   = 2
_COL_SP_GA       = 3
_COL_SP_PRIO     = 4
_COL_SP_RANGE    = 5
_SP_COLS = 6

_COL_PROG_NAME = 0
_COL_PROG_SP   = 1

# Einfärbung (FA-3306c) und Wochenraster-Farben je Gewerk-Kategorie (FA-3302c)
_ERROR_BG   = "#FFCDD2"
_WARNING_BG = "#FFF3C4"
_CATEGORY_COLORS = {
    "licht": "#FFF6CC", "licht_color": "#FCE4EC", "jalousie": "#DCEBFF",
    "heizung": "#FFE0D6", "lueftung": "#E0F2F1", "energie": "#E3F5DC",
}
_OTHER_COLOR = "#EEEEEE"


def _iso_to_qdate(text: str) -> QDate:
    try:
        d = date.fromisoformat(text)
        return QDate(d.year, d.month, d.day)
    except ValueError:
        return QDate.currentDate()


class _SwitchPointDialog(QDialog):
    """Dialog zum Anlegen/Bearbeiten eines Schaltzeitpunkts (FA-3302e)."""

    def __init__(self, sp: SwitchPoint, project: KnxProject, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Schaltzeitpunkt")
        self._sp = sp
        self._project = project

        layout = QFormLayout(self)

        # Zeitart
        self._cb_type = QComboBox()
        self._cb_type.addItem("Feste Uhrzeit", "FIXED")
        self._cb_type.addItem("Astro (Sonnenauf-/-untergang)", "ASTRO")
        idx = self._cb_type.findData(sp.time_type)
        if idx >= 0:
            self._cb_type.setCurrentIndex(idx)
        self._cb_type.currentIndexChanged.connect(
            lambda _: self._on_type_changed(self._cb_type.currentData())
        )
        layout.addRow("Zeitart:", self._cb_type)

        # Uhrzeit
        self._te_time = QTimeEdit()
        self._te_time.setDisplayFormat("HH:mm")
        h, m = (int(x) for x in sp.fixed_time.split(":"))
        self._te_time.setTime(QTime(h, m))
        layout.addRow("Uhrzeit (bei fester Zeit):", self._te_time)

        # Astro-Event
        self._cb_astro = QComboBox()
        self._cb_astro.addItem("Sonnenaufgang", "SUNRISE")
        self._cb_astro.addItem("Sonnenuntergang", "SUNSET")
        idx = self._cb_astro.findData(sp.astro_event)
        if idx >= 0:
            self._cb_astro.setCurrentIndex(idx)
        self._cb_astro.currentIndexChanged.connect(self._update_astro_preview)
        layout.addRow("Astro-Ereignis:", self._cb_astro)

        # Offset
        self._sb_offset = QSpinBox()
        self._sb_offset.setRange(-120, 120)
        self._sb_offset.setSuffix(" min")
        self._sb_offset.setValue(sp.astro_offset_min)
        self._sb_offset.valueChanged.connect(self._update_astro_preview)
        layout.addRow("Offset (Astro):", self._sb_offset)

        # Astro-Vorschau für heute (FA-3303c)
        self._astro_preview = QLabel()
        self._astro_preview.setStyleSheet("color: #555; font-style: italic;")
        layout.addRow("", self._astro_preview)

        # Aktionswert
        self._le_value = QLineEdit(sp.action_value)
        self._le_value.setToolTip("z.B. 1/0 für Ein/Aus, 0–100 für Prozent, "
                                  "Szenennummer 1–64")
        layout.addRow("Aktionswert:", self._le_value)

        # Priorität
        self._cb_prio = QComboBox()
        self._cb_prio.addItems(["Normal", "Erhöht"])
        self._cb_prio.setCurrentText(sp.priority)
        layout.addRow("Priorität:", self._cb_prio)

        # GA-Auswahl mit Filter, gruppiert nach HG/MG (FA-3302f)
        self._le_filter = QLineEdit()
        self._le_filter.setPlaceholderText("Filter: Adresse, Bezeichnung, Gewerk oder Raum …")
        self._le_filter.textChanged.connect(self._fill_ga_combo)
        layout.addRow("Gruppenadresse:", self._le_filter)
        self._cb_ga = QComboBox()
        layout.addRow("", self._cb_ga)
        self._selected_ga = sp.target_ga_id
        self._fill_ga_combo()

        # Optionaler Datumsbereich (FA-3302e)
        self._chk_range = QCheckBox("Nur im Zeitraum")
        self._de_from = QDateEdit()
        self._de_to = QDateEdit()
        for edit, value in ((self._de_from, sp.date_range_start),
                            (self._de_to, sp.date_range_end)):
            edit.setDisplayFormat("dd.MM.yyyy")
            edit.setCalendarPopup(True)
            edit.setDate(_iso_to_qdate(value))
        self._chk_range.setChecked(bool(sp.date_range_start or sp.date_range_end))
        self._chk_range.toggled.connect(self._on_range_toggled)
        range_row = QHBoxLayout()
        range_row.addWidget(self._chk_range)
        range_row.addWidget(QLabel("von"))
        range_row.addWidget(self._de_from)
        range_row.addWidget(QLabel("bis"))
        range_row.addWidget(self._de_to)
        layout.addRow("Datumsbereich:", range_row)
        self._on_range_toggled(self._chk_range.isChecked())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._on_type_changed(sp.time_type)

    def _fill_ga_combo(self, *_args):
        current = self._cb_ga.currentData() if self._cb_ga.count() else self._selected_ga
        needle = self._le_filter.text().strip().lower()
        self._cb_ga.blockSignals(True)
        self._cb_ga.clear()
        self._cb_ga.addItem("— keine —", "")
        model: QStandardItemModel = self._cb_ga.model()
        for hg in sorted(self._project.group_addresses.main_groups, key=lambda h: h.number):
            for mg in sorted(hg.middle_groups, key=lambda m: m.number):
                gas = [ga for ga in sorted(mg.group_addresses, key=lambda g: g.sub_group)
                       if not ga.is_placeholder and (not needle or needle in " ".join((
                           ga.address, ga.designation, ga.gewerk_code, ga.room_number,
                       )).lower())]
                if not gas:
                    continue
                self._cb_ga.addItem(f"── HG {hg.number} {hg.name} / MG {mg.number} {mg.name} ──")
                model.item(self._cb_ga.count() - 1).setEnabled(False)
                for ga in gas:
                    self._cb_ga.addItem(f"   {ga.address} {ga.designation}", ga.id)
        idx = self._cb_ga.findData(current) if current else 0
        self._cb_ga.setCurrentIndex(max(idx, 0))
        self._cb_ga.blockSignals(False)

    def _on_range_toggled(self, checked: bool):
        self._de_from.setEnabled(checked)
        self._de_to.setEnabled(checked)

    def _on_type_changed(self, t: str):
        fixed = t == "FIXED"
        self._te_time.setEnabled(fixed)
        self._cb_astro.setEnabled(not fixed)
        self._sb_offset.setEnabled(not fixed)
        self._astro_preview.setVisible(not fixed)
        self._update_astro_preview()

    def _update_astro_preview(self, *_args):
        event = self._cb_astro.currentData()
        offset = self._sb_offset.value()
        base = TimeProgramService.calc_astro(event, date.today(), self._project.location)
        result = TimeProgramService.calc_astro(event, date.today(), self._project.location, offset)
        name = "Sonnenaufgang" if event == "SUNRISE" else "Sonnenuntergang"
        if base and result:
            self._astro_preview.setText(
                f"Heute: {name} {base} {'+' if offset >= 0 else '−'} {abs(offset)} min "
                f"= {result} Uhr")
        else:
            self._astro_preview.setText("Heute: kein Sonnenauf-/-untergang berechenbar")

    def apply_to(self, sp: SwitchPoint):
        sp.time_type = self._cb_type.currentData()
        t = self._te_time.time()
        sp.fixed_time = f"{t.hour():02d}:{t.minute():02d}"
        sp.astro_event = self._cb_astro.currentData()
        sp.astro_offset_min = self._sb_offset.value()
        sp.action_value = self._le_value.text().strip() or "1"
        sp.priority = self._cb_prio.currentText()
        sp.target_ga_id = self._cb_ga.currentData() or ""
        if self._chk_range.isChecked():
            sp.date_range_start = self._de_from.date().toString("yyyy-MM-dd")
            sp.date_range_end = self._de_to.date().toString("yyyy-MM-dd")
        else:
            sp.date_range_start = sp.date_range_end = ""


class _LocationDialog(QDialog):
    """Dialog zur Eingabe des Projektstandorts."""

    def __init__(self, location, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Projektstandort (Astro-Timer)")
        self._location = location

        layout = QFormLayout(self)

        self._sb_lat = QDoubleSpinBox()
        self._sb_lat.setRange(-90.0, 90.0)
        self._sb_lat.setDecimals(4)
        self._sb_lat.setValue(location.latitude)
        layout.addRow("Breitengrad (°N):", self._sb_lat)

        self._sb_lon = QDoubleSpinBox()
        self._sb_lon.setRange(-180.0, 180.0)
        self._sb_lon.setDecimals(4)
        self._sb_lon.setValue(location.longitude)
        layout.addRow("Längengrad (°O):", self._sb_lon)

        self._cb_country = QComboBox()
        self._cb_country.addItems(["CH", "DE", "AT"])
        self._cb_country.setCurrentText(location.country)
        layout.addRow("Land:", self._cb_country)

        self._le_region = QLineEdit(location.region)
        layout.addRow("Region/Kanton:", self._le_region)

        self._le_plz = QLineEdit(location.postal_code)
        layout.addRow("PLZ:", self._le_plz)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def apply_to(self, location):
        location.latitude = self._sb_lat.value()
        location.longitude = self._sb_lon.value()
        location.country = self._cb_country.currentText()
        location.region = self._le_region.text().strip()
        location.postal_code = self._le_plz.text().strip()


class TimeProgramView(QWidget):
    """Hauptansicht für Zeitsteuerung (FA-3301–3308)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._service = TimeProgramService()
        self._current_tp: TimeProgram | None = None
        self._current_dp: DayProfile | None = None

        layout = QVBoxLayout(self)

        # ── Header ─────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Zeitsteuerung")
        title.setObjectName("title")
        hdr.addWidget(title)
        hdr.addStretch()

        btn_location = QPushButton("Standort…")
        btn_location.clicked.connect(self._edit_location)
        hdr.addWidget(btn_location)

        btn_astro_ga = QPushButton("Astro-GAs erzeugen")
        btn_astro_ga.setToolTip("Erstellt fehlende Astro-Gruppenadressen in HG0/MG7")
        btn_astro_ga.clicked.connect(self._ensure_astro_gas)
        hdr.addWidget(btn_astro_ga)

        btn_validate = QPushButton("Validieren")
        btn_validate.clicked.connect(self._validate_all)
        hdr.addWidget(btn_validate)

        layout.addLayout(hdr)

        # ── Astro-Vorschau (FA-3303) ───────────────────────────────────────────
        self._astro_label = QLabel()
        self._astro_label.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(self._astro_label)

        # ── Hinweisbalken: Probleme (FA-3306c), fehlende Ziel-GAs (FA-3305b) ──
        self._banner = QLabel()
        self._banner.setWordWrap(True)
        self._banner.setVisible(False)
        layout.addWidget(self._banner)

        # ── Hauptbereich: Program-Liste + Tabs ─────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # Linke Seite: Programmliste (FA-3302b, FA-3302g)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        lbl_prog = QLabel("Zeitprogramme")
        lbl_prog.setStyleSheet("font-weight: bold;")
        ll.addWidget(lbl_prog)

        self._prog_table = QTableWidget(0, 2)
        self._prog_table.setHorizontalHeaderLabels(["Name", "Schaltpunkte"])
        self._prog_table.verticalHeader().setVisible(False)
        self._prog_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._prog_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._prog_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._prog_table.horizontalHeader().setSectionResizeMode(
            _COL_PROG_NAME, QHeaderView.ResizeMode.Stretch)
        self._prog_table.horizontalHeader().setSectionResizeMode(
            _COL_PROG_SP, QHeaderView.ResizeMode.ResizeToContents)
        self._prog_table.setToolTip("Haken = aktiv. Doppelklick auf den Namen zum Umbenennen.")
        self._prog_table.currentCellChanged.connect(self._on_program_selected)
        self._prog_table.itemChanged.connect(self._on_program_item_changed)
        ll.addWidget(self._prog_table)

        prog_btns = QHBoxLayout()
        btn_add_prog = QPushButton("+ Neu")
        btn_add_prog.clicked.connect(self._add_program)
        btn_dup = QPushButton("Duplizieren")
        btn_dup.clicked.connect(self._duplicate_program)
        btn_del_prog = QPushButton("Löschen")
        btn_del_prog.clicked.connect(self._delete_program)
        prog_btns.addWidget(btn_add_prog)
        prog_btns.addWidget(btn_dup)
        prog_btns.addWidget(btn_del_prog)
        ll.addLayout(prog_btns)
        tmpl_btns = QHBoxLayout()
        btn_tmpl = QPushButton("Aus Vorlage erstellen…")
        btn_tmpl.clicked.connect(self._load_template)
        btn_save_tmpl = QPushButton("Als Vorlage speichern…")
        btn_save_tmpl.setToolTip("Gewähltes Zeitprogramm ohne Ziel-GAs als eigene "
                                 "Vorlage speichern (für alle Projekte)")
        btn_save_tmpl.clicked.connect(self._save_template)
        tmpl_btns.addWidget(btn_tmpl)
        tmpl_btns.addWidget(btn_save_tmpl)
        ll.addLayout(tmpl_btns)

        splitter.addWidget(left)

        # Rechte Seite: Tabs
        right = QTabWidget()
        self._tab_sp = self._build_switchpoint_tab()
        right.addTab(self._tab_sp, "Schaltzeitpunkte")
        self._tab_days = self._build_days_tab()
        right.addTab(self._tab_days, "Wochentage")
        self._tab_week = self._build_week_tab()
        right.addTab(self._tab_week, "Wochenraster")

        splitter.addWidget(right)
        splitter.setSizes([280, 700])

        self._refresh_astro()
        self._refresh_programs()

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _build_switchpoint_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)

        # Tagesprofil-Auswahl
        dp_row = QHBoxLayout()
        dp_row.addWidget(QLabel("Tagesprofil:"))
        self._cb_dp = QComboBox()
        self._cb_dp.currentIndexChanged.connect(self._on_dp_selected)
        dp_row.addWidget(self._cb_dp, stretch=1)
        btn_add_dp = QPushButton("+ Profil")
        btn_add_dp.clicked.connect(self._add_day_profile)
        btn_del_dp = QPushButton("Profil löschen")
        btn_del_dp.clicked.connect(self._delete_day_profile)
        dp_row.addWidget(btn_add_dp)
        dp_row.addWidget(btn_del_dp)
        vl.addLayout(dp_row)

        # Schaltzeitpunkt-Tabelle
        self._sp_table = QTableWidget(0, _SP_COLS)
        self._sp_table.setHorizontalHeaderLabels(
            ["Zeit", "Wochentage", "Wert", "Gruppenadresse", "Priorität", "Zeitraum"]
        )
        self._sp_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._sp_table.horizontalHeader().setSectionResizeMode(
            _COL_SP_GA, QHeaderView.ResizeMode.Stretch
        )
        self._sp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._sp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._sp_table.doubleClicked.connect(self._edit_switch_point)
        vl.addWidget(self._sp_table, stretch=1)

        sp_btns = QHBoxLayout()
        btn_add_sp = QPushButton("+ Schaltzeitpunkt")
        btn_add_sp.clicked.connect(self._add_switch_point)
        btn_edit_sp = QPushButton("Bearbeiten")
        btn_edit_sp.clicked.connect(self._edit_switch_point)
        btn_del_sp = QPushButton("Löschen")
        btn_del_sp.clicked.connect(self._delete_switch_point)
        sp_btns.addWidget(btn_add_sp)
        sp_btns.addWidget(btn_edit_sp)
        sp_btns.addWidget(btn_del_sp)
        sp_btns.addStretch()
        vl.addLayout(sp_btns)

        return w

    def _build_days_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.addWidget(QLabel("Wochentage für das aktuell gewählte Tagesprofil:"))

        self._day_checks: list[QCheckBox] = []
        for i, name in enumerate(WEEKDAY_NAMES):
            cb = QCheckBox(name)
            cb.setProperty("bit_index", i)
            cb.stateChanged.connect(self._on_day_check_changed)
            self._day_checks.append(cb)
            vl.addWidget(cb)

        vl.addStretch()
        return w

    def _build_week_tab(self) -> QWidget:
        """Wochenraster (FA-3302c): Stunden × Wochentage, Einträge nach Gewerk
        der Ziel-GA eingefärbt; Astro-Zeiten für heute."""
        w = QWidget()
        vl = QVBoxLayout(w)
        self._week_table = QTableWidget(24, len(WEEKDAY_SHORT))
        self._week_table.setHorizontalHeaderLabels(WEEKDAY_SHORT)
        self._week_table.setVerticalHeaderLabels([f"{h:02d}:00" for h in range(24)])
        self._week_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._week_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._week_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        vl.addWidget(self._week_table)
        hint = QLabel("Farbe nach Gewerk der Ziel-GA: Licht gelb, Storen blau, "
                      "Heizung rot, Lüftung türkis. Astro-Zeitpunkte mit der Zeit von heute.")
        hint.setStyleSheet("color: #666;")
        hint.setWordWrap(True)
        vl.addWidget(hint)
        return w

    # ── Refresh ───────────────────────────────────────────────────────────────

    def _refresh_astro(self):
        if self._project is None:
            return
        times = self._service.today_astro(self._project)
        loc = self._project.location
        rise = times.get("SUNRISE") or "—"
        sset = times.get("SUNSET") or "—"
        self._astro_label.setText(
            f"Standort: {loc.latitude:.4f}°N / {loc.longitude:.4f}°O ({loc.country}) — "
            f"Heute: Sonnenaufgang {rise}, Sonnenuntergang {sset}"
        )
        # Feiertag mit Anzahl im laufenden Jahr (FA-3304c)
        if self._day_checks:
            year = date.today().year
            count = holiday_count(loc.country, year)
            self._day_checks[-1].setText(f"{WEEKDAY_NAMES[-1]} ({count} Tage in {year})")

    def _refresh_programs(self, select_id: str = ""):
        if self._project is None:
            return
        current_id = select_id or (self._current_tp.id if self._current_tp else "")
        self._prog_table.blockSignals(True)
        self._prog_table.setRowCount(len(self._project.time_programs))
        select_row = -1
        for row, tp in enumerate(self._project.time_programs):
            name = QTableWidgetItem(tp.name)
            name.setData(Qt.ItemDataRole.UserRole, tp.id)
            name.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            name.setCheckState(Qt.CheckState.Checked if tp.active else Qt.CheckState.Unchecked)
            count = QTableWidgetItem(str(tp.switch_point_count))
            count.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
            count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if not tp.active:
                for item in (name, count):
                    item.setForeground(QBrush(QColor("#9E9E9E")))
                name.setToolTip("Inaktiv – Haken setzen zum Aktivieren")
            self._prog_table.setItem(row, _COL_PROG_NAME, name)
            self._prog_table.setItem(row, _COL_PROG_SP, count)
            if tp.id == current_id:
                select_row = row
        self._prog_table.blockSignals(False)
        if select_row >= 0:
            self._prog_table.setCurrentCell(select_row, _COL_PROG_NAME)
        self._refresh_validation()

    def _refresh_dp_combo(self):
        self._cb_dp.blockSignals(True)
        self._cb_dp.clear()
        if self._current_tp:
            for i, dp in enumerate(self._current_tp.day_profiles):
                days = ", ".join(dp.weekdays) or "—"
                self._cb_dp.addItem(f"Profil {i+1}: {days}", i)
        self._cb_dp.blockSignals(False)
        if self._cb_dp.count() > 0:
            self._cb_dp.setCurrentIndex(0)
            self._on_dp_selected(0)
        else:
            self._current_dp = None
            self._refresh_sp_table()
        self._refresh_week()

    def _refresh_sp_table(self):
        self._sp_table.setRowCount(0)
        if not self._current_dp:
            self._refresh_validation()
            return
        days_str = ", ".join(self._current_dp.weekdays)
        # GA-Lookup-Dict einmalig aufbauen statt O(n) pro Schaltzeitpunkt
        ga_by_id = {g.id: g for g in self._project.group_addresses.all_addresses()}
        for sp in self._current_dp.switch_points:
            row = self._sp_table.rowCount()
            self._sp_table.insertRow(row)
            ga_label = ""
            if sp.target_ga_id:
                ga = ga_by_id.get(sp.target_ga_id)
                ga_label = (f"{ga.main_group}/{ga.middle_group}/{ga.sub_group} "
                            f"{ga.designation}") if ga else "(GA nicht gefunden)"
            period = ""
            if sp.date_range_start or sp.date_range_end:
                period = " – ".join(
                    _iso_to_qdate(v).toString("dd.MM.yyyy") if v else "…"
                    for v in (sp.date_range_start, sp.date_range_end))
            self._sp_table.setItem(row, _COL_SP_TIME, QTableWidgetItem(sp.display_time))
            self._sp_table.setItem(row, _COL_SP_DAYS, QTableWidgetItem(days_str))
            self._sp_table.setItem(row, _COL_SP_ACTION, QTableWidgetItem(sp.action_value))
            self._sp_table.setItem(row, _COL_SP_GA, QTableWidgetItem(ga_label))
            self._sp_table.setItem(row, _COL_SP_PRIO, QTableWidgetItem(sp.priority))
            self._sp_table.setItem(row, _COL_SP_RANGE, QTableWidgetItem(period))
            self._sp_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, sp.id)
        self._refresh_validation()

    def _refresh_day_checks(self):
        if not self._current_dp:
            for cb in self._day_checks:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
            return
        mask = self._current_dp.weekday_mask
        for i, cb in enumerate(self._day_checks):
            cb.blockSignals(True)
            cb.setChecked(bool(mask & (1 << i)))
            cb.blockSignals(False)

    def _refresh_week(self):
        """Wochenraster des gewählten Programms neu aufbauen (FA-3302c)."""
        self._week_table.clearContents()
        if not self._current_tp:
            return
        ga_by_id = {g.id: g for g in self._project.group_addresses.all_addresses()}
        catalog = self._project.gewerk_catalog
        cells: dict[tuple[int, int], list[tuple[str, str]]] = {}
        for dp in self._current_tp.day_profiles:
            for sp in dp.switch_points:
                when = switch_point_time(sp, self._project.location)
                if not when:
                    continue
                hour = int(when.split(":")[0])
                ga = ga_by_id.get(sp.target_ga_id)
                gewerk = catalog.get(ga.gewerk_code) if ga and ga.gewerk_code else None
                color = _CATEGORY_COLORS.get(gewerk.category if gewerk else "", _OTHER_COLOR)
                target = ga.designation.split(" (")[0] if ga else "ohne GA"
                text = f"{when} → {sp.action_value}  {target}"
                for day in range(len(WEEKDAY_SHORT)):
                    if dp.weekday_mask & (1 << day):
                        cells.setdefault((hour, day), []).append((text, color))
        for (hour, day), entries in cells.items():
            entries.sort()
            item = QTableWidgetItem("\n".join(text for text, _ in entries))
            item.setBackground(QBrush(QColor(entries[0][1])))
            item.setToolTip("\n".join(text for text, _ in entries))
            self._week_table.setItem(hour, day, item)

    def _refresh_validation(self):
        """Schaltzeitpunkte mit Fehlern rot, mit Warnungen gelb; Hinweisbalken
        mit der Gesamtzahl und fehlenden Ziel-GAs (FA-3306c, FA-3305b)."""
        if self._project is None:
            return
        problems = self._service.validate_all(self._project)
        by_sp: dict[str, str] = {}
        for p in problems:
            if p.sp_id and by_sp.get(p.sp_id) != "error":
                by_sp[p.sp_id] = p.severity
        for row in range(self._sp_table.rowCount()):
            first = self._sp_table.item(row, 0)
            level = by_sp.get(first.data(Qt.ItemDataRole.UserRole) if first else "")
            color = _ERROR_BG if level == "error" else _WARNING_BG if level else None
            tips = [p.message for p in problems
                    if first and p.sp_id == first.data(Qt.ItemDataRole.UserRole)]
            for col in range(self._sp_table.columnCount()):
                item = self._sp_table.item(row, col)
                if item:
                    item.setBackground(QBrush(QColor(color)) if color else QBrush())
                    item.setToolTip("\n".join(tips))

        parts = []
        n_err = sum(1 for p in problems if p.severity == "error")
        n_warn = len(problems) - n_err
        if problems:
            parts.append(f"Zeitsteuerung: {n_err} Fehler, {n_warn} Warnung(en) – "
                         "«Validieren» zeigt die Einzelheiten.")
        missing = missing_target_count(self._current_tp) if self._current_tp else 0
        if missing:
            parts.append(f"{missing} Schaltzeitpunkt(e) haben noch keine Ziel-GA – bitte zuweisen.")
        self._banner.setText("\n".join(parts))
        bg = _ERROR_BG if n_err else _WARNING_BG
        self._banner.setStyleSheet(f"background: {bg}; padding: 6px; border-radius: 3px;")
        self._banner.setVisible(bool(parts))

    # ── Event-Handler ─────────────────────────────────────────────────────────

    def _on_program_selected(self, row, _col=0, _prev_row=-1, _prev_col=-1):
        item = self._prog_table.item(row, _COL_PROG_NAME) if row >= 0 else None
        if item is None:
            self._current_tp = None
        else:
            tp_id = item.data(Qt.ItemDataRole.UserRole)
            self._current_tp = self._service.get_program(self._project, tp_id)
        self._refresh_dp_combo()
        self._refresh_validation()

    def _on_program_item_changed(self, item: QTableWidgetItem):
        """Umbenennen per Doppelklick und aktiv/inaktiv per Haken (FA-3302g)."""
        if item.column() != _COL_PROG_NAME:
            return
        tp = self._service.get_program(self._project, item.data(Qt.ItemDataRole.UserRole))
        if tp is None:
            return
        name = item.text().strip()
        active = item.checkState() == Qt.CheckState.Checked
        if name and name != tp.name or active != tp.active:
            tp.name = name or tp.name
            tp.active = active
            # Neu aufbauen erst nach diesem Signal: die Zeile, die es gerade
            # sendet, würde sonst mitten im Aufruf gelöscht
            QTimer.singleShot(0, lambda: self._refresh_programs(select_id=tp.id))

    def _on_dp_selected(self, idx: int):
        if self._current_tp and 0 <= idx < len(self._current_tp.day_profiles):
            self._current_dp = self._current_tp.day_profiles[idx]
        else:
            self._current_dp = None
        self._refresh_sp_table()
        self._refresh_day_checks()

    def _on_day_check_changed(self):
        if not self._current_dp:
            return
        mask = 0
        for cb in self._day_checks:
            if cb.isChecked():
                mask |= 1 << cb.property("bit_index")
        self._current_dp.weekday_mask = mask
        self._refresh_dp_combo()

    # ── Programm CRUD ─────────────────────────────────────────────────────────

    def _add_program(self):
        tp = self._service.add_program(self._project)
        self._service.add_day_profile(tp)
        self._refresh_programs(select_id=tp.id)

    def _duplicate_program(self):
        if not self._current_tp:
            return
        tp = self._service.duplicate_program(self._project, self._current_tp)
        self._refresh_programs(select_id=tp.id)

    def _load_template(self):
        templates = self._service.list_templates()
        if not templates:
            QMessageBox.information(self, "Vorlagen", "Keine Vorlagen gefunden.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Aus Vorlage erstellen")
        vl = QVBoxLayout(dlg)
        cb = QComboBox()
        for t in templates:
            label = t.get("name", t["id"]) + (" (eigene)" if t.get("user") else "")
            cb.addItem(label, t["id"])
        vl.addWidget(QLabel("Vorlage auswählen:"))
        vl.addWidget(cb)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        vl.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            tid = cb.currentData()
            tp = self._service.add_from_template(self._project, tid)
            if tp:
                self._refresh_programs(select_id=tp.id)

    def _save_template(self):
        """Eigene Vorlage aus dem gewählten Programm (FA-3305c)."""
        if not self._current_tp:
            return
        name, ok = QInputDialog.getText(
            self, "Als Vorlage speichern",
            "Name der Vorlage (gleicher Name ersetzt eine eigene Vorlage):",
            text=self._current_tp.name)
        if not ok or not name.strip():
            return
        try:
            self._service.save_template(self._current_tp, name)
        except OSError as exc:
            QMessageBox.critical(self, "Vorlage nicht gespeichert", str(exc))
            return
        QMessageBox.information(
            self, "Vorlage gespeichert",
            f"Vorlage «{name.strip()}» gespeichert. Ziel-GAs werden beim Erstellen "
            "aus der Vorlage leer gelassen.")

    def _delete_program(self):
        if not self._current_tp:
            return
        self._service.remove_program(self._project, self._current_tp.id)
        self._current_tp = None
        self._refresh_programs()
        self._refresh_dp_combo()

    # ── Tagesprofil CRUD ──────────────────────────────────────────────────────

    def _add_day_profile(self):
        if not self._current_tp:
            return
        self._service.add_day_profile(self._current_tp)
        self._refresh_dp_combo()

    def _delete_day_profile(self):
        if not self._current_tp or not self._current_dp:
            return
        idx = self._cb_dp.currentIndex()
        if 0 <= idx < len(self._current_tp.day_profiles):
            self._current_tp.day_profiles.pop(idx)
        self._current_dp = None
        self._refresh_dp_combo()

    # ── Schaltzeitpunkt CRUD ──────────────────────────────────────────────────

    def _add_switch_point(self):
        if not self._current_dp:
            return
        sp = SwitchPoint()
        dlg = _SwitchPointDialog(sp, self._project, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply_to(sp)
            self._current_dp.switch_points.append(sp)
            self._after_switch_points_changed()

    def _edit_switch_point(self):
        row = self._sp_table.currentRow()
        if row < 0 or not self._current_dp:
            return
        sp_id = self._sp_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        sp = next((s for s in self._current_dp.switch_points if s.id == sp_id), None)
        if sp is None:
            return
        dlg = _SwitchPointDialog(sp, self._project, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply_to(sp)
            self._after_switch_points_changed()

    def _delete_switch_point(self):
        row = self._sp_table.currentRow()
        if row < 0 or not self._current_dp:
            return
        sp_id = self._sp_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._service.remove_switch_point(self._current_dp, sp_id)
        self._after_switch_points_changed()

    def _after_switch_points_changed(self):
        self._refresh_sp_table()
        self._refresh_week()
        self._refresh_programs()   # Anzahl Schaltpunkte in der Liste

    # ── Standort & Astro ──────────────────────────────────────────────────────

    def _edit_location(self):
        dlg = _LocationDialog(self._project.location, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply_to(self._project.location)
            self._refresh_astro()
            self._refresh_week()

    def _ensure_astro_gas(self):
        n = self._service.ensure_astro_gas(self._project)
        QMessageBox.information(
            self, "Astro-GAs",
            f"{n} neue Astro-Gruppenadresse(n) in HG0/MG7 angelegt."
            if n else "Alle Astro-Gruppen­adressen bereits vorhanden."
        )

    # ── Validierung ───────────────────────────────────────────────────────────

    def _validate_all(self):
        errors = self._service.validate_all(self._project)
        self._refresh_validation()
        if not errors:
            QMessageBox.information(self, "Validierung", "Keine Fehler gefunden.")
            return
        lines = [f"[{e.severity.upper()}] {e.program_name}: {e.message}"
                 for e in errors]
        QMessageBox.warning(self, "Validierung", "\n".join(lines))

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def set_project(self, project: KnxProject):
        self._project = project
        self._current_tp = None
        self._current_dp = None
        self._refresh_astro()
        self._refresh_programs()
        self._refresh_dp_combo()

    def refresh(self):
        self._refresh_astro()
        self._refresh_programs()
        if self._current_tp:
            self._refresh_dp_combo()
