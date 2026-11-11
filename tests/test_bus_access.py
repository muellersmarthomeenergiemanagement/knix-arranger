"""
Buszugriff, Etappe 1a: Live-Gruppenmonitor (FA-3101 ff., services/bus_access).
Ohne Netzwerk: Umwandlung, Zuordnung zum Projekt, Filter, CSV, Einstellungen.
"""
from __future__ import annotations

import csv
from datetime import datetime

import pytest

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.bus_access import (
    ROUTING, ROUTING_SECURE, TUNNEL_SECURE, TUNNEL_UDP, ConnectionSettings, LiveTelegram,
    MonitorContext, Secrets, connection_config, export_csv, row_matches, telegram_from_xknx,
)

xknx = pytest.importorskip("xknx")


def _project():
    kueche = Room(number="E05", name="Küche")
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="Erdgeschoss", short_code="EG", apartments=[Apartment(rooms=[kueche])])])])])
    licht = GroupAddress(main_group=1, middle_group=0, sub_group=1,
                         designation="L_E05_01 E/A  (Decke)", datapoint_type="DPST-1-1",
                         gewerk_code="L", room_id=kueche.id)
    temp = GroupAddress(main_group=1, middle_group=2, sub_group=3,
                        designation="H_E05_01 IST", datapoint_type="DPST-9-1",
                        gewerk_code="H", room_id=kueche.id)
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=1, middle_groups=[MiddleGroup(number=0, group_addresses=[licht]),
                                 MiddleGroup(number=2, group_addresses=[temp])])])
    project.topology = Topology(areas=[Area(area_number=1, lines=[Line(line_number=1, devices=[
        Device(device_type="sensor", physical_address="1.1.12", product="Taster EDIZIOdue"),
    ])])])
    return project


def _xknx_telegram(destination, payload, source="1.1.12"):
    from xknx.telegram import Telegram, TelegramDirection
    from xknx.telegram.address import GroupAddress, IndividualAddress
    if isinstance(destination, str):
        destination = GroupAddress(destination)
    return Telegram(destination_address=destination, source_address=IndividualAddress(source),
                    direction=TelegramDirection.INCOMING, payload=payload)


def test_telegram_from_xknx():
    from xknx.dpt import DPTArray, DPTBinary
    from xknx.telegram.address import IndividualAddress
    from xknx.telegram.apci import GroupValueRead, GroupValueWrite, MemoryRead

    now = datetime(2026, 11, 11, 14, 0, 5)
    t = telegram_from_xknx(_xknx_telegram("1/0/1", GroupValueWrite(DPTBinary(1))), now)
    assert (t.source, t.destination, t.service, t.payload, t.size) == (
        "1.1.12", "1/0/1", "Write", "01", 0)
    t = telegram_from_xknx(_xknx_telegram("1/2/3", GroupValueWrite(DPTArray((0x0C, 0x1A)))))
    assert (t.payload, t.size) == ("0C1A", 2)
    t = telegram_from_xknx(_xknx_telegram("1/2/3", GroupValueRead()))
    assert (t.service, t.payload) == ("Read", "")
    # Gerätezugriff (ETS programmiert) erscheint nicht im Gruppenmonitor
    assert telegram_from_xknx(_xknx_telegram(IndividualAddress("1.1.5"),
                                             MemoryRead(address=0x10, count=1))) is None


def test_row_with_project_data():
    context = MonitorContext(_project())
    now = datetime(2026, 11, 11, 14, 0, 5, 123000)
    row = context.row(LiveTelegram(now, "1.1.12", "1/0/1", "Write", "01", 0))
    assert row.sender == "1.1.12 Taster EDIZIOdue"
    assert row.designation == "L_E05_01 E/A (Decke)"
    assert row.value == "Ein"
    assert row.gewerk.startswith("L")
    assert row.floor == "Erdgeschoss"
    assert row.cells()[0] == "14:00:05.123"
    temp = context.row(LiveTelegram(now, "1.1.12", "1/2/3", "Write", "0C1A", 2))
    assert temp.value.endswith("°C")
    unknown = context.row(LiveTelegram(now, "1.1.99", "5/5/5", "Write", "01", 0))
    assert (unknown.known, unknown.value, unknown.sender) == (False, "01", "1.1.99")
    read = context.row(LiveTelegram(now, "1.1.12", "1/2/3", "Read"))
    assert read.value == "" and read.cells()[4] == "Lesen"


def test_filter_by_text_gewerk_floor():
    context = MonitorContext(_project())
    now = datetime(2026, 11, 11)
    licht = context.row(LiveTelegram(now, "1.1.12", "1/0/1", "Write", "01", 0))
    heizung = context.row(LiveTelegram(now, "1.1.12", "1/2/3", "Write", "0C1A", 2))
    assert row_matches(licht, "1/0/1") and not row_matches(heizung, "1/0/1")
    assert row_matches(licht, "decke")
    assert row_matches(heizung, gewerk="H") and not row_matches(licht, gewerk="H")
    assert row_matches(licht, floor="Erdgeschoss") and not row_matches(licht, floor="OG")
    # Gewerk-Kürzel genau: «L» findet nicht «LD»
    licht.gewerk = "LD Licht dimmen"
    assert not row_matches(licht, gewerk="L") and row_matches(licht, gewerk="LD")


def test_csv_export(tmp_path):
    context = MonitorContext(_project())
    rows = [context.row(LiveTelegram(datetime(2026, 11, 11, 8, 30), "1.1.12", "1/0/1",
                                     "Write", "01", 0))]
    path = tmp_path / "monitor.csv"
    assert export_csv(rows, str(path)) == 1
    with open(path, encoding="utf-8-sig") as fh:
        lines = list(csv.reader(fh, delimiter=";"))
    assert lines[0][:4] == ["Datum", "Zeit", "Absender", "GA"]
    assert lines[1][0] == "11.11.2026" and "Ein" in lines[1] and lines[1][-1] == "DPST-1-1"


def test_settings_saved_without_passwords_and_checked():
    settings = ConnectionSettings(kind=TUNNEL_SECURE, host="10.0.0.5", user_id=2)
    data = settings.to_dict()
    assert "password" not in str(data).lower()
    assert ConnectionSettings.from_dict(data) == settings
    assert ConnectionSettings.from_dict({"kind": "unbekannt"}).kind == TUNNEL_UDP
    assert settings.problems(Secrets()) == [
        "Benutzer-ID und Passwort des Tunnels oder eine Schlüsseldatei angeben."]
    assert settings.problems(Secrets(user_password="geheim")) == []
    assert ConnectionSettings(kind=TUNNEL_UDP).problems() == [
        "Adresse der Schnittstelle (IP oder Name) fehlt."]
    assert ConnectionSettings(kind=ROUTING).problems() == []
    assert ConnectionSettings(kind=ROUTING_SECURE).problems(Secrets()) == [
        "Backbone-Schlüssel oder Schlüsseldatei fehlt."]


def test_connection_config_for_xknx():
    from xknx.io import ConnectionType
    config = connection_config(ConnectionSettings(host="192.168.1.20", route_back=True),
                               Secrets())
    assert config.connection_type == ConnectionType.TUNNELING
    assert (config.gateway_ip, config.gateway_port, config.route_back) == (
        "192.168.1.20", 3671, True)
    config = connection_config(ConnectionSettings(kind=TUNNEL_SECURE, host="10.0.0.5",
                                                  user_id=3),
                               Secrets(user_password="geheim"))
    assert config.connection_type == ConnectionType.TUNNELING_TCP_SECURE
    assert (config.secure_config.user_id, config.secure_config.user_password) == (3, "geheim")
    assert connection_config(ConnectionSettings(kind=ROUTING), Secrets()).connection_type \
        == ConnectionType.ROUTING


def _view(project):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.views.live_monitor_view import LiveMonitorView
    view = LiveMonitorView()
    view.set_project(project)
    return view


def test_live_monitor_view_shows_filters_pauses_and_exports(tmp_path, monkeypatch):
    view = _view(_project())
    now = datetime(2026, 11, 11, 9, 0)
    view._on_telegram(LiveTelegram(now, "1.1.12", "1/0/1", "Write", "01", 0))
    view._on_telegram(LiveTelegram(now, "1.1.12", "1/2/3", "Write", "0C1A", 2))
    view._flush()
    assert len(view._model.rows) == 2 and view._proxy.rowCount() == 2
    assert view._proxy.index(0, 5).data() == "Ein"

    view._search.setText("1/2/3")
    assert view._proxy.rowCount() == 1
    view._search.clear()
    view._gewerk.setCurrentIndex(view._gewerk.findData("H"))
    assert view._proxy.rowCount() == 1
    view._gewerk.setCurrentIndex(0)

    # Anhalten: weiter aufzeichnen, erst beim Fortsetzen anzeigen
    view._pause_btn.setChecked(True)
    view._on_telegram(LiveTelegram(now, "1.1.12", "1/0/1", "Write", "00", 0))
    view._flush()
    assert len(view._model.rows) == 2 and "1 angehalten" in view._count.text()
    view._pause_btn.setChecked(False)
    assert len(view._model.rows) == 3

    path = tmp_path / "aufzeichnung.csv"
    from knix_arranger.ui import license_gate
    monkeypatch.setattr(license_gate, "get_save_file_name", lambda *a, **k: (str(path), ""))
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    view._export()
    assert path.read_text(encoding="utf-8-sig").count("\n") == 4


def test_live_monitor_states_and_new_project():
    view = _view(_project())
    view._on_state("error", "Schnittstelle antwortet nicht")
    view._on_state("disconnected", "")          # Fehlermeldung bleibt stehen
    assert view._status.text().startswith("Fehler: Schnittstelle")
    assert view._connect_btn.isEnabled() and not view._disconnect_btn.isEnabled()
    view.set_project(_project())                # anderes Projekt: Zuordnung neu
    assert view._context is not None


def test_connection_dialog_checks_and_returns_settings():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.bus_connection_dialog import BusConnectionDialog
    dialog = BusConnectionDialog(ConnectionSettings(kind=TUNNEL_SECURE, host="10.0.0.5",
                                                    user_id=2))
    assert dialog._user_password.isVisibleTo(dialog)
    dialog._user_password.setText("geheim")
    assert dialog.settings().user_id == 2 and dialog.secrets().user_password == "geheim"
    dialog._kind.setCurrentIndex(dialog._kind.findData(ROUTING))
    assert not dialog._host.isVisibleTo(dialog)


def _fake_tunnel_server(sock, stop):
    """Schein-Tunnelserver (UDP): Verbindung annehmen, ein Gruppentelegramm
    1/0/1 = 1 von 1.1.12 schicken, Zustandsabfrage und Trennen beantworten."""
    import socket
    import time
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.dpt import DPTBinary
    from xknx.knxip import (
        HPAI, ConnectionStateResponse, ConnectResponse, ConnectResponseData,
        DisconnectResponse, KNXIPFrame, KNXIPServiceType, TunnellingRequest,
    )
    from xknx.telegram import Telegram, TelegramDirection
    from xknx.telegram.address import GroupAddress, IndividualAddress
    from xknx.telegram.apci import GroupValueWrite

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
            time.sleep(0.2)
            telegram = Telegram(destination_address=GroupAddress("1/0/1"),
                                source_address=IndividualAddress("1.1.12"),
                                direction=TelegramDirection.INCOMING,
                                payload=GroupValueWrite(DPTBinary(1)))
            cemi = CEMIFrame(code=CEMIMessageCode.L_DATA_IND,
                             data=CEMILData.init_from_telegram(telegram))
            sock.sendto(KNXIPFrame.init_from_body(TunnellingRequest(
                communication_channel_id=7, sequence_counter=0, raw_cemi=cemi.to_knx(),
            )).to_knx(), client)
        elif service == KNXIPServiceType.CONNECTIONSTATE_REQUEST:
            sock.sendto(KNXIPFrame.init_from_body(
                ConnectionStateResponse(communication_channel_id=7)).to_knx(), addr)
        elif service == KNXIPServiceType.DISCONNECT_REQUEST:
            sock.sendto(KNXIPFrame.init_from_body(
                DisconnectResponse(communication_channel_id=7)).to_knx(), addr)


def test_connection_receives_telegram_from_tunnel_server():
    """Ganzer Weg ohne Anlage: Thread, xknx, Tunnel, Rückruf, Trennen."""
    import socket
    import threading
    import time
    from knix_arranger.services.bus_access import BusConnection

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop = threading.Event()
    server = threading.Thread(target=_fake_tunnel_server, args=(sock, stop), daemon=True)
    server.start()
    received, states, raw = [], [], []
    connection = BusConnection(received.append, lambda state, _text: states.append(state),
                               lambda frame, when: raw.append((frame, when)))
    try:
        connection.start(ConnectionSettings(host="127.0.0.1", port=sock.getsockname()[1]),
                         Secrets())
        for _ in range(50):
            if received:
                break
            time.sleep(0.1)
    finally:
        connection.stop()
        stop.set()
        server.join(2)
        sock.close()
    assert [(t.source, t.destination, t.service, t.payload) for t in received] == [
        ("1.1.12", "1/0/1", "Write", "01")]
    assert "connected" in states and states[-1] == "disconnected"
    assert not connection.running
    # roher cEMI-Rahmen (L_Data.ind) für die Busanalyse
    assert len(raw) == 1 and raw[0][0].startswith("29")
    from knix_arranger.services.bus_access import live_recording
    summary = live_recording(raw, connection="Tunnel · Test")
    assert summary["telegrams"] == 1 and summary["connection"] == "Tunnel · Test"
    assert summary["pairs"][0][:4] == ["1.1.12", "1/0/1", "Write", 1]


def test_connection_error_when_nobody_answers():
    import time
    from knix_arranger.services.bus_access import BusConnection
    states = []
    connection = BusConnection(lambda t: None, lambda state, text: states.append((state, text)))
    connection.start(ConnectionSettings(host="127.0.0.1", port=3999), Secrets())
    for _ in range(100):
        if not connection.running:
            break
        time.sleep(0.1)
    connection.stop()
    assert states[-1][0] == "error"
    assert states[-1][1].startswith("Schnittstelle antwortet nicht")


def _raw_frame(destination="1/0/1", source="1.1.12", value=1) -> str:
    """Roher cEMI-Rahmen L_Data.ind (Hex) wie von der Schnittstelle."""
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.dpt import DPTBinary
    from xknx.telegram import Telegram, TelegramDirection
    from xknx.telegram.address import GroupAddress, IndividualAddress
    from xknx.telegram.apci import GroupValueWrite
    telegram = Telegram(destination_address=GroupAddress(destination),
                        source_address=IndividualAddress(source),
                        direction=TelegramDirection.INCOMING,
                        payload=GroupValueWrite(DPTBinary(value)))
    return CEMIFrame(code=CEMIMessageCode.L_DATA_IND,
                     data=CEMILData.init_from_telegram(telegram)).to_knx().hex().upper()


def test_live_recording_like_ets_group_monitor():
    from knix_arranger.services.bus_access import live_recording
    from knix_arranger.services.bus_monitor import BusLogError
    t0 = datetime(2026, 11, 11, 16, 0, 0)
    frames = [(_raw_frame(), t0), (_raw_frame(value=0), t0.replace(second=30)),
              (_raw_frame("5/5/5", "1.1.99"), t0.replace(minute=1))]
    summary = live_recording(frames)
    assert summary["file"] == "Live-Monitor 11.11.2026 16:00"
    assert summary["mode"].startswith("Gruppenmonitor")
    assert (summary["telegrams"], summary["repeats"], summary["ack_known"]) == (3, 0, False)
    assert [p[:4] for p in summary["pairs"]] == [["1.1.12", "1/0/1", "Write", 2],
                                                 ["1.1.99", "5/5/5", "Write", 1]]
    assert len(summary["minutes"]) == 2               # Buslast je Minute
    with pytest.raises(BusLogError):
        live_recording([])


def test_live_monitor_hands_recording_to_bus_analysis(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from knix_arranger.services.bus_monitor import analyze
    project = _project()
    view = _view(project)
    assert not view._analysis_btn.isEnabled()
    t0 = datetime(2026, 11, 11, 16, 0, 0)
    view._on_raw(_raw_frame(), t0)
    view._on_raw(_raw_frame("5/5/5", "1.1.99"), t0)
    view._update_controls()
    assert view._analysis_btn.isEnabled()
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    added = []
    view.recording_added.connect(lambda: added.append(True))
    view._to_analysis()
    assert added and len(project.bus_recordings) == 1 and "2 Telegramme" in shown[0]
    analysis = analyze(project, project.bus_recordings[0])
    assert [s.address for s in analysis.unknown] == ["1.1.99"]     # Absender ausserhalb
    assert [p.dst for p in analysis.missing_gas] == ["5/5/5"]           # GA nicht im Projekt
    view._clear()
    assert not view._raw and not view._analysis_btn.isEnabled()
