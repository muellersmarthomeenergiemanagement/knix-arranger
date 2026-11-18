"""
Geführter Funktionstest (FA-3104): Schritte je Element planen, Ergebnis in
die Checkliste, Ablauf im Dialog mit einem Schein-Bus (Rückmeldung, keine
Rückmeldung, Zustand schon so, Storen, Frage vor Ort, Anhalten).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime

import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.documentation import (
    ITEM_KIND_FUNCTION, RESULT_DEFECT, RESULT_OK, ChecklistItem, CommissioningChecklist,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services import function_test
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.bus_access import LiveTelegram
from knix_arranger.services.function_test import (
    KIND_BLIND, KIND_DIM, KIND_SWITCH, feedback_matches, plan_steps, record_result,
)
from knix_arranger.services.topology_engine import TopologyEngine


def _build():
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="Funktionstest")
    wohnen = Room(number="01", name="Wohnen", gewerk_assignments=[
        GewerkAssignment(gewerk_code="L", count=1),
        GewerkAssignment(gewerk_code="LD", count=1),
        GewerkAssignment(gewerk_code="J", count=1),
        GewerkAssignment(gewerk_code="H", count=1),       # kein Test
        GewerkAssignment(gewerk_code="G", count=1)])      # nie automatisch
    kueche = Room(number="02", name="Küche", gewerk_assignments=[
        GewerkAssignment(gewerk_code="L", count=1)])
    floor = Floor(name="EG", short_code="EG", main_group_number=2,
                  apartments=[Apartment(name="Zone", rooms=[wohnen, kueche])])
    project.areal = Areal(buildings=[Building(name="H", wings=[Wing(floors=[floor])])])
    engine = TopologyEngine(project.config.topology_mode)
    project.topology = engine.calculate_topology(project.areal)
    engine.populate_devices(project.topology, project.all_rooms, project.gewerk_catalog)
    regenerate_addresses(project)
    logging.disable(logging.NOTSET)
    return project, wohnen, kueche


@pytest.fixture
def planned():
    return _build()


def _step(steps, code):
    return next(s for s in steps if s.gewerk_code == code)


def test_plan_per_gewerk(planned):
    project, wohnen, kueche = planned
    steps = plan_steps(project)
    assert [s.gewerk_code for s in steps] == ["L", "LD", "J", "G", "L"]   # ohne H
    light, dimmer, blind, gate = (_step(steps, c) for c in ("L", "LD", "J", "G"))
    gas = {g.address: g for g in project.group_addresses.all_addresses()}
    assert light.kind == KIND_SWITCH and gas[light.commands["E/A"]].function_name == "E/A"
    assert gas[light.feedback].function_name == "RM"
    assert dimmer.kind == KIND_DIM and gas[dimmer.feedback].function_name == "RM WERT"
    assert blind.kind == KIND_BLIND and set(blind.commands) == {"AUF/AB", "STOPP"}
    assert gas[blind.feedback].function_name == "STATUS POSITION HOEHE"
    assert gate.skip and not gate.actions()
    assert [s.room for s in plan_steps(project, {kueche.id})] == ["02 Küche"]


def test_actions_switch_dim_blind(planned):
    steps = plan_steps(planned[0])
    light, dimmer, blind = (_step(steps, c) for c in ("L", "LD", "J"))
    assert [(a.kind, a.text) for a in light.actions()] == [
        ("send", "Ein"), ("feedback", ""), ("send", "Aus")]
    assert [(a.payload, a.size) for a in dimmer.actions() if a.kind == "send"] == [
        ("80", 1), ("00", 1)]
    assert [a.text for a in blind.actions() if a.kind == "send"] == [
        "Ab", "Stopp", "Auf", "Stopp"]
    assert [a.seconds for a in blind.actions() if a.kind == "wait"] == [2.0, 2.0]
    light.feedback = ""                       # ohne Rückmelde-GA: fragen
    assert [a.kind for a in light.actions()] == ["send", "wait", "ask", "send"]


def test_feedback_matches():
    now = datetime.now()
    on = LiveTelegram(now, "1.1.1", "2/6/1", "Write", "01", 0)
    off = LiveTelegram(now, "1.1.1", "2/6/1", "Write", "00", 0)
    assert feedback_matches("on", on) and not feedback_matches("on", off)
    assert feedback_matches("nonzero", LiveTelegram(now, "1.1.1", "2/6/2", "Response", "80", 1))
    assert not feedback_matches("nonzero", LiveTelegram(now, "1.1.1", "2/6/2", "Write", "00", 1))
    assert feedback_matches("", off)
    assert not feedback_matches("", LiveTelegram(now, "", "2/6/1", "Write", "01", 0, sent=True))
    assert not feedback_matches("", LiveTelegram(now, "1.1.1", "2/6/1", "Read"))


def _checklist(project, room, step):
    """Checkliste von früher: nur ein Tasten-Prüfpunkt auf der GA des
    Elements (wie der Taster im Chalet), keine Aktorkanäle."""
    taste = ChecklistItem(item_kind=ITEM_KIND_FUNCTION, check_type="Taste 1",
                          function_ga=step.designations[0], room_id=room.id,
                          be_type="Tastereinheit", be_number="1.1.40")
    project.checklists = [CommissioningChecklist(room_id=room.id, room_name="01 Wohnen",
                                                 items=[taste])]
    return [taste]


def _actuator(project, step):
    """Prüfpunkt des Elements in der Gruppe «Aktorkanäle»."""
    from knix_arranger.models.documentation import ACTUATOR_GROUP
    found = [i for c in project.checklists for i in c.items
             if i.be_type == ACTUATOR_GROUP and i.check_type == step.code]
    assert len(found) <= 1
    return found[0] if found else None


def test_record_result_on_actuator_not_on_key(planned):
    """Das Ergebnis gehört dem Aktorkanal; die Taste prüft man am Taster."""
    project, wohnen, _kueche = planned
    light = _step(plan_steps(project), "L")
    taste = _checklist(project, wohnen, light)[0]
    count = record_result(project, light, False, "Funktionstest: keine Rückmeldung", "MM",
                          date(2026, 11, 18))
    assert count == 1 and taste.result == ""
    item = _actuator(project, light)
    assert (item.result, item.checked_by, item.checked_date) == (RESULT_DEFECT, "MM",
                                                                 "2026-11-18")
    assert item.check_type == light.code == "L_EG_01_01"
    assert item.function_ga.startswith(light.commands["E/A"] + "  ")
    assert item.notes == "Funktionstest: keine Rückmeldung"
    record_result(project, light, True, "ok", "MM")              # kein zweiter Punkt
    assert _actuator(project, light).result == RESULT_OK
    project.checklists = []
    assert record_result(project, light, True, "ok") == 0        # ohne Checkliste


def test_checklists_have_actuator_group(planned):
    """Checkliste erstellen bzw. abgleichen: je Raum die Gruppe
    «Aktorkanäle» mit allen Elementen, auch nicht automatisch prüfbaren;
    der Ausdruck (PDF/Excel) hat dafür eine Karte."""
    from knix_arranger.models.documentation import ACTUATOR_GROUP
    from knix_arranger.services.documentation_service import DocumentationService
    project, wohnen, kueche = planned
    lists = DocumentationService(project).create_checklists()
    by_room = {c.room_id: [i for i in c.items if i.be_type == ACTUATOR_GROUP] for c in lists}
    assert [i.check_type for i in by_room[wohnen.id]] == [
        "L_EG_01_01", "LD_EG_01_01", "J_EG_01_01", "G_EG_01_01"]
    assert by_room[wohnen.id][3].description.endswith("vor Ort prüfen")
    assert [i.check_type for i in by_room[kueche.id]] == ["L_EG_02_01"]
    # Abgleichen bei einer Checkliste von früher ergänzt sie
    light = _step(plan_steps(project), "L")
    _checklist(project, wohnen, light)
    added, _total = DocumentationService(project).sync_project_checklists()
    assert added >= 5 and _actuator(project, light) is not None
    sections = DocumentationService(project)._checklist_sections()
    cards = {title: rows for _f, room, cards in sections if room == "01 Wohnen"
             for title, rows in cards}
    rows = cards["Aktorkanäle (Funktionstest)"]
    assert [r[0].split("\n")[0] for r in rows] == [
        "L_EG_01_01", "LD_EG_01_01", "J_EG_01_01", "G_EG_01_01"]
    assert all("\n" in r[0] for r in rows)              # Objekt unter dem Code
    item = _actuator(project, light)
    assert rows[0][3] == [(wohnen.id, ACTUATOR_GROUP, "", item.check_type, item.function_ga)]


def test_place_and_actuator(planned):
    """Was vor Ort reagieren muss: Klartext des Elements, sonst der Ort aus
    der GA-Bezeichnung, sonst das Gewerk; dazu der Aktorkanal."""
    from types import SimpleNamespace
    from knix_arranger.services.function_test import _place
    ga = lambda d: SimpleNamespace(designation=d)
    assert _place(ga("J.OG.02.04_move (Balkon Bibliothek)")) == "Balkon Bibliothek"
    assert _place(ga("L.OG.02.01_ea")) == ""
    assert _place(ga("Bibliothek Decke")) == "Bibliothek Decke"
    assert _place(None) == ""
    project, wohnen, _k = planned
    light = next(a for a in wohnen.gewerk_assignments if a.gewerk_code == "L")
    light.set_element_labels(["Pendel Esstisch"])
    steps = plan_steps(project)
    step = _step(steps, "L")
    assert step.place == "Pendel Esstisch"
    assert step.title() == "Pendel Esstisch (L_EG_01_01)"
    assert all(s.place for s in steps)
    assert step.description().startswith("Pendel Esstisch – Ein, dann Aus")
    step.actuator = "1.1.5 Ausgang A"
    assert step.description().endswith("· Aktor 1.1.5 Ausgang A")


def test_sync_updates_actuator_text_keeps_result(planned):
    """Abgleichen führt den Text der Aktorkanäle nach, das Ergebnis bleibt."""
    from knix_arranger.services.documentation_service import DocumentationService
    project, wohnen, _k = planned
    project.checklists = DocumentationService(project).create_checklists()
    light = _step(plan_steps(project), "L")
    record_result(project, light, True, "ok", "MM")
    item = _actuator(project, light)
    item.description = "alt"
    next(a for a in wohnen.gewerk_assignments
         if a.gewerk_code == "L").set_element_labels(["Pendel Esstisch"])
    DocumentationService(project).sync_project_checklists()
    item = _actuator(project, light)
    assert item.description.startswith("Pendel Esstisch") and item.result == RESULT_OK


def test_dialog_confirm_on_site_even_with_feedback(planned, fast, monkeypatch):
    """Rückmeldung da, aber vor Ort hat ein anderes Objekt reagiert
    (Lasten vertauscht): Mangel."""
    project, wohnen, _k = planned
    light = _step(plan_steps(project), "L")
    _checklist(project, wohnen, light)
    from knix_arranger.ui.dialogs.function_test_dialog import FunctionTestDialog
    answers = []

    def answer(self):
        answers.append(1)
        self._answer = False
        self._next_action()
    monkeypatch.setattr(FunctionTestDialog, "_ask", answer)
    bus = _Bus(reply=lambda a, p: [_fb(light.feedback, p)] if a == light.commands["E/A"] else [])
    dialog = _run(project, bus, [light], confirm=True)
    assert answers == [1] and dialog.result_of(0) is False
    item = _actuator(project, light)
    assert item.result == RESULT_DEFECT and "falsches oder kein Objekt" in item.notes
    assert [(a, p) for a, s, p in bus.sent if s == "Write"][-1] == (light.commands["E/A"], "00")


def test_imported_blinds_without_status_ask():
    """Importierte Storen ohne Status-KO am Kanal: vor Ort fragen."""
    project, _w, _k = _build()
    step = _step(plan_steps(project), "J")
    step.feedback = ""
    assert "ask" in [a.kind for a in step.actions()]


# ── Ablauf im Dialog ───────────────────────────────────────────────────────

class _Bus:
    """Schein-Live-Monitor: bestätigt jedes Telegramm sofort; reply(Befehl)
    liefert die Rückmeldungen des Aktors."""

    def __init__(self, reply=None, read_reply=None):
        self.connected = True
        self.sent: list[tuple] = []
        self.listeners = []
        self.reply = reply or (lambda address, payload: [])
        self.read_reply = read_reply or (lambda address: None)

    def add_listener(self, fn):
        self.listeners.append(fn)

    def remove_listener(self, fn):
        self.listeners.remove(fn)

    def value_text(self, telegram):
        return {"01": "Ein", "00": "Aus"}.get(telegram.payload, telegram.payload)

    def send_telegram(self, destination, service, payload, size, on_done):
        self.sent.append((destination, service, payload))
        on_done("")
        answers = (self.reply(destination, payload) if service == "Write"
                   else [self.read_reply(destination)])
        for answer in answers:
            if answer is not None:
                for fn in list(self.listeners):
                    fn(answer)
        return True


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(function_test, "BLIND_TRAVEL", 0.05)
    monkeypatch.setattr(function_test, "FEEDBACK_TIMEOUT", 0.2)
    from knix_arranger.ui.dialogs import function_test_dialog
    monkeypatch.setattr(function_test_dialog, "STEP_PAUSE", 0.01)
    monkeypatch.setattr(function_test_dialog, "READ_WAIT", 0.2)


def _run(project, bus, steps, rows=None, confirm=False):
    app = _app()
    from knix_arranger.ui.dialogs.function_test_dialog import FunctionTestDialog
    dialog = FunctionTestDialog(project, bus, steps, "MM")
    dialog._confirm_box.setChecked(confirm)
    if rows is not None:
        dialog._check_all(False)
        from PySide6.QtCore import Qt
        for row in rows:
            dialog._table.item(row, 0).setCheckState(Qt.Checked)
    assert dialog.start(confirmed=True)
    deadline = time.monotonic() + 10
    while dialog._running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert not dialog._running
    return dialog


_C_RESULT = 7


def _fb(address, payload, service="Write", size=0):
    return LiveTelegram(datetime.now(), "1.1.20", address, service, payload, size)


def test_dialog_light_with_feedback_ok(planned, fast):
    project, wohnen, _k = planned
    light = _step(plan_steps(project), "L")
    items = _checklist(project, wohnen, light)
    bus = _Bus(reply=lambda a, p: [_fb(light.feedback, p)] if a == light.commands["E/A"] else [])
    dialog = _run(project, bus, [light])
    assert bus.sent == [(light.commands["E/A"], "Write", "01"),
                        (light.commands["E/A"], "Write", "00")]
    assert dialog.result_of(0) is True
    item = _actuator(project, light)
    assert item.result == RESULT_OK and item.checked_by == "MM"
    assert f"Rückmeldung {light.feedback} = Ein" in item.notes
    assert items[0].result == ""                   # Taste unberührt
    assert "in der Checkliste" in dialog._table.item(0, _C_RESULT).text()
    assert not bus.listeners                       # abgemeldet


def test_dialog_no_feedback_reads_then_defect(planned, fast):
    project, wohnen, _k = planned
    light = _step(plan_steps(project), "L")
    items = _checklist(project, wohnen, light)
    bus = _Bus()                                   # Aktor schweigt
    dialog = _run(project, bus, [light])
    assert (light.feedback, "Read", "") in bus.sent
    item = _actuator(project, light)
    assert dialog.result_of(0) is False and item.result == RESULT_DEFECT
    assert "keine Rückmeldung" in item.notes and items[0].result == ""


def test_dialog_already_on_answers_read(planned, fast):
    """Leuchte war schon an: keine Meldung auf «Ein», aber die Antwort auf
    die Leseanfrage zeigt Ein."""
    project, _w, _k = planned
    light = _step(plan_steps(project), "L")
    bus = _Bus(read_reply=lambda a: _fb(a, "01", "Response") if a == light.feedback else None)
    dialog = _run(project, bus, [light])
    assert dialog.result_of(0) is True


def test_dialog_blind_sequence(planned, fast):
    project, _w, _k = planned
    blind = _step(plan_steps(project), "J")
    bus = _Bus(reply=lambda a, p: [_fb(blind.feedback, "33", size=1)]
               if a == blind.commands["STOPP"] else [])
    dialog = _run(project, bus, [blind])
    move, stop = blind.commands["AUF/AB"], blind.commands["STOPP"]
    assert [(a, p) for a, s, p in bus.sent if s == "Write"] == [
        (move, "01"), (stop, "01"), (move, "00"), (stop, "00")]
    assert dialog.result_of(0) is True


def test_dialog_asks_without_feedback_ga(planned, fast, monkeypatch):
    project, _w, _k = planned
    light = _step(plan_steps(project), "L")
    light.feedback = ""
    from knix_arranger.ui.dialogs.function_test_dialog import FunctionTestDialog

    def answer_no(self):
        self._answer = False
        self._next_action()
    monkeypatch.setattr(FunctionTestDialog, "_ask", answer_no)
    dialog = _run(project, _Bus(), [light])
    assert dialog.result_of(0) is False
    assert "vor Ort" in dialog._table.item(0, _C_RESULT).text()


def test_dialog_stop_resets_element_without_result(planned, fast):
    project, wohnen, kueche = planned
    steps = [s for s in plan_steps(project) if s.gewerk_code == "L"]
    items = _checklist(project, wohnen, steps[0])
    bus = _Bus()
    app = _app()
    from knix_arranger.ui.dialogs.function_test_dialog import FunctionTestDialog
    dialog = FunctionTestDialog(project, bus, steps, "MM")
    assert dialog.start(confirmed=True)
    dialog.stop()                                  # während des ersten Elements
    deadline = time.monotonic() + 5
    while dialog._running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    first = steps[0].commands["E/A"]
    assert [(a, p) for a, s, p in bus.sent if s == "Write"] == [(first, "01"), (first, "00")]
    assert dialog.result_of(0) is None and _actuator(project, steps[0]) is None
    assert steps[1].commands["E/A"] not in [a for a, _s, _p in bus.sent]
    assert dialog._status.text().startswith("Angehalten")


def test_dialog_send_error_stops(planned, fast):
    project, _w, _k = planned
    light = _step(plan_steps(project), "L")

    class Failing(_Bus):
        def send_telegram(self, destination, service, payload, size, on_done):
            on_done("Die Schnittstelle hat das Telegramm nicht bestätigt.")
            return False
    dialog = _run(project, Failing(), [light])
    assert dialog.result_of(0) is None
    assert dialog._status.text().startswith("Abgebrochen")


def test_dialog_needs_connection(planned, monkeypatch):
    _app()
    from PySide6.QtWidgets import QMessageBox
    from knix_arranger.ui.dialogs.function_test_dialog import FunctionTestDialog
    project, _w, _k = planned
    bus = _Bus()
    bus.connected = False
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    dialog = FunctionTestDialog(project, bus, plan_steps(project), "MM")
    assert not dialog.start(confirmed=True) and "Verbinden" in shown[0]
    # Tor nie wählbar
    from PySide6.QtCore import Qt
    gate_row = [s.gewerk_code for s in dialog._steps].index("G")
    assert not dialog._table.item(gate_row, 0).flags() & Qt.ItemIsUserCheckable


def test_commissioning_view_offers_test_only_when_connected(planned, monkeypatch):
    _app()
    from PySide6.QtWidgets import QMessageBox
    from knix_arranger.ui.views.commissioning_view import CommissioningView
    project, _w, _k = planned
    view = CommissioningView(project)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    view._function_test(None)
    assert "Live-Monitor" in shown[0]
    opened = []
    from knix_arranger.ui.dialogs import function_test_dialog
    monkeypatch.setattr(function_test_dialog.FunctionTestDialog, "exec",
                        lambda self: opened.append(len(self._steps)))
    view.bus_monitor = _Bus()
    view._function_test(None)
    assert opened == [5]
