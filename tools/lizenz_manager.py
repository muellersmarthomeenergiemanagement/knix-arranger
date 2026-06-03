"""
KNiX Arranger – Lizenz-Manager (GUI)
Lizenzdateien erstellen und verwalten.

Ausfuehren:
    python tools/lizenz_manager.py
"""
import os
import sys
import csv
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QComboBox,
    QSpinBox, QHeaderView, QFileDialog, QMessageBox, QLineEdit,
    QGroupBox, QFormLayout, QAbstractItemView, QFrame,
)
from PySide6.QtCore import Qt
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
        self.setMinimumSize(780, 520)
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

        central = QWidget()
        self.setCentralWidget(central)
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

        add_btn = QPushButton("+ Hinzufügen")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._add_row)
        self._name_input.returnPressed.connect(self._add_row)
        self._email_input.returnPressed.connect(self._add_row)

        form.addRow("Name:", self._name_input)
        form.addRow("E-Mail:", self._email_input)
        form.addRow("Lizenztyp:", self._type_combo)
        form.addRow("", add_btn)
        layout.addWidget(input_group)

        # Tabelle
        table_group = QGroupBox("Lizenznehmer")
        table_layout = QVBoxLayout(table_group)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "E-Mail", "Lizenztyp"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        table_layout.addWidget(self._table)

        row_btns = QHBoxLayout()
        del_btn = QPushButton("Zeile entfernen")
        del_btn.setObjectName("secondary")
        del_btn.clicked.connect(self._remove_row)
        import_btn = QPushButton("CSV importieren…")
        import_btn.setObjectName("secondary")
        import_btn.clicked.connect(self._import_csv)
        row_btns.addWidget(del_btn)
        row_btns.addWidget(import_btn)
        row_btns.addStretch()
        table_layout.addLayout(row_btns)
        layout.addWidget(table_group)

        # Aktionen
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #ddd;")
        layout.addWidget(sep)

        action_row = QHBoxLayout()

        self._status = QLabel("")
        self._status.setStyleSheet("color: #555; font-size: 12px;")
        action_row.addWidget(self._status, 1)

        open_btn = QPushButton("Ausgabeordner öffnen")
        open_btn.setObjectName("secondary")
        open_btn.clicked.connect(self._open_out_dir)
        action_row.addWidget(open_btn)

        gen_btn = QPushButton("Lizenzen generieren")
        gen_btn.setObjectName("primary")
        gen_btn.setMinimumWidth(180)
        gen_btn.clicked.connect(self._generate)
        action_row.addWidget(gen_btn)

        layout.addLayout(action_row)

        self._load_csv()

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def _add_row(self):
        name  = self._name_input.text().strip()
        email = self._email_input.text().strip()
        if not name or not email:
            self._set_status("Bitte Name und E-Mail eingeben.", error=True)
            return

        ltype = self._type_combo.currentText()
        self._insert_row(name, email, ltype)
        self._name_input.clear()
        self._email_input.clear()
        self._name_input.setFocus()
        self._save_csv()
        self._set_status(f"{name} hinzugefügt.")

    def _insert_row(self, name, email, ltype):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(name))
        self._table.setItem(row, 1, QTableWidgetItem(email))
        combo = QComboBox()
        combo.addItems(["Testlizenz (30 Tage)", "Jahreslizenz (365 Tage)", "Einzellizenz (unbegrenzt)"])
        idx = combo.findText(ltype)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        self._table.setCellWidget(row, 2, combo)

    def _remove_row(self):
        row = self._table.currentRow()
        if row >= 0:
            name = self._table.item(row, 0).text() if self._table.item(row, 0) else ""
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

        ok = 0
        errors = []
        for r in range(rows):
            name  = self._table.item(r, 0).text().strip() if self._table.item(r, 0) else ""
            email = self._table.item(r, 1).text().strip() if self._table.item(r, 1) else ""
            combo = self._table.cellWidget(r, 2)
            ltype_text = combo.currentText() if combo else "Testlizenz (30 Tage)"

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

            # Alte Lizenzdateien derselben Person entfernen
            for old in OUT_DIR.glob(f"{safe}_*.knxlic"):
                if str(old) != out_path:
                    old.unlink()

            try:
                generate_license(name, email, ltype, days, out_path)
                ok += 1
            except Exception as e:
                errors.append(f"{name}: {e}")

        if errors:
            QMessageBox.warning(self, "Fehler", "\n".join(errors))

        if ok:
            self._set_status(f"{ok} Lizenzdatei(en) erstellt in {OUT_DIR}/")
            QMessageBox.information(self, "Fertig",
                f"{ok} Lizenzdatei(en) wurden erstellt.\n\nOrdner: {OUT_DIR}")
        else:
            self._set_status("Keine Lizenzen erstellt.", error=True)

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "CSV-Datei öffnen", "", "CSV (*.csv)")
        if not path:
            return
        self._load_csv(Path(path))

    def _open_out_dir(self):
        OUT_DIR.mkdir(exist_ok=True)
        os.startfile(str(OUT_DIR))

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

            self._table.setRowCount(0)
            for row in rows:
                name  = row.get("name", "").strip()
                email = row.get("email", "").strip()
                ltype = row.get("lizenztyp", "Testlizenz (30 Tage)").strip()
                if name or email:
                    self._insert_row(name, email, ltype)
        except Exception as e:
            self._set_status(f"CSV-Fehler: {e}", error=True)

    def _save_csv(self):
        try:
            with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["name", "email", "lizenztyp"])
                for r in range(self._table.rowCount()):
                    name  = self._table.item(r, 0).text() if self._table.item(r, 0) else ""
                    email = self._table.item(r, 1).text() if self._table.item(r, 1) else ""
                    combo = self._table.cellWidget(r, 2)
                    ltype = combo.currentText() if combo else "Testlizenz (30 Tage)"
                    writer.writerow([name, email, ltype])
        except Exception as e:
            self._set_status(f"Speicherfehler: {e}", error=True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = LizenzManager()
    window.show()
    sys.exit(app.exec())
