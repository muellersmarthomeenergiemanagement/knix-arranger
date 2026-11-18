"""Sensorprüfung (FA-3107): Bereiche, Auswertung, Eintrag, Dialog."""
from __future__ import annotations

import os
from datetime import datetime

from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, Room, Wing,
)
from knix_arranger.models.documentation import (
    ITEM_KIND_DEVICE, ITEM_KIND_FUNCTION, RESULT_DEFECT, RESULT_OK, ChecklistItem,
    CommissioningChecklist,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line
from knix_arranger.services.bus_access import LiveTelegram
from knix_arranger.services.dpt_values import numeric_value
from knix_arranger.services.sensor_test import (
    KIND_MESSAGE, KIND_VALUE, STATE_BAD, STATE_OK, STATE_OPEN, SensorSession,
    plan_sensor_points, plausible_range, record_sensor_result,
)


def test_numeric_value():
    assert numeric_value("DPST-9-1", "0C1A", 2) == 21.0
    assert numeric_value("DPST-5-1", "FF", 1) == 100
    assert numeric_value("DPST-7-13", "01F4", 2) == 500
    assert numeric_value("DPST-1-1", "01", 0) is None
    assert numeric_value("DPST-9-1", "0C", 1) is None        # falsche Länge


def test_plausible_range():
    assert plausible_range("DPST-9-1", "Raumtemperatur", "03 Wohnen") == (5, 40, "°C")
    assert plausible_range("DPST-9-1", "Temp.Sensor", "02 Garage")[0] == -20
    assert plausible_range("DPST-9-1", "Aussentemperatur", "Dach")[0] == -40
    assert plausible_range("DPST-9-1", "Raumtemperatur", "02 Hamam")[1] == 110
    assert plausible_range("DPST-9-1", "Taupunkt: Messwert", "00 Halle")[0] == -30
    assert plausible_range("DPST-9-7", "Feuchte", "")[:2] == (1, 100)
    assert plausible_range("DPST-1-5", "Alarm", "") is None


def _project():
    """Wohnen mit Rauchmelder (Temperatur, Alarm, Quittieren als Eingang)
    und Taster mit Temperaturfühler; dazu ihre Prüfpunkte."""
    project = KnxProject(name="Sensoren")
    room = Room(number="03", name="Wohnen", bedienelemente=[
        Bedienelement(element_type="Rauchmelder", participant_number="1.1.25"),
        Bedienelement(element_type="Tastereinheit", participant_number="1.1.48")])
    floor = Floor(name="EG", short_code="EG", apartments=[Apartment(name="Z", rooms=[room])])
    project.areal = Areal(buildings=[Building(name="H", wings=[Wing(floors=[floor])])])
    smoke = Device(physical_address="1.1.25", device_type="sensor", product="Salva KNX TH",
                   communication_objects=[
                       CommunicationObject(object_number=43, name="Temp.Sensor: Messwert", object_function="Ausgang",
                                           flags="KL-Ü--", data_type="DPST-9-1",
                                           connected_gas=["1/2/1"]),
                       CommunicationObject(object_number=1491, name="Rauchm.:Alarm (0: Aktiv)", object_function="Ausgang",
                                           flags="KL-Ü--", data_type="DPST-1-5",
                                           connected_gas=["1/3/102"]),
                       CommunicationObject(object_number=1493, name="Rauchm.: Alarm Aus", object_function="Eingang",
                                           flags="K-S---", data_type="DPST-1-1",
                                           connected_gas=["1/3/104"])])
    taster = Device(physical_address="1.1.48", device_type="sensor", product="EDIZIOdue",
                    communication_objects=[
                        CommunicationObject(object_number=70, name="Raumtemperatur", object_function="senden", flags="KL-Ü--",
                                            data_type="DPST-9-1", connected_gas=["3/2/32"]),
                        CommunicationObject(object_number=0, name="Taste 1", object_function="Schalten", flags="K-SÜ--",
                                            data_type="DPST-1-1", connected_gas=["3/0/1"]),
                        CommunicationObject(object_number=19, name="Taste 4, links", object_function="Dimmen", flags="K--Ü--",
                                            data_type="DPST-3-7", connected_gas=["3/0/91"])])
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1, devices=[smoke, taster])])]
    items = [ChecklistItem(item_kind=ITEM_KIND_DEVICE, check_type="Kommunikation",
                           room_id=room.id, be_type="Rauchmelder", be_number="1.1.25"),
             ChecklistItem(item_kind=ITEM_KIND_FUNCTION, check_type="Temp.Sensor: Messwert",
                           function_ga="1/2/1  H.UG.01.1_ist Temp", room_id=room.id,
                           be_type="Rauchmelder", be_number="1.1.25")]
    project.checklists = [CommissioningChecklist(room_id=room.id, room_name="03 Wohnen",
                                                 items=items)]
    return project, room, items


def test_plan_points():
    project, room, _items = _project()
    points = plan_sensor_points(project)
    assert [(p.be_number, p.address, p.kind) for p in points] == [
        ("1.1.25", "1/2/1", KIND_VALUE), ("1.1.25", "1/3/102", KIND_MESSAGE),
        ("1.1.48", "3/2/32", KIND_VALUE)]           # Eingang, Tasten, Dimmen nicht
    assert points[0].expected() == "5 … 40 °C" and points[0].readable
    assert points[0].room == "03 Wohnen"
    assert plan_sensor_points(project, {"anderer Raum"}) == []
    assert len(plan_sensor_points(project, {room.id})) == 3


def _tel(source, destination, payload, size=2, service="Write", sent=False):
    return LiveTelegram(datetime.now(), source, destination, service, payload, size, sent=sent)


def test_session_plausible_bad_and_foreign():
    project, _room, _items = _project()
    session = SensorSession(plan_sensor_points(project))
    assert session.on_telegram(_tel("1.1.25", "1/2/1", "0C1A"), "21 °C") == [0]
    assert session.state[0] == STATE_OK and "21 °C" in session.note(0)
    session.on_telegram(_tel("1.1.25", "1/2/1", "0000"), "0 °C")       # unplausibel
    session.on_telegram(_tel("1.1.25", "1/2/1", "0C1A"), "21 °C")
    assert session.state[0] == STATE_BAD and "0 °C" in session.note(0)   # bleibt
    # Meldung: jeder Wert zählt
    session.on_telegram(_tel("1.1.25", "1/3/102", "01", 0, "Response"), "Alarm")
    assert session.state[1] == STATE_OK
    # fremder Absender auf der Sensor-GA: Hinweis, kein Ergebnis
    assert session.on_telegram(_tel("1.1.99", "3/2/32", "0C1A"), "21 °C") == [2]
    assert session.state[2] == STATE_OPEN and session.readings[2].others == {"1.1.99"}
    # eigene Leseanfragen und gesendete zählen nicht
    assert not session.on_telegram(_tel("", "3/2/32", "", None, "Read"))
    assert session.to_read() == [2]
    assert session.summary() == (1, 1, 1)


def test_record_sensor_result():
    project, _room, items = _project()
    point = plan_sensor_points(project)[0]
    assert record_sensor_result(project, point, False, "Sensorprüfung: x", "MM") == 1
    assert items[1].result == RESULT_DEFECT and items[1].checked_by == "MM"
    assert items[0].result == ""
    project.checklists = []
    assert record_sensor_result(project, point, True, "x") == 0


class _Monitor:
    def __init__(self, history=()):
        self.connected = True
        self.listening = True
        self.listeners = []
        self.sent = []
        self._history = list(history)

    def history(self):
        return self._history

    def add_listener(self, fn):
        self.listeners.append(fn)

    def remove_listener(self, fn):
        self.listeners.remove(fn)

    def value_text(self, telegram):
        return {"0C1A": "21 °C", "01": "Alarm"}.get(telegram.payload, telegram.payload)

    def send_telegram(self, destination, service, payload, size, on_done):
        self.sent.append((destination, service))
        on_done("")
        return True

    def emit(self, telegram):
        for fn in list(self.listeners):
            fn(telegram)


def test_dialog_history_reads_and_records():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.sensor_test_dialog import SensorTestDialog
    project, _room, items = _project()
    monitor = _Monitor(history=[_tel("1.1.25", "1/2/1", "0C1A")])   # schon empfangen
    dialog = SensorTestDialog(project, monitor, plan_sensor_points(project), "MM")
    dialog.start()
    assert dialog.result_text(0) == "OK"
    assert items[1].result == RESULT_OK and items[0].result == RESULT_OK  # Kommunikation
    assert "1 OK" in dialog._status.text()
    dialog.read_missing()
    import time
    deadline = time.monotonic() + 5
    while dialog._reads and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert monitor.sent == [("1/3/102", "Read"), ("3/2/32", "Read")]
    monitor.emit(_tel("1.1.48", "3/2/32", "0C1A", service="Response"))
    assert dialog.result_text(2) == "OK"
    dialog.done(0)
    assert not monitor.listeners
