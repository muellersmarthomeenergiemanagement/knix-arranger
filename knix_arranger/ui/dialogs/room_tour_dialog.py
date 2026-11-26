"""
Rundgang «Räume zuordnen» (FA-3105c): Raum für Raum geführt.
1) In welchem Raum sind Sie?  2) Alle Tasten drücken (KNiX nimmt auf, nur
Tasten-KOs, ohne Grundrauschen)  3) Was gehört in diesen Raum? (Aktorkanäle
nach Gewerk; Kanäle ohne Taster mit «Lasten suchen»: einzeln kurz schalten,
vor Ort bestätigen)  -> Raum abschliessen, nächster Raum.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...services import room_from_bus as rb
from ..styles import COLOR_OK, COLOR_WARNING, TEXT_MUTED
from .room_assign_dialog import NewRoomDialog

_ROOM, _KEYS, _REACT, _DONE = range(4)


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {TEXT_MUTED};")
    return label


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("font-weight: 600; font-size: 15px;")
    return label


class RoomTourDialog(QDialog):

    def __init__(self, project, monitor=None, bus=None, parent=None):
        super().__init__(parent)
        self._project = project
        self._monitor = monitor
        self._bus = bus
        self._plan = rb.analyse(project)
        self._session: rb.RoomSession | None = None
        self._room = None
        self._done_rooms: list[str] = []          # Raum-IDs
        self._listening = False

        self.setWindowTitle("Räume zuordnen – Rundgang")
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        self._progress = QLabel()
        self._progress.setStyleSheet(f"color: {TEXT_MUTED};")
        layout.addWidget(self._progress)
        self._pages = QStackedWidget()
        self._pages.addWidget(self._room_page())
        self._pages.addWidget(self._keys_page())
        self._pages.addWidget(self._react_page())
        self._pages.addWidget(self._done_page())
        layout.addWidget(self._pages, 1)

        nav = QHBoxLayout()
        self._back = QPushButton("Zurück")
        self._back.setObjectName("secondary")
        self._back.clicked.connect(self._go_back)
        self._next = QPushButton()
        self._next.setDefault(True)
        self._next.clicked.connect(self._go_next)
        self._close = QPushButton("Schliessen")
        self._close.setObjectName("secondary")
        self._close.clicked.connect(self.reject)
        nav.addWidget(self._close)
        nav.addStretch(1)
        nav.addWidget(self._back)
        nav.addWidget(self._next)
        layout.addLayout(nav)

        if monitor is not None and getattr(monitor, "listening", False):
            monitor.add_listener(self._on_telegram)
            self._listening = True
        self._show_page(_ROOM)

    # ── Seiten ───────────────────────────────────────────────────────────

    def _room_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_heading("Schritt 1 von 3 – In welchem Raum sind Sie?"))
        layout.addWidget(_muted(
            "Raum wählen oder neu anlegen. Danach drücken Sie im Raum alle Tasten; KNiX "
            "nimmt auf, welche Taster sich melden und welche Aktorkanäle darauf "
            "reagieren."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Raum:"))
        self._room_combo = QComboBox()
        row.addWidget(self._room_combo, 1)
        new_room = QPushButton("Neuer Raum…")
        new_room.setObjectName("secondary")
        new_room.clicked.connect(self._new_room)
        row.addWidget(new_room)
        layout.addLayout(row)
        self._connection = QLabel()
        self._connection.setWordWrap(True)
        layout.addWidget(self._connection)
        layout.addStretch(1)
        return page

    def _keys_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._keys_title = _heading("")
        layout.addWidget(self._keys_title)
        layout.addWidget(_muted(
            "Jede Taste kurz drücken, Präsenzmelder: im Erfassungsbereich bewegen. Es "
            "zählen nur Tasten-Objekte; Messwerte, Meldungen und was schon vor dem Start "
            "regelmässig gesendet wurde, bleiben draussen. Wurde eine Taste im Nachbarraum "
            "gedrückt: markieren und «Gehört nicht hierher»."))
        self._last_press = QLabel()
        self._last_press.setWordWrap(True)
        self._last_press.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._last_press)
        self._pressed = QListWidget()
        layout.addWidget(self._pressed, 1)
        row = QHBoxLayout()
        remove = QPushButton("Gehört nicht hierher")
        remove.setObjectName("secondary")
        remove.clicked.connect(self._remove_pressed)
        row.addWidget(remove)
        row.addStretch(1)
        row.addWidget(QLabel("Von Hand dazunehmen:"))
        self._manual = QComboBox()
        self._manual.setMinimumWidth(280)
        row.addWidget(self._manual)
        add = QPushButton("Dazunehmen")
        add.setObjectName("secondary")
        add.clicked.connect(self._add_manual)
        row.addWidget(add)
        layout.addLayout(row)
        self._ignored = _muted("")
        layout.addWidget(self._ignored)
        return page

    def _react_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._react_title = _heading("")
        layout.addWidget(self._react_title)
        layout.addWidget(_muted(
            "Aktorkanäle, die mit den gedrückten Tastern verknüpft sind oder nach einem "
            "Tastendruck geschaltet bzw. Status gemeldet haben. Anhaken, was wirklich in "
            "diesem Raum ist. Kanäle mit einem anderen Raum sind nicht angehakt. Was kein "
            "Taster auslöst, findet «Lasten suchen»."))
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Aktorkanal", "Herkunft", "Raum bisher"])
        self._tree.setColumnWidth(0, 360)
        self._tree.setColumnWidth(1, 150)
        layout.addWidget(self._tree, 1)
        row = QHBoxLayout()
        self._loads_btn = QPushButton("Lasten suchen…")
        self._loads_btn.setObjectName("secondary")
        self._loads_btn.clicked.connect(self._search_loads)
        row.addWidget(self._loads_btn)
        self._loads_hint = _muted("")
        row.addWidget(self._loads_hint, 1)
        layout.addLayout(row)
        return page

    def _done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._done_title = _heading("")
        layout.addWidget(self._done_title)
        self._done_text = QLabel()
        self._done_text.setWordWrap(True)
        layout.addWidget(self._done_text)
        layout.addWidget(QLabel("Noch ohne Raum:"))
        self._open = QListWidget()
        layout.addWidget(self._open, 1)
        return page

    # ── Ablauf ───────────────────────────────────────────────────────────

    def _show_page(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._back.setVisible(index in (_KEYS, _REACT))
        self._next.setText({_ROOM: "Weiter: Tasten drücken",
                            _KEYS: "Weiter: Was hat reagiert?",
                            _REACT: "Raum abschliessen",
                            _DONE: "Nächster Raum"}[index])
        if index == _ROOM:
            self._fill_rooms()
            if self._listening:
                self._connection.setText("Verbunden – KNiX hört mit, sendet nichts.")
                self._connection.setStyleSheet(f"color: {COLOR_OK};")
            else:
                self._connection.setText(
                    "Ohne Busverbindung: Taster im nächsten Schritt von Hand dazunehmen. "
                    "Für den Rundgang vor Ort im Live-Monitor verbinden und neu öffnen.")
                self._connection.setStyleSheet(f"color: {COLOR_WARNING};")
        self._update_progress()

    def _go_next(self) -> None:
        page = self._pages.currentIndex()
        if page == _ROOM:
            room = self._selected_room()
            if room is None:
                QMessageBox.information(self, "Rundgang",
                                        "Zuerst einen Raum wählen oder «Neuer Raum…» anlegen.")
                return
            self._room = room
            history = self._monitor.history() if self._listening and hasattr(
                self._monitor, "history") else ()
            self._session = rb.RoomSession(self._plan, history)
            label = rb.room_label(self._project, room.id)
            self._keys_title.setText(f"Schritt 2 von 3 – {label}: Drücken Sie alle Tasten")
            self._last_press.setText("Warte auf den ersten Tastendruck …" if self._listening
                                     else "")
            self._fill_manual()
            self._fill_pressed()
            self._show_page(_KEYS)
        elif page == _KEYS:
            if not self._session.pressed and QMessageBox.question(
                    self, "Rundgang", "Noch kein Taster erfasst. Trotzdem weiter? "
                    "Aktorkanäle ohne Taster finden Sie im nächsten Schritt mit "
                    "«Lasten suchen».") != QMessageBox.Yes:
                return
            self._react_title.setText(
                f"Schritt 3 von 3 – Was gehört in "
                f"{rb.room_label(self._project, self._room.id)}?")
            self._tree.clear()
            self._fill_tree()
            self._update_loads_button()
            self._show_page(_REACT)
        elif page == _REACT:
            self._finish_room()
        else:
            self._room = None
            self._room_combo.setCurrentIndex(0)
            self._show_page(_ROOM)

    def _go_back(self) -> None:
        page = self._pages.currentIndex()
        self._show_page(_ROOM if page == _KEYS else _KEYS)

    def done(self, result: int) -> None:
        if self._listening and self._monitor is not None:
            self._monitor.remove_listener(self._on_telegram)
            self._listening = False
        super().done(result)

    # ── Bus ──────────────────────────────────────────────────────────────

    def _on_telegram(self, telegram) -> None:
        page = self._pages.currentIndex()
        if self._session is None or page not in (_KEYS, _REACT):
            return
        before = len(self._session.candidates()) if page == _REACT else 0
        address = self._session.feed(telegram, time.monotonic())
        if page == _KEYS:
            if address:
                device = self._plan.operators[address].device
                self._last_press.setText(
                    f"Gedrückt: {address} {self._product(device)} – {telegram.destination}")
                self._last_press.setStyleSheet(f"font-weight: 600; color: {COLOR_OK};")
                self._fill_pressed(address)
            self._update_ignored()
        elif address or len(self._session.candidates()) != before:
            self._fill_tree()

    # ── Anzeige ──────────────────────────────────────────────────────────

    @staticmethod
    def _product(device) -> str:
        return device.product_name or device.product or ""

    def _update_progress(self) -> None:
        ops, all_ops, chs, all_chs = rb.progress(self._project, self._plan)
        names = [rb.room_label(self._project, r) for r in self._done_rooms]
        done = f" · in diesem Rundgang: {', '.join(names)}" if names else ""
        self._progress.setText(f"Zugeordnet: {ops} von {all_ops} Tastern/Sensoren, "
                               f"{chs} von {all_chs} Aktorkanälen{done}")

    def _update_ignored(self) -> None:
        count = self._session.ignored if self._session else 0
        self._ignored.setText(f"{count} Telegramme als Grundrauschen bzw. «gehört nicht "
                              "hierher» übergangen." if count else "")

    def _fill_rooms(self) -> None:
        current = self._room_combo.currentData() or (self._room.id if self._room else "")
        self._room_combo.clear()
        self._room_combo.addItem("– Raum wählen –", "")
        for label, _floor, room in rb.all_rooms(self._project):
            done = " ✓" if room.id in self._done_rooms else ""
            self._room_combo.addItem(label + done, room.id)
        self._room_combo.setCurrentIndex(max(self._room_combo.findData(current), 0))

    def _selected_room(self):
        room_id = self._room_combo.currentData() or ""
        return next((r for _l, _f, r in rb.all_rooms(self._project) if r.id == room_id), None)

    def _new_room(self) -> None:
        # Stockwerk und Zone wie beim zuletzt gewählten Raum vorschlagen
        last = self._room_combo.currentData() or (self._done_rooms[-1] if self._done_rooms
                                                  else "")
        floor, zone = rb.room_place(self._project, last)
        dialog = NewRoomDialog(self._project, self, floor, zone)
        if dialog.exec() != QDialog.Accepted:
            return
        if self._bus is not None:
            self._bus.begin_change("Raum angelegt")
        room = dialog.create_room()
        if self._bus is not None:
            self._bus.emit_building_changed()
        # neu füllen: mit der ersten benannten Zone ändern sich alle Anzeigen
        self._fill_rooms()
        self._room_combo.setCurrentIndex(max(self._room_combo.findData(room.id), 0))

    def _fill_manual(self) -> None:
        self._manual.clear()
        for pa in sorted(self._plan.operators, key=rb._pa_key):
            device = self._plan.operators[pa].device
            room = rb.room_label(self._project, device.room_id)
            self._manual.addItem(f"{pa} {self._product(device)}"
                                 + (f" ({room})" if room else ""), pa)

    def _fill_pressed(self, highlight: str = "") -> None:
        self._pressed.clear()
        for press in self._session.pressed.values():
            device = self._plan.operators[press.address].device
            room = rb.room_label(self._project, device.room_id)
            how = "von Hand" if press.manual and not press.count else f"{press.count}× gedrückt"
            text = f"{press.address} {self._product(device)} – {how}"
            if room and device.room_id != self._room.id:
                text += f" – bisher {room}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, press.address)
            self._pressed.addItem(item)
            if press.address == highlight:
                self._pressed.setCurrentItem(item)
        self._update_ignored()

    def _remove_pressed(self) -> None:
        item = self._pressed.currentItem()
        if item is not None:
            self._session.remove(item.data(Qt.UserRole))
            self._fill_pressed()

    def _add_manual(self) -> None:
        address = self._manual.currentData()
        if address:
            self._session.add(address)
            self._fill_pressed(address)

    def _fill_tree(self) -> None:
        checked = self._checked_channels(default=None)
        self._tree.clear()
        catalog = getattr(self._project, "gewerk_catalog", None)
        by_gewerk: dict[str, list] = {}
        for key, origin in self._session.candidates():
            channel = self._plan.channels[key]
            by_gewerk.setdefault(channel.gewerk or "SF", []).append((channel, origin))
        for code in sorted(by_gewerk):
            gewerk = catalog.get(code) if hasattr(catalog, "get") else None
            name = (getattr(gewerk, "name", "") or code).split(" (")[0]
            parent = QTreeWidgetItem([f"{code} – {name}"])
            parent.setFirstColumnSpanned(True)
            self._tree.addTopLevelItem(parent)
            for channel, origin in by_gewerk[code]:
                room_id = rb.channel_room(self._project, channel)
                item = QTreeWidgetItem([channel.label, origin,
                                        rb.room_label(self._project, room_id) or "–"])
                item.setData(0, Qt.UserRole, channel.key)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                on = checked.get(channel.key) if checked is not None and \
                    channel.key in checked else (not room_id or room_id == self._room.id)
                item.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
                parent.addChild(item)
            parent.setExpanded(True)
        if not by_gewerk:
            self._tree.addTopLevelItem(QTreeWidgetItem(
                ["Keine Aktorkanäle – die Taster gehen nur an einen Logikserver ohne "
                 "Reaktion, oder es wurde keine Taste gedrückt."]))

    # ── Lasten suchen ────────────────────────────────────────────────────

    def _loads_to_search(self) -> list:
        """Kanäle ohne Raum, die noch nicht in der Liste stehen."""
        shown = set(self._checked_channels() or {})
        return [c for c in rb.open_channels(self._project, self._plan) if c.key not in shown]

    def _update_loads_button(self) -> None:
        connected = getattr(self._monitor, "connected", False)
        count = len(self._loads_to_search())
        self._loads_btn.setEnabled(connected and count > 0)
        if not connected:
            self._loads_hint.setText("Lasten suchen braucht die Busverbindung.")
        elif count:
            self._loads_hint.setText(
                f"Noch {count} Aktorkanäle ohne Raum: KNiX schaltet sie einzeln kurz, "
                "Sie sagen, ob hier etwas reagiert.")
        else:
            self._loads_hint.setText("Alle Aktorkanäle haben einen Raum.")

    def _search_loads(self) -> None:
        from .load_search_dialog import LoadSearchDialog
        channels = self._loads_to_search()
        shown = self._checked_channels() or {}
        preferred = {self._plan.channels[k].gewerk or "SF" for k in shown}
        dialog = LoadSearchDialog(self._project, self._monitor, channels,
                                  rb.room_label(self._project, self._room.id), preferred, self)
        dialog.exec()
        self._take_found(dialog.found)

    def _take_found(self, keys) -> None:
        added = [k for k in keys if k not in self._session.found]
        if added:
            self._session.found.extend(added)
            self._fill_tree()
        self._update_loads_button()

    def _checked_channels(self, default=None) -> dict | None:
        """Bisherige Häkchen (bleiben beim Nachfüllen erhalten)."""
        result = {}
        for i in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(i)
            for j in range(parent.childCount()):
                item = parent.child(j)
                key = item.data(0, Qt.UserRole)
                if key is not None:
                    result[key] = item.checkState(0) == Qt.Checked
        return result if result else default

    def _finish_room(self) -> None:
        room = self._room
        keys = [k for k, on in (self._checked_channels() or {}).items() if on]
        operators = list(self._session.pressed)
        label = rb.room_label(self._project, room.id)
        if self._bus is not None:
            self._bus.begin_change(f"Raum zugeordnet: {label}")
        total = rb.AssignResult()
        for index, address in enumerate(operators or [""]):
            result = rb.assign(self._project, self._plan, room, address,
                               keys if index == 0 else ())
            total.device_moved |= result.device_moved
            total.channels += result.channels
            total.renamed += result.renamed
        if self._bus is not None:
            self._bus.emit_topology_changed()
            self._bus.emit_addresses_changed()
        if room.id not in self._done_rooms:
            self._done_rooms.append(room.id)
        self._done_title.setText(f"{label} abgeschlossen")
        self._done_text.setText(
            f"{len(operators)} Taster/Sensoren, {total.channels} Aktorkanäle neu im Raum, "
            f"{total.renamed} GAs umbenannt. Rückgängig über Bearbeiten.")
        self._fill_open()
        self._session = None
        self._show_page(_DONE)

    def _fill_open(self) -> None:
        self._open.clear()
        for pa in sorted(self._plan.operators, key=rb._pa_key):
            device = self._plan.operators[pa].device
            if not device.room_id:
                self._open.addItem(f"{pa} {self._product(device)}")
        for channel in sorted(self._plan.channels.values(),
                              key=lambda c: (rb._pa_key(c.device_address), c.channel)):
            if not rb.channel_room(self._project, channel):
                self._open.addItem(f"{channel.label} ({channel.gewerk or 'SF'})")
