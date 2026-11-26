"""
Fehlende Herstellerdateien (FA-3108f): welche .knxprod fehlt (Hersteller,
Bestellnummer, Applikation, Geräte), Datei hinzufügen, aus einem ETS-Projekt
herauslösen, Produktordner öffnen und die Geräte nachführen.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...services import missing_products as mp
from ..styles import COLOR_OK, TEXT_MUTED

_COLUMNS = ["Hersteller", "Bestellnummer", "Applikation", "Geräte"]


class MissingProductsDialog(QDialog):

    def __init__(self, project, bus=None, catalog=None, parent=None):
        super().__init__(parent)
        self._project = project
        self._bus = bus
        self._catalog = catalog
        self.completed: list[str] = []     # nachgeführte Geräte (für Flags lesen)
        self.setWindowTitle("Fehlende Herstellerdateien")
        self.resize(860, 460)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Für diese Geräte steht die Applikation nicht im Produktkatalog. Ohne "
            "Herstellerdatei (.knxprod) fehlen Produkt, KO-Texte und bei manchen Geräten "
            "die Flags; die gelesenen Verknüpfungen bleiben erhalten. Die passende Datei "
            "beim Hersteller laden – oder aus einem ETS-Projekt mit denselben Geräten "
            "herauslösen.")
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(intro)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((210, 160, 150)):
            self._table.setColumnWidth(column, width)
        layout.addWidget(self._table, 1)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        row = QHBoxLayout()
        add = QPushButton("Datei hinzufügen…")
        add.setToolTip("Herstellerdatei(en) wählen: einlesen und in den Produktordner legen")
        add.clicked.connect(self._add_files)
        from_ets = QPushButton("Aus ETS-Projekt…")
        from_ets.setObjectName("secondary")
        from_ets.setToolTip("Eine .knxproj enthält die Produktdaten ihrer Geräte – ein "
                            "anderes Projekt mit denselben Geräten genügt")
        from_ets.clicked.connect(self._from_knxproj)
        folder = QPushButton("Ordner öffnen")
        folder.setObjectName("secondary")
        folder.setToolTip("Produktordner im Explorer öffnen; dort abgelegte Dateien "
                          "liest «Nachführen» mit ein")
        folder.clicked.connect(self._open_folder)
        self._complete_btn = QPushButton("Nachführen")
        self._complete_btn.setToolTip(
            "Geräte, deren Applikation jetzt im Katalog steht: Produkt und KOs zuordnen, "
            "Verknüpfungen behalten, Bedeutung der GAs neu ergänzen")
        self._complete_btn.clicked.connect(self._complete)
        close = QPushButton("Schliessen")
        close.setObjectName("secondary")
        close.clicked.connect(self.accept)
        for button in (add, from_ets, folder):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(self._complete_btn)
        row.addWidget(close)
        layout.addLayout(row)
        self._fill()

    def _fill(self) -> None:
        entries = mp.missing(self._project)
        self._table.setRowCount(len(entries))
        for index, entry in enumerate(entries):
            cells = (f"{entry.manufacturer} ({entry.manufacturer_id})" if entry.manufacturer_id
                     else entry.manufacturer,
                     ", ".join(entry.order_numbers) or "–",
                     entry.application_text,
                     ", ".join(entry.addresses))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._table.setItem(index, column, item)
        if not entries:
            self._status.setText("Alle Geräte haben ein Produkt aus dem Katalog.")
            self._status.setStyleSheet(f"color: {COLOR_OK};")
        self._complete_btn.setEnabled(bool(entries))

    # ── Dateien ──────────────────────────────────────────────────────────

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Herstellerdateien wählen", "", "Herstellerdateien (*.knxprod)")
        if paths:
            self._read(lambda: mp.read_files(paths, self._catalog))

    def _from_knxproj(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "ETS-Projekt mit denselben Geräten wählen", "", "ETS-Projekt (*.knxproj)")
        if path:
            self._read(lambda: mp.from_knxproj(path, self._catalog))

    def _read(self, action) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = action()
        finally:
            QApplication.restoreOverrideCursor()
        text = f"{result.products} Produkte eingelesen."
        if result.problems:
            text += " Übersprungen: " + "; ".join(result.problems[:4])
        self._status.setStyleSheet("")
        self._status.setText(text)
        if result.products:
            self._complete(prefix=text)

    def _open_folder(self) -> None:
        from ...services.product_folder import products_folder
        folder = products_folder()
        if not folder:
            QMessageBox.information(self, "Produktordner",
                                    "Kein Produktordner eingerichtet (Einstellungen).")
            return
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ── Nachführen ───────────────────────────────────────────────────────

    def _complete(self, prefix: str = "") -> None:
        # im Ordner abgelegte, noch nicht eingelesene Dateien (nach Rückfrage)
        from .product_reading import offer_pending
        catalog = self._catalog
        if catalog is None:
            from ...services.product_sync import shared_catalog
            catalog = shared_catalog()
        pending = offer_pending(
            self, mp.needed_manufacturers(mp.findings_of_devices(self._project), catalog),
            catalog)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if self._bus is not None:
                self._bus.begin_change("Herstellerdateien nachgeführt")
            result = mp.complete(self._project, self._catalog)
        finally:
            QApplication.restoreOverrideCursor()
        if result.completed and self._bus is not None:
            self._bus.emit_topology_changed()
            self._bus.emit_addresses_changed()
        self.completed.extend(result.completed)
        text = result.text()
        if pending.products:
            text = f"{pending.products} Produkte aus dem Produktordner eingelesen.\n" + text
        if prefix:
            text = prefix + "\n" + text
        self._fill()
        self._status.setStyleSheet(f"color: {COLOR_OK};" if result.completed else "")
        self._status.setText(text)
