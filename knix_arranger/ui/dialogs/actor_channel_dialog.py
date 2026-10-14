"""
Kanäle und KOs eines Aktors/Gateways zuordnen (Materialliste).

Oben: Stromkreise des Geräts -> Kanal im Gerät (Benennung des Herstellers,
z.B. "Kanal C", "Ausgang 5"). Unten: für den gewählten Stromkreis je GA,
mit welchem KO des Kanals sie verknüpft wird -- oder «nicht verknüpfen».
KOs, die niemand braucht, bleiben frei. Siehe services/actor_channels.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...services.actor_channels import (
    device_channels, device_circuits, device_com_objects, omit_functions, suggested_co_map,
    unneeded_functions,
)

_NOT_LINKED = -1   # KO-Nummern beginnen teils bei 0


def ko_text(co) -> str:
    text = co.name if co.object_function in co.name else \
        f"{co.name} – {co.object_function}".strip(" –")
    return f"{co.object_number}: {text}"


def ko_combo(cos: list, others: list) -> QComboBox:
    """Auswahl: «nicht verknüpfen», die KOs des Kanals, dann die übrigen
    des Geräts; durchsuchbar (Tippen filtert, auch mitten im Text)."""
    combo = QComboBox()
    combo.addItem("— nicht verknüpfen", _NOT_LINKED)
    for co in cos:
        combo.addItem(ko_text(co), co.object_number)
    if others:
        if cos:
            combo.insertSeparator(combo.count())
        for co in others:
            combo.addItem(ko_text(co), co.object_number)
    combo.setEnabled(bool(cos or others))
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.completer().setFilterMode(Qt.MatchContains)
    combo.completer().setCompletionMode(QCompleter.PopupCompletion)
    return combo


class ActorChannelDialog(QDialog):
    """devices: Geräte des Materiallisten-Eintrags (gleiches Produkt)."""

    def __init__(self, project, devices: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kanäle und KOs zuordnen")
        self.setMinimumSize(760, 560)
        self._project = project
        self._devices = devices
        # Je Gerät: Stromkreise, Kanäle, gewählter Kanal und KO-Auswahl
        self._state: dict[str, dict] = {}
        self._device = None
        self._circuit = None

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Gerät:"))
        self._device_combo = QComboBox()
        for device in devices:
            text = f"{device.physical_address}  {device.manufacturer} {device.order_number}".strip()
            self._device_combo.addItem(f"{text} – {device.product_name or device.product}",
                                       device.id)
        self._device_combo.setVisible(len(devices) > 1)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)
        top.addWidget(self._device_combo, 1)
        self._device_label = QLabel()
        top.addWidget(self._device_label, 1)
        layout.addLayout(top)

        self._circuit_table = QTableWidget(0, 3)
        self._circuit_table.setHorizontalHeaderLabels(["Stromkreis", "Kanal im Gerät", "GAs"])
        self._circuit_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._circuit_table.setColumnWidth(1, 170)
        self._circuit_table.setColumnWidth(2, 50)
        self._circuit_table.verticalHeader().setVisible(False)
        self._circuit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._circuit_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._circuit_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._circuit_table.itemSelectionChanged.connect(self._on_circuit_selected)
        layout.addWidget(self._circuit_table, 3)

        self._channel_info = QLabel()
        self._channel_info.setWordWrap(True)
        layout.addWidget(self._channel_info)

        self._co_group = QGroupBox("KOs des Stromkreises")
        co_layout = QVBoxLayout(self._co_group)
        self._co_hint = QLabel()
        self._co_hint.setWordWrap(True)
        self._co_hint.setStyleSheet("color: #666;")
        co_layout.addWidget(self._co_hint)
        self._co_table = QTableWidget(0, 3)
        self._co_table.setHorizontalHeaderLabels(["GA-Funktion", "GA", "KO im Kanal"])
        self._co_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._co_table.setColumnWidth(0, 160)
        self._co_table.setColumnWidth(1, 80)
        self._co_table.verticalHeader().setVisible(False)
        self._co_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        co_layout.addWidget(self._co_table)
        layout.addWidget(self._co_group, 2)

        # Nur so viele GAs wie nötig: Funktionen ohne KO im Kanal weglassen
        # (nur geplante, noch nicht in die ETS übertragene Projekte)
        self._omit_check = QCheckBox("Nicht benötigte Funktionen weglassen")
        self._omit_check.setToolTip(
            "Funktionen, für die der Kanal keinen KO hat (z.B. DIM/WERT eines\n"
            "Lichtkreises an einem Schaltaktor), erhalten keine GA. Ihr Platz im\n"
            "Block bleibt als Reserve frei – die übrigen Adressen ändern sich nicht,\n"
            "die Lücke lässt sich später füllen (z.B. Licht -> Licht dimmbar).")
        self._omit_check.toggled.connect(lambda _on: self._update_omit_info())
        self._omit_check.setVisible(not project.addresses_fixed)
        layout.addWidget(self._omit_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_device_changed()

    # ── Zustand je Gerät ──

    def _state_for(self, device) -> dict:
        if device.id not in self._state:
            circuits = device_circuits(self._project, device)
            channels = device_channels(device, fallback_count=len(circuits))
            by_number = {ch.number: ch for ch in channels}
            channel_sel = {c.key: (device.channel_map or {}).get(c.key) or c.channel
                           for c in circuits}
            co_sel = {}
            for c in circuits:
                saved = (device.co_map or {}).get(c.key)
                co_sel[c.key] = (dict(saved) if saved is not None
                                 else suggested_co_map(by_number.get(channel_sel[c.key]), c))
            self._state[device.id] = {"circuits": circuits, "channels": channels,
                                      "all_cos": device_com_objects(device),
                                      "by_number": by_number, "channel": channel_sel,
                                      "co": co_sel}
        return self._state[device.id]

    def _on_device_changed(self):
        index = max(0, self._device_combo.currentIndex())
        if not self._devices:
            return
        self._device = self._devices[index]
        state = self._state_for(self._device)
        d = self._device
        self._device_label.setText(
            "" if len(self._devices) > 1 else
            f"<b>{d.physical_address}</b> {d.manufacturer} {d.order_number} – "
            f"{d.product_name or d.product}")
        table = self._circuit_table
        table.blockSignals(True)
        table.setRowCount(0)
        for row, circuit in enumerate(state["circuits"]):
            table.insertRow(row)
            item = QTableWidgetItem(circuit.label)
            item.setData(Qt.UserRole, circuit.key)
            table.setItem(row, 0, item)
            combo = QComboBox()
            for ch in state["channels"]:
                combo.addItem(ch.label, ch.number)
            if combo.findData(state["channel"][circuit.key]) < 0:
                combo.addItem(f"Kanal {state['channel'][circuit.key]}",
                              state["channel"][circuit.key])
            combo.setCurrentIndex(combo.findData(state["channel"][circuit.key]))
            combo.currentIndexChanged.connect(
                lambda _i, c=circuit, cb=combo: self._on_channel_changed(c, cb.currentData()))
            table.setCellWidget(row, 1, combo)
            gas = QTableWidgetItem(str(len(circuit.functions)))
            gas.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, 2, gas)
        table.blockSignals(False)
        self._update_channel_info()
        if table.rowCount():
            table.selectRow(0)
        else:
            self._circuit = None
            self._show_cos()

    def _on_channel_changed(self, circuit, number: int):
        state = self._state_for(self._device)
        state["channel"][circuit.key] = number
        # Neuer Kanal: KOs neu vorschlagen
        state["co"][circuit.key] = suggested_co_map(state["by_number"].get(number), circuit)
        self._update_channel_info()
        if self._circuit is circuit:
            self._show_cos()

    def _update_channel_info(self):
        state = self._state_for(self._device)
        chosen = list(state["channel"].values())
        free = [ch.label for ch in state["channels"] if ch.number not in chosen]
        doubles = sorted({state["by_number"][n].label if n in state["by_number"] else str(n)
                          for n in chosen if chosen.count(n) > 1})
        self._update_omit_info()
        text = f"Frei: {', '.join(free)}" if free else "Alle Kanäle belegt."
        if doubles:
            text += (f"<br><span style='color:#b26a00'>⚠ Mehrfach vergeben: "
                     f"{', '.join(doubles)}</span>")
        self._channel_info.setText(text)

    def _unneeded(self, device) -> dict[str, list[str]]:
        """Stromkreis -> Funktionen ohne KO im gewählten Kanal."""
        state = self._state_for(device)
        result = {}
        for circuit in state["circuits"]:
            channel = state["by_number"].get(state["channel"][circuit.key])
            functions = unneeded_functions(channel, circuit,
                                           state["co"].get(circuit.key, {}))
            if functions:
                result[circuit.key] = functions
        return result

    def _update_omit_info(self):
        if not hasattr(self, "_omit_check") or self._device is None:
            return
        unneeded = self._unneeded(self._device)
        count = sum(len(f) for f in unneeded.values())
        names = sorted({f for fs in unneeded.values() for f in fs})
        self._omit_check.setEnabled(bool(count))
        self._omit_check.setText(
            f"Nicht benötigte Funktionen weglassen: {count} GAs entfallen "
            f"({', '.join(names)}), Plätze bleiben Reserve" if count else
            "Nicht benötigte Funktionen weglassen (keine erkannt)")

    # ── KOs des gewählten Stromkreises ──

    def _on_circuit_selected(self):
        rows = self._circuit_table.selectionModel().selectedRows()
        state = self._state_for(self._device)
        self._circuit = state["circuits"][rows[0].row()] if rows else None
        self._show_cos()

    def _show_cos(self):
        table = self._co_table
        table.setRowCount(0)
        circuit = self._circuit
        if circuit is None:
            self._co_group.setTitle("KOs des Stromkreises")
            self._co_hint.setText("")
            return
        state = self._state_for(self._device)
        channel = state["by_number"].get(state["channel"][circuit.key])
        self._co_group.setTitle(f"KOs: {circuit.label}"
                                + (f" › {channel.label}" if channel else ""))
        cos = channel.com_objects if channel else []
        # Immer auch die übrigen KOs des Geräts: von Hand wählbar, wenn die
        # Kanäle oder Funktionen des Herstellers nicht erkannt werden
        in_channel = {co.object_number for co in cos}
        others = [co for co in state["all_cos"] if co.object_number not in in_channel]
        if not cos and not others:
            self._co_hint.setText(
                "Keine KOs bekannt (Produkt ohne KNXPROD-Daten) – die KO-Verknüpfung "
                "schlägt wie bisher allgemeine Objekte vor.")
        elif not cos:
            self._co_hint.setText(
                f"Kanal im Gerät nicht erkannt – alle {len(others)} KOs des Geräts zur "
                "Auswahl. Tippen sucht (z.B. «Shutter» oder die KO-Nummer).")
        else:
            self._co_hint.setText(
                "Je GA den KO wählen; «nicht verknüpfen», wenn die GA hier nicht gebraucht "
                f"wird. Oben die {len(cos)} KOs des Kanals, darunter die übrigen des "
                "Geräts; Tippen sucht.")
        selection = state["co"].setdefault(circuit.key, {})
        for row, (function, ga) in enumerate(circuit.functions):
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(function))
            table.setItem(row, 1, QTableWidgetItem(ga))
            combo = ko_combo(cos, others)
            current = selection.get(function)
            index = combo.findData(current) if current is not None else -1
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.currentIndexChanged.connect(
                lambda _i, f=function, cb=combo, sel=selection: (
                    sel.__setitem__(f, cb.currentData()), self._update_omit_info()))
            table.setCellWidget(row, 2, combo)

    # ── Ergebnis ──

    def apply(self) -> int:
        """Schreibt Kanal- und KO-Zuordnung in die bearbeiteten Geräte; mit
        «weglassen» auch die nicht benötigten Funktionen. Gibt die Anzahl
        neu weggelassener Funktionen zurück (dann GAs neu erzeugen)."""
        by_id = {d.id: d for d in self._devices}
        omitted = 0
        for device_id, state in self._state.items():
            device = by_id[device_id]
            device.channel_map = dict(state["channel"])
            has_cos = bool(state["all_cos"])
            # Funktionen ohne gewählten KO ausdrücklich «nicht verknüpfen»:
            # sonst legte die KO-Verknüpfung dafür einen generischen KO an
            # (Schaltaktor: «Dimmen relativ», den es am Gerät nicht gibt)
            functions = {c.key: [f for f, _ga in c.functions] for c in state["circuits"]}
            device.co_map = ({key: {**{f: _NOT_LINKED for f in functions.get(key, [])},
                                    **sel}
                              for key, sel in state["co"].items()}
                             if has_cos else {})
            if not self._omit_check.isHidden() and self._omit_check.isChecked():
                for key, functions in self._unneeded(device).items():
                    omitted += omit_functions(self._project, key, functions)
        return omitted
