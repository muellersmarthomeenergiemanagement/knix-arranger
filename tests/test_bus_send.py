"""
Buszugriff: Wert senden und GA lesen (FA-3102b). Ohne Anlage: Werte
umwandeln, cEMI-Rahmen, Senden über einen Schein-Tunnelserver und eine
Schein-USB-Schnittstelle, Vorsicht bei Alarm/Wetter/Tor, Dialog und Monitor.
"""
from __future__ import annotations

import concurrent.futures
import os
import socket
import threading
import time
from datetime import datetime

import pytest

from knix_arranger.services.bus_access import (
    TUNNEL_UDP, USB, USB_BUSMONITOR, BusConnection, BusSendError, ConnectionSettings,
    LiveTelegram, MonitorContext, PendingReads, Secrets, group_address_raw, group_cemi,
)
from knix_arranger.services.dpt_values import (
    can_encode, decode_value, encode_value, value_suggestions,
)
from tests.test_bus_access import _project

xknx = pytest.importorskip("xknx")


# ── Werte ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dpt, text, payload, size", [
    ("DPST-1-1", "Ein", "01", 0), ("DPST-1-1", "aus", "00", 0), ("1.008", "Ab", "01", 0),
    ("DPST-1-1", "1", "01", 0), ("DPST-3-7", "heller 100 %", "09", 0),
    ("DPST-3-7", "dunkler 25 %", "03", 0), ("DPST-3-7", "Stopp", "00", 0),
    ("DPST-5-1", "50 %", "80", 1), ("DPST-5-1", "100", "FF", 1), ("5.010", "7", "07", 1),
    ("DPST-9-1", "21,5 °C", "0C33", 2), ("DPST-9-1", "-30", "8A24", 2),
    ("7.001", "300", "012C", 2), ("8.001", "−12", "FFF4", 2),
    ("13.013", "-5", "FFFFFFFB", 4), ("14.056", "1234.5", "449A5000", 4),
    ("10.001", "07:30", "071E00", 3), ("11.001", "18.11.2026", "120B1A", 3),
    ("17.001", "Szene 3", "02", 1), ("18.001", "Szene 2 speichern", "81", 1),
    ("232.600", "#FF8000", "FF8000", 3), ("232.600", "bbaa00", "BBAA00", 3),
])
def test_encode_value(dpt, text, payload, size):
    assert encode_value(dpt, text) == (payload, size)


@pytest.mark.parametrize("dpt, text", [
    ("DPST-1-1", "Ein"), ("DPST-5-1", "75 %"), ("DPST-9-1", "-7.5 °C"),
    ("DPST-3-8", "ab 50 %"), ("17.001", "Szene 12"), ("16.000", "Hallo"),
])
def test_encode_then_decode_gives_same_value(dpt, text):
    payload, size = encode_value(dpt, text)
    shown = decode_value(dpt, payload, size)
    assert shown.replace(" ", "").strip("«»").lower() == \
        text.replace(" ", "").lower().replace("°c", "°c")


@pytest.mark.parametrize("dpt, text, message", [
    ("DPST-1-1", "vielleicht", "Aus / Ein"), ("DPST-5-1", "120", "zwischen 0 und 100"),
    ("", "1", "keinen Datenpunkttyp"), ("DPST-9-1", "abc", "keine Zahl"),
    ("10.001", "25:00", "HH:MM"), ("16.000", "x" * 15, "14 Zeichen"),
    ("DPST-1-1", "", "fehlt"),
])
def test_encode_value_explains_errors(dpt, text, message):
    with pytest.raises(ValueError, match=message):
        encode_value(dpt, text)


def test_suggestions_and_sendable_types():
    assert value_suggestions("DPST-1-1") == ["Ein", "Aus"]
    assert value_suggestions("1.008") == ["Ab", "Auf"]
    assert "Stopp" in value_suggestions("DPST-3-7")
    assert can_encode("DPST-9-1") and not can_encode("DPT-15") and not can_encode("")


# ── Rahmen ─────────────────────────────────────────────────────────────────

def test_group_address_raw():
    assert group_address_raw("1/2/3") == 0x0A03
    assert group_address_raw("31/7/255") == 0xFFFF
    assert group_address_raw("1/515") == 0x0A03
    for wrong in ("1/8/0", "32/0/0", "1.1.1", "", "a/b/c"):
        with pytest.raises(BusSendError):
            group_address_raw(wrong)


@pytest.mark.parametrize("service, payload, size", [
    ("Write", "01", 0), ("Write", "0C1A", 2), ("Read", "", None), ("Response", "80", 1),
])
def test_group_cemi_like_xknx(service, payload, size):
    """Der USB-Rahmen entspricht dem, was xknx für denselben Befehl baut."""
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.telegram.address import IndividualAddress
    from knix_arranger.services.bus_access import _xknx_telegram
    live = LiveTelegram(datetime.now(), "", "1/2/3", service, payload, size, sent=True)
    expected = CEMIFrame(code=CEMIMessageCode.L_DATA_REQ, data=CEMILData.init_from_telegram(
        _xknx_telegram(live), src_addr=IndividualAddress(0))).to_knx()
    assert group_cemi("1/2/3", service, payload, size) == expected


# ── Lesen ──────────────────────────────────────────────────────────────────

def test_pending_reads_answer_and_timeout():
    reads = PendingReads(timeout=3)
    got = []
    reads.add("1/2/3", got.append, now=100)
    reads.add("1/0/1", got.append, now=100)
    now = datetime.now()
    # eigene Anfrage und Schreiben beantworten nichts
    assert reads.answered(LiveTelegram(now, "1.1.250", "1/2/3", "Read", sent=True)) == []
    assert reads.answered(LiveTelegram(now, "1.1.5", "1/2/3", "Write", "0C1A", 2)) == []
    assert len(reads.answered(LiveTelegram(now, "1.1.5", "1/2/3", "Response", "0C1A", 2))) == 1
    assert reads.expired(102) == [] and len(reads) == 1
    assert [a for a, _c in reads.expired(103)] == ["1/0/1"] and len(reads) == 0
    # Anfrage nicht gesendet: Vormerkung zurück
    reads.add("1/0/1", got.append, now=200)
    assert reads.cancel("1/0/1", got.append) and len(reads) == 0
    assert not reads.cancel("1/0/1", got.append)


def test_caution_for_alarm_weather_doors():
    project = _project()
    from knix_arranger.models.group_address import GroupAddress, MiddleGroup
    mg = project.group_addresses.main_groups[0]
    mg.middle_groups.append(MiddleGroup(number=7, group_addresses=[
        GroupAddress(main_group=1, middle_group=7, sub_group=1, designation="W WIND ALARM",
                     datapoint_type="DPST-1-5", gewerk_code="W"),
        GroupAddress(main_group=1, middle_group=7, sub_group=2, designation="FK Küche",
                     datapoint_type="DPST-1-19", gewerk_code="FK"),
        GroupAddress(main_group=1, middle_group=7, sub_group=3, designation="Sammelalarm",
                     datapoint_type="DPST-1-5"),
    ]))
    context = MonitorContext(project)
    assert context.caution("1/0/1") == ""                    # Licht
    assert context.caution("1/7/1").startswith("W ")         # Wetterstation
    assert context.caution("1/7/2").startswith("FK ")        # Kategorie Alarm
    assert "Sammelalarm" in context.caution("1/7/3")         # Name


# ── Senden über einen Schein-Tunnelserver ──────────────────────────────────

def _echo_tunnel_server(sock, stop, log):
    """Tunnelserver, der jedes Telegramm bestätigt (Tunnel-ACK und
    L_Data.con) und eine Leseanfrage auf 1/2/3 mit 21.5 °C von 1.1.5
    beantwortet."""
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.dpt import DPTArray
    from xknx.knxip import (
        HPAI, ConnectionStateResponse, ConnectResponse, ConnectResponseData,
        DisconnectResponse, KNXIPFrame, KNXIPServiceType, TunnellingAck, TunnellingRequest,
    )
    from xknx.telegram import Telegram, TelegramDirection
    from xknx.telegram.address import GroupAddress, IndividualAddress
    from xknx.telegram.apci import GroupValueRead, GroupValueResponse

    client, counter = None, 0

    def tunnel(raw: bytes) -> None:
        nonlocal counter
        sock.sendto(KNXIPFrame.init_from_body(TunnellingRequest(
            communication_channel_id=7, sequence_counter=counter, raw_cemi=raw)).to_knx(),
            client)
        counter = (counter + 1) % 256

    while not stop.is_set():
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        frame, _ = KNXIPFrame.from_knx(data)
        service = frame.header.service_type_ident
        if service == KNXIPServiceType.CONNECT_REQUEST:
            client = (addr[0], frame.body.data_endpoint.port or addr[1])
            sock.sendto(KNXIPFrame.init_from_body(ConnectResponse(
                communication_channel=7, data_endpoint=HPAI("127.0.0.1", sock.getsockname()[1]),
                crd=ConnectResponseData(individual_address=IndividualAddress("1.1.250")),
            )).to_knx(), client)
        elif service == KNXIPServiceType.TUNNELLING_REQUEST:
            sock.sendto(KNXIPFrame.init_from_body(TunnellingAck(
                communication_channel_id=7,
                sequence_counter=frame.body.sequence_counter)).to_knx(), addr)
            raw = bytes(frame.body.raw_cemi)
            log.append(raw)
            tunnel(bytes([0x2E]) + raw[1:])                     # L_Data.con positiv
            cemi = CEMIFrame.from_knx(raw)
            telegram = cemi.data.telegram()
            if isinstance(telegram.payload, GroupValueRead) \
                    and telegram.destination_address == GroupAddress("1/2/3"):
                answer = Telegram(destination_address=GroupAddress("1/2/3"),
                                  source_address=IndividualAddress("1.1.5"),
                                  direction=TelegramDirection.INCOMING,
                                  payload=GroupValueResponse(DPTArray((0x0C, 0x33))))
                tunnel(CEMIFrame(code=CEMIMessageCode.L_DATA_IND,
                                 data=CEMILData.init_from_telegram(answer)).to_knx())
        elif service == KNXIPServiceType.CONNECTIONSTATE_REQUEST:
            sock.sendto(KNXIPFrame.init_from_body(
                ConnectionStateResponse(communication_channel_id=7)).to_knx(), addr)
        elif service == KNXIPServiceType.DISCONNECT_REQUEST:
            sock.sendto(KNXIPFrame.init_from_body(
                DisconnectResponse(communication_channel_id=7)).to_knx(), addr)


def _wait(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_send_and_read_over_tunnel():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop, log = threading.Event(), []
    server = threading.Thread(target=_echo_tunnel_server, args=(sock, stop, log), daemon=True)
    server.start()
    received, raw = [], []
    connection = BusConnection(received.append, lambda s, t: None,
                               lambda frame, when: raw.append((frame, when)))
    with pytest.raises(BusSendError, match="Nicht verbunden"):
        connection.send("1/0/1", "Write", "01", 0)
    try:
        connection.start(ConnectionSettings(kind=TUNNEL_UDP, host="127.0.0.1",
                                            port=sock.getsockname()[1]), Secrets())
        assert _wait(lambda: connection.connected)
        assert connection.can_send
        sent = connection.send("1/0/1", "Write", "01", 0).result(timeout=5)
        assert (sent.source, sent.destination, sent.payload, sent.sent) == (
            "1.1.250", "1/0/1", "01", True)
        connection.send("1/2/3", "Read").result(timeout=5)
        assert _wait(lambda: any(t.service == "Response" for t in received))
    finally:
        connection.stop()
        stop.set()
        server.join(2)
        sock.close()
    # beim Server angekommen: Schreiben 1/0/1 = 1, Lesen 1/2/3
    assert log[0] == group_cemi("1/0/1", "Write", "01", 0)[:4] + log[0][4:6] + \
        group_cemi("1/0/1", "Write", "01", 0)[6:]
    assert sorted((t.service, t.destination, t.sent) for t in received) == [
        ("Read", "1/2/3", True), ("Response", "1/2/3", False), ("Write", "1/0/1", True)]
    # eigene Telegramme stehen auch in der Aufzeichnung für die Busanalyse
    from knix_arranger.services.bus_access import live_recording
    summary = live_recording(raw)
    pairs = {(p[0], p[1], p[2]) for p in summary["pairs"]}
    assert ("1.1.250", "1/0/1", "Write") in pairs and ("1.1.5", "1/2/3", "Response") in pairs
    with pytest.raises(BusSendError):
        connection.send("1/0/1", "Write", "01", 0)        # getrennt


# ── Senden über USB ────────────────────────────────────────────────────────

class _UsbSession:
    """Ersatz für knx_usb.UsbSession im Gruppenmonitor: bestätigt jedes
    L_Data.req mit L_Data.con (positiv oder, mit fail, negativ)."""

    def __init__(self, fail=False):
        self.sent, self.queue, self.fail = [], [], fail
        self.link = self

    def send(self, protocol, emi, body):
        self.sent.append(body)
        con = bytearray(body)
        con[0] = 0x2E
        if self.fail:
            con[2] |= 0x01
        self.queue.append(bytes(con))

    def frames(self, timeout_ms=200):
        return self.queue.pop(0) if self.queue else None


def _usb_run(connection, session, settings):
    from knix_arranger.services.bus_access import _usb_loop
    stop = threading.Event()
    original = session.frames
    idle = [0]

    def frames(timeout_ms=200):
        frame = original(timeout_ms)
        idle[0] = 0 if frame else idle[0] + 1
        if idle[0] > 2:
            stop.set()
        return frame
    session.frames = frames
    _usb_loop(connection, settings, session, stop)


def test_send_over_usb_confirmed_and_recorded():
    received, raw = [], []
    connection = BusConnection(received.append, lambda s, t: None,
                               lambda frame, when: raw.append(frame))
    settings = ConnectionSettings(kind=USB, usb_device="0908:02DC:X",
                                  individual_address="1.1.254")
    connection._settings, connection.connected = settings, True
    connection.local_address = "1.1.254"
    future = connection.send("1/2/3", "Write", "0C33", 2)
    session = _UsbSession()
    _usb_run(connection, session, settings)
    assert session.sent == [group_cemi("1/2/3", "Write", "0C33", 2)]
    live = future.result(timeout=0)
    assert (live.source, live.destination, live.payload, live.sent) == (
        "1.1.254", "1/2/3", "0C33", True)
    assert received == [live]
    assert raw and raw[0].startswith("29")         # als L_Data.ind aufgezeichnet


def test_send_over_usb_negative_confirmation():
    connection = BusConnection(lambda t: None, lambda s, t: None)
    settings = ConnectionSettings(kind=USB, usb_device="0908:02DC:X")
    connection._settings, connection.connected = settings, True
    future = connection.send("1/0/1", "Write", "01", 0)
    _usb_run(connection, _UsbSession(fail=True), settings)
    with pytest.raises(BusSendError, match="Fehler beim Senden"):
        future.result(timeout=0)


def test_usb_busmonitor_does_not_send():
    connection = BusConnection(lambda t: None, lambda s, t: None)
    connection._settings = ConnectionSettings(kind=USB_BUSMONITOR, usb_device="0908:02DC:X")
    connection.connected = True
    assert not connection.can_send
    with pytest.raises(BusSendError, match="Busmonitor"):
        connection.send("1/0/1", "Write", "01", 0)


# ── Dialog und Monitor ─────────────────────────────────────────────────────

def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_send_dialog_encodes_and_confirms(monkeypatch):
    _app()
    from PySide6.QtWidgets import QMessageBox
    from knix_arranger.ui.dialogs.bus_send_dialog import BusSendDialog
    context = MonitorContext(_project())
    dialog = BusSendDialog(context, "1/2/3")
    assert dialog._dpt.text() == "9.001" and "IST" in dialog._designation.text()
    dialog._value.setEditText("abc")
    assert not dialog._send_btn.isEnabled() and "keine Zahl" in dialog._preview.text()
    dialog._value.setEditText("21.5")
    assert dialog._send_btn.isEnabled() and "0C33" in dialog._preview.text()
    dialog._send()
    assert dialog.values == ("1/2/3", "0C33", 2, "21.5")

    # Vorsicht: zweite Frage, «Nein» sendet nicht
    context.caution = lambda address: "A Alarm: Vorsicht"
    dialog = BusSendDialog(context, "1/0/1")
    assert dialog._caution.isVisibleTo(dialog)
    dialog._value.setEditText("Ein")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.No)
    dialog._send()
    assert dialog.values is None
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Yes)
    dialog._send()
    assert dialog.values == ("1/0/1", "01", 0, "Ein")


def test_live_monitor_reads_value_and_reports_missing_answer(monkeypatch):
    _app()
    from knix_arranger.ui.views.live_monitor_view import LiveMonitorView
    view = LiveMonitorView()
    view.set_project(_project())
    sent = []

    def fake_send(destination, service="Write", payload="", size=None):
        sent.append((destination, service))
        future = concurrent.futures.Future()
        future.set_result(LiveTelegram(datetime.now(), "1.1.250", destination, service,
                                       sent=True))
        return future
    monkeypatch.setattr(view._connection, "send", fake_send)
    monkeypatch.setattr(type(view._connection), "can_send", property(lambda self: True))
    results = []
    assert view.read("1/2/3", results.append)
    _app().processEvents()                           # Bestätigung (Qt-Signal)
    assert sent == [("1/2/3", "Read")] and len(view._reads) == 1
    view._on_telegram(LiveTelegram(datetime.now(), "1.1.12", "1/2/3", "Response", "0C33", 2))
    assert results == ["1/2/3 H_E05_01 IST: 21.5 °C (Antwort von 1.1.12 Taster EDIZIOdue)"]

    view.read("1/0/1", results.append)
    _app().processEvents()
    monkeypatch.setattr("knix_arranger.ui.views.live_monitor_view.time.monotonic",
                        lambda: 1e12)
    view._flush()
    assert results[-1].startswith("1/0/1 L_E05_01 E/A (Decke): keine Antwort")


def test_live_monitor_without_connection_explains(monkeypatch):
    _app()
    from PySide6.QtWidgets import QMessageBox
    from knix_arranger.ui.views.live_monitor_view import LiveMonitorView
    view = LiveMonitorView()
    view.set_project(_project())
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    assert not view.send_to("1/0/1") and not view.read("1/0/1")
    assert "Verbinden" in shown[0]
    assert not view._send_btn.isEnabled()


def test_bus_entries_in_menus_only_when_connected():
    _app()
    from PySide6.QtWidgets import QMenu
    from knix_arranger.ui.jump_menu import add_bus_actions

    class Jumps:
        connected = False

        def bus_connected(self):
            return self.connected

    jumps = Jumps()
    menu = QMenu()
    add_bus_actions(menu, jumps, "1/0/1")
    assert not menu.actions()
    jumps.connected = True
    add_bus_actions(menu, jumps, "1/0/1")
    assert [a.text() for a in menu.actions() if a.text()] == [
        "1/0/1 am Bus lesen", "Wert auf 1/0/1 senden…"]
