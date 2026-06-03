"""
KNX Secure Konfigurationsansicht (FA-2701).

Ermöglicht die Verwaltung von KNX Secure Schlüsseln, GA-Sicherheitsmodi
und zeigt Gerätekompatibilitätsinformationen an.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton,
    QTableWidget, QTableWidgetItem, QGroupBox, QTabWidget, QHeaderView,
    QAbstractItemView, QMessageBox, QComboBox, QLineEdit, QFormLayout,
    QSplitter, QInputDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from ...models.project import KnxProject
from ...models.knx_secure import (
    KnxSecureConfig, GA_SECURITY_MODES, SECURE_MODES, SECURE_MODE_LABELS,
    is_valid_knx_key,
)
from ...services.knx_secure_service import KnxSecureService
from ..column_utils import fit_columns

_COL_DEV_NAME   = 0
_COL_DEV_ADDR   = 1
_COL_DEV_LINE   = 2
_COL_DEV_SECURE = 3
_COL_DEV_FDSK   = 4
_COL_DEV_TKEY   = 5
_DEV_COLS = 6

_COL_GA_ADDR  = 0
_COL_GA_NAME  = 1
_COL_GA_FUNC  = 2
_COL_GA_SEC   = 3
_GA_COLS = 4

_COL_GAKEY_ADDR = 0
_COL_GAKEY_KEY  = 1
_GAKEY_COLS = 3


class KnxSecureView(QWidget):
    """Hauptansicht für KNX Secure (FA-2701)."""

    def __init__(self, project: KnxProject, parent=None):
        super().__init__(parent)
        self._project = project
        self._service = KnxSecureService()
        self._building_view = None

        layout = QVBoxLayout(self)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("<b>KNX Secure Konfiguration</b>")
        title.setStyleSheet("font-size: 14px;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._btn_validate = QPushButton("Konfiguration validieren…")
        self._btn_validate.setToolTip(
            "Prüft alle KNX Secure Einstellungen auf Vollständigkeit und Konsistenz (FA-2706)"
        )
        self._btn_validate.clicked.connect(self._validate_config)
        hdr.addWidget(self._btn_validate)

        layout.addLayout(hdr)

        info = QLabel(
            "KNX Secure sichert die Kommunikation auf dem KNX-Bus durch AES-128-CCM-Verschlüsselung "
            "(KNX Data Secure: EN 50090-3-4 | KNX IP Secure: ISO 22510 | Kryptographie: ISO 18033-3)."
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
        self._tabs.addTab(self._build_keys_tab(), "Schlüssel (FA-2702)")
        self._tabs.addTab(self._build_ga_tab(), "GA-Sicherheit (FA-2703)")
        self._tabs.addTab(self._build_devices_tab(), "Gerätekompatibilität (FA-2704/2705)")
        self._tabs.addTab(self._build_warnings_tab(), "Mischlinien-Warnungen (FA-2705)")
        layout.addWidget(self._tabs, 1)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def set_project(self, project: KnxProject):
        self._project = project
        self.refresh()

    def refresh(self):
        cfg = self._project.knx_secure
        self._enable_check.setChecked(cfg.enabled)
        # Sicherheitsmodus setzen
        idx = self._mode_combo.findData(cfg.secure_mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        self._tabs.setEnabled(cfg.enabled)
        self._populate_keys_tab(cfg)
        self._populate_ga_tab()
        self._populate_devices_tab(cfg)
        self._populate_warnings_tab(cfg)

    def _on_enable_toggled(self, checked: bool):
        self._project.knx_secure.enabled = checked
        self._tabs.setEnabled(checked)

    def _on_mode_changed(self, _index: int):
        mode = self._mode_combo.currentData()
        if mode:
            self._project.knx_secure.secure_mode = mode

    # ── Schlüssel-Tab ─────────────────────────────────────────────────────────

    def _build_keys_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Projektschlüssel
        proj_box = QGroupBox("Projektweite Schlüssel")
        form = QFormLayout()

        self._backbone_edit = QLineEdit()
        self._backbone_edit.setPlaceholderText("32 Hex-Zeichen (128 bit) – KNX IP Secure")
        self._backbone_edit.setReadOnly(True)
        self._backbone_edit.setToolTip(
            "Backbone Key: gemeinsamer Schlüssel für KNX IP Secure Routing\n"
            "(Multicast 224.0.23.12). Wird von ETS generiert."
        )
        form.addRow("Backbone Key:", self._backbone_edit)

        self._group_key_edit = QLineEdit()
        self._group_key_edit.setPlaceholderText("32 Hex-Zeichen (128 bit) – Standard Runtime Key")
        self._group_key_edit.setReadOnly(True)
        self._group_key_edit.setToolTip(
            "Group Key: Standard-Laufzeitschlüssel für alle GAs ohne eigenen GA Key.\n"
            "Via Tool Key verschlüsselt an Geräte übertragen."
        )
        form.addRow("Group Key:", self._group_key_edit)

        proj_box.setLayout(form)
        layout.addWidget(proj_box)

        btn_row = QHBoxLayout()
        self._btn_gen_all = QPushButton("Alle Schlüssel generieren")
        self._btn_gen_all.setToolTip("Erzeugt fehlende AES-128 Schlüssel für alle Ebenen")
        self._btn_gen_all.clicked.connect(self._generate_all_keys)
        btn_row.addWidget(self._btn_gen_all)

        self._btn_regen_backbone = QPushButton("Backbone Key erneuern")
        self._btn_regen_backbone.clicked.connect(lambda: self._regen_key("backbone_key"))
        btn_row.addWidget(self._btn_regen_backbone)

        self._btn_regen_group = QPushButton("Group Key erneuern")
        self._btn_regen_group.clicked.connect(lambda: self._regen_key("group_key"))
        btn_row.addWidget(self._btn_regen_group)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # GA Runtime Keys (ersetzt nicht-standardkonformes Linienschlüssel-Konzept)
        ga_key_label = QLabel(
            "GA Runtime Keys – individuelle Laufzeitschlüssel pro Gruppenadresse:"
        )
        ga_key_label.setToolTip(
            "Laufzeitschlüssel werden via Tool Key verschlüsselt an Geräte übertragen.\n"
            "Ersetzt das frühere Linienschlüssel-Konzept (kein KNX-Standard)."
        )
        layout.addWidget(ga_key_label)

        self._ga_key_table = QTableWidget()
        self._ga_key_table.setColumnCount(_GAKEY_COLS)
        self._ga_key_table.setHorizontalHeaderLabels(["GA-Adresse", "Runtime Key", ""])
        self._ga_key_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._ga_key_table)

        return w

    def _populate_keys_tab(self, cfg: KnxSecureConfig):
        self._backbone_edit.setText(cfg.backbone_key)
        self._group_key_edit.setText(cfg.group_key)

        all_gas = list(self._project.group_addresses.all_addresses())
        rows = []
        for ga in all_gas:
            addr = ga.address
            if addr:
                key = cfg.ga_keys.get(addr, "")
                rows.append((addr, key))

        self._ga_key_table.setRowCount(len(rows))
        for i, (addr, key) in enumerate(rows):
            self._ga_key_table.setItem(i, _COL_GAKEY_ADDR, QTableWidgetItem(addr))
            display_key = (key[:8] + "…" + key[-4:]) if len(key) == 32 else key
            self._ga_key_table.setItem(i, _COL_GAKEY_KEY, QTableWidgetItem(display_key))
            btn = QPushButton("Erneuern")
            btn.clicked.connect(lambda checked, a=addr: self._regen_ga_key(a))
            self._ga_key_table.setCellWidget(i, 2, btn)
        fit_columns(self._ga_key_table)

    def _generate_all_keys(self):
        n = self._service.generate_all_project_keys(
            self._project.knx_secure, self._project
        )
        self._populate_keys_tab(self._project.knx_secure)
        self._populate_devices_tab(self._project.knx_secure)
        QMessageBox.information(self, "Schlüssel generiert",
                                f"{n} neue AES-128-Schlüssel generiert.")

    def _regen_key(self, key_type: str):
        self._service.regenerate_key(self._project.knx_secure, key_type)
        self._populate_keys_tab(self._project.knx_secure)

    def _regen_ga_key(self, ga_address: str):
        self._service.regenerate_key(
            self._project.knx_secure, "ga_key", scope_id=ga_address
        )
        self._populate_keys_tab(self._project.knx_secure)

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
            "<b>FDSK (Factory Default Setup Key):</b> Geräteindividueller Schlüssel, "
            "ab Werk aufgedruckt (QR-Code oder alphanumerisch). Wird einmalig verwendet, "
            "um den Tool Key verschlüsselt zu übertragen – niemals über den Bus gesendet. "
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
            "Gerätename", "Phys. Adresse", "Linie", "KNX Secure", "FDSK", "Tool Key"
        ])
        self._dev_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._dev_table.horizontalHeader().setStretchLastSection(True)
        self._dev_table.cellDoubleClicked.connect(self._on_dev_table_double_click)
        layout.addWidget(self._dev_table)

        legend = QLabel(
            "Rot = Gerät unterstützt kein KNX Secure. "
            "FDSK-Spalte: Doppelklick zum manuellen Eingeben des FDSK vom Geräteetikett."
        )
        legend.setWordWrap(True)
        layout.addWidget(legend)

        return w

    def _populate_devices_tab(self, cfg: KnxSecureConfig):
        infos = list(cfg.device_infos.values())
        self._dev_table.setRowCount(len(infos))
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

            fdsk_display = (info.fdsk[:8] + "…") if info.fdsk else "– eingeben"
            fdsk_item = QTableWidgetItem(fdsk_display)
            if not info.fdsk:
                fdsk_item.setForeground(QColor("#9E9E9E"))
            self._dev_table.setItem(i, _COL_DEV_FDSK, fdsk_item)

            tkey_display = (info.tool_key[:8] + "…") if info.tool_key else ""
            self._dev_table.setItem(i, _COL_DEV_TKEY, QTableWidgetItem(tkey_display))

        fit_columns(self._dev_table)

    def _on_dev_table_double_click(self, row: int, col: int):
        """FDSK manuell eingeben via Doppelklick auf FDSK-Spalte."""
        if col != _COL_DEV_FDSK:
            return
        infos = list(self._project.knx_secure.device_infos.values())
        if row >= len(infos):
            return
        info = infos[row]
        current = info.fdsk or ""
        text, ok = QInputDialog.getText(
            self,
            f"FDSK eingeben – {info.device_name}",
            "FDSK (32 Hex-Zeichen, vom Geräteetikett / QR-Code):",
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
        """Validiert die vollständige KNX Secure Konfiguration (FA-2706)."""
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
        needs_backbone = summary.get("secure_mode") in ("ip_secure", "both")

        lines = [
            f"Modus: {mode_label}",
            "",
            f"{'✓' if summary.get('backbone_key_set') else ('✗' if needs_backbone else '–')} "
            f"Backbone Key: {'gesetzt' if summary.get('backbone_key_set') else 'FEHLT' if needs_backbone else 'nicht benötigt (Data Secure)'}",
            f"{'✓' if summary.get('group_key_set') else '✗'} Group Key: "
            f"{'gesetzt' if summary.get('group_key_set') else 'FEHLT'}",
            f"✓ GA Runtime Keys: {summary.get('ga_keys_count', 0)} gesetzt",
            f"✓ KNX Secure-Geräte: "
            f"{summary.get('secure_devices', 0)} / {summary.get('device_infos_count', 0)}",
            f"{'✓' if summary.get('fdsk_entered', 0) > 0 else '⚠'} FDSKs eingegeben: "
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
        if not summary.get("group_key_set"):
            issues.append("Group Key fehlt")
        if needs_backbone and not summary.get("backbone_key_set"):
            issues.append("Backbone Key fehlt (für IP Secure benötigt)")
        if summary.get("fdsk_entered", 0) == 0 and summary.get("device_infos_count", 0) > 0:
            issues.append("Keine FDSKs eingegeben – Tool Key-Übertragung nicht möglich")

        if issues or warnings:
            QMessageBox.warning(self, "⚠ Konfiguration unvollständig", "\n".join(lines))
        else:
            QMessageBox.information(
                self, "✓ KNX Secure Konfiguration OK",
                "\n".join(lines) + "\n\nDie KNX Secure Konfiguration ist vollständig."
            )
