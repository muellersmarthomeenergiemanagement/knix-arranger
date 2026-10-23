"""
Dialog "Funktion" (FA-530): Name, Typ, Raum oder Zone, Elemente und GAs einer
geplanten Funktion (reine Befehls-GAs, keine Rückmeldung).

GAs je Funktionspunkt: KNiX legt sie an (Standard), eine bestehende GA wird
mitbenutzt, oder der Punkt fällt weg; eigene Punkte mit Name und DPT kommen
dazu. "Benutzerdefiniert" (FT-0) startet ohne Punkte.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox, QListWidget,
    QListWidgetItem, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QInputDialog,
)

from ...models.ets_function import CustomPoint, KnixFunction, FunctionMember
from ...services.ets_function_plan import (
    CUSTOM_DPTS, PLAN_POINTS, PLAN_TYPES, Location, _omitted, _point_label,
    function_ga_map, member_candidates, plan_type_label,
)

# Art je Funktionspunkt
_AUTO, _LINKED, _OMIT = "auto", "linked", "omit"


class FunctionEditDialog(QDialog):
    """Bearbeitet eine Kopie; result_function() liefert das Ergebnis."""

    def __init__(self, project, function: KnixFunction | None = None,
                 preset_location: tuple[str, str] = ("", ""), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Funktion bearbeiten" if function else "Neue Funktion")
        self.setMinimumSize(520, 520)
        self._project = project
        self._function = KnixFunction.from_dict(function.to_dict()) if function else KnixFunction()
        if function is None:
            self._function.room_id, self._function.zone_id = preset_location
        # Arbeitsstand der GAs (Übernahme vor 1.4.18: omitted None -> Liste)
        self._omit = set(_omitted(self._function))
        self._custom = [CustomPoint(c.function, c.dpt) for c in self._function.custom_points]
        self._linked = dict(self._function.linked_gas)
        self._current_gas = (function_ga_map(project, function)
                             if function is not None else {})

        layout = QVBoxLayout(self)
        hint = QLabel("Die Funktion bedient die gewählten Elemente gemeinsam, z.B. von "
                      "einer Taste aus. Ihre Befehls-GAs liegen in der HG des Stockwerks "
                      "am Ende der Mittelgruppe (ab UG 250 rückwärts) und werden "
                      "zusätzlich auf die Aktorkanäle der Elemente "
                      "verknüpft. Eine Rückmeldung hat die Funktion nicht.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        layout.addWidget(hint)

        form = QFormLayout()
        self._name = QLineEdit(self._function.name)
        self._name.setPlaceholderText("z.B. Fensterfront")
        form.addRow("Name:", self._name)

        self._type = QComboBox()
        for ftype in PLAN_TYPES:
            self._type.addItem(plan_type_label(ftype), ftype)
        self._type.setCurrentIndex(max(0, self._type.findData(self._function.function_type)))
        form.addRow("Typ:", self._type)

        self._location = QComboBox()
        self._locations: list[tuple[str, str, Location]] = []
        for floor in project.areal.all_floors:
            floor_text = floor.name or floor.short_code
            for apartment in floor.apartments:
                if len(apartment.rooms) > 1 or len(floor.apartments) > 1:
                    zone = Location(floor, None, apartment)
                    self._locations.append(("", apartment.id, zone))
                    self._location.addItem(f"{floor_text} › {zone.label}")
                for room in apartment.rooms:
                    loc = Location(floor, room, apartment)
                    self._locations.append((room.id, "", loc))
                    self._location.addItem(f"{floor_text} › {loc.label}")
        current = next((i for i, (rid, zid, _l) in enumerate(self._locations)
                        if (rid, zid) == (self._function.room_id, self._function.zone_id)), 0)
        self._location.setCurrentIndex(current)
        form.addRow("Raum / Zone:", self._location)
        layout.addLayout(form)

        layout.addWidget(QLabel("Elemente:"))
        self._members = QListWidget()
        layout.addWidget(self._members, 1)

        layout.addWidget(QLabel("GAs der Funktion:"))
        self._gas = QTableWidget(0, 3)
        self._gas.setHorizontalHeaderLabels(["Funktionspunkt", "GA", "Art"])
        self._gas.verticalHeader().setVisible(False)
        self._gas.setSelectionMode(QAbstractItemView.NoSelection)
        self._gas.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self._gas, 1)
        add_row = QHBoxLayout()
        self._btn_add_point = QPushButton("+ GA hinzufügen…")
        self._btn_add_point.setToolTip("Eigener Funktionspunkt mit Name und DPT, z.B. «SZENE»")
        self._btn_add_point.clicked.connect(self._add_point)
        add_row.addWidget(self._btn_add_point)
        add_row.addStretch()
        layout.addLayout(add_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._type.currentIndexChanged.connect(self._fill_members)
        self._type.currentIndexChanged.connect(self._on_type_changed)
        self._location.currentIndexChanged.connect(self._fill_members)
        self._fill_members()
        self._fill_gas()

    def _current_location(self) -> Location | None:
        index = self._location.currentIndex()
        return self._locations[index][2] if 0 <= index < len(self._locations) else None

    def _fill_members(self) -> None:
        selected = {(m.assignment_id, m.element_number) for m in self._function.members}
        self._members.blockSignals(True)
        self._members.clear()
        location = self._current_location()
        candidates = member_candidates(location, self._type.currentData()) if location else []
        for member in candidates:
            item = QListWidgetItem(member.label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            key = (member.assignment.id, member.element_number)
            item.setCheckState(Qt.Checked if key in selected else Qt.Unchecked)
            item.setData(Qt.UserRole, key)
            self._members.addItem(item)
        if not candidates:
            self._members.addItem("Keine passenden Elemente an diesem Ort.")
        self._members.blockSignals(False)

    # ── GAs ──────────────────────────────────────────────────────────────

    def _points(self) -> list[tuple[str, bool]]:
        """(Funktionspunkt, eigener Punkt?) in der Reihenfolge der Funktion."""
        standard = [(p.function, False)
                    for p in PLAN_POINTS.get(self._type.currentData(), ())]
        names = {n for n, _c in standard}
        return standard + [(c.function, True) for c in self._custom if c.function not in names]

    def _on_type_changed(self) -> None:
        # Standardpunkte des alten Typs gelten nicht mehr
        names = {p.function for p in PLAN_POINTS.get(self._type.currentData(), ())}
        custom = {c.function for c in self._custom}
        self._omit &= names
        self._linked = {k: v for k, v in self._linked.items() if k in names | custom}
        self._fill_gas()

    def _fill_gas(self) -> None:
        function_type = self._type.currentData()
        points = self._points()
        self._gas.setRowCount(len(points))
        for row, (point, custom) in enumerate(points):
            label = point if custom else _point_label(function_type, point)
            item = QTableWidgetItem(label + ("  (eigener)" if custom else ""))
            item.setFlags(Qt.ItemIsEnabled)
            item.setData(Qt.UserRole, point)
            self._gas.setItem(row, 0, item)
            if point in self._linked:
                kind = _LINKED
                ga_text = f"{self._linked[point]}  (bestehend)"
            elif point in self._omit:
                kind = _OMIT
                ga_text = "– weggelassen"
            else:
                kind = _AUTO
                current = self._current_gas.get(point)
                ga_text = (f"{current.address}  {current.designation}"
                           if current is not None and current.function_id == self._function.id
                           else "wird von KNiX angelegt")
            ga_item = QTableWidgetItem(ga_text)
            ga_item.setFlags(Qt.ItemIsEnabled)
            self._gas.setItem(row, 1, ga_item)
            combo = QComboBox()
            combo.addItem("KNiX legt an", _AUTO)
            combo.addItem("Bestehende GA…", _LINKED)
            combo.addItem("Entfernen" if custom else "Weglassen", _OMIT)
            combo.setCurrentIndex(combo.findData(kind))
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, pt=point, cu=custom: self._on_kind(pt, cu, c.currentData()))
            self._gas.setCellWidget(row, 2, combo)
        self._gas.resizeColumnsToContents()

    def _on_kind(self, point: str, custom: bool, kind: str) -> None:
        if kind == _LINKED:
            from .ga_picker_dialog import GaPickerDialog
            location = self._current_location()
            room = location.rooms[0] if location and location.rooms else None
            current = self._linked.get(point, "")
            dialog = GaPickerDialog(self._project, room, current_ga_designation=current,
                                    parent=self) if room is not None else None
            if dialog is not None and dialog.exec() and dialog.selected_ga is not None:
                ga = dialog.selected_ga
                self._linked[point] = f"{ga.address}  {ga.designation}"
                self._omit.discard(point)
        elif kind == _OMIT:
            self._linked.pop(point, None)
            if custom:
                self._custom = [c for c in self._custom if c.function != point]
            else:
                self._omit.add(point)
        else:
            self._linked.pop(point, None)
            self._omit.discard(point)
        self._fill_gas()

    def element_functions(self) -> dict[str, str]:
        """Befehls-Funktionen der gewählten Elemente -> DPT (z.B. BESCHATTUNG):
        heisst ein eigener Punkt gleich, legt KNiX ihn auf deren Aktorkanäle."""
        from ...services.ets_function_plan import _element_gas
        element_gas = _element_gas(self._project)
        result: dict[str, str] = {}
        for key in self._checked():
            for function, ga in element_gas.get(tuple(key), {}).items():
                result.setdefault(function, ga.datapoint_type)
        existing = {n for n, _c in self._points()}
        # Rückmeldungen sendet der Aktor -- eine Funktion hat nur Befehle
        return {f: d for f, d in sorted(result.items())
                if f not in existing and not f.startswith(("RM", "STATUS"))}

    def _add_point(self) -> None:
        offered = self.element_functions()
        name, ok = QInputDialog.getItem(
            self, "GA hinzufügen",
            "Funktion der Elemente wählen (dann verknüpft KNiX sie auf deren "
            "Aktorkanäle)\noder eigenen Namen eingeben, z.B. SZENE:",
            list(offered), 0, True)
        name = " ".join(name.split()).upper()
        if not ok or not name:
            return
        if name in {n for n, _c in self._points()}:
            QMessageBox.information(self, "GA hinzufügen", f"«{name}» gibt es schon.")
            return
        dpt = offered.get(name, "")
        if not dpt:
            labels = [label for _dpt, label in CUSTOM_DPTS]
            label, ok = QInputDialog.getItem(self, "GA hinzufügen", "Datenpunkttyp:",
                                             labels, 0, False)
            if not ok:
                return
            dpt = next(d for d, text in CUSTOM_DPTS if text == label)
        self._custom.append(CustomPoint(name, dpt))
        self._fill_gas()

    def _checked(self) -> list[tuple[str, int]]:
        result = []
        for i in range(self._members.count()):
            item = self._members.item(i)
            key = item.data(Qt.UserRole)
            if key and item.checkState() == Qt.Checked:
                result.append(tuple(key))
        return result

    def _accept(self) -> None:
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "Funktion", "Bitte einen Namen eingeben.")
            return
        location = self._current_location()
        if location is None:
            QMessageBox.warning(self, "Funktion", "Bitte einen Raum oder eine Zone wählen.")
            return
        members = self._checked()
        function_type = self._type.currentData()
        # Benutzerdefiniert: Elemente freiwillig (z.B. nur bestehende GAs)
        if not members and function_type != "FT-0":
            QMessageBox.warning(self, "Funktion", "Bitte mindestens ein Element wählen.")
            return
        if not [p for p, _c in self._points() if p not in self._omit]:
            QMessageBox.warning(self, "Funktion", "Die Funktion braucht mindestens eine GA – "
                                "mit «+ GA hinzufügen…» oder «Bestehende GA…».")
            return
        rid, zid, _loc = self._locations[self._location.currentIndex()]
        fn = self._function
        moved = (rid, zid) != (fn.room_id, fn.zone_id)
        fn.name = name
        fn.function_type = self._type.currentData()
        fn.room_id, fn.zone_id = rid, zid
        fn.members = [FunctionMember(a, n) for a, n in members]
        fn.omitted = sorted(self._omit)
        fn.custom_points = list(self._custom)
        fn.linked_gas = dict(self._linked)
        if moved or not any(f.id == fn.id for f in self._project.functions):
            from ...services.ets_function_plan import next_number
            fn.number = next_number(self._project, fn)
        self.accept()

    def result_function(self) -> KnixFunction:
        return self._function
