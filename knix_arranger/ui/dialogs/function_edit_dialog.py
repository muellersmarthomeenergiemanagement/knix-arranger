"""
Dialog "Funktion" (FA-530): Name, Typ, Raum oder Zone, Elemente und
Rückmeldung einer geplanten Funktion.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QComboBox, QListWidget,
    QListWidgetItem, QVBoxLayout, QLabel, QMessageBox,
)

from ...models.ets_function import KnixFunction, FunctionMember
from ...services.ets_function_plan import (
    PLAN_TYPES, Location, member_candidates,
)
from ...services.ets_function_service import type_label


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

        layout = QVBoxLayout(self)
        hint = QLabel("Die Funktion bedient die gewählten Elemente gemeinsam. Ihre GAs "
                      "liegen in der HG des Stockwerks ab UG 200 und werden zusätzlich "
                      "auf die Aktorkanäle der Elemente verknüpft.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        layout.addWidget(hint)

        form = QFormLayout()
        self._name = QLineEdit(self._function.name)
        self._name.setPlaceholderText("z.B. Fensterfront")
        form.addRow("Name:", self._name)

        self._type = QComboBox()
        for ftype in PLAN_TYPES:
            self._type.addItem(type_label(ftype), ftype)
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

        status_form = QFormLayout()
        self._status = QComboBox()
        status_form.addRow("Rückmeldung:", self._status)
        layout.addLayout(status_form)
        status_hint = QLabel("Nur ein Kanal darf die Rückmeldung senden (Leitkanal); "
                             "die übrigen senden nur ihre eigene.")
        status_hint.setWordWrap(True)
        status_hint.setStyleSheet("color: #666;")
        layout.addWidget(status_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._type.currentIndexChanged.connect(self._fill_members)
        self._location.currentIndexChanged.connect(self._fill_members)
        self._members.itemChanged.connect(lambda _i: self._fill_status())
        self._fill_members()

    def _current_location(self) -> Location | None:
        index = self._location.currentIndex()
        return self._locations[index][2] if 0 <= index < len(self._locations) else None

    def _fill_members(self) -> None:
        selected = {(m.assignment_id, m.element_number) for m in self._function.members}
        lead = (self._function.members[self._function.lead]
                if 0 <= self._function.lead < len(self._function.members) else None)
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
        self._lead_key = f"{lead.assignment_id}|{lead.element_number}" if lead else None
        self._fill_status()

    def _checked(self) -> list[tuple[str, int]]:
        result = []
        for i in range(self._members.count()):
            item = self._members.item(i)
            key = item.data(Qt.UserRole)
            if key and item.checkState() == Qt.Checked:
                result.append(tuple(key))
        return result

    def _fill_status(self) -> None:
        previous = self._status.currentData() if self._status.count() else None
        if previous is None and self._function.with_status:
            previous = self._lead_key
        elif previous is None:
            previous = "none"
        self._status.clear()
        labels = {tuple(self._members.item(i).data(Qt.UserRole) or ()): self._members.item(i).text()
                  for i in range(self._members.count())}
        for key in self._checked():
            self._status.addItem(f"Leitkanal: {labels.get(key, '')}", f"{key[0]}|{key[1]}")
        self._status.addItem("Ohne Rückmeldung", "none")
        index = self._status.findData(previous)
        self._status.setCurrentIndex(index if index >= 0 else 0)

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
        if not members:
            QMessageBox.warning(self, "Funktion", "Bitte mindestens ein Element wählen.")
            return
        rid, zid, _loc = self._locations[self._location.currentIndex()]
        fn = self._function
        moved = (rid, zid) != (fn.room_id, fn.zone_id)
        fn.name = name
        fn.function_type = self._type.currentData()
        fn.room_id, fn.zone_id = rid, zid
        fn.members = [FunctionMember(a, n) for a, n in members]
        status = self._status.currentData()
        fn.with_status = status != "none"
        keys = [f"{a}|{n}" for a, n in members]
        fn.lead = keys.index(status) if fn.with_status and status in keys else 0
        if moved or not any(f.id == fn.id for f in self._project.functions):
            from ...services.ets_function_plan import next_number
            fn.number = next_number(self._project, fn)
        self.accept()

    def result_function(self) -> KnixFunction:
        return self._function
