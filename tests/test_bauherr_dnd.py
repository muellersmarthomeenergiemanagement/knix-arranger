"""
Bauherrenberatung: Funktion auf eine Taste ziehen (FA-1015 e).

Fall aus Projekt_23 Chalet Franziska: in der Technik ist kein Taster
vorgesehen, Licht Technik wird vom Taster in der Waschküche geschaltet.
Die Funktionsliste markiert es als "ohne Bedienung" (FA-619); nach dem
Ziehen auf eine freie Taste ist es bedient.
"""
from __future__ import annotations
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, GewerkAssignment, Room,
    SensorFunktion, Wing,
)
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.ui.views.bauherr_form_view import BauherrFormView, _SlotWidget
from knix_arranger.ui.widgets.function_palette import FUNCTION_MIME


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _project():
    wasch = Room(number="CUG01", name="Waschküche",
                 gewerk_assignments=[GewerkAssignment(gewerk_code="L")])
    technik = Room(number="CUG02", name="Technik",
                   gewerk_assignments=[GewerkAssignment(gewerk_code="L")])
    wasch.bedienelemente = [Bedienelement(
        element_type="Tastereinheit", channels=2, participant_number="1.1.101",
        funktionen=[SensorFunktion(gewerk_code="L", element_number=1)])]
    floor = Floor(name="Untergeschoss", short_code="UG", main_group_number=4,
                  apartments=[Apartment(name="Wohnung", rooms=[wasch, technik])])
    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=[Building(name="Chalet", wings=[Wing(floors=[floor])])])
    gas = [GroupAddress(main_group=4, middle_group=0, sub_group=sub, designation=d,
                        gewerk_code="L", room_id=room.id, element_number=1,
                        function_name="E/A")
           for sub, room, d in ((0, wasch, "L_CUG01_01 E/A (Wohnung / Waschküche)"),
                                (20, technik, "L_CUG02_01 E/A (Wohnung / Technik)"))]
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=4, name="UG", middle_groups=[MiddleGroup(number=0, name="Licht",
                                                        group_addresses=gas)])])
    return project, wasch, technik


def _view(project, room):
    view = BauherrFormView()
    view.set_project(project)
    for i in range(view._room_list.count()):
        if view._room_list.item(i).data(Qt.UserRole) is room:
            view._room_list.setCurrentRow(i)
    return view


def _palette_entries(view) -> list[tuple[str, str]]:
    tree = view._palette._tree
    return [(tree.topLevelItem(i).text(0), tree.topLevelItem(i).child(j).text(0))
            for i in range(tree.topLevelItemCount())
            for j in range(tree.topLevelItem(i).childCount())]


def _drop(slot, payload, fmt=FUNCTION_MIME) -> QDropEvent:
    mime = QMimeData()
    mime.setData(fmt, json.dumps(payload).encode("utf-8"))
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    slot.dropEvent(event)
    return event


def _empty_slot(view) -> _SlotWidget:
    return next(s for s in view.findChildren(_SlotWidget) if s._sf is None)


def test_palette_marks_element_without_operation():
    project, wasch, technik = _project()
    view = _view(project, wasch)
    entries = _palette_entries(view)
    assert any("Technik" in room and "ohne Bedienung" in text for room, text in entries)
    assert not any("Waschküche" in room and "ohne Bedienung" in text for room, text in entries)

    view._palette._only_open.setChecked(True)
    assert [room for room, _ in _palette_entries(view)] == ["CUG02  Technik"]


def test_drop_assigns_function_from_other_room():
    project, wasch, technik = _project()
    view = _view(project, wasch)
    be = wasch.bedienelemente[0]

    event = _drop(_empty_slot(view), {"code": "L", "element": 1, "room_id": technik.id})
    assert event.isAccepted()
    new = be.funktionen[-1]
    assert (new.gewerk_code, new.element_number, new.source_room_id) == ("L", 1, technik.id)
    assert be.is_auto is False   # bleibt bei der Neuberechnung erhalten

    QApplication.processEvents()   # Liste wird verzögert nachgeführt
    assert not any("ohne Bedienung" in text for _, text in _palette_entries(view))


def test_foreign_or_unknown_drops_are_ignored():
    project, wasch, technik = _project()
    view = _view(project, wasch)
    slot = _empty_slot(view)
    count = len(wasch.bedienelemente[0].funktionen)

    assert not _drop(slot, {"code": "L"}, fmt="text/plain").isAccepted()
    assert not _drop(slot, {"code": "J", "element": 1, "room_id": technik.id}).isAccepted()
    assert len(wasch.bedienelemente[0].funktionen) == count


# ── Taste verschieben/tauschen, Taster entfernen ────────────────────────────

def _project_two_keys():
    project, wasch, technik = _project()
    technik.bedienelemente = [Bedienelement(
        element_type="Tastereinheit", channels=1, participant_number="1.1.102",
        funktionen=[SensorFunktion(gewerk_code="L", element_number=1)])]
    wasch.bedienelemente[0].funktionen.append(
        SensorFunktion(gewerk_code="L", element_number=1, source_room_id=technik.id))
    return project, wasch, technik


def _slots(view, be):
    return [s for s in view.findChildren(_SlotWidget) if s._be is be and s._long_of is None]


def _slot_mime(be, sf) -> QMimeData:
    from knix_arranger.ui.views.bauherr_form_view import SLOT_MIME
    mime = QMimeData()
    mime.setData(SLOT_MIME, json.dumps({"be_id": be.id, "sf_id": sf.id}).encode("utf-8"))
    return mime


def test_swap_two_keys_by_drop():
    project, wasch, technik = _project_two_keys()
    view = _view(project, wasch)
    be = wasch.bedienelemente[0]
    first, second = be.funktionen
    target = next(s for s in _slots(view, be) if s._sf is second)

    mime = _slot_mime(be, first)   # Referenz halten: QDropEvent übernimmt sie nicht
    event = QDropEvent(QPointF(5, 5), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    target.dropEvent(event)

    assert event.isAccepted() and event.dropAction() == Qt.MoveAction
    assert be.funktionen == [second, first]


def test_key_does_not_accept_itself():
    project, wasch, technik = _project_two_keys()
    view = _view(project, wasch)
    be = wasch.bedienelemente[0]
    slot = next(s for s in _slots(view, be) if s._sf is be.funktionen[0])
    assert slot._slot_payload(_slot_mime(be, be.funktionen[0])) is None


def test_remove_last_taster_drops_room_from_list(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from knix_arranger.ui.views.bauherr_form_view import _TasterWidget
    project, wasch, technik = _project_two_keys()
    view = _view(project, technik)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    taster = next(w for w in view.findChildren(_TasterWidget)
                  if w.be_id == technik.bedienelemente[0].id)
    taster._on_remove_taster()

    assert technik.bedienelemente[0].suppressed
    rooms = [view._room_list.item(i).data(Qt.UserRole) for i in range(view._room_list.count())]
    assert technik not in rooms and wasch in rooms
