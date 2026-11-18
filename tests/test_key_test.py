"""Tastentest (FA-3106): Mithören, Auswerten, Eintragen."""
from __future__ import annotations

import os
from datetime import date, datetime

from knix_arranger.models.documentation import (
    ITEM_KIND_DEVICE, ITEM_KIND_FUNCTION, RESULT_DEFECT, RESULT_OK, ChecklistItem,
    CommissioningChecklist,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.bus_access import LiveTelegram
from knix_arranger.services.key_test import (
    LATE_REACTION, PRESS_DOUBLE, PRESS_LONG, PRESS_SHORT, REACTION_TIMEOUT, STATE_CONFIRM,
    STATE_DEFECT, STATE_OK, STATE_OPEN, STATE_SENT, KeyCheck, KeySession, _press,
    record_device_proven, record_key_result,
)


def _checks():
    blind = dict(room_id="r1", be_number="1.1.52", be_type="Tastereinheit",
                 be_title="1.1.52 · EDIZIOdue", reactions={"3/6/27"},
                 actuators=["1.1.5 Motor 3"])
    return [
        KeyCheck(channel="Taste 1", address="3/1/25", designation="J.OG.02.04_move",
                 label="Storen Balkon", press=PRESS_LONG, **blind),
        KeyCheck(channel="Taste 1", address="3/1/26", designation="J.OG.02.04_step",
                 label="Storen Balkon", **blind),
        KeyCheck(room_id="r1", be_number="1.1.40", be_type="Tastereinheit",
                 be_title="1.1.40", channel="Taste 1, links", address="3/4/20",
                 label="Szene High", designation="Raum2_Szene High"),
    ]


def _tel(source, destination, payload="01", service="Write", sent=False):
    return LiveTelegram(datetime.now(), source, destination, service, payload, 0, sent=sent)


def test_press_and_texts():
    assert _press("Taste 1", "AUF/AB, Jalousie", "") == PRESS_LONG
    assert _press("Taste 1", "Schritt/Stop, Jalousie", "") == PRESS_SHORT
    assert _press("Taste 1, Doppelklick", "AUF/AB", "") == PRESS_DOUBLE
    assert _press("Taste 2, links (langer Tastendruck)", "EIN/AUS", "") == PRESS_LONG
    assert _press("Taste 1, links", "EIN/AUS, Schalten", "") == PRESS_SHORT
    check = KeyCheck("r", "1.1.40", "T", "", "Taste 2, links (langer Tastendruck)", "3/4/29",
                     designation="Raum2_Licht Zentral", press=PRESS_LONG)
    assert check.key == "Taste 2, links"
    assert check.instruction() == "Taste 2, links lang drücken"
    assert check.function() == "Raum2_Licht Zentral"


def test_key_with_actuator_status_ok():
    session = KeySession(_checks())
    event = session.on_telegram(_tel("1.1.52", "3/1/25"), 10.0, "Ab")
    assert event.rows == [0] and session.state[0] == STATE_SENT
    assert session.value[0] == "Ab"
    session.on_telegram(_tel("1.1.5", "3/6/27", "33"), 11.0, "20 %")
    assert session.state[0] == STATE_OK and "Status 3/6/27 = 20 %" in session.note[0]
    assert session.state[1] == STATE_OPEN
    assert session.next_open() == 1


def test_no_status_then_tester_decides_late_status_counts():
    session = KeySession(_checks())
    session.on_telegram(_tel("1.1.52", "3/1/25"), 0.0)
    assert session.tick(REACTION_TIMEOUT + 0.1) == [0]
    assert session.state[0] == STATE_CONFIRM and "kein Status" in session.note[0]
    # Storen melden die Position am Ende der Fahrt
    session.on_telegram(_tel("1.1.5", "3/6/27", "FF"), 40.0)
    assert session.state[0] == STATE_OK
    session.on_telegram(_tel("1.1.52", "3/1/26"), 200.0)
    session.tick(200.0 + REACTION_TIMEOUT + 1)
    session.on_telegram(_tel("1.1.5", "3/6/27"), 200.0 + LATE_REACTION + 1)  # zu spät
    assert session.state[1] == STATE_CONFIRM
    session.decide(1, False)
    assert session.state[1] == STATE_DEFECT and "Mangel vor Ort" in session.note[1]


def test_no_actuator_listens_asks_directly():
    session = KeySession(_checks())
    session.on_telegram(_tel("1.1.40", "3/4/20", "01"), 0.0)
    assert session.state[2] == STATE_CONFIRM
    session.decide(2, True)
    assert session.state[2] == STATE_OK and "vor Ort bestätigt" in session.note[2]


def test_confirm_mode_asks_even_with_status():
    session = KeySession(_checks(), confirm=True)
    session.on_telegram(_tel("1.1.52", "3/1/25"), 0.0)
    session.on_telegram(_tel("1.1.5", "3/6/27"), 1.0)
    assert session.state[0] == STATE_CONFIRM and "Status 3/6/27" in session.note[0]


def test_findings_and_ignored():
    session = KeySession(_checks(), room_addresses={"1.1.40": {"3/2/22"}})
    # Taster des Raums auf nicht geplanter GA
    assert "nicht geplant" in session.on_telegram(_tel("1.1.52", "3/1/99"), 0.0).finding
    # Temperatur des Tasters: bekannt, kein Befund
    assert not session.on_telegram(_tel("1.1.40", "3/2/22", "0C1A"), 0.0).finding
    # geplante GA von einem anderen Gerät
    finding = session.on_telegram(_tel("1.1.60", "3/4/20"), 0.0).finding
    assert "1.1.60" in finding and "1.1.40" in finding
    assert session.state[2] == STATE_OPEN
    # eigene Telegramme und Leseanfragen zählen nicht
    assert not session.on_telegram(_tel("1.1.52", "3/1/25", sent=True), 0.0).rows
    assert not session.on_telegram(_tel("1.1.52", "3/1/25", "", "Read"), 0.0).rows
    assert len(session.findings) == 2


def _project_with_checklist():
    project = KnxProject(name="Tastentest")
    items = [
        ChecklistItem(item_kind=ITEM_KIND_DEVICE, check_type=t, room_id="r1",
                      be_type="Tastereinheit", be_number="1.1.52")
        for t in ("Montage", "Physik. Adresse", "Applikation", "Kommunikation")]
    items += [
        ChecklistItem(item_kind=ITEM_KIND_FUNCTION, check_type="Taste 1",
                      function_ga="3/1/25  J.OG.02.04_move  ( Balkon )", room_id="r1",
                      be_type="Tastereinheit", be_number="1.1.52", result=RESULT_DEFECT,
                      notes="Funktionstest: keine Reaktion (vor Ort)"),
        ChecklistItem(item_kind=ITEM_KIND_FUNCTION, check_type="Taste 1",
                      function_ga="3/1/26  J.OG.02.04_step", room_id="r1",
                      be_type="Tastereinheit", be_number="1.1.52"),
    ]
    project.checklists = [CommissioningChecklist(room_id="r1", room_name="Bibliothek",
                                                 items=items)]
    return project, items


def test_record_key_result_and_device_checks():
    project, items = _project_with_checklist()
    check = _checks()[0]
    assert record_key_result(project, check, True, "Tastentest: ok", "MM",
                             date(2026, 11, 18)) == 1
    assert (items[4].result, items[4].checked_by, items[4].notes) == (
        RESULT_OK, "MM", "Tastentest: ok")          # früherer Eintrag überschrieben
    assert items[5].result == ""                     # andere GA der Taste
    assert record_device_proven(project, check, "MM") == 3
    assert [i.result for i in items[:4]] == ["", RESULT_OK, RESULT_OK, RESULT_OK]
    items[3].result = RESULT_DEFECT
    items[1].result = ""
    assert record_device_proven(project, check, "MM") == 1   # Mangel bleibt
    assert items[3].result == RESULT_DEFECT
    project.checklists = []
    assert record_key_result(project, check, True, "x") == 0


def test_planned_project_resolves_names_and_status():
    """Geplant steht im Prüfpunkt der Name ("L_EG_01_01 E/A (Wohnen)"):
    GA über die Struktur, Status aus der Gliederung (RM), Eintrag auf den
    Prüfpunkt der Taste."""
    from tests.test_function_test import _build
    from knix_arranger.services.documentation_service import DocumentationService
    from knix_arranger.services.key_test import plan_key_checks
    project, wohnen, _k = _build()
    project.checklists = DocumentationService(project).create_checklists()
    checks = plan_key_checks(project, wohnen.id)
    gas = {g.address: g for g in project.group_addresses.all_addresses()}
    light = next(c for c in checks if c.channel == "Taste 1")
    assert gas[light.address].function_name == "E/A" and light.press == PRESS_SHORT
    assert "RM" in {gas[a].function_name for a in light.reactions}
    blind = [c for c in checks if c.channel == "Taste 3"]
    assert {c.press for c in blind} == {PRESS_LONG, PRESS_SHORT}
    assert record_key_result(project, light, True, "Tastentest: ok") == 1
    item = next(i for c in project.checklists for i in c.items
                if i.function_ga == light.function_ga and i.check_type == "Taste 1")
    assert item.result == RESULT_OK


# ── Dialog ────────────────────────────────────────────────────────────────

class _Monitor:
    def __init__(self):
        self.connected = False
        self.listening = True
        self.listeners = []

    def add_listener(self, fn):
        self.listeners.append(fn)

    def remove_listener(self, fn):
        self.listeners.remove(fn)

    def value_text(self, telegram):
        return {"01": "Ein", "00": "Aus"}.get(telegram.payload, telegram.payload)

    def emit(self, telegram):
        for fn in list(self.listeners):
            fn(telegram)


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_records_and_shows_findings():
    _app()
    from knix_arranger.ui.dialogs.key_test_dialog import KeyTestDialog
    project, items = _project_with_checklist()
    monitor = _Monitor()
    dialog = KeyTestDialog(project, monitor, "Bibliothek", _checks(), "MM")
    recorded = []
    dialog.recorded.connect(lambda: recorded.append(1))
    dialog.start()
    assert monitor.listeners
    assert "Taste 1 lang drücken" in dialog._next.text()
    monitor.emit(_tel("1.1.52", "3/1/25"))
    assert "warte auf Aktor" in dialog.result_text(0)
    assert items[2].result == RESULT_OK              # Applikation belegt
    monitor.emit(_tel("1.1.5", "3/6/27", "33"))
    assert dialog.result_text(0).startswith("OK") and items[4].result == RESULT_OK
    assert "Taste 1 kurz drücken" in dialog._next.text()
    # Szene ohne Aktor: Tester entscheidet
    monitor.emit(_tel("1.1.40", "3/4/20"))
    assert "reagiert?" in dialog._next.text()
    dialog._table.selectRow(2)
    dialog.decide(False)
    assert dialog.result_text(2).startswith("Mangel")
    assert "nicht in der Checkliste" in dialog.result_text(2)   # kein Prüfpunkt dafür
    monitor.emit(_tel("1.1.52", "3/1/99"))
    assert dialog._findings.count() == 1
    assert recorded
    dialog.done(0)
    assert not monitor.listeners
