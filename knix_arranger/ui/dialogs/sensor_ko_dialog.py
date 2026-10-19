"""
KOs eines Tasters/Sensors den Gruppenadressen zuordnen (Materialliste ›
«Kanäle und KOs zuordnen…» bei Bedienelementen und Sensoren).

Je Gerät jede GA, die es sendet, empfängt oder selbst trägt, mit dem KO des
Geräts -- oder «nicht verknüpfen». Siehe services/sensor_channels. Die
Zuordnung wird je Produkt gemerkt (services/ko_templates) und lässt sich auf
die übrigen Geräte des Eintrags übertragen.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...services.actor_channels import device_com_objects
from ...services.ko_plausibility import ko_variants, sensor_selection_problems
from ...services.ko_templates import (
    apply_sensor_template, load_template, save_template, sensor_template_entries,
)
from ...services.sensor_channels import (
    BRIGHTNESS_ROLE, SENSOR_CO_KEY, SOURCE_KEY, _channel_cos, brightness_sources,
    display_variant, ga_key, split_rocker,
    sensor_co_map, sensor_links, sensor_plan, suggested_sensor_co_map,
)
from .actor_channel_dialog import focus_banner, ko_combo, mark_focus_row
from ...services.ko_size import dpt_bits, size_text


class SensorKoDialog(QDialog):
    """devices: Geräte des Materiallisten-Eintrags (gleiches Produkt), je
    Gerät eine eigene Zuordnung."""

    def __init__(self, project, devices: list, parent=None, focus: tuple | None = None):
        super().__init__(parent)
        self.setWindowTitle("KOs zuordnen")
        self.setMinimumSize(820, 520)
        self._project = project
        self._devices = devices
        # (Geräte-id, ga_key, Funktion, KO-Vorschlag): Sprung aus der Validierung
        self._focus = focus
        self._state: dict[str, dict] = {}
        self._device = None
        self._plan = sensor_plan(project)   # einmal für alle Geräte

        layout = QVBoxLayout(self)
        banner = focus_banner(focus)
        if banner is not None:
            layout.addWidget(banner)
        top = QHBoxLayout()
        top.addWidget(QLabel("Gerät:"))
        self._device_combo = QComboBox()
        for device in devices:
            self._device_combo.addItem(self._device_text(device), device.id)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        top.addWidget(self._device_combo, 1)
        self._copy_button = QPushButton("Auf gleiche Geräte übertragen")
        self._copy_button.setToolTip(
            "Die Zuordnung dieses Geräts für alle übrigen Geräte dieses Eintrags\n"
            "übernehmen (gleiche Taste/Kanal und Funktion)")
        self._copy_button.clicked.connect(self._copy_to_others)
        self._copy_button.setVisible(len(devices) > 1)
        top.addWidget(self._copy_button)
        layout.addLayout(top)

        self._hint = QLabel()
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Taste / Kanal", "Funktion", "GA (Grösse)", "KO"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setColumnWidth(0, 120)
        self._table.setColumnWidth(2, 150)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self._table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if focus is not None:
            device_id, key, _function, suggested = focus
            index = next((i for i, d in enumerate(devices) if d.id == device_id), 0)
            self._device_combo.blockSignals(True)
            self._device_combo.setCurrentIndex(index)
            self._device_combo.blockSignals(False)
            if suggested is not None and suggested >= 0:
                self._state_for(devices[index])["selection"][key] = suggested
        self._on_device_changed()

    @staticmethod
    def _device_text(device) -> str:
        head = " ".join(p for p in (device.physical_address, device.manufacturer,
                                    device.order_number) if p)
        return f"{head} – {device.product_name or device.product}"

    def _state_for(self, device) -> dict:
        if device.id not in self._state:
            links = sensor_links(self._project, device, self._plan)
            all_cos = device_com_objects(device)
            saved = sensor_co_map(device)
            # Vorrang: Auswahl am Gerät, gemerkte Zuordnung des Produkts, Vorschlag
            template = apply_sensor_template(load_template(device), links,
                                             {co.object_number for co in all_cos})
            suggested = suggested_sensor_co_map(device, links, device.communication_objects)
            # Gemerkte KOs, die nicht zur Funktion passen (FA-634), gelten nicht
            variants = ko_variants(device)
            for key in sensor_selection_problems(links, template, variants):
                template.pop(key, None)
            selection = {link.key: saved.get(link.key, template.get(
                link.key, suggested.get(link.key, -1))) for link in links}
            self._state[device.id] = {"links": links, "all_cos": all_cos,
                                      "variants": variants,
                                      "selection": selection, "saved": saved,
                                      "sources": dict((device.co_map or {}).get(SOURCE_KEY)
                                                      or {}),
                                      "brightness": brightness_sources(self._project, device)}
        return self._state[device.id]

    def _on_device_changed(self):
        if not self._devices:
            return
        self._device = self._devices[max(0, self._device_combo.currentIndex())]
        state = self._state_for(self._device)
        links, all_cos = state["links"], state["all_cos"]
        if not all_cos:
            self._hint.setText("Keine KOs bekannt (Produkt ohne KNXPROD-Daten).")
        elif not links:
            self._hint.setText("Dieses Gerät sendet und empfängt keine Gruppenadressen "
                               "(Funktionszuordnung, Gewerk, Zusatzfunktionen).")
        else:
            self._hint.setText(
                f"Je GA den KO des Geräts wählen ({len(all_cos)} KOs; → sendet, ← empfängt); "
                "«nicht verknüpfen», "
                "wenn die GA hier nicht gebraucht wird. Oben die KOs der Taste bzw. des "
                "Kanals, darunter die übrigen; Tippen sucht. Die KO-Nummern hängen in der "
                "ETS von den Parametern ab -- Vorschläge prüfen.")
        table = self._table
        table.setRowCount(0)
        selection = state["selection"]
        for row, link in enumerate(links):
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(link.channel))
            arrow = "←" if link.feedback else "→"
            function = QTableWidgetItem(f"{arrow} {link.function}")
            function.setToolTip(link.ga_designation)
            table.setItem(row, 1, function)
            if link.role == BRIGHTNESS_ROLE.code and len(state["brightness"]) > 1:
                table.setCellWidget(row, 2, self._source_combo(state, link))
            else:
                size = size_text(dpt_bits(link.dpt))
                table.setItem(row, 2, QTableWidgetItem(
                    f"{link.ga_address} ({size})" if size and link.ga_address else link.ga_address))
            # Je Nummer die Variante, die zur Taste und ihrer Belegung passt
            # (Feller: «0: Taste 1 – EIN/AUS, Dimmen» statt «Object 1»)
            variants = state["variants"]
            own_all = _channel_cos(self._device.communication_objects, link.channel)
            own_numbers = list(dict.fromkeys(co.object_number for co in own_all))
            if len(own_numbers) >= len(all_cos):
                own_numbers = []
            split = split_rocker(link, links)
            own = [display_variant([c for c in own_all if c.object_number == n], link, split)
                   for n in own_numbers]
            others = [display_variant(variants.get(co.object_number, [co]), link, split)
                      for co in all_cos if co.object_number not in set(own_numbers)]
            combo = ko_combo(own, others)
            index = combo.findData(selection.get(link.key, -1))
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _i, k=link.key, cb=combo, sel=selection: sel.__setitem__(k, cb.currentData()))
            table.setCellWidget(row, 3, combo)
            if (self._focus is not None and self._device.id == self._focus[0]
                    and link.key == self._focus[1]):
                mark_focus_row(table, row, combo)

    def _copy_to_others(self):
        """Zuordnung des gewählten Geräts auf die übrigen übertragen."""
        if self._device is None:
            return
        state = self._state_for(self._device)
        entries = sensor_template_entries(state["links"], state["selection"])
        for device in self._devices:
            if device is self._device:
                continue
            other = self._state_for(device)
            other["selection"].update(apply_sensor_template(
                entries, other["links"], {co.object_number for co in other["all_cos"]}))
            # Gleiche Helligkeitsquelle je Kanal
            other["sources"].update(state["sources"])
        self._hint.setText(self._hint.text().split("<br>")[0]
                           + f"<br>Übertragen auf {len(self._devices) - 1} weitere Geräte.")

    @staticmethod
    def _source_combo(state: dict, link) -> QComboBox:
        """Quelle der externen Helligkeit: Wetterstation Süd/Ost/West oder
        die Helligkeit eines anderen Melders."""
        combo = QComboBox()
        for ga in state["brightness"]:
            combo.addItem(f"{ga.address}  {ga.function_name}", ga_key(ga))
            combo.setItemData(combo.count() - 1, ga.designation, Qt.ToolTipRole)
        current = next((ga_key(ga) for ga in state["brightness"]
                        if ga.address == link.ga_address), None)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(
            lambda _i, k=link.key, cb=combo: state["sources"].__setitem__(k, cb.currentData()))
        return combo

    def apply(self) -> None:
        """Schreibt die KO-Auswahl in die bearbeiteten Geräte und merkt sie
        für das Produkt; Einträge für GAs, die das Gerät nicht mehr hat,
        bleiben erhalten."""
        by_id = {d.id: d for d in self._devices}
        for device_id, state in self._state.items():
            if not state["all_cos"]:
                continue
            device = by_id[device_id]
            merged = dict(state["saved"])
            merged.update(state["selection"])
            co_map = dict(device.co_map or {})
            co_map[SENSOR_CO_KEY] = merged
            if state["sources"]:
                co_map[SOURCE_KEY] = dict(state["sources"])
            device.co_map = co_map
            save_template(device, sensor_template_entries(state["links"], state["selection"]))
