"""
KNiX Arranger – Lizenz-Manager (GUI)
Lizenzdateien erstellen und verwalten.

Ausfuehren:
    python tools/lizenz_manager.py
"""
import os
import sys
import csv
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QComboBox,
    QSpinBox, QHeaderView, QFileDialog, QMessageBox, QLineEdit,
    QGroupBox, QFormLayout, QAbstractItemView, QFrame, QCheckBox,
    QInputDialog, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

CSV_PATH  = Path(__file__).parent / "betatester.csv"
OUT_DIR   = Path(__file__).parent / "lizenzen"

GREEN      = "#2e7d32"
DARK_GREEN = "#1b5e20"
LIGHT_GREEN= "#e8f5e9"


class LizenzManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KNiX Arranger – Lizenz-Manager")
        # Mindestbreite so, dass die Aktionszeile unten vollständig lesbar ist;
        # Startgrösse passt auch auf einen Laptop mit 1280x720
        self.setMinimumSize(900, 600)
        self.resize(1100, 680)
        self.setStyleSheet(f"""
            QMainWindow {{ background: #f4f6f8; }}
            QPushButton {{
                padding: 6px 16px; border-radius: 4px;
                font-size: 13px;
            }}
            QPushButton#primary {{
                background: {GREEN}; color: white; font-weight: bold;
            }}
            QPushButton#primary:hover {{ background: {DARK_GREEN}; }}
            QPushButton#secondary {{
                background: white; color: #333;
                border: 1px solid #ccc;
            }}
            QPushButton#secondary:hover {{ background: #f0f0f0; }}
            QTableWidget {{ background: white; gridline-color: #e0e0e0; }}
            QHeaderView::section {{
                background: {LIGHT_GREEN}; font-weight: bold;
                padding: 6px; border: none; border-bottom: 1px solid #ccc;
            }}
            QGroupBox {{
                font-weight: bold; color: {DARK_GREEN};
                border: 1px solid #c8e6c9; border-radius: 6px;
                margin-top: 8px; padding-top: 8px;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; }}
        """)

        # Inhalt in einem Bildlaufbereich: bei kleinem Fenster erscheint eine
        # Bildlaufleiste, statt dass Buttons und Texte gestaucht werden. Die
        # Aktionszeile unten (bottom_layout) bleibt fest sichtbar.
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self.setCentralWidget(outer)

        central = QWidget()
        scroll = QScrollArea()
        scroll.setWidget(central)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer_layout.addWidget(scroll, 1)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 0, 16, 12)
        bottom_layout.setSpacing(8)
        outer_layout.addWidget(bottom)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Titel
        title = QLabel("KNiX Arranger  –  Lizenz-Manager")
        title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {DARK_GREEN};")
        layout.addWidget(title)

        # Eingabe-Bereich
        input_group = QGroupBox("Neuen Lizenznehmer hinzufügen")
        form = QFormLayout(input_group)
        form.setSpacing(8)

        self._name_input  = QLineEdit()
        self._name_input.setPlaceholderText("z.B. Max Muster")
        self._email_input = QLineEdit()
        self._email_input.setPlaceholderText("z.B. max@muster.ch")

        self._type_combo = QComboBox()
        self._type_combo.addItems(["Testlizenz (30 Tage)", "Jahreslizenz (365 Tage)", "Einzellizenz (unbegrenzt)"])

        self._anrede_combo = QComboBox()
        self._anrede_combo.addItems(["Sie", "Du"])

        add_btn = QPushButton("+ Hinzufügen")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_row)
        self._name_input.returnPressed.connect(self._add_row)
        self._email_input.returnPressed.connect(self._add_row)

        form.addRow("Name:", self._name_input)
        form.addRow("E-Mail:", self._email_input)
        form.addRow("Lizenztyp:", self._type_combo)
        form.addRow("Anrede:", self._anrede_combo)
        form.addRow("", add_btn)
        layout.addWidget(input_group)

        # Tabelle
        table_group = QGroupBox("Lizenznehmer")
        table_layout = QVBoxLayout(table_group)

        hint = QLabel(
            "Nur angehakte Zeilen werden bei «Lizenzen generieren» verarbeitet "
            "(Lizenzdatei erstellt und ggf. Outlook-Entwurf geöffnet)."
        )
        hint.setStyleSheet("color: #555; font-size: 12px;")
        hint.setWordWrap(True)
        table_layout.addWidget(hint)

        self._table = QTableWidget(0, 5)
        self._table.setMinimumHeight(170)  # Kopfzeile + mind. drei Lizenznehmer
        self._table.setHorizontalHeaderLabels(["", "Name", "E-Mail", "Lizenztyp", "Anrede"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        # Name/E-Mail-Aenderungen direkt in der Tabelle sofort speichern
        self._loading = False
        self._table.itemChanged.connect(self._on_item_changed)
        table_layout.addWidget(self._table)

        row_btns = QHBoxLayout()
        del_btn = QPushButton("Zeile entfernen")
        del_btn.setObjectName("secondary")
        del_btn.clicked.connect(self._remove_row)
        import_btn = QPushButton("CSV importieren…")
        import_btn.setObjectName("secondary")
        import_btn.clicked.connect(self._import_csv)
        select_all_btn = QPushButton("Alle auswählen")
        select_all_btn.setObjectName("secondary")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        select_none_btn = QPushButton("Keine auswählen")
        select_none_btn.setObjectName("secondary")
        select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        row_btns.addWidget(del_btn)
        row_btns.addWidget(import_btn)
        row_btns.addWidget(select_all_btn)
        row_btns.addWidget(select_none_btn)
        row_btns.addStretch()
        table_layout.addLayout(row_btns)
        layout.addWidget(table_group)

        # Aktionen
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #ddd;")
        bottom_layout.addWidget(sep)

        # Statusmeldung in eigener Zeile, damit sie die Buttons nicht verdrängt
        self._status = QLabel("")
        self._status.setStyleSheet("color: #555; font-size: 12px;")
        self._status.setWordWrap(True)
        bottom_layout.addWidget(self._status)

        action_row = QHBoxLayout()

        self._outlook_checkbox = QCheckBox("Danach Outlook-Entwurf öffnen")
        self._outlook_checkbox.setChecked(True)
        self._outlook_checkbox.setToolTip(
            "Öffnet pro Lizenznehmer eine vorausgefüllte E-Mail (mit Lizenzdatei\n"
            "und GitHub-Download-Link als Anhang/Text) in MS Outlook zur Kontrolle.\n"
            "Versand erfolgt manuell durch Klick auf «Senden» in Outlook."
        )
        action_row.addWidget(self._outlook_checkbox)
        action_row.addStretch()

        open_btn = QPushButton("Ausgabeordner öffnen")
        open_btn.setObjectName("secondary")
        open_btn.clicked.connect(self._open_out_dir)
        action_row.addWidget(open_btn)

        resend_btn = QPushButton("Bestehende Lizenz erneut senden…")
        resend_btn.setObjectName("secondary")
        resend_btn.setToolTip(
            "Öffnet einen Outlook-Entwurf für eine bereits erstellte .knxlic-Datei,\n"
            "ohne die Lizenz neu zu generieren (Ablaufdatum bleibt unverändert)."
        )
        resend_btn.clicked.connect(self._resend_existing_license)
        action_row.addWidget(resend_btn)

        gen_btn = QPushButton("Lizenzen generieren")
        gen_btn.setObjectName("primary")
        gen_btn.setMinimumWidth(180)
        gen_btn.clicked.connect(self._generate)
        action_row.addWidget(gen_btn)

        bottom_layout.addLayout(action_row)

        self._load_csv()

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def _add_row(self):
        name  = self._name_input.text().strip()
        email = self._email_input.text().strip()
        if not name or not email:
            self._set_status("Bitte Name und E-Mail eingeben.", error=True)
            return

        ltype = self._type_combo.currentText()
        anrede = self._anrede_combo.currentText()
        # Neu hinzugefuegte Zeile automatisch anhaken -- das ist im Regelfall
        # genau die eine Person, fuer die man gerade eine Lizenz erstellen will,
        # waehrend bereits vorhandene/importierte Zeilen unangehakt bleiben.
        self._insert_row(name, email, ltype, anrede, checked=True)
        self._name_input.clear()
        self._email_input.clear()
        self._name_input.setFocus()
        self._save_csv()
        self._set_status(f"{name} hinzugefügt.")

    def _insert_row(self, name, email, ltype, anrede="Sie", checked=False):
        # Waehrend des Aufbaus keine Zwischenstaende speichern
        was_loading, self._loading = self._loading, True
        try:
            self._fill_new_row(name, email, ltype, anrede, checked)
        finally:
            self._loading = was_loading

    def _fill_new_row(self, name, email, ltype, anrede, checked):
        row = self._table.rowCount()
        self._table.insertRow(row)

        check_item = QTableWidgetItem()
        check_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        check_item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._table.setItem(row, 0, check_item)

        self._table.setItem(row, 1, QTableWidgetItem(name))
        self._table.setItem(row, 2, QTableWidgetItem(email))
        combo = QComboBox()
        combo.addItems(["Testlizenz (30 Tage)", "Jahreslizenz (365 Tage)", "Einzellizenz (unbegrenzt)"])
        idx = combo.findText(ltype)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(self._on_row_changed)
        self._table.setCellWidget(row, 3, combo)

        anrede_combo = QComboBox()
        anrede_combo.addItems(["Sie", "Du"])
        a_idx = anrede_combo.findText(anrede)
        anrede_combo.setCurrentIndex(a_idx if a_idx >= 0 else 0)
        anrede_combo.currentIndexChanged.connect(self._on_row_changed)
        self._table.setCellWidget(row, 4, anrede_combo)

    def _on_row_changed(self, *_):
        """Lizenztyp/Anrede geaendert -> sofort in die CSV schreiben."""
        if not self._loading:
            self._save_csv()

    def _on_item_changed(self, item):
        # Spalte 0 (Checkbox) wird bewusst nicht gespeichert
        if item.column() != 0:
            self._on_row_changed()

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 0)
            if item:
                item.setCheckState(state)

    def _remove_row(self):
        row = self._table.currentRow()
        if row >= 0:
            name = self._table.item(row, 1).text() if self._table.item(row, 1) else ""
            self._table.removeRow(row)
            self._save_csv()
            self._set_status(f"{name} entfernt.")

    def _generate(self):
        from key_generator import generate_license
        OUT_DIR.mkdir(exist_ok=True)

        rows = self._table.rowCount()
        if rows == 0:
            self._set_status("Keine Einträge vorhanden.", error=True)
            return

        selected_rows = [
            r for r in range(rows)
            if self._table.item(r, 0) and self._table.item(r, 0).checkState() == Qt.Checked
        ]
        if not selected_rows:
            self._set_status(
                "Keine Lizenznehmer ausgewählt – bitte die gewünschten Zeilen ankreuzen.",
                error=True,
            )
            return

        ok = 0
        errors = []
        created = []  # (name, email, out_path, formal, renewal, valid_until) fuer Outlook-Entwuerfe
        for r in selected_rows:
            name  = self._table.item(r, 1).text().strip() if self._table.item(r, 1) else ""
            email = self._table.item(r, 2).text().strip() if self._table.item(r, 2) else ""
            combo = self._table.cellWidget(r, 3)
            ltype_text = combo.currentText() if combo else "Testlizenz (30 Tage)"
            anrede_combo = self._table.cellWidget(r, 4)
            formal = (anrede_combo.currentText() if anrede_combo else "Sie") == "Sie"

            if not name or not email:
                errors.append(f"Zeile {r+1}: Name oder E-Mail fehlt")
                continue

            type_map  = {"Testlizenz (30 Tage)": "trial",
                         "Jahreslizenz (365 Tage)": "annual",
                         "Einzellizenz (unbegrenzt)": "single"}
            days_map  = {"Testlizenz (30 Tage)": 30,
                         "Jahreslizenz (365 Tage)": 365,
                         "Einzellizenz (unbegrenzt)": 36500}
            ltype     = type_map.get(ltype_text, "trial")
            days      = days_map.get(ltype_text, 30)

            safe = name.replace(" ", "_").replace("/", "-")[:30]
            expiry = (datetime.today() + timedelta(days=days)).strftime("%Y-%m-%d")
            out_path = str(OUT_DIR / f"{safe}_{expiry}.knxlic")

            # Gibt es schon eine Lizenzdatei dieser Person, ist es eine Erneuerung
            # (eigener Mailtext). Alte Dateien werden dabei entfernt.
            renewal = False
            for old in OUT_DIR.glob(f"{safe}_*.knxlic"):
                renewal = True
                if str(old) != out_path:
                    old.unlink()
            valid_until = None if ltype == "single" else (
                datetime.today() + timedelta(days=days)).strftime("%d.%m.%Y")

            try:
                generate_license(name, email, ltype, days, out_path)
                ok += 1
                created.append((name, email, out_path, formal, renewal, valid_until))
            except Exception as e:
                errors.append(f"{name}: {e}")

        if errors:
            QMessageBox.warning(self, "Fehler", "\n".join(errors))

        if ok:
            self._set_status(f"{ok} Lizenzdatei(en) erstellt in {OUT_DIR}/")
            QMessageBox.information(self, "Fertig",
                f"{ok} Lizenzdatei(en) wurden erstellt.\n\nOrdner: {OUT_DIR}")
            if self._outlook_checkbox.isChecked():
                self._open_outlook_drafts(created)
        else:
            self._set_status("Keine Lizenzen erstellt.", error=True)

    def _open_outlook_drafts(self, entries):
        """Oeffnet pro Lizenznehmer einen vorausgefuellten Outlook-Entwurf."""
        if not entries:
            return
        try:
            from outlook_mail import create_license_draft
        except ImportError:
            QMessageBox.warning(
                self, "Outlook nicht verfügbar",
                "pywin32 ist nicht installiert (pip install pywin32).\n"
                "Outlook-Entwürfe wurden übersprungen."
            )
            return

        mail_errors = []
        for name, email, out_path, formal, renewal, valid_until in entries:
            try:
                create_license_draft(
                    name, email, out_path, display=True, formal=formal,
                    renewal=renewal, valid_until=valid_until,
                )
            except Exception as e:
                mail_errors.append(f"{name}: {e}")

        if mail_errors:
            QMessageBox.warning(
                self, "Outlook-Fehler",
                "Bei folgenden Einträgen konnte kein Outlook-Entwurf erstellt "
                "werden (ist MS Outlook installiert und ein Profil eingerichtet?):\n\n"
                + "\n".join(mail_errors)
            )
        else:
            self._set_status(
                f"{len(entries)} Outlook-Entwurf/-Entwürfe geöffnet. Nach «Senden» "
                "erscheint hier die Versandbestätigung."
            )
            self._start_mail_watch(len(entries))

    def _resend_existing_license(self):
        """Oeffnet einen Outlook-Entwurf fuer eine bereits erstellte .knxlic-Datei,
        OHNE eine neue Lizenz zu generieren -- Ablaufdatum und Inhalt der Datei
        bleiben unveraendert. Name/E-Mail werden direkt aus der Lizenzdatei
        gelesen (nicht aus der Tabelle), damit das auch nach Entfernen der
        Zeile oder fuer Lizenzen ausserhalb der aktuellen CSV funktioniert."""
        OUT_DIR.mkdir(exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "Bestehende Lizenzdatei wählen", str(OUT_DIR), "KNiX Lizenz (*.knxlic)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)["payload"]
            customer = payload["customer"]
            email = payload["email"]
        except Exception as e:
            QMessageBox.warning(
                self, "Fehler",
                f"Lizenzdatei konnte nicht gelesen werden:\n{e}"
            )
            return

        anrede, ok = QInputDialog.getItem(
            self, "Anrede wählen", f"Anrede für {customer}:", ["Sie", "Du"], 0, False
        )
        if not ok:
            return

        try:
            from outlook_mail import create_license_draft
        except ImportError:
            QMessageBox.warning(
                self, "Outlook nicht verfügbar",
                "pywin32 ist nicht installiert (pip install pywin32)."
            )
            return

        try:
            create_license_draft(customer, email, path, display=True, formal=(anrede == "Sie"))
            self._set_status(
                f"Outlook-Entwurf für {customer} ({email}) erneut geöffnet – "
                "Lizenzdatei unverändert. Nach «Senden» erscheint hier die Versandbestätigung."
            )
            self._start_mail_watch(1)
        except Exception as e:
            QMessageBox.warning(
                self, "Outlook-Fehler",
                f"Entwurf konnte nicht erstellt werden:\n{e}"
            )

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "CSV-Datei öffnen", "", "CSV (*.csv)")
        if not path:
            return
        self._load_csv(Path(path))

    def _open_out_dir(self):
        OUT_DIR.mkdir(exist_ok=True)
        os.startfile(str(OUT_DIR))

    # ── Versandstatus (Outlook classic läuft unsichtbar) ──────────────────────

    _WATCH_INTERVAL_MS = 4000
    _WATCH_MAX_S = 600       # höchstens 10 Minuten beobachten
    _KICK_AFTER_S = 30       # hängt eine Mail so lange, "Senden/Empfangen" anstossen
    _STUCK_AFTER_S = 120     # danach als hängend melden

    def _start_mail_watch(self, expected: int) -> None:
        """Beobachtet nach dem Öffnen der Entwürfe Postausgang und "Gesendete
        Elemente" von Outlook classic und zeigt den Versandstatus an."""
        self._watch_since = datetime.now() - timedelta(seconds=30)
        self._watch_started = datetime.now()
        self._watch_expected = expected
        self._outbox_seen_at = None
        self._kicked = False
        if not hasattr(self, "_watch_timer"):
            self._watch_timer = QTimer(self)
            self._watch_timer.timeout.connect(self._poll_mail_status)
        self._watch_timer.start(self._WATCH_INTERVAL_MS)

    def _poll_mail_status(self) -> None:
        try:
            from outlook_mail import license_mail_status, trigger_send_receive
            status = license_mail_status(self._watch_since)
        except Exception:
            return  # Outlook gerade nicht erreichbar -- beim nächsten Takt erneut

        now = datetime.now()
        sent, outbox = status["sent"], status["outbox"]
        if outbox:
            self._outbox_seen_at = self._outbox_seen_at or now
            waiting = (now - self._outbox_seen_at).total_seconds()
            if waiting >= self._KICK_AFTER_S and not self._kicked:
                self._kicked = True
                try:
                    trigger_send_receive()
                except Exception:
                    pass
            if waiting >= self._STUCK_AFTER_S:
                self._set_status(
                    f"⚠ {len(outbox)} Lizenz-Mail(s) hängen im Postausgang von Outlook classic "
                    "und werden nicht gesendet. Bitte Outlook classic öffnen (outlook.exe), "
                    "Postausgang prüfen und die Mail dort öffnen und erneut senden.",
                    error=True,
                )
            else:
                self._set_status(f"⏳ {len(outbox)} Lizenz-Mail(s) im Postausgang – wird gesendet …")
        else:
            self._outbox_seen_at = None
            if sent:
                subject, when = sent[0]
                self._set_status(f"✓ Gesendet um {when:%H:%M}: «{subject}». Postausgang leer.")
            else:
                self._set_status("Entwurf offen – nach «Senden» erscheint hier die Bestätigung.")

        done = len(sent) >= self._watch_expected and not outbox
        if done or (now - self._watch_started).total_seconds() > self._WATCH_MAX_S:
            self._watch_timer.stop()

    def closeEvent(self, event):
        """Warnt, wenn beim Schliessen noch Lizenz-Mails im Postausgang liegen."""
        try:
            from outlook_mail import license_mail_status
            outbox = license_mail_status(datetime.now())["outbox"]
        except Exception:
            outbox = []
        if outbox:
            answer = QMessageBox.question(
                self, "Lizenz-Mail noch nicht gesendet",
                f"Im Postausgang von Outlook classic liegen noch {len(outbox)} "
                "Lizenz-Mail(s). Trotzdem schliessen?\n\n"
                "Tipp: Outlook classic (outlook.exe) öffnen und den Postausgang prüfen.",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        event.accept()

    def _set_status(self, msg, error=False):
        color = "red" if error else GREEN
        self._status.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._status.setText(msg)

    # ── CSV laden / speichern ─────────────────────────────────────────────────

    def _load_csv(self, path: Path = CSV_PATH):
        if not path.exists():
            return
        try:
            for enc in ("utf-8-sig", "utf-8", "cp1252"):
                try:
                    with open(path, newline="", encoding=enc) as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return

            self._loading = True
            try:
                self._table.setRowCount(0)
                for row in rows:
                    name   = row.get("name", "").strip()
                    email  = row.get("email", "").strip()
                    ltype  = row.get("lizenztyp", "Testlizenz (30 Tage)").strip()
                    anrede = (row.get("anrede") or "Sie").strip() or "Sie"
                    if name or email:
                        self._insert_row(name, email, ltype, anrede)
            finally:
                self._loading = False
        except Exception as e:
            self._set_status(f"CSV-Fehler: {e}", error=True)

    def _save_csv(self):
        try:
            with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["name", "email", "lizenztyp", "anrede"])
                for r in range(self._table.rowCount()):
                    name  = self._table.item(r, 1).text() if self._table.item(r, 1) else ""
                    email = self._table.item(r, 2).text() if self._table.item(r, 2) else ""
                    combo = self._table.cellWidget(r, 3)
                    ltype = combo.currentText() if combo else "Testlizenz (30 Tage)"
                    anrede_combo = self._table.cellWidget(r, 4)
                    anrede = anrede_combo.currentText() if anrede_combo else "Sie"
                    writer.writerow([name, email, ltype, anrede])
        except Exception as e:
            self._set_status(f"Speicherfehler: {e}", error=True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = LizenzManager()
    window.show()
    sys.exit(app.exec())
