"""
Zeitsteuerung-Ansicht (FA-3301–3308).

Zeigt Wochenprogramme, Tagesprofile, Schaltzeitpunkte,
Astro-Vorschau und Standorteinstellungen.
"""
from __future__ import annotations
from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QTabWidget, QGroupBox, QComboBox, QCheckBox, QSpinBox,
    QTimeEdit, QFormLayout, QSplitter, QHeaderView, QAbstractItemView,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QLineEdit, QMessageBox,
    QScrollArea,
)
from PySide6.QtCore import Qt, QTime

from ...models.project import KnxProject
from ...models.time_program import (
    TimeProgram, DayProfile, SwitchPoint,
    WEEKDAY_MON, WEEKDAY_TUE, WEEKDAY_WED, WEEKDAY_THU, WEEKDAY_FRI,
    WEEKDAY_SAT, WEEKDAY_SUN, WEEKDAY_HOL,
    WEEKDAY_SHORT, WEEKDAY_NAMES,
)
from ...services.time_program_service import TimeProgramService

_COL_SP_TIME     = 0
_COL_SP_DAYS     = 1
_COL_SP_ACTION   = 2
_COL_SP_GA       = 3
_COL_SP_PRIO     = 4
_SP_COLS = 5


class _SwitchPointDialog(QDialog):
    """Dialog zum Anlegen/Bearbeiten eines Schaltzeitpunkts."""

    def __init__(self, sp: SwitchPoint, project: KnxProject, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Schaltzeitpunkt")
        self._sp = sp
        self._project = project

        layout = QFormLayout(self)

        # Zeitart
        self._cb_type = QComboBox()
        self._cb_type.addItems(["FIXED", "ASTRO"])
        self._cb_type.setCurrentText(sp.time_type)
        self._cb_type.currentTextChanged.connect(self._on_type_changed)
        layout.addRow("Zeitart:", self._cb_type)

        # Uhrzeit
        self._te_time = QTimeEdit()
        self._te_time.setDisplayFormat("HH:mm")
        h, m = (int(x) for x in sp.fixed_time.split(":"))
        self._te_time.setTime(QTime(h, m))
        layout.addRow("Uhrzeit (FIXED):", self._te_time)

        # Astro-Event
        self._cb_astro = QComboBox()
        self._cb_astro.addItems(["SUNRISE", "SUNSET"])
        self._cb_astro.setCurrentText(sp.astro_event)
        layout.addRow("Astro-Ereignis:", self._cb_astro)

        # Offset
        self._sb_offset = QSpinBox()
        self._sb_offset.setRange(-120, 120)
        self._sb_offset.setSuffix(" min")
        self._sb_offset.setValue(sp.astro_offset_min)
        layout.addRow("Offset (Astro):", self._sb_offset)

        # Aktionswert
        self._le_value = QLineEdit(sp.action_value)
        layout.addRow("Aktionswert:", self._le_value)

        # Priorität
        self._cb_prio = QComboBox()
        self._cb_prio.addItems(["Normal", "Erhöht"])
        self._cb_prio.setCurrentText(sp.priority)
        layout.addRow("Priorität:", self._cb_prio)

        # GA-Auswahl
        self._cb_ga = QComboBox()
        self._cb_ga.addItem("— keine —", "")
        for ga in project.group_addresses.all_addresses():
            label = f"{ga.main_group}/{ga.middle_group}/{ga.sub_group} {ga.designation}"
            self._cb_ga.addItem(label, ga.id)
        idx = self._cb_ga.findData(sp.target_ga_id)
        if idx >= 0:
            self._cb_ga.setCurrentIndex(idx)
        layout.addRow("Gruppenadresse:", self._cb_ga)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._on_type_changed(sp.time_type)

    def _on_type_changed(self, t: str):
        fixed = t == "FIXED"
        self._te_time.setEnabled(fixed)
        self._cb_astro.setEnabled(not fixed)
        self._sb_offset.setEnabled(not fixed)

    def apply_to(self, sp: SwitchPoint):
        sp.time_type = self._cb_type.currentText()
        t = self._te_time.time()
        sp.fixed_time = f"{t.hour():02d}:{t.minute():02d}"
        sp.astro_event = self._cb_astro.currentText()
        sp.astro_offset_min = self._sb_offset.value()
        sp.action_value = self._le_value.text().strip() or "1"
        sp.priority = self._cb_prio.currentText()
        sp.target_ga_id = self._cb_ga.currentData() or ""


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
        title = QLabel("<b>Zeitsteuerung</b>")
        title.setStyleSheet("font-size: 14px;")
        hdr.addWidget(title)
        hdr.addStretch()

        btn_location = QPushButton("Standort…")
        btn_location.clicked.connect(self._edit_location)
        hdr.addWidget(btn_location)

        btn_astro_ga = QPushButton("Astro-GAs erzeugen")
        btn_astro_ga.setToolTip("Erstellt fehlende Astro-Gruppenadressn in HG0/MG7 (FA-3308)")
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

        # ── Hauptbereich: Program-Liste + Tabs ─────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # Linke Seite: Programmliste
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)

        lbl_prog = QLabel("Zeitprogramme")
        lbl_prog.setStyleSheet("font-weight: bold;")
        ll.addWidget(lbl_prog)

        self._prog_list = QListWidget()
        self._prog_list.currentItemChanged.connect(self._on_program_selected)
        ll.addWidget(self._prog_list)

        prog_btns = QHBoxLayout()
        btn_add_prog = QPushButton("+ Neu")
        btn_add_prog.clicked.connect(self._add_program)
        btn_tmpl = QPushButton("Vorlage…")
        btn_tmpl.clicked.connect(self._load_template)
        btn_del_prog = QPushButton("Löschen")
        btn_del_prog.clicked.connect(self._delete_program)
        prog_btns.addWidget(btn_add_prog)
        prog_btns.addWidget(btn_tmpl)
        prog_btns.addWidget(btn_del_prog)
        ll.addLayout(prog_btns)

        splitter.addWidget(left)

        # Rechte Seite: Tabs
        right = QTabWidget()

        # Tab: Tagesprofile + Schaltzeitpunkte
        self._tab_sp = self._build_switchpoint_tab()
        right.addTab(self._tab_sp, "Schaltzeitpunkte")

        # Tab: Wochentage (Bitmaske)
        self._tab_days = self._build_days_tab()
        right.addTab(self._tab_days, "Wochentage")

        splitter.addWidget(right)
        splitter.setSizes([240, 700])

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
            ["Zeit", "Wochentage", "Wert", "Gruppenadresse", "Priorität"]
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

    def _refresh_programs(self):
        if self._project is None:
            return
        self._prog_list.blockSignals(True)
        self._prog_list.clear()
        for tp in self._project.time_programs:
            label = f"{'✓' if tp.active else '○'} {tp.name} ({tp.switch_point_count} SP)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, tp.id)
            self._prog_list.addItem(item)
        self._prog_list.blockSignals(False)

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

    def _refresh_sp_table(self):
        self._sp_table.setRowCount(0)
        if not self._current_dp:
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
                            f"{ga.designation}") if ga else sp.target_ga_id
            self._sp_table.setItem(row, _COL_SP_TIME, QTableWidgetItem(sp.display_time))
            self._sp_table.setItem(row, _COL_SP_DAYS, QTableWidgetItem(days_str))
            self._sp_table.setItem(row, _COL_SP_ACTION, QTableWidgetItem(sp.action_value))
            self._sp_table.setItem(row, _COL_SP_GA, QTableWidgetItem(ga_label))
            self._sp_table.setItem(row, _COL_SP_PRIO, QTableWidgetItem(sp.priority))
            self._sp_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, sp.id)

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

    # ── Event-Handler ─────────────────────────────────────────────────────────

    def _on_program_selected(self, current, _prev):
        if current is None:
            self._current_tp = None
        else:
            tp_id = current.data(Qt.ItemDataRole.UserRole)
            self._current_tp = self._service.get_program(self._project, tp_id)
        self._refresh_dp_combo()

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
        self._refresh_programs()

    def _load_template(self):
        templates = self._service.list_templates()
        if not templates:
            QMessageBox.information(self, "Vorlagen", "Keine Vorlagen gefunden.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Vorlage laden")
        vl = QVBoxLayout(dlg)
        cb = QComboBox()
        for t in templates:
            cb.addItem(t.get("name", t["id"]), t["id"])
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
                self._refresh_programs()

    def _delete_program(self):
        item = self._prog_list.currentItem()
        if not item:
            return
        tp_id = item.data(Qt.ItemDataRole.UserRole)
        self._service.remove_program(self._project, tp_id)
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
            self._refresh_sp_table()

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
            self._refresh_sp_table()

    def _delete_switch_point(self):
        row = self._sp_table.currentRow()
        if row < 0 or not self._current_dp:
            return
        sp_id = self._sp_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._service.remove_switch_point(self._current_dp, sp_id)
        self._refresh_sp_table()

    # ── Standort & Astro ──────────────────────────────────────────────────────

    def _edit_location(self):
        dlg = _LocationDialog(self._project.location, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply_to(self._project.location)
            self._refresh_astro()

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
