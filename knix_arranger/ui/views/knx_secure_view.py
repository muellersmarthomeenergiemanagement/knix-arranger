"""
KNX Secure Archivansicht (FA-2701, überarbeitet).

Dokumentiert die beiden einzigen Geheimnisse, die im gesamten Projekt
tatsächlich Bestand haben und nicht rekonstruierbar sind, falls sie
verloren gehen:
- FDSK/Zertifikat je Gerät (ab Werk mitgeliefert)
- ETS6-Projektpasswort (ohne dieses ist das ETS6-Projekt nicht wiederherstellbar)

KNiX Arranger generiert und verwaltet KEINE KNX-Secure-Laufzeitschlüssel --
diese kennt und erzeugt ausschliesslich ETS6 aus dem FDSK. Die sensiblen
Felder werden mit einem selbstgewählten Master-Passwort verschlüsselt
gespeichert (siehe KnxSecureService).
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton,
    QTableWidget, QTableWidgetItem, QGroupBox, QTabWidget, QHeaderView,
    QAbstractItemView, QMessageBox, QComboBox, QLineEdit, QFormLayout,
    QSplitter, QInputDialog, QTextEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from ...models.project import KnxProject
from ...models.knx_secure import (
    KnxSecureConfig, GA_SECURITY_MODES, SECURE_MODES, SECURE_MODE_LABELS,
    is_valid_knx_key,
)
from ...services.knx_secure_service import KnxSecureService, KnxSecureWrongPassword
from ..column_utils import fit_columns

_COL_DEV_NAME   = 0
_COL_DEV_ADDR   = 1
_COL_DEV_LINE   = 2
_COL_DEV_SECURE = 3
_COL_DEV_FDSK   = 4
_DEV_COLS = 5

_COL_GA_ADDR  = 0
_COL_GA_NAME  = 1
_COL_GA_FUNC  = 2
_COL_GA_SEC   = 3
_GA_COLS = 4


class KnxSecureView(QWidget):
    """Hauptansicht für das KNX-Secure-Archiv (FA-2701)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._service = KnxSecureService()

        layout = QVBoxLayout(self)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("<b>KNX Secure – Zertifikats- und Zugangsdaten-Archiv</b>")
        title.setStyleSheet("font-size: 14px;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._lock_status = QLabel("")
        hdr.addWidget(self._lock_status)

        self._btn_unlock = QPushButton("🔒 Entsperren…")
        self._btn_unlock.clicked.connect(self._on_unlock_clicked)
        hdr.addWidget(self._btn_unlock)

        self._btn_validate = QPushButton("Archiv validieren…")
        self._btn_validate.clicked.connect(self._validate_config)
        hdr.addWidget(self._btn_validate)

        layout.addLayout(hdr)

        info = QLabel(
            "KNiX Arranger generiert und verwaltet KEINE KNX-Secure-Laufzeitschlüssel -- "
            "diese erzeugt ausschliesslich die ETS6 aus dem geräteindividuellen Zertifikat "
            "(FDSK). Dieses Modul archiviert nur, was tatsächlich unwiederbringlich verloren "
            "geht, wenn es nicht dokumentiert wird: das FDSK-Zertifikat je Gerät und das "
            "ETS6-Projektpasswort. Diese Werte werden mit einem selbstgewählten "
            "Master-Passwort verschlüsselt gespeichert -- geht dieses verloren, sind auch "
            "die archivierten Werte nicht wiederherstellbar."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # ── Aktivierungsschalter + Sicherheitsmodus ───────────────────────────
        enable_box = QGroupBox("KNX Secure aktivieren")
        enable_layout = QFormLayout()

        self._enable_check = QCheckBox("KNX Secure für dieses Projekt aktivieren (FA-2701)")
        self._enable_check.toggled.connect(self._on_enable_toggled)
        enable_layout.addRow("Aktiviert:", self._enable_check)

        self._mode_combo = QComboBox()
        for mode in SECURE_MODES:
            self._mode_combo.addItem(SECURE_MODE_LABELS[mode], userData=mode)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._mode_combo.setToolTip(
            "KNX Data Secure: Sicherheit auf TP-Ebene (medienunabhängig).\n"
            "KNX IP Secure: Sicherheit auf IP-Ebene (Backbone Key für Routing).\n"
            "Beide: Vollständige Absicherung TP + IP."
        )
        enable_layout.addRow("Sicherheitsmodus:", self._mode_combo)

        enable_box.setLayout(enable_layout)
        layout.addWidget(enable_box)

        # ── Tabs ──────────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_access_tab(), "Zugangsdaten (ETS6-Passwort)")
        self._tabs.addTab(self._build_ga_tab(), "GA-Sicherheit (FA-2703)")
        self._tabs.addTab(self._build_devices_tab(), "Gerätekompatibilität / FDSK (FA-2704)")
        self._tabs.addTab(self._build_warnings_tab(), "Mischlinien-Warnungen (FA-2705)")
        layout.addWidget(self._tabs, 1)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def set_project(self, project: KnxProject):
        self._project = project
        self.refresh()

    def refresh(self):
        cfg = self._project.knx_secure
        self._enable_check.setChecked(cfg.enabled)
        idx = self._mode_combo.findData(cfg.secure_mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        self._tabs.setEnabled(cfg.enabled)
        self._update_lock_status()
        self._populate_access_tab(cfg)
        self._populate_ga_tab()
        self._populate_devices_tab(cfg)
        self._populate_warnings_tab(cfg)

    def _update_lock_status(self):
        cfg = self._project.knx_secure
        if cfg.is_locked:
            self._lock_status.setText("🔒 Archiv gesperrt")
            self._lock_status.setStyleSheet("color: #C62828; font-weight: bold;")
            self._btn_unlock.setVisible(True)
        elif cfg._session_password:
            self._lock_status.setText("🔓 Archiv entsperrt")
            self._lock_status.setStyleSheet("color: #2E7D32;")
            self._btn_unlock.setVisible(False)
        else:
            self._lock_status.setText("Kein Master-Passwort gesetzt")
            self._lock_status.setStyleSheet("color: #9E9E9E;")
            self._btn_unlock.setVisible(False)

    def _on_enable_toggled(self, checked: bool):
        self._project.knx_secure.enabled = checked
        self._tabs.setEnabled(checked)

    def _on_mode_changed(self, _index: int):
        mode = self._mode_combo.currentData()
        if mode:
            self._project.knx_secure.secure_mode = mode

    # ── Passwort-Sperre ───────────────────────────────────────────────────────

    def _on_unlock_clicked(self):
        self._ensure_unlocked(silent_if_ready=False)

    def _ensure_unlocked(self, silent_if_ready: bool = True) -> bool:
        """Stellt sicher, dass sensible Felder bearbeitet/angezeigt werden können.

        - Archiv bereits entsperrt oder Master-Passwort schon gesetzt: True.
        - Archiv gesperrt (verschlüsselte Daten vorhanden): Passwort abfragen
          und entschlüsseln.
        - Noch nie verschlüsselt: neues Master-Passwort festlegen (mit
          Bestätigung).
        Gibt False zurück, wenn der Nutzer abbricht oder das Passwort falsch ist.
        """
        cfg = self._project.knx_secure
        if cfg._session_password and not cfg.is_locked:
            return True

        if cfg.is_locked:
            password, ok = QInputDialog.getText(
                self, "Archiv entsperren",
                "Master-Passwort für das KNX-Secure-Archiv:",
                QLineEdit.Password,
            )
            if not ok or not password:
                return False
            try:
                unlocked = KnxSecureService.unlock(cfg, password)
            except KnxSecureWrongPassword:
                QMessageBox.warning(
                    self, "Falsches Passwort",
                    "Das eingegebene Master-Passwort ist falsch."
                )
                return False
            self._project.knx_secure = unlocked
            self.refresh()
            return True

        # Noch nie verschlüsselt -- neues Master-Passwort festlegen
        pw1, ok1 = QInputDialog.getText(
            self, "Master-Passwort festlegen",
            "Neues Master-Passwort für dieses KNX-Secure-Archiv:",
            QLineEdit.Password,
        )
        if not ok1 or not pw1:
            return False
        pw2, ok2 = QInputDialog.getText(
            self, "Master-Passwort bestätigen",
            "Master-Passwort wiederholen:",
            QLineEdit.Password,
        )
        if not ok2 or pw1 != pw2:
            QMessageBox.warning(self, "Nicht übereinstimmend",
                                "Die eingegebenen Passwörter stimmen nicht überein.")
            return False
        QMessageBox.information(
            self, "Master-Passwort gesetzt",
            "Das Master-Passwort wird NICHT im Projekt gespeichert.\n\n"
            "Bewahren Sie es getrennt vom Projekt auf (z. B. Passwort-Manager). "
            "Geht es verloren, sind die archivierten Werte nicht wiederherstellbar."
        )
        KnxSecureService.unlock(cfg, pw1)
        self._update_lock_status()
        return True

    # ── Zugangsdaten-Tab ──────────────────────────────────────────────────────

    def _build_access_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        warn = QLabel(
            "<b>ETS6-Projektpasswort:</b> Schützt das ETS6-Projekt selbst. Ohne dieses "
            "Passwort kann NIEMAND mehr auf das Projekt zugreifen -- auch KNX/der "
            "Hersteller können es nicht zurücksetzen oder wiederherstellen."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #B71C1C;")
        layout.addWidget(warn)

        form = QFormLayout()

        self._ets_pw_edit = QLineEdit()
        self._ets_pw_edit.setEchoMode(QLineEdit.Password)
        self._ets_pw_edit.setPlaceholderText("ETS6-Projektpasswort")
        self._ets_pw_edit.editingFinished.connect(self._on_ets_password_edited)
        form.addRow("ETS6-Projektpasswort:", self._ets_pw_edit)

        self._btn_show_pw = QPushButton("Anzeigen")
        self._btn_show_pw.setCheckable(True)
        self._btn_show_pw.toggled.connect(self._on_toggle_show_password)
        form.addRow("", self._btn_show_pw)

        self._note_edit = QTextEdit()
        self._note_edit.setPlaceholderText(
            "z. B. Hinterlegungsort des Passworts (Tresor, Passwort-Manager, "
            "Ansprechperson) und Wiederherstellungsplan"
        )
        self._note_edit.setMaximumHeight(100)
        self._note_edit.textChanged.connect(self._on_note_edited)
        form.addRow("Notiz / Wiederherstellungsplan:", self._note_edit)

        layout.addLayout(form)
        layout.addStretch()
        return w

    def _populate_access_tab(self, cfg: KnxSecureConfig):
        blocked = cfg.is_locked
        self._ets_pw_edit.blockSignals(True)
        self._ets_pw_edit.setText(cfg.ets_project_password)
        self._ets_pw_edit.setEnabled(not blocked)
        self._ets_pw_edit.blockSignals(False)

        self._note_edit.blockSignals(True)
        self._note_edit.setPlainText(cfg.ets_password_note)
        self._note_edit.setEnabled(not blocked)
        self._note_edit.blockSignals(False)

    def _on_toggle_show_password(self, checked: bool):
        self._ets_pw_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        self._btn_show_pw.setText("Verbergen" if checked else "Anzeigen")

    def _on_ets_password_edited(self):
        new_value = self._ets_pw_edit.text()
        cfg = self._project.knx_secure
        if new_value == cfg.ets_project_password:
            return
        if not self._ensure_unlocked():
            self._ets_pw_edit.setText(self._project.knx_secure.ets_project_password)
            return
        self._project.knx_secure.ets_project_password = new_value
        self._update_lock_status()

    def _on_note_edited(self):
        cfg = self._project.knx_secure
        new_value = self._note_edit.toPlainText()
        if new_value == cfg.ets_password_note:
            return
        if not self._ensure_unlocked():
            self._note_edit.blockSignals(True)
            self._note_edit.setPlainText(cfg.ets_password_note)
            self._note_edit.blockSignals(False)
            return
        self._project.knx_secure.ets_password_note = new_value

    # ── GA-Sicherheits-Tab ────────────────────────────────────────────────────

    def _build_ga_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel(
            "KNX-Standard erlaubt Mischinstallationen (Secure + Non-Secure GAs). "
            "Der Auto-Vorschlag setzt nur explizit sicherheitsrelevante GAs auf 'Ein'."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self._btn_auto_suggest = QPushButton("Auto-Vorschlag anwenden")
        self._btn_auto_suggest.setToolTip(
            "Setzt GA-Security auf 'Ein' für sicherheitsrelevante GAs "
            "(Schalten, Szenen, Zentralfunktionen, Sperren, Alarm)"
        )
        self._btn_auto_suggest.clicked.connect(self._auto_suggest_security)
        btn_row.addWidget(self._btn_auto_suggest)

        self._btn_all_on = QPushButton("Alle auf 'Ein'")
        self._btn_all_on.clicked.connect(lambda: self._set_all_ga_security("Ein"))
        btn_row.addWidget(self._btn_all_on)

        self._btn_all_auto = QPushButton("Alle auf 'Auto'")
        self._btn_all_auto.clicked.connect(lambda: self._set_all_ga_security("Auto"))
        btn_row.addWidget(self._btn_all_auto)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._ga_table = QTableWidget()
        self._ga_table.setColumnCount(_GA_COLS)
        self._ga_table.setHorizontalHeaderLabels(["Adresse", "Bezeichnung", "Funktion", "Security"])
        self._ga_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._ga_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._ga_table)
        return w

    def _populate_ga_tab(self):
        all_gas = list(self._project.group_addresses.all_addresses())
        self._ga_table.setRowCount(len(all_gas))
        for i, ga in enumerate(all_gas):
            self._ga_table.setItem(i, _COL_GA_ADDR, QTableWidgetItem(ga.address))
            self._ga_table.setItem(i, _COL_GA_NAME, QTableWidgetItem(ga.designation or ga.description))
            self._ga_table.setItem(i, _COL_GA_FUNC, QTableWidgetItem(ga.function_name))

            combo = QComboBox()
            combo.addItems(GA_SECURITY_MODES)
            idx = combo.findText(ga.security)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.currentTextChanged.connect(
                lambda text, g=ga: setattr(g, "security", text)
            )
            self._ga_table.setCellWidget(i, _COL_GA_SEC, combo)

            if ga.security == "Ein":
                for col in range(_GA_COLS - 1):
                    item = self._ga_table.item(i, col)
                    if item:
                        item.setForeground(QColor("#1565C0"))
        fit_columns(self._ga_table)

    def _auto_suggest_security(self):
        n = self._service.auto_suggest_ga_security(self._project)
        self._populate_ga_tab()
        QMessageBox.information(self, "GA-Sicherheit",
                                f"{n} GA(s) auf 'Ein' gesetzt.")

    def _set_all_ga_security(self, mode: str):
        for ga in self._project.group_addresses.all_addresses():
            ga.security = mode
        self._populate_ga_tab()

    # ── Gerätekompatibilitäts-Tab ─────────────────────────────────────────────

    def _build_devices_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        fdsk_info = QLabel(
            "<b>FDSK (Factory Default Setup Key):</b> Geräteindividuelles Zertifikat, "
            "ab Werk mit dem Gerät mitgeliefert (Aufkleber/QR-Code/Zertifikatskarte). "
            "ETS6 leitet daraus einmalig die eigentlichen Laufzeitschlüssel ab -- "
            "KNiX Arranger kann diesen Wert nicht generieren, nur archivieren. "
            "Doppelklick auf FDSK-Spalte zum Eingeben."
        )
        fdsk_info.setWordWrap(True)
        layout.addWidget(fdsk_info)

        btn_row = QHBoxLayout()
        self._btn_refresh_compat = QPushButton("Kompatibilität prüfen")
        self._btn_refresh_compat.setToolTip(
            "Aktualisiert Secure-Flags anhand der Topologie-Gerätedaten"
        )
        self._btn_refresh_compat.clicked.connect(self._refresh_compatibility)
        btn_row.addWidget(self._btn_refresh_compat)

        self._btn_refresh_from_mat = QPushButton("Secure-Flags aus Materialliste")
        self._btn_refresh_from_mat.setToolTip(
            "Liest KNX Secure-Unterstützung aus den KNXPROD-Produktdaten\n"
            "der Materialliste (benötigt KNXPROD-Import mit Secure-Daten) (FA-2705)"
        )
        self._btn_refresh_from_mat.clicked.connect(self._refresh_from_material_list)
        btn_row.addWidget(self._btn_refresh_from_mat)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._dev_table = QTableWidget()
        self._dev_table.setColumnCount(_DEV_COLS)
        self._dev_table.setHorizontalHeaderLabels([
            "Gerätename", "Phys. Adresse", "Linie", "KNX Secure", "FDSK"
        ])
        self._dev_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._dev_table.horizontalHeader().setStretchLastSection(True)
        self._dev_table.cellDoubleClicked.connect(self._on_dev_table_double_click)
        layout.addWidget(self._dev_table)

        legend = QLabel(
            "Rot = Gerät unterstützt kein KNX Secure. "
            "FDSK-Spalte: Doppelklick zum manuellen Eingeben des FDSK vom Zertifikat/Geräteetikett."
        )
        legend.setWordWrap(True)
        layout.addWidget(legend)

        return w

    def _populate_devices_tab(self, cfg: KnxSecureConfig):
        infos = list(cfg.device_infos.values())
        self._dev_table.setRowCount(len(infos))
        locked = cfg.is_locked
        for i, info in enumerate(infos):
            line_label = ""
            for area in self._project.topology.areas:
                for line in area.lines:
                    if line.id == info.line_id:
                        line_label = f"{area.area_number}.{line.line_number}"
                        break

            self._dev_table.setItem(i, _COL_DEV_NAME, QTableWidgetItem(info.device_name))
            self._dev_table.setItem(i, _COL_DEV_ADDR, QTableWidgetItem(info.physical_address))
            self._dev_table.setItem(i, _COL_DEV_LINE, QTableWidgetItem(line_label))

            sec_item = QTableWidgetItem("Ja" if info.secure_supported else "Nein")
            if not info.secure_supported:
                sec_item.setForeground(QColor("#C62828"))
            self._dev_table.setItem(i, _COL_DEV_SECURE, sec_item)

            if locked:
                fdsk_display = "🔒 gesperrt"
            else:
                fdsk_display = (info.fdsk[:8] + "…") if info.fdsk else "– eingeben"
            fdsk_item = QTableWidgetItem(fdsk_display)
            if not info.fdsk:
                fdsk_item.setForeground(QColor("#9E9E9E"))
            self._dev_table.setItem(i, _COL_DEV_FDSK, fdsk_item)

        fit_columns(self._dev_table)

    def _on_dev_table_double_click(self, row: int, col: int):
        """FDSK manuell eingeben via Doppelklick auf FDSK-Spalte."""
        if col != _COL_DEV_FDSK:
            return
        if not self._ensure_unlocked():
            return
        infos = list(self._project.knx_secure.device_infos.values())
        if row >= len(infos):
            return
        info = infos[row]
        current = info.fdsk or ""
        text, ok = QInputDialog.getText(
            self,
            f"FDSK eingeben – {info.device_name}",
            "FDSK (32 Hex-Zeichen, vom Zertifikat / QR-Code):",
            QLineEdit.Normal,
            current,
        )
        if not ok:
            return
        text = text.strip().upper().replace(" ", "").replace("-", "")
        if text and not is_valid_knx_key(text):
            QMessageBox.warning(
                self, "Ungültiger FDSK",
                "Der FDSK muss genau 32 Hex-Zeichen enthalten (0–9, A–F)."
            )
            return
        info.fdsk = text
        self._populate_devices_tab(self._project.knx_secure)

    def _refresh_compatibility(self):
        self._service.update_device_compatibility(
            self._project.knx_secure, self._project
        )
        self._populate_devices_tab(self._project.knx_secure)

    # ── Mischlinien-Warnungen-Tab ─────────────────────────────────────────────

    def _build_warnings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel(
            "Eine Linie mit gemischten Secure/Non-Secure-Geräten kompromittiert "
            "die Sicherheit aller Geräte in dieser Linie (FA-2705)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self._btn_check_mixed = QPushButton("Mischlinien prüfen")
        self._btn_check_mixed.clicked.connect(self._check_mixed)
        btn_row.addWidget(self._btn_check_mixed)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._warnings_table = QTableWidget()
        self._warnings_table.setColumnCount(4)
        self._warnings_table.setHorizontalHeaderLabels([
            "Linie", "Secure-Geräte", "Non-Secure-Geräte", "Meldung"
        ])
        self._warnings_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._warnings_table)
        return w

    def _populate_warnings_tab(self, cfg: KnxSecureConfig):
        warnings = self._service.check_mixed_lines(cfg, self._project)
        self._warnings_table.setRowCount(len(warnings))
        for i, w in enumerate(warnings):
            self._warnings_table.setItem(
                i, 0, QTableWidgetItem(f"{w.area_number}.{w.line_number} {w.line_name}")
            )
            self._warnings_table.setItem(i, 1, QTableWidgetItem(", ".join(w.secure_devices)))
            self._warnings_table.setItem(i, 2, QTableWidgetItem(", ".join(w.non_secure_devices)))
            msg_item = QTableWidgetItem(w.message)
            msg_item.setForeground(QColor("#B71C1C"))
            self._warnings_table.setItem(i, 3, msg_item)
        fit_columns(self._warnings_table)

    def _check_mixed(self):
        self._service.update_device_compatibility(
            self._project.knx_secure, self._project
        )
        self._populate_warnings_tab(self._project.knx_secure)

    def _refresh_from_material_list(self):
        """Aktualisiert Secure-Flags aus den KNXPROD-Produktdaten der Materialliste (FA-2705)."""
        mat_list = self._project.material_list
        if not mat_list or not mat_list.entries:
            QMessageBox.information(
                self, "Materialliste leer",
                "Die Materialliste enthält keine Einträge.\n\n"
                "Importieren Sie zuerst Produktdaten via KNXPROD-Import."
            )
            return

        secure_map: dict[str, bool] = {}
        for entry in mat_list.entries:
            if entry.device_id:
                secure_map[entry.device_id] = entry.secure_supported

        cfg = self._project.knx_secure
        updated = 0
        for area in self._project.topology.areas:
            for line in area.lines:
                for dev in line.devices:
                    if dev.id in secure_map:
                        if dev.id in cfg.device_infos:
                            cfg.device_infos[dev.id].secure_supported = secure_map[dev.id]
                            updated += 1

        self._populate_devices_tab(cfg)

        secure_count = sum(1 for d in cfg.device_infos.values() if d.secure_supported)
        total = len(cfg.device_infos)
        QMessageBox.information(
            self, "Secure-Flags aktualisiert",
            f"{updated} Gerät(e) aus Materialliste aktualisiert.\n"
            f"KNX Secure-fähig: {secure_count} von {total} Geräten."
        )

    def _validate_config(self):
        """Validiert das KNX-Secure-Archiv auf Vollständigkeit (FA-2706)."""
        cfg = self._project.knx_secure

        if not cfg.enabled:
            QMessageBox.information(
                self, "KNX Secure nicht aktiv",
                "KNX Secure ist für dieses Projekt nicht aktiviert.\n\n"
                "Aktivieren Sie KNX Secure über den Schalter oben."
            )
            return

        summary = self._service.get_summary(cfg, self._project)
        warnings = self._service.check_mixed_lines(cfg, self._project)

        mode_label = SECURE_MODE_LABELS.get(summary.get("secure_mode", ""), "–")

        lines = [
            f"Modus: {mode_label}",
            "",
            f"{'🔒' if summary.get('locked') else '✓'} Archiv-Status: "
            f"{'gesperrt (Passwort erforderlich)' if summary.get('locked') else 'entsperrt/lesbar'}",
            f"{'✓' if summary.get('ets_password_set') else '⚠'} ETS6-Projektpasswort: "
            f"{'hinterlegt' if summary.get('ets_password_set') else 'FEHLT'}",
            f"✓ KNX Secure-fähige Geräte: "
            f"{summary.get('secure_devices', 0)} / {summary.get('device_infos_count', 0)}",
            f"{'✓' if summary.get('fdsk_entered', 0) > 0 else '⚠'} FDSK-Zertifikate erfasst: "
            f"{summary.get('fdsk_entered', 0)} / {summary.get('device_infos_count', 0)}",
            f"✓ GAs mit Security 'Ein': {summary.get('ga_security_on', 0)}",
            "",
            f"{'⚠' if warnings else '✓'} Mischlinien-Warnungen: {len(warnings)}",
        ]

        if warnings:
            lines.append("\nBetroffene Linien:")
            for w in warnings[:5]:
                lines.append(f"  • {w.area_number}.{w.line_number} {w.line_name}: {w.message}")
            if len(warnings) > 5:
                lines.append(f"  … und {len(warnings) - 5} weitere")

        issues = []
        if not summary.get("ets_password_set") and not summary.get("locked"):
            issues.append("ETS6-Projektpasswort ist nicht hinterlegt")
        if summary.get("fdsk_entered", 0) == 0 and summary.get("device_infos_count", 0) > 0:
            issues.append("Keine FDSK-Zertifikate erfasst")

        if issues or warnings:
            QMessageBox.warning(self, "⚠ Archiv unvollständig", "\n".join(lines))
        else:
            QMessageBox.information(
                self, "✓ KNX Secure Archiv OK",
                "\n".join(lines) + "\n\nDas Archiv ist vollständig."
            )
