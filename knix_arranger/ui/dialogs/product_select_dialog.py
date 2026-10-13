"""
Produkt-Auswahl-Dialog (FA-2303, FA-2304)

Erlaubt die Suche und Auswahl von KNX-Geräten aus dem lokalen Katalog
sowie den Import weiterer Geräte via KNXPROD-Dateien und das Nachladen
des Online-Katalogs (FA-1303, FA-1402).
"""
from __future__ import annotations
import logging
import os
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QTableWidget, QTableWidgetItem, QPushButton,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox,
    QGroupBox, QSpinBox, QFormLayout, QProgressDialog, QMenu, QInputDialog,
    QSplitter, QTreeWidget, QTreeWidgetItem, QWidget, QStyledItemDelegate, QStyle,
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QFont, QColor, QKeySequence, QBrush, QPalette

from ...services.product_search_service import ProductSearchService, ProductSuggestion
from ...services.knxprod_catalog_service import KnxprodCatalogService
from ...services.product_classifier import TYPE_GROUPS, type_group
from ...services.recent_products import load_recent, add_recent
from ...models.material_list import MaterialEntry, MATERIAL_CATEGORIES
from ...models.topology import Topology, Line

logger = logging.getLogger("knix_arranger.product_select_dialog")


def _default_products_folder() -> str:
    """Liefert den Standardordner für gesammelte KNXPROD-Dateien
    (<Arbeitsverzeichnis>/Produkte KNX, siehe WorkspaceSetupDialog), falls
    ein Arbeitsverzeichnis konfiguriert ist und der Ordner existiert."""
    from ...utils.app_settings import get_setting
    workspace_root = get_setting("workspace_root_path", "")
    if not workspace_root:
        return ""
    candidate = os.path.join(workspace_root, "Produkte KNX")
    return candidate if os.path.isdir(candidate) else ""

# Mapping: interne catalog-Kategorie → Anzeigename
_CAT_DISPLAY = {
    "actor": "Aktor",
    "sensor": "Sensor",
    "infrastructure": "Infrastruktur",
}
_CAT_FILTER_OPTIONS = ["Alle", "Aktor", "Sensor", "Infrastruktur"]
_CAT_FILTER_MAP = {
    "Alle": "",
    "Aktor": "actor",
    "Sensor": "sensor",
    "Infrastruktur": "infrastructure",
}

# Spalten der Produktliste
_COL_TYPE, _COL_MFR, _COL_ORDER, _COL_NAME, _COL_CH, _COL_KO = range(6)
_COLUMNS = ["Typ", "Hersteller", "Bestellnummer", "Produktname", "Kanäle", "KOs"]

# Vorauswahl im Typenbaum aus der Kategorie des Aufrufers
_CATEGORY_TO_GROUP = {"actor": "Aktoren", "sensor": "Bedienung & Sensoren"}
_GROUP_TYPES = {group: types for group, types in TYPE_GROUPS}
_ALL_TYPES = {t for _g, types in TYPE_GROUPS for t in types}


def _group_of(prod: ProductSuggestion) -> str:
    """Gruppe im Typenbaum; Typen ausserhalb der Einordnung (z.B. "Taster
    4-fach" im Basiskatalog) nach ihrer Kategorie."""
    device_type = prod.display_type()
    if device_type in _ALL_TYPES:
        return type_group(device_type)
    return _CATEGORY_TO_GROUP.get(prod.category, "Systemgeräte")


def _initial_type_filter(device_type: str, category: str) -> tuple[str, str]:
    """("type"|"group"|"", Name) für die Vorauswahl, z.B. aus der Materialliste
    ("Schaltaktor 8-fach") oder einem Gateway-Gewerk ("KNX-Schnittstelle")."""
    import re
    base = re.sub(r"\s+\d+\s*-?\s*fach$", "", device_type or "").strip()
    if base in _ALL_TYPES and base != "KNX-Schnittstelle":
        return "type", base
    if base and ("Gateway" in base or base == "KNX-Schnittstelle"):
        return "group", "Gateways & Schnittstellen"
    if category in _CATEGORY_TO_GROUP:
        return "group", _CATEGORY_TO_GROUP[category]
    return "", ""


def _knxprod_paths(mime) -> list[str]:
    """.knxprod-Dateien aus Zwischenablage oder Ziehen (auch Ordner)."""
    if mime is None or not mime.hasUrls():
        return []
    paths = []
    for url in mime.urls():
        path = url.toLocalFile()
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                paths += [os.path.join(root, fn) for fn in files
                          if fn.lower().endswith(".knxprod")]
        elif path.lower().endswith(".knxprod") and os.path.isfile(path):
            paths.append(path)
    return sorted(set(paths))


class _ReadableSelectionDelegate(QStyledItemDelegate):
    """Markierte Zeilen weiss auf Markierungsfarbe -- auch Zellen mit eigener
    Schrift- oder Hintergrundfarbe (Online-Katalog blau, veraltet grau,
    "Zuletzt verwendet" gelb) wären sonst kaum lesbar."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.state & QStyle.State_Selected:
            option.backgroundBrush = QBrush()
            white = QColor("white")
            option.palette.setColor(QPalette.Text, white)
            option.palette.setColor(QPalette.HighlightedText, white)


class _NumberItem(QTableWidgetItem):
    """Zahl, numerisch sortiert; 0 als "–"."""

    def __init__(self, value: int):
        super().__init__(str(value) if value else "–")
        self._value = value or 0
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, _NumberItem):
            return self._value < other._value
        return super().__lt__(other)


# Schriftfarbe für Produkte aus dem Online-Katalog
_ONLINE_COLOR = QColor("#1f5fa8")

# Mapping: catalog-Kategorie + device_type → MaterialEntry.category
_DEVICE_TYPE_TO_ML_CAT = {
    "Linienkoppler": "Linienkoppler",
    "Bereichskoppler": "Bereichskoppler",
    "IP-Router": "IP-Router",
    "Netzteil": "Netzteil",
    "DALI-Gateway": "DALI-Gateway",
}


class ProductSelectDialog(QDialog):
    """
    Dialog zur Produktauswahl aus dem lokalen KNX-Katalog (FA-2303).

    Gibt bei Bestätigung eine fertige ``MaterialEntry``-Instanz zurück,
    die direkt zur Materialliste hinzugefügt werden kann.
    """

    def __init__(
        self,
        preferred_manufacturers: list[str] | None = None,
        initial_category_filter: str = "",   # "actor", "sensor", "infrastructure", ""
        topology: Topology | None = None,
        parent=None,
        initial_device_type: str = "",       # z.B. "Schaltaktor 8-fach", Vorauswahl
    ):
        super().__init__(parent)
        self.setWindowTitle("Produkt auswählen")
        self.setMinimumSize(980, 620)
        # .knxprod-Dateien hineinziehen oder mit Strg+V einfügen
        self.setAcceptDrops(True)

        from ...services.product_sync import shared_catalog
        # Einmal je Sitzung geladen (eigener Katalog kann >100 MB gross sein)
        self._search_service = shared_catalog() or ProductSearchService()
        self._preferred = preferred_manufacturers or []
        self._all_results: list[ProductSuggestion] = []
        self._selected: ProductSuggestion | None = None
        self._topology = topology
        self._selected_line: Line | None = None
        # Filter aus dem Typenbaum: ("group"|"type"|"", Name)
        self._type_filter = _initial_type_filter(initial_device_type,
                                                 initial_category_filter)

        self._build_ui(initial_category_filter)
        self._populate_recent_table()
        self._refresh_results()

    # ------------------------------------------------------------------ UI

    def _build_ui(self, initial_category_filter: str):
        layout = QVBoxLayout(self)

        # --- Zuletzt verwendet ---
        self._recent_group = QGroupBox("Zuletzt verwendet")
        recent_layout = QVBoxLayout()
        self._recent_table = QTableWidget(0, len(_COLUMNS))
        self._recent_table.setHorizontalHeaderLabels(_COLUMNS)
        self._recent_table.horizontalHeader().setSectionResizeMode(_COL_NAME,
                                                                   QHeaderView.Stretch)
        self._recent_table.verticalHeader().setVisible(False)
        self._set_column_widths(self._recent_table)
        self._recent_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._recent_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._recent_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._recent_table.setMaximumHeight(140)
        self._recent_table.doubleClicked.connect(self._on_recent_double_click)
        recent_layout.addWidget(self._recent_table)
        self._recent_group.setLayout(recent_layout)
        self._recent_group.setVisible(False)
        layout.addWidget(self._recent_group)

        # --- Filter-Zeile ---
        filter_group = QGroupBox("Filter")
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Suche:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Produktname, Bestellnummer, Hersteller…")
        self._search_edit.textChanged.connect(self._refresh_results)
        # Strg+V mit .knxprod-Dateien in der Zwischenablage: importieren
        self._search_edit.installEventFilter(self)
        filter_layout.addWidget(self._search_edit, 2)

        filter_layout.addWidget(QLabel("Hersteller:"))
        self._mfr_combo = QComboBox()
        self._mfr_combo.addItem("Alle")
        for m in self._search_service.known_manufacturers():
            self._mfr_combo.addItem(m)
        self._mfr_combo.currentIndexChanged.connect(self._refresh_results)
        filter_layout.addWidget(self._mfr_combo)

        # Katalogpflege in einem Menü, damit die Filterzeile Platz hat
        catalog_menu = QMenu(self)
        catalog_menu.setToolTipsVisible(True)
        act = catalog_menu.addAction("KNXPROD importieren…", self._import_knxprod)
        act.setToolTip(
            "Herstellerdatei (.knxprod) importieren und Produkte in den Katalog aufnehmen\n"
            "Auch: Dateien in dieses Fenster ziehen oder kopieren und mit Strg+V einfügen"
        )
        act = catalog_menu.addAction("Ordner importieren…", self._import_knxprod_folder)
        act.setToolTip(
            "Alle .knxprod-Dateien in einem Ordner (inkl. Unterordner) importieren.\n"
            "Bereits vorhandene Produkte (gleicher Hersteller + Bestellnummer) werden "
            "aktualisiert – so lässt sich der Katalog nach einem Parser-Update auffrischen."
        )
        catalog_menu.addSeparator()
        self._show_hidden_action = catalog_menu.addAction("Ausgeblendete anzeigen")
        self._show_hidden_action.setCheckable(True)
        self._show_hidden_action.setToolTip(
            "Ausgeblendete Produkte grau anzeigen, um sie wieder einzublenden"
        )
        self._show_hidden_action.toggled.connect(lambda _on: self._refresh_results())
        catalog_menu.addSeparator()
        act = catalog_menu.addAction("Online-Katalog aktualisieren", self._update_online_catalog)
        act.setToolTip(
            "Lädt die aktuelle Produktliste von KNiX Arranger aus dem Internet\n"
            "und nimmt neue Produkte in den Katalog auf (blau dargestellt).\n"
            "Eigene KNXPROD-Importe bleiben unverändert."
        )
        btn_catalog = QPushButton("Katalog")
        btn_catalog.setObjectName("secondary")
        btn_catalog.setMenu(catalog_menu)
        filter_layout.addWidget(btn_catalog)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # --- Typenbaum | Ergebnis-Tabelle + Infobereich ---
        splitter = QSplitter(Qt.Horizontal)
        self._type_tree = QTreeWidget()
        self._type_tree.setHeaderHidden(True)
        self._type_tree.setMinimumWidth(200)
        self._type_tree.itemSelectionChanged.connect(self._on_type_selected)
        splitter.addWidget(self._type_tree)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        result_row = QHBoxLayout()
        self._result_label = QLabel("0 Produkte gefunden")
        self._result_label.setObjectName("subtitle")
        result_row.addWidget(self._result_label)
        result_row.addStretch()
        drop_hint = QLabel("KNXPROD hierher ziehen oder mit Strg+V einfügen")
        drop_hint.setStyleSheet("color: #666;")
        result_row.addWidget(drop_hint)
        self._online_label = QLabel()
        self._online_label.setStyleSheet("color: #666;")
        result_row.addWidget(self._online_label)
        right_layout.addLayout(result_row)
        self._update_online_label()

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(_COL_NAME, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._set_column_widths(self._table)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_table_context_menu)
        right_layout.addWidget(self._table)

        self._details = QLabel()
        self._details.setWordWrap(True)
        self._details.setTextFormat(Qt.RichText)
        self._details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._details.setMinimumHeight(64)
        self._details.setStyleSheet("padding: 6px; border-top: 1px solid #ddd;")
        right_layout.addWidget(self._details)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 760])
        layout.addWidget(splitter, 1)

        # --- Menge ---
        qty_layout = QHBoxLayout()
        qty_layout.addWidget(QLabel("Menge:"))
        self._qty_spin = QSpinBox()
        self._qty_spin.setMinimum(1)
        self._qty_spin.setMaximum(999)
        self._qty_spin.setValue(1)
        qty_layout.addWidget(self._qty_spin)
        qty_layout.addStretch()
        layout.addLayout(qty_layout)

        # --- Linienauswahl (optional, nur wenn Topologie vorhanden) ---
        if self._topology and self._topology.areas:
            line_layout = QHBoxLayout()
            line_layout.addWidget(QLabel("Linie:"))
            self._line_combo = QComboBox()
            self._line_combo.addItem("(keine Zuweisung)", None)
            for area in self._topology.areas:
                for line in area.lines:
                    label = f"{area.area_number}.{line.line_number} – {line.name}"
                    self._line_combo.addItem(label, line)
            self._line_combo.currentIndexChanged.connect(self._on_line_changed)
            line_layout.addWidget(self._line_combo)
            line_layout.addStretch()
            layout.addLayout(line_layout)
        else:
            self._line_combo = None

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_ok = QPushButton("Übernehmen")
        self._btn_ok.setEnabled(False)
        self._btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_ok)

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._recent_table.selectionModel().selectionChanged.connect(
            self._on_recent_selection_changed
        )

    # ------------------------------------------------------------------ Zuletzt verwendet

    def _populate_recent_table(self):
        """Befüllt "Zuletzt verwendet": die gespeicherten Einträge aufgelöst
        über den Katalog (aktueller Typ, Kanäle, KOs), ohne Doppelte (z.B.
        derselbe Hersteller in zwei Schreibweisen)."""
        from ...utils.manufacturers import product_key
        self._recent_table.setSortingEnabled(False)
        self._recent_table.setRowCount(0)
        _highlight = QColor("#fff9e6")  # zartes Gelb als Unterschied zur Haupttabelle
        bold = QFont()
        bold.setBold(True)

        seen = set()
        for entry in load_recent():
            stored = ProductSuggestion(
                manufacturer=entry.get("manufacturer", ""),
                order_number=entry.get("order_number", ""),
                product_name=entry.get("product_name", ""),
                channels=entry.get("channels", 0),
                category=entry.get("category", ""),
                actor_type=entry.get("actor_type", ""),
                sensor_type=entry.get("sensor_type", ""),
                device_type=entry.get("device_type", ""),
            )
            prod = self._catalog_product(stored) or stored
            key = product_key(prod.manufacturer, prod.order_number, prod.product_name)
            if key in seen:
                continue
            seen.add(key)
            row = self._recent_table.rowCount()
            self._recent_table.insertRow(row)
            items = [
                QTableWidgetItem(prod.display_type()),
                QTableWidgetItem(prod.manufacturer),
                QTableWidgetItem(prod.order_number),
                QTableWidgetItem(prod.product_name),
                _NumberItem(prod.channels),
                _NumberItem(prod.co_count),
            ]
            for col, item in enumerate(items):
                item.setData(Qt.UserRole, prod)
                item.setBackground(_highlight)
                self._recent_table.setItem(row, col, item)
            if prod.manufacturer in self._preferred:
                for item in items:
                    item.setFont(bold)

        visible = self._recent_table.rowCount() > 0
        self._recent_group.setVisible(visible)

    def _on_recent_selection_changed(self):
        rows = self._recent_table.selectionModel().selectedRows()
        if not rows:
            return
        prod: ProductSuggestion = self._recent_table.item(rows[0].row(), 0).data(Qt.UserRole)
        if prod:
            # "Zuletzt verwendet" speichert nur Stammdaten: das Katalogprodukt
            # samt KOs verwenden (sonst ging z.B. das Revox ohne KOs ins Projekt)
            self._selected = self._catalog_product(prod) or prod
            self._btn_ok.setEnabled(True)
            self._update_details(self._selected)
            # Selektion in Haupttabelle aufheben
            self._table.blockSignals(True)
            self._table.clearSelection()
            self._table.blockSignals(False)

    def _catalog_product(self, prod: ProductSuggestion) -> ProductSuggestion | None:
        """Katalogeintrag (mit KOs) zu einem Eintrag aus "Zuletzt verwendet";
        Hersteller in anderer Schreibweise gilt als derselbe."""
        from ...utils.manufacturers import product_key
        wanted = product_key(prod.manufacturer, prod.order_number, prod.product_name)
        return next((r for r in self._search_service.search_all(
                         prod.order_number, include_hidden=True)
                     if product_key(r.manufacturer, r.order_number, r.product_name)
                     == wanted), None)

    def _on_recent_double_click(self):
        if self._selected:
            self.accept()

    def accept(self):
        """Speichert die Auswahl als 'zuletzt verwendet' und schliesst den Dialog."""
        if self._selected:
            prod = self._selected
            add_recent({
                "order_number": prod.order_number,
                "manufacturer": prod.manufacturer,
                "product_name": prod.product_name,
                "channels": prod.channels,
                "category": prod.category,
                "actor_type": prod.actor_type,
                "sensor_type": prod.sensor_type,
                "device_type": prod.device_type,
            })
        super().accept()

    # ------------------------------------------------------------------ Suche

    def _refresh_results(self):
        query = self._search_edit.text().strip()
        mfr_filter = self._mfr_combo.currentText()
        if mfr_filter == "Alle":
            mfr_filter = ""

        results = self._search_service.search_all(
            query=query,
            preferred_manufacturers=self._preferred if self._preferred else None,
            include_hidden=self._show_hidden_action.isChecked(),
        )
        if mfr_filter:
            results = [r for r in results if r.manufacturer == mfr_filter]

        # Der Typenbaum zählt Suche und Hersteller, aber nicht den Typ selbst
        self._base_results = results
        self._populate_type_tree(results)
        self._apply_type_filter()

    def _apply_type_filter(self):
        kind, name = self._type_filter
        results = self._base_results
        if kind == "group":
            results = [r for r in results if _group_of(r) == name]
        elif kind == "type":
            results = [r for r in results if r.display_type() == name]
        self._all_results = results
        self._populate_table(results)

    def _populate_type_tree(self, results: list[ProductSuggestion]):
        """Gruppen und Typen mit Anzahl; die Auswahl bleibt erhalten."""
        counts: dict[str, dict[str, int]] = {}
        for r in results:
            group = counts.setdefault(_group_of(r), {})
            group[r.display_type()] = group.get(r.display_type(), 0) + 1
        tree = self._type_tree
        tree.blockSignals(True)
        tree.clear()
        root = QTreeWidgetItem(tree, [f"Alle Produkte ({len(results)})"])
        root.setData(0, Qt.UserRole, ("", ""))
        selected = root
        for group, _types in TYPE_GROUPS:
            types = counts.get(group, {})
            if not types and self._type_filter != ("group", group):
                continue
            g_item = QTreeWidgetItem(tree, [f"{group} ({sum(types.values())})"])
            g_item.setData(0, Qt.UserRole, ("group", group))
            if self._type_filter == ("group", group):
                selected = g_item
            order = {t: i for i, t in enumerate(_GROUP_TYPES.get(group, ()))}
            for device_type in sorted(types, key=lambda t: (order.get(t, 99), t)):
                t_item = QTreeWidgetItem(g_item, [f"{device_type} ({types[device_type]})"])
                t_item.setData(0, Qt.UserRole, ("type", device_type))
                if self._type_filter == ("type", device_type):
                    selected = t_item
                    g_item.setExpanded(True)
            if self._type_filter == ("group", group):
                g_item.setExpanded(True)
        if self._type_filter[0] == "type" and selected is root:
            # Typ ohne Treffer (z.B. nach Suche): als leere Zeile behalten
            kind, name = self._type_filter
            selected = QTreeWidgetItem(tree, [f"{name} (0)"])
            selected.setData(0, Qt.UserRole, (kind, name))
        tree.setCurrentItem(selected)
        tree.blockSignals(False)

    def _set_column_widths(self, table: QTableWidget) -> None:
        table.setItemDelegate(_ReadableSelectionDelegate(table))
        for col, width in ((_COL_TYPE, 170), (_COL_MFR, 120), (_COL_ORDER, 150),
                           (_COL_CH, 60), (_COL_KO, 60)):
            table.setColumnWidth(col, width)

    def has_type_preselection(self) -> bool:
        """Typ oder Gruppe im Typenbaum vorausgewählt (z.B. aus der Materialliste)."""
        return bool(self._type_filter[0])

    def _on_type_selected(self):
        item = self._type_tree.currentItem()
        self._type_filter = item.data(0, Qt.UserRole) if item else ("", "")
        self._apply_type_filter()

    def _populate_table(self, results: list[ProductSuggestion]):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        bold = QFont()
        bold.setBold(True)
        italic_grey = QFont()
        italic_grey.setItalic(True)

        for row, prod in enumerate(results):
            self._table.insertRow(row)
            device_type = prod.display_type()
            name_text = prod.product_name
            tooltip = ""
            if prod.superseded_by:
                name_text += "  ⚠ veraltet"
                tooltip = f"Ersetzt durch Bestellnummer: {prod.superseded_by}"

            items = [
                QTableWidgetItem(device_type),
                QTableWidgetItem(prod.manufacturer),
                QTableWidgetItem(prod.order_number),
                QTableWidgetItem(name_text),
                _NumberItem(prod.channels),
                _NumberItem(prod.co_count),
            ]
            items[_COL_KO].setToolTip("Kommunikationsobjekte aus dem KNXPROD-Import"
                                      if prod.co_count else
                                      "Keine KOs – GAs entstehen aus dem Gewerk")
            for col, item in enumerate(items):
                # Index in self._all_results, bleibt beim Sortieren erhalten
                item.setData(Qt.UserRole, row)
                self._table.setItem(row, col, item)

            # Bevorzugte Hersteller fett
            if prod.manufacturer in self._preferred:
                for item in items:
                    item.setFont(bold)

            # Produkte aus dem Online-Katalog blau (FA-1303/1402)
            if prod.online and not prod.superseded_by:
                for item in items:
                    item.setForeground(_ONLINE_COLOR)
                    item.setToolTip("Aus dem Online-Katalog")

            # Veraltete und ausgeblendete Produkte grau/kursiv absetzen
            if prod.superseded_by or prod.hidden:
                if prod.hidden:
                    items[_COL_NAME].setText(name_text + "  (ausgeblendet)")
                    tooltip = "Ausgeblendet – Rechtsklick: wieder einblenden"
                for item in items:
                    item.setFont(italic_grey)
                    item.setForeground(QColor("#757575"))
                    item.setToolTip(tooltip)

        self._table.setSortingEnabled(True)
        n = len(results)
        self._result_label.setText(
            f"{n} Produkt{'e' if n != 1 else ''} gefunden"
        )
        self._btn_ok.setEnabled(False)
        self._selected = None
        self._update_details(None)

    # ------------------------------------------------------------------ Online-Katalog

    def _update_online_label(self):
        status = self._search_service.online_catalog_status()
        if not status.fetched_at:
            self._online_label.setText("Online-Katalog: noch nicht geladen")
            return
        stand = status.updated or status.fetched_at[:10]
        self._online_label.setText(
            f"Online-Katalog: {len(status.products)} Produkte, Stand {stand}"
        )

    def _update_online_catalog(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = self._search_service.update_online_catalog()
        finally:
            QApplication.restoreOverrideCursor()

        if not result.ok:
            QMessageBox.warning(
                self, "Online-Katalog",
                "Der Online-Katalog konnte nicht geladen werden.\n\n"
                f"{result.error}\n\n"
                "Es werden weiterhin die zuletzt geladenen Produkte angezeigt.",
            )
            return

        current_mfrs = {
            self._mfr_combo.itemText(i)
            for i in range(self._mfr_combo.count())
        }
        for prod in result.products:
            mfr = prod.get("manufacturer", "")
            if mfr not in current_mfrs:
                self._mfr_combo.addItem(mfr)
                current_mfrs.add(mfr)

        self._refresh_results()
        self._update_online_label()
        msg = f"{len(result.products)} Produkte aus dem Online-Katalog geladen."
        if result.skipped:
            msg += f"\n{result.skipped} unvollständige Einträge wurden übersprungen."
        QMessageBox.information(self, "Online-Katalog", msg)

    # ------------------------------------------------------------------ Auswahl

    def _on_selection_changed(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._btn_ok.setEnabled(False)
            self._selected = None
            return
        # Selektion in Zuletzt-verwendet-Tabelle aufheben
        self._recent_table.blockSignals(True)
        self._recent_table.clearSelection()
        self._recent_table.blockSignals(False)

        self._selected = self._product_at_row(rows[0].row())
        self._btn_ok.setEnabled(self._selected is not None)
        self._update_details(self._selected)

    def _on_double_click(self):
        if self._selected:
            self.accept()

    # ------------------------------------------------------------------ Veraltet-Markierung

    def _product_at_row(self, row: int) -> ProductSuggestion | None:
        """ProductSuggestion einer Tabellenzeile (Index im UserRole, bleibt
        beim Sortieren erhalten)."""
        item = self._table.item(row, 0)
        index = item.data(Qt.UserRole) if item else None
        if index is None or not 0 <= index < len(self._all_results):
            return None
        return self._all_results[index]

    def _update_details(self, prod: ProductSuggestion | None):
        """Infobereich: Quelle, KOs, Kanäle in der Benennung des Herstellers,
        ETS-Kennung, Secure, veraltet/ausgeblendet."""
        if prod is None:
            self._details.setText("<span style='color:#666'>Produkt wählen, um Details "
                                  "zu sehen.</span>")
            return
        from html import escape
        from ...services.product_zones import zone_label, zone_scheme, zones_of
        parts = [f"<b>{escape(prod.product_name)}</b> · {escape(prod.manufacturer)} "
                 f"{escape(prod.order_number)} · {escape(prod.display_type())}"]
        facts = []
        zones = []
        if prod.co_count:
            facts.append(f"KNXPROD-Import, {prod.co_count} KOs")
            product = {"com_objects": prod.com_objects}
            zones = zones_of(product)
            if zones:
                scheme = zone_scheme(product)
                plural = {"Kanal": "Kanäle", "Ausgang": "Ausgänge", "Raum": "Räume",
                          "Zone": "Zonen", "Kanal C": "Kanäle", "Motor": "Motoren"}.get(scheme.label, scheme.label)
                facts.append(f"{len(zones)} {plural} im Gerät: "
                             f"{escape(zone_label(product, zones[0]))} – "
                             f"{escape(zone_label(product, zones[-1]))}")
        elif prod.online:
            facts.append("Online-Katalog, ohne KOs")
        else:
            facts.append("ohne KOs – GAs entstehen aus dem Gewerk")
        if prod.channels and not zones:
            facts.append(f"{prod.channels} Kanäle laut Produktname")
        if prod.secure_supported:
            facts.append("KNX Secure")
        if prod.superseded_by:
            facts.append(f"veraltet, ersetzt durch {escape(prod.superseded_by)}")
        if prod.hidden:
            facts.append("ausgeblendet")
        parts.append(" · ".join(facts))
        if prod.product_ref_id:
            parts.append(f"<span style='color:#666'>ETS: {escape(prod.product_ref_id)}</span>")
        self._details.setText("<br>".join(parts))

    def _show_table_context_menu(self, pos):
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        self._table.selectRow(row)
        prod = self._product_at_row(row)
        if prod is None:
            return

        menu = QMenu(self)
        act_edit = menu.addAction("Bearbeiten…")
        act_hide = menu.addAction("Wieder einblenden" if prod.hidden else "Ausblenden")
        menu.addSeparator()
        if prod.superseded_by:
            action = menu.addAction("Veraltet-Markierung entfernen")
        else:
            action = menu.addAction("Als veraltet markieren…")
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if chosen == act_edit:
            self._edit_product(prod)
            return
        if chosen == act_hide:
            self._search_service.set_hidden(prod.manufacturer, prod.order_number,
                                            not prod.hidden, prod.product_name)
            self._refresh_results()
            return
        if chosen != action:
            return

        if prod.superseded_by:
            self._search_service.mark_superseded(prod.manufacturer, prod.order_number, "",
                                                prod.product_name)
            self._refresh_results()
            return

        self._mark_product_superseded(prod)

    def _edit_product(self, prod: ProductSuggestion):
        """Stammdaten des Produkts bearbeiten (ProductEditDialog)."""
        from .product_edit_dialog import ProductEditDialog
        entry = self._search_service.find_product(
            prod.manufacturer, prod.order_number, prod.product_name)
        if entry is None:
            return
        dlg = ProductEditDialog(entry, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            product = self._search_service.edit_product(
                prod.manufacturer, prod.order_number, dlg.changes(), prod.product_name)
        except ValueError as e:
            QMessageBox.warning(self, "Produkt bearbeiten", str(e))
            return
        if product and self._mfr_combo.findText(product["manufacturer"]) < 0:
            self._mfr_combo.addItem(product["manufacturer"])
        self._refresh_results()

    def _mark_product_superseded(self, prod: ProductSuggestion):
        """Fragt das Nachfolgeprodukt ab (gleicher Hersteller) und markiert
        `prod` entsprechend als veraltet."""
        candidates = [
            p for p in self._search_service.products_for_manufacturer(prod.manufacturer)
            if p.get("order_number", "") != prod.order_number
        ]
        if not candidates:
            QMessageBox.information(
                self, "Kein Nachfolger verfügbar",
                f"Für Hersteller \"{prod.manufacturer}\" gibt es im Katalog kein "
                "anderes Produkt, das als Nachfolger gewählt werden könnte.",
            )
            return

        labels = [
            f"{c.get('order_number', '')} – {c.get('product_name', '')}"
            for c in candidates
        ]
        choice, ok = QInputDialog.getItem(
            self, "Als veraltet markieren",
            f"\"{prod.product_name}\" ({prod.order_number}) ist ersetzt durch:",
            labels, 0, False,
        )
        if not ok or not choice:
            return

        successor_order_number = candidates[labels.index(choice)].get("order_number", "")
        self._search_service.mark_superseded(
            prod.manufacturer, prod.order_number, successor_order_number, prod.product_name,
        )
        self._refresh_results()

    def _on_line_changed(self, index: int):
        if self._line_combo:
            self._selected_line = self._line_combo.currentData()

    def get_selected_line(self) -> Line | None:
        """Gibt die gewählte Linie zurück (None wenn keine Zuweisung)."""
        return self._selected_line

    # ------------------------------------------------------------------ KNXPROD

    def _import_knxprod(self):
        filepaths, _ = QFileDialog.getOpenFileNames(
            self, "KNXPROD-Dateien importieren (Mehrfachauswahl möglich)", "",
            "KNX Produktdatenbankdateien (*.knxprod);;Alle Dateien (*.*)",
        )
        if filepaths:
            self._import_paths(filepaths)

    def _import_knxprod_folder(self):
        """
        Importiert alle .knxprod-Dateien eines Ordners (inkl. Unterordner) in
        einem Rutsch. Bereits vorhandene Produkte (gleicher Hersteller +
        Bestellnummer) werden dabei überschrieben (siehe ProductSearchService._upsert)
        -- so lässt sich der Katalog nach einer Parser-Korrektur einfach auffrischen,
        indem derselbe Ordner erneut importiert wird.
        """
        folder = QFileDialog.getExistingDirectory(
            self, "Ordner mit KNXPROD-Dateien wählen (inkl. Unterordner)",
            _default_products_folder(),
        )
        if not folder:
            return
        filepaths = sorted(
            os.path.join(root, fn)
            for root, _dirs, files in os.walk(folder)
            for fn in files if fn.lower().endswith(".knxprod")
        )
        if not filepaths:
            QMessageBox.information(
                self, "Keine Dateien gefunden",
                f"Im Ordner \"{folder}\" wurden keine .knxprod-Dateien gefunden.",
            )
            return
        self._import_paths(filepaths, folder)

    def _import_paths(self, filepaths: list[str], base_folder: str = "") -> int:
        """Importiert KNXPROD-Dateien in den Katalog (Datei-/Ordnerauswahl,
        Einfügen, Ziehen). Gibt die Anzahl importierter Produkte zurück.
        Bereits vorhandene Produkte (gleicher Hersteller + Bestellnummer)
        werden aktualisiert."""
        progress = None
        if len(filepaths) > 3:
            progress = QProgressDialog(
                "Importiere KNXPROD-Dateien…", "Abbrechen", 0, len(filepaths), self,
            )
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)

        svc = KnxprodCatalogService()
        all_products = []
        errors: list[tuple[str, str]] = []
        empty: list[str] = []
        processed = 0
        for filepath in filepaths:
            name = (os.path.relpath(filepath, base_folder) if base_folder
                    else os.path.basename(filepath))
            if progress is not None:
                progress.setLabelText(f"Importiere: {name}")
                progress.setValue(processed)
                QApplication.processEvents()
                if progress.wasCanceled():
                    break
            try:
                products = svc.import_file(filepath)
            except ValueError as e:
                errors.append((name, str(e)))
            else:
                if products:
                    all_products.extend(products)
                else:
                    empty.append(name)
            processed += 1
        if progress is not None:
            progress.setValue(len(filepaths))

        problems = ([f"• {n}: {e}" for n, e in errors]
                    + [f"• {n}: keine Produktdaten gefunden" for n in empty])
        # Der Import kann dauern: ohne explizites Aktivieren bliebe der Dialog
        # im Hintergrund, falls der Nutzer das Fenster gewechselt hat
        self.raise_()
        self.activateWindow()
        if not all_products:
            QMessageBox.critical(
                self, "Import-Fehler",
                f"Keine der {processed} Datei(en) konnte importiert werden:\n\n"
                + "\n".join(problems),
            )
            return 0

        # In den Katalog aufnehmen -- ein Schreibvorgang für alle Produkte,
        # persistiert dauerhaft (%APPDATA%), nicht nur für diese Dialog-Instanz
        self._search_service.add_products([p.to_catalog_dict() for p in all_products])
        current_mfrs = {self._mfr_combo.itemText(i) for i in range(self._mfr_combo.count())}
        for prod in all_products:
            if prod.manufacturer not in current_mfrs:
                self._mfr_combo.addItem(prod.manufacturer)
                current_mfrs.add(prod.manufacturer)
        self._refresh_results()

        ok_count = processed - len(errors) - len(empty)
        summary = (f"{len(all_products)} Produkte aus {ok_count} von {processed} "
                   f"Datei(en) importiert bzw. aktualisiert.")
        if processed < len(filepaths):
            summary += f"\n\nAbgebrochen nach {processed} von {len(filepaths)} Datei(en)."
        if problems:
            summary += "\n\nÜbersprungen:\n" + "\n".join(problems)
        QMessageBox.information(self, "Import erfolgreich", summary)
        return len(all_products)

    # ── Einfügen (Strg+V) und Ziehen ──

    def _paste_knxprod(self) -> bool:
        """Importiert .knxprod-Dateien aus der Zwischenablage (im Explorer
        kopiert); False, wenn keine darin sind."""
        paths = _knxprod_paths(QApplication.clipboard().mimeData())
        if not paths:
            return False
        self._import_paths(paths)
        return True

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste) and self._paste_knxprod():
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        # Im Suchfeld fügt Strg+V Text ein -- ausser es sind KNXPROD-Dateien kopiert
        if (obj is self._search_edit and event.type() == QEvent.KeyPress
                and event.matches(QKeySequence.Paste) and self._paste_knxprod()):
            return True
        return super().eventFilter(obj, event)

    def dragEnterEvent(self, event):
        if _knxprod_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = _knxprod_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self._import_paths(paths)

    # ------------------------------------------------------------------ Ergebnis

    @property
    def selected_product(self) -> ProductSuggestion | None:
        return self._selected

    def get_material_entry(self) -> MaterialEntry | None:
        """
        Gibt die ausgewählte Produktauswahl als MaterialEntry zurück.
        Kann nach accept() abgerufen werden.
        """
        if not self._selected:
            return None

        prod = self._selected
        qty = self._qty_spin.value()

        # MaterialEntry-Kategorie aus Produkt ableiten
        from ...services.product_classifier import type_group
        if prod.device_type in _DEVICE_TYPE_TO_ML_CAT:
            ml_cat = _DEVICE_TYPE_TO_ML_CAT[prod.device_type]
        elif prod.category == "actor":
            ml_cat = "Aktor"
        elif prod.category == "sensor":
            ml_cat = "Sensor"
        elif type_group(prod.device_type) == "Gateways & Schnittstellen":
            ml_cat = "Gateway / Schnittstellen"
        else:
            ml_cat = "Sonstiges"

        entry = MaterialEntry(
            quantity=qty,
            category=ml_cat,
            device_type=prod.display_type(),
            manufacturer=prod.manufacturer,
            order_number=prod.order_number,
            product_name=prod.product_name,
            unit_price=0.0,
            source="manual",
            assigned_channels=prod.channels,
        )

        if self._selected_line and self._topology:
            area_num = ""
            for area in self._topology.areas:
                if self._selected_line in area.lines:
                    area_num = str(area.area_number)
                    break
            entry.line_id = self._selected_line.id
            entry.line_name = (
                f"{area_num}.{self._selected_line.line_number}"
                f" {self._selected_line.name}".strip()
            )

        return entry
