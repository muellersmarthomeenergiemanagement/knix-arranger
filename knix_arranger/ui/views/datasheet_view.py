"""
Produktdatenblätter-Verwaltung (FA-1201 bis FA-1205)
"""
from __future__ import annotations
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QLineEdit,
    QGroupBox, QFormLayout, QAbstractItemView,
    QFileDialog, QInputDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QColor
from ...models.project import KnxProject
from ..column_utils import fit_columns


@dataclass
class _DeviceRef:
    """Verweis auf eine Gruppe gleichartiger Geräte mit Produktdaten."""
    type_label: str          # "Topologie-Gerät" oder "Bedienelement"
    sub_type: str            # device_type oder element_type
    sources: list            # list[topology.Device | building.Bedienelement]

    @property
    def source(self):
        """Erstes Element der Gruppe (für Lesezugriffe auf Produktdaten)."""
        return self.sources[0] if self.sources else None

    @property
    def quantity(self) -> int:
        return len(self.sources)


class DatasheetView(QWidget):
    """Produktdatenblätter: Upload, Verknuepfung, Übersicht."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project: KnxProject | None = None
        self._devices: list[_DeviceRef] = []

        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()

        title = QLabel("Produktdatenblätter")
        title.setObjectName("title")
        header_row.addWidget(title)

        header_row.addStretch()

        btn_refresh = QPushButton("Aktualisieren")
        btn_refresh.setToolTip(
            "Geräteliste aus der aktuellen Topologie und Gebäudestruktur neu einlesen"
        )
        btn_refresh.clicked.connect(self._on_refresh)
        header_row.addWidget(btn_refresh)

        layout.addLayout(header_row)

        self._info = QLabel("")
        self._info.setObjectName("subtitle")
        layout.addWidget(self._info)

        content = QHBoxLayout()

        # Geräte-Tabelle
        left = QVBoxLayout()
        left.addWidget(QLabel("Geräte mit Produktdaten:"))

        self._device_table = QTableWidget()
        self._device_table.setColumnCount(7)
        self._device_table.setHorizontalHeaderLabels([
            "Anz.", "Typ", "Geräteart", "Hersteller", "Best.-Nr.", "Produkt", "Datenblätter",
        ])
        self._device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._device_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._device_table.horizontalHeader().setStretchLastSection(True)
        self._device_table.setAlternatingRowColors(True)
        self._device_table.currentCellChanged.connect(self._on_device_selected)
        left.addWidget(self._device_table)

        content.addLayout(left, 2)

        # Detail-Panel
        right = QVBoxLayout()

        # Produktdaten
        self._product_group = QGroupBox("Produktdaten (FA-1205)")
        prod_form = QFormLayout()

        self._prod_manufacturer = QLineEdit()
        prod_form.addRow("Hersteller:", self._prod_manufacturer)

        self._prod_order_nr = QLineEdit()
        prod_form.addRow("Bestellnummer:", self._prod_order_nr)

        self._prod_name = QLineEdit()
        prod_form.addRow("Produktbezeichnung:", self._prod_name)

        self._prod_app_program = QLineEdit()
        prod_form.addRow("ETS-Applikation:", self._prod_app_program)

        self._btn_apply = QPushButton("Übernehmen")
        self._btn_apply.clicked.connect(self._apply_product)
        prod_form.addRow("", self._btn_apply)

        self._product_group.setLayout(prod_form)
        right.addWidget(self._product_group)

        # Datenblätter
        self._ds_group = QGroupBox("Datenblätter (FA-1201/1202)")
        ds_layout = QVBoxLayout()

        self._ds_table = QTableWidget()
        self._ds_table.setColumnCount(2)
        self._ds_table.setHorizontalHeaderLabels(["Name / URL", "Pfad / Link"])
        self._ds_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._ds_table.horizontalHeader().setStretchLastSection(True)
        self._ds_table.setToolTip("Doppelklick: Datei öffnen oder URL im Browser aufrufen")
        self._ds_table.doubleClicked.connect(self._open_ds_entry)
        ds_layout.addWidget(self._ds_table)

        ds_btn_layout = QHBoxLayout()
        self._btn_add_ds = QPushButton("PDF hinzufügen…")
        self._btn_add_ds.clicked.connect(self._add_datasheet)
        self._btn_search_online = QPushButton("Im Internet suchen")
        self._btn_search_online.setToolTip(
            "Google-Suche nach Hersteller + Bestellnummer + Produktname öffnen"
        )
        self._btn_search_online.clicked.connect(self._search_online)
        self._btn_save_url = QPushButton("URL speichern…")
        self._btn_save_url.setToolTip(
            "Gefundene Datenblatt-URL manuell eintragen und speichern"
        )
        self._btn_save_url.clicked.connect(self._add_url_link)
        self._btn_download_ds = QPushButton("Lokal speichern…")
        self._btn_download_ds.setToolTip(
            "Alle URL-Datenblätter herunterladen und lokal im Projektordner speichern"
        )
        self._btn_download_ds.clicked.connect(self._download_datasheets)
        self._btn_remove_ds = QPushButton("Entfernen")
        self._btn_remove_ds.setObjectName("danger")
        self._btn_remove_ds.clicked.connect(self._remove_datasheet)
        ds_btn_layout.addWidget(self._btn_add_ds)
        ds_btn_layout.addWidget(self._btn_search_online)
        ds_btn_layout.addWidget(self._btn_save_url)
        ds_btn_layout.addWidget(self._btn_download_ds)
        ds_btn_layout.addWidget(self._btn_remove_ds)
        ds_btn_layout.addStretch()
        ds_layout.addLayout(ds_btn_layout)

        self._ds_group.setLayout(ds_layout)
        right.addWidget(self._ds_group)

        # Kommunikationsobjekte
        self._co_group = QGroupBox("Kommunikationsobjekte (aus KNXPROD)")
        co_layout = QVBoxLayout()

        self._co_summary = QLabel("Kein Produkt mit ComObject-Daten ausgewählt.")
        self._co_summary.setObjectName("subtitle")
        co_layout.addWidget(self._co_summary)

        self._co_table = QTableWidget()
        self._co_table.setColumnCount(5)
        self._co_table.setHorizontalHeaderLabels(
            ["Nr.", "Name", "Funktion", "DPT", "Flags"]
        )
        self._co_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._co_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._co_table.horizontalHeader().setStretchLastSection(True)
        self._co_table.setAlternatingRowColors(True)
        self._co_table.setMaximumHeight(200)
        co_layout.addWidget(self._co_table)

        self._co_group.setLayout(co_layout)
        right.addWidget(self._co_group)

        right.addStretch()
        content.addLayout(right, 1)

        layout.addLayout(content)

    def set_project(self, project: KnxProject):
        self._project = project
        self._refresh_devices()

    def _refresh_devices(self):
        if not self._project:
            self._device_table.setRowCount(0)
            self._devices = []
            self._info.setText("")
            self._co_table.setRowCount(0)
            self._co_summary.setText("Kein Produkt mit ComObject-Daten ausgewählt.")
            return

        # Lookup-Tabellen: Gerät nach ID und physikalischer Adresse
        _id_to_dev: dict = {}
        _addr_to_dev: dict = {}
        for area in self._project.topology.areas:
            if area.backbone_power_supply is not None:
                dev = area.backbone_power_supply
                _id_to_dev[dev.id] = dev
                if dev.physical_address:
                    _addr_to_dev[dev.physical_address] = dev
            for line in area.lines:
                for device in line.devices:
                    _id_to_dev[device.id] = device
                    if device.physical_address:
                        _addr_to_dev[device.physical_address] = device

        _be_by_id: dict = {}
        _be_by_addr: dict = {}
        for room in self._project.all_rooms:
            for be in room.bedienelemente:
                _be_by_id[be.id] = be
                if be.participant_number:
                    _be_by_addr[be.participant_number] = be

        # Eine Zeile pro Materiallisten-Eintrag (gleiche Anzahl wie Materialliste)
        self._devices = []
        for entry in self._project.material_list.entries:
            sources = []
            for addr in entry.physical_addresses:
                dev = _addr_to_dev.get(addr) or _be_by_addr.get(addr)
                if dev and dev not in sources:
                    sources.append(dev)
            if not sources and entry.device_id:
                dev = _id_to_dev.get(entry.device_id) or _be_by_id.get(entry.device_id)
                if dev:
                    sources.append(dev)
            if not sources:
                continue  # kein passendes Gerät in der Topologie
            type_label = "Bedienelement" if hasattr(sources[0], "participant_number") else "Topologie-Gerät"
            self._devices.append(_DeviceRef(
                type_label=type_label,
                sub_type=entry.device_type,
                sources=sources,
            ))

        self._device_table.setRowCount(len(self._devices))
        total_ds = 0
        for i, ref in enumerate(self._devices):
            src = ref.source
            ds_count = len(src.datasheets)
            total_ds += ds_count
            product_name = getattr(src, "product_name", "") or getattr(src, "product", "")
            qty_item = QTableWidgetItem(str(ref.quantity))
            qty_item.setTextAlignment(Qt.AlignCenter)
            self._device_table.setItem(i, 0, qty_item)
            self._device_table.setItem(i, 1, QTableWidgetItem(ref.type_label))
            self._device_table.setItem(i, 2, QTableWidgetItem(ref.sub_type))
            self._device_table.setItem(i, 3, QTableWidgetItem(src.manufacturer))
            self._device_table.setItem(i, 4, QTableWidgetItem(src.order_number))
            self._device_table.setItem(i, 5, QTableWidgetItem(product_name))
            self._device_table.setItem(i, 6, QTableWidgetItem(str(ds_count)))

        fit_columns(self._device_table)
        total_singles = sum(r.quantity for r in self._devices)
        self._info.setText(
            f"{len(self._devices)} Gerätepositionen "
            f"({total_singles} Einzelgeräte), "
            f"{total_ds} Datenblätter hinterlegt"
        )

    def _on_device_selected(self, row, col, prev_row, prev_col):
        if row < 0 or row >= len(self._devices):
            return
        src = self._devices[row].source
        self._prod_manufacturer.setText(src.manufacturer)
        self._prod_order_nr.setText(src.order_number)
        product_name = getattr(src, "product_name", "") or getattr(src, "product", "")
        self._prod_name.setText(product_name)
        app = getattr(src, "application_program", "")
        self._prod_app_program.setText(app)
        self._refresh_datasheets(src)
        self._refresh_com_objects(src)

    def _refresh_datasheets(self, src):
        self._ds_table.setRowCount(len(src.datasheets))
        for i, path in enumerate(src.datasheets):
            is_url = path.startswith("http://") or path.startswith("https://")
            if is_url:
                # Kompakte Anzeige: Domäne + Endteil der URL
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(path)
                    short = f"[Web] {parsed.netloc}…{parsed.path[-30:]}" if len(parsed.path) > 30 else f"[Web] {parsed.netloc}{parsed.path}"
                except Exception:
                    short = path
                name_item = QTableWidgetItem(short)
                name_item.setToolTip(path)
            else:
                name_item = QTableWidgetItem(Path(path).name)
                name_item.setToolTip(path)
            self._ds_table.setItem(i, 0, name_item)
            self._ds_table.setItem(i, 1, QTableWidgetItem(path))
        fit_columns(self._ds_table)

    def _get_selected_ref(self) -> _DeviceRef | None:
        row = self._device_table.currentRow()
        if row < 0 or row >= len(self._devices):
            return None
        return self._devices[row]

    def _apply_product(self):
        ref = self._get_selected_ref()
        if not ref:
            return
        for src in ref.sources:
            src.manufacturer = self._prod_manufacturer.text()
            src.order_number = self._prod_order_nr.text()
            if hasattr(src, "product_name"):
                src.product_name = self._prod_name.text()
            else:
                src.product = self._prod_name.text()
            if hasattr(src, "application_program"):
                src.application_program = self._prod_app_program.text()
        self._refresh_devices()

    def _datasheets_folder(self) -> str:
        """Gibt den Datenblätter-Unterordner des Projekts zurück (leer wenn unbekannt)."""
        if self._project and self._project.folder_path:
            return os.path.join(self._project.folder_path, "Datenblätter")
        return ""

    def _add_datasheet(self):
        ref = self._get_selected_ref()
        if not ref:
            return
        start_dir = self._datasheets_folder() or ""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Produktdatenblatt hinzufügen", start_dir,
            "PDF-Dateien (*.pdf);;Alle Dateien (*.*)",
        )
        if paths:
            for src in ref.sources:
                for p in paths:
                    if p not in src.datasheets:
                        src.datasheets.append(p)
            self._refresh_datasheets(ref.source)
            self._refresh_devices()

    def _download_datasheets(self):
        """Lädt alle URL-Datenblätter herunter und speichert sie lokal."""
        if not self._project:
            return

        default_folder = self._datasheets_folder() or os.getcwd()
        os.makedirs(default_folder, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(
            self, "Zielordner für Datenblätter wählen", default_folder,
        )
        if not folder:
            return

        url_to_local: dict[str, str] = {}
        downloaded = 0
        skipped = 0
        failed: list[str] = []

        for ref in self._devices:
            for src in ref.sources:
                new_datasheets = []
                for ds in src.datasheets:
                    if not (ds.startswith("http://") or ds.startswith("https://")):
                        new_datasheets.append(ds)
                        continue
                    if ds in url_to_local:
                        new_datasheets.append(url_to_local[ds])
                        continue
                    parsed = urlparse(ds)
                    fname = Path(parsed.path).name or "datenblatt.pdf"
                    if not fname.lower().endswith(".pdf"):
                        fname += ".pdf"
                    dest = os.path.join(folder, fname)
                    if os.path.exists(dest):
                        url_to_local[ds] = dest
                        new_datasheets.append(dest)
                        skipped += 1
                        continue
                    # Kollision vermeiden: Zähler-Suffix
                    base, ext = os.path.splitext(fname)
                    counter = 2
                    while os.path.exists(dest):
                        dest = os.path.join(folder, f"{base}_{counter}{ext}")
                        counter += 1
                    try:
                        urllib.request.urlretrieve(ds, dest)
                        url_to_local[ds] = dest
                        new_datasheets.append(dest)
                        downloaded += 1
                    except Exception as exc:
                        url_to_local[ds] = ds  # URL bei Fehler behalten
                        new_datasheets.append(ds)
                        failed.append(f"{fname}: {exc}")
                src.datasheets = new_datasheets

        parts = []
        if downloaded:
            parts.append(f"{downloaded} heruntergeladen")
        if skipped:
            parts.append(f"{skipped} bereits vorhanden (übersprungen)")
        summary = ", ".join(parts) or "Keine URL-Datenblätter gefunden"
        msg = f"{summary}\nZielordner: {folder}"
        if failed:
            msg += f"\n\n{len(failed)} Fehler:\n" + "\n".join(failed[:5])
        QMessageBox.information(self, "Download abgeschlossen", msg)

        ref = self._get_selected_ref()
        if ref:
            self._refresh_datasheets(ref.source)
        self._refresh_devices()

    def _remove_datasheet(self):
        ref = self._get_selected_ref()
        if not ref:
            return
        row = self._ds_table.currentRow()
        if 0 <= row < len(ref.source.datasheets):
            path_to_remove = ref.source.datasheets[row]
            for src in ref.sources:
                if path_to_remove in src.datasheets:
                    src.datasheets.remove(path_to_remove)
            self._refresh_datasheets(ref.source)
            self._refresh_devices()

    def _refresh_com_objects(self, src):
        """Zeigt ComObjects des ausgewählten Geräts (aus Device.communication_objects)."""
        cos = getattr(src, "communication_objects", [])
        self._co_table.setRowCount(0)

        if not cos:
            self._co_summary.setText(
                "Keine ComObject-Daten vorhanden. "
                "Produkt aus KNXPROD-Datei zuweisen."
            )
            return

        # GA-Bedarf schätzen: needs_ga wenn Flags K+W, K+S, K+L oder K+U enthalten
        ga_count = 0
        for co in cos:
            flags = getattr(co, "flags", "") or ""
            if "K" in flags and any(f in flags for f in ("Ü", "S", "L", "U")):
                ga_count += 1

        total = len(cos)
        self._co_summary.setText(
            f"{total} ComObjects  |  GA-Bedarf (Est.): ca. {ga_count} GAs je Gerät"
        )

        _needs_ga_color = QColor("#1B5E20")   # dunkelgrün = aktives Objekt

        self._co_table.setSortingEnabled(False)
        for co in cos:
            row = self._co_table.rowCount()
            self._co_table.insertRow(row)

            flags = getattr(co, "flags", "")
            needs_ga = "K" in flags and any(f in flags for f in ("Ü", "S", "L", "U"))

            items = [
                QTableWidgetItem(str(getattr(co, "object_number", ""))),
                QTableWidgetItem(getattr(co, "name", "")),
                QTableWidgetItem(getattr(co, "object_function", "")),
                QTableWidgetItem(getattr(co, "data_type", "")),
                QTableWidgetItem(flags),
            ]
            items[0].setTextAlignment(Qt.AlignCenter)
            items[4].setTextAlignment(Qt.AlignCenter)

            if needs_ga:
                for item in items:
                    item.setForeground(_needs_ga_color)

            for col, item in enumerate(items):
                self._co_table.setItem(row, col, item)

        self._co_table.setSortingEnabled(True)
        fit_columns(self._co_table)

    def _on_refresh(self):
        """Liest Gerätedaten neu ein (z.B. nach Produktzuweisung in Materialliste)."""
        self._refresh_devices()

    def _search_online(self):
        """
        Baut eine Google-Suchanfrage aus Hersteller, Bestellnummer und
        Produktbezeichnung und öffnet sie im Standard-Browser.
        Suchbegriffe: «Hersteller Bestellnummer Produktname Datenblatt filetype:pdf»
        """
        ref = self._get_selected_ref()
        if not ref:
            QMessageBox.information(self, "Kein Gerät gewählt",
                                    "Bitte zuerst ein Gerät in der linken Liste auswählen.")
            return

        src = ref.source
        product_name = getattr(src, "product_name", "") or getattr(src, "product", "")
        parts = [p for p in [src.manufacturer, src.order_number, product_name] if p]
        if not parts:
            QMessageBox.information(self, "Keine Produktdaten",
                                    "Für das gewählte Gerät sind noch keine Herstellerangaben vorhanden.\n"
                                    "Bitte zuerst Hersteller und Bestellnummer eintragen.")
            return

        query = " ".join(parts) + " Datenblatt filetype:pdf"
        search_url = f"https://www.google.com/search?q={quote_plus(query)}"
        QDesktopServices.openUrl(QUrl(search_url))

    def _add_url_link(self):
        """
        Fragt nach einer URL und speichert diese als Datenblatt-Link
        bei allen Geräten der gewählten Gruppe.
        """
        ref = self._get_selected_ref()
        if not ref:
            QMessageBox.information(self, "Kein Gerät gewählt",
                                    "Bitte zuerst ein Gerät in der linken Liste auswählen.")
            return

        url, ok = QInputDialog.getText(
            self,
            "Datenblatt-URL speichern",
            "URL des Datenblatts (z.B. https://www.hersteller.com/produkt.pdf):",
        )
        if not ok:
            return

        url = url.strip()
        if not url:
            return

        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.warning(self, "Ungültige URL",
                                "Die URL muss mit «http://» oder «https://» beginnen.")
            return

        if url in ref.source.datasheets:
            QMessageBox.information(self, "Bereits vorhanden",
                                    "Dieser Link ist bereits für das Gerät hinterlegt.")
            return

        for src in ref.sources:
            if url not in src.datasheets:
                src.datasheets.append(url)
        self._refresh_datasheets(ref.source)
        self._refresh_devices()

    def _open_ds_entry(self, index):
        """
        Öffnet den Eintrag der Datenblatttabelle per Doppelklick:
        - URL → Standard-Browser
        - Dateipfad → OS-Standardprogramm (z.B. PDF-Viewer)
        """
        ref = self._get_selected_ref()
        if not ref or index.row() >= len(ref.source.datasheets):
            return

        path = ref.source.datasheets[index.row()]
        if path.startswith("http://") or path.startswith("https://"):
            url = QUrl(path)
        else:
            url = QUrl.fromLocalFile(path)
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self, "Öffnen fehlgeschlagen",
                f"Die Datei oder URL konnte nicht geöffnet werden:\n{path}\n\n"
                "Bitte prüfen Sie, ob die Datei vorhanden ist und ein "
                "geeignetes Programm zum Öffnen registriert ist.",
            )
