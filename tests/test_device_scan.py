"""
Teilnehmer suchen (FA-3108): Kennungen lesen, Vergleich mit dem Projekt
und die Suche über einen Schein-Tunnelserver mit simulierten Geräten
(System B, BCU 1, gesperrt, stumm, fehlend).
"""
from __future__ import annotations

import os
import socket
import threading
from types import SimpleNamespace

import pytest

from knix_arranger.services import device_scan as ds
from knix_arranger.services.bus_access import (
    TUNNEL_UDP, BusConnection, BusSendError, ConnectionSettings, Secrets,
)

xknx = pytest.importorskip("xknx")


# ── Kennungen ──────────────────────────────────────────────────────────────

def test_parse_lines():
    assert ds.parse_lines("1.1, 1.2;1.1 2.3") == [(1, 1), (1, 2), (2, 3)]
    for wrong, message in (("", "Keine Linie"), ("1.1.5", "keine Linie"),
                           ("16.1", "bis 15"), ("a", "keine Linie")):
        with pytest.raises(ValueError, match=message):
            ds.parse_lines(wrong)


def test_identity_bytes():
    assert ds.program_from_bytes(bytes.fromhex("0002470111")) == ("M-0002", "4701-11")
    assert ds.program_from_bytes(b"\x00") == ("", "")
    assert ds.serial_from_bytes(bytes.fromhex("000211223344")) == "0002:11223344"
    assert ds.bcu1_identity(bytes.fromhex("1E102205")) == ("M-001E", "1022-05")
    assert ds.order_text(b"GH Q631\x00\x00\x00") == "GH Q631"
    assert ds.order_text(b"\x00" * 10) == ""
    assert ds.order_text(b"\x01\x02") == ""                # nicht lesbar: keine
    assert ds.mask_text(0x07B0) == "07B0 System B"
    assert ds.mask_text(0x0012) == "0012 BCU 1"
    assert ds.mask_text(0x091A) == "091A Koppler"
    assert ds.mask_text(None) == ""


def test_expected_program_from_hw2prog():
    device = SimpleNamespace(
        manufacturer_id="M-0002",
        hw2prog_id="M-0002_H-GH.20Q631.200047.20R0111-1_HP-4701-11-952C")
    assert ds.expected_program(device) == ("M-0002", "4701-11")
    assert ds.expected_program(SimpleNamespace(hw2prog_id="")) == ("", "")


# ── Vergleich ──────────────────────────────────────────────────────────────

def _device(address, mfr="M-0002", hp="4701-11", serial="", secure=False, **extra):
    return SimpleNamespace(
        physical_address=address, manufacturer_id=mfr, manufacturer="",
        hw2prog_id=f"{mfr}_H-X-1_HP-{hp}-952C" if hp else "",
        serial_number=serial, secure_supported=secure, external=False,
        product=f"Produkt {address}", product_name="", order_number="",
        application_program="App", **extra)


def _project(devices, secure=False):
    line = SimpleNamespace(devices=devices)
    return SimpleNamespace(topology=SimpleNamespace(areas=[SimpleNamespace(lines=[line])]),
                           knx_secure=SimpleNamespace(enabled=secure))


def test_compare_with_project():
    project = _project([
        _device("1.1.1"),                                    # stimmt
        _device("1.1.2", serial="0002:AAAAAAAA"),            # getauscht
        _device("1.1.3", hp="4701-12"),                      # andere Version
        _device("1.1.4", mfr="M-0083"),                      # anderer Hersteller
        _device("1.1.5", secure=True),                       # stumm, Secure
        _device("1.1.6"),                                    # stumm
        _device("1.1.8", secure=True),                       # gesperrt
        _device("1.2.1"),                                    # andere Linie: nicht gesucht
        _device("1.1.-"),                                    # ohne Adresse
    ], secure=True)
    found = [
        ds.ScanFinding("1.1.1", True, 0x07B0, "M-0002", "0002:11111111", program="4701-11",
                       program_manufacturer="M-0002"),
        ds.ScanFinding("1.1.2", True, 0x07B0, "M-0002", "0002:BBBBBBBB", program="4701-11"),
        ds.ScanFinding("1.1.3", True, 0x07B0, "M-0002", program="4701-11"),
        ds.ScanFinding("1.1.4", True, 0x07B0, "M-0002", program="4701-11"),
        ds.ScanFinding("1.1.8", True, 0x07B0),
        ds.ScanFinding("1.1.9", True, 0x0012, "M-001E", program="1022-05"),
        ds.ScanFinding("1.1.250", True, own=True),
    ]
    rows = {r.address: r for r in ds.compare(project, found, [(1, 1)])}
    assert set(rows) == {"1.1.1", "1.1.2", "1.1.3", "1.1.4", "1.1.5", "1.1.6", "1.1.8",
                         "1.1.9", "1.1.250"}
    assert rows["1.1.1"].status == ds.STATUS_OK
    assert "Seriennummer im Projekt leer" in rows["1.1.1"].note
    assert rows["1.1.2"].status == ds.STATUS_DIFFERENT and "getauscht" in rows["1.1.2"].note
    assert "Applikationsversion (11 statt 12)" in rows["1.1.3"].note
    assert "Hersteller ABB statt MDT" in rows["1.1.4"].note
    assert rows["1.1.5"].status == ds.STATUS_MISSING and "Secure" in rows["1.1.5"].note
    assert rows["1.1.6"].status == ds.STATUS_MISSING and "Secure" not in rows["1.1.6"].note
    assert rows["1.1.8"].status == ds.STATUS_LOCKED and "Secure" in rows["1.1.8"].note
    assert rows["1.1.9"].status == ds.STATUS_EXTRA
    assert (rows["1.1.9"].manufacturer, rows["1.1.9"].application) == ("Feller", "1022-05")
    assert rows["1.1.250"].status == ds.STATUS_OWN
    assert ds.summary(list(rows.values())) == (
        "1 stimmt, 3 abweichend, 1 nicht im Projekt, 1 Daten gesperrt, 2 antwortet nicht")
    # ohne Projekt: alles Gefundene ist neu
    assert {r.status for r in ds.compare(None, found[:1], [(1, 1)])} == {ds.STATUS_EXTRA}


def test_export_csv(tmp_path):
    rows = ds.compare(_project([_device("1.1.1")]), [], [(1, 1)])
    path = tmp_path / "t.csv"
    assert ds.export_csv(rows, str(path)) == 1
    text = path.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("Adresse;Ergebnis") and "antwortet nicht" in text


# ── Suche über einen Schein-Tunnelserver ───────────────────────────────────

# simulierte Geräte auf Linie 1.1
_DEVICES = {
    "1.1.5": {"mask": 0x07B0, "props": {
        (0, 12): bytes.fromhex("0002"), (0, 11): bytes.fromhex("000211223344"),
        (0, 78): bytes.fromhex("000000000047"), (0, 15): b"GH Q631\x00\x00\x00",
        (3, 1): bytes.fromhex("0003"), (3, 13): bytes.fromhex("0002470111"),
        # Tabellen-Objekte: Typ, geladen, Lage im Speicher
        (1, 1): bytes.fromhex("0001"), (2, 1): bytes.fromhex("0002"),
        (1, 5): bytes([1]), (2, 5): bytes([1]),
        (1, 7): bytes.fromhex("00004000"), (2, 7): bytes.fromhex("00005000"),
        (4, 1): bytes.fromhex("0009")},
        "memory": {
            # 3 GAs: 1/0/1, 1/0/2, 2/1/5 (ohne eigene Adresse)
            0x4000: bytes.fromhex("0003" "0801" "0802" "1105"),
            # KO 0 an 1/0/1 und 2/1/5, KO 4 an 1/0/2 (je TSAP, ASAP 2 Byte)
            0x5000: bytes.fromhex("0003" "00010000" "00030000" "00020004")},
        # KO-Tabelle (Typ 9) als PID_TABLE: KO 0 K S Ü, KO 4 K S
        "tables": {4: [bytes([0x54, 0x00]), bytes([0x00, 0x00]), bytes([0x00, 0x00]),
                       bytes([0x00, 0x00]), bytes([0x14, 0x07]), bytes([0x00, 0x00])]}},
    "1.1.7": {"mask": 0x0012, "memory": {
        0x0104: bytes.fromhex("1E102205"),
        # Anzahl 3 inkl. eigener Adresse 1.1.7, GAs 1/0/1 und 1/0/3
        0x0111: bytes([0x50]), 0x0116: bytes.fromhex("03" "1107" "0801" "0803"),
        # KO 0 an 1/0/1, KO 1 an 1/0/3
        0x0150: bytes.fromhex("02" "0100" "0201"),
        # KO-Tabelle: Anzahl, RAM-Zeiger, je KO Wert-Zeiger, Konfiguration, Typ
        0x0112: bytes([0x70]), 0x0170: bytes.fromhex("02" "C0" "205400" "211C00")}},
    "1.1.9": {"mask": 0x07B0, "props": {}},          # gibt nichts preis
    "1.1.11": {"silent": True},                      # quittiert, antwortet nie
    # System B mit Tabellen über 0xFFFF (Elsner Salva 0x13000): erweitertes Lesen
    "1.1.13": {"mask": 0x07B0, "props": {
        (0, 12): bytes.fromhex("00C9"), (3, 1): bytes.fromhex("0003"),
        (3, 13): bytes.fromhex("00C9010110"),
        (1, 1): bytes.fromhex("0001"), (2, 1): bytes.fromhex("0002"),
        (1, 5): bytes([1]), (2, 5): bytes([1]),
        (1, 7): bytes.fromhex("00013000"), (2, 7): bytes.fromhex("00013100")},
        "memory": {0x13000: bytes.fromhex("0002" "0801" "0A05"),
                   0x13100: bytes.fromhex("0002" "00010002" "00020003")}},
    # System 7 (ABB 0701): Lage laut Objekt passt nicht, Tabellen an der BCU-2-Lage;
    # Hersteller 0000 (wie Theben HTS), Seriennummer aus Nullen
    "1.1.15": {"mask": 0x0701, "props": {
        (0, 12): bytes.fromhex("0000"), (0, 11): bytes.fromhex("000200000000"),
        (3, 1): bytes.fromhex("0003"), (3, 13): bytes.fromhex("0002A00212"),
        (1, 1): bytes.fromhex("0001"), (2, 1): bytes.fromhex("0002"),
        (1, 5): bytes([1]), (2, 5): bytes([1]),
        (1, 7): bytes.fromhex("00004000"), (2, 7): bytes.fromhex("00004100")},
        "memory": {0x4000: bytes.fromhex("FFFF"),
                   0x0111: bytes([0x60]), 0x0116: bytes.fromhex("02" "110F" "0803"),
                   0x0160: bytes.fromhex("01" "0105")}},
    # ABB 0701: Speicher gesperrt (0 Byte), Tabellen nur als Eigenschaft PID_TABLE
    "1.1.19": {"mask": 0x0701, "memory_locked": True, "props": {
        (0, 12): bytes.fromhex("0002"), (3, 1): bytes.fromhex("0003"),
        (3, 13): bytes.fromhex("0002A00110"),
        (1, 1): bytes.fromhex("0001"), (2, 1): bytes.fromhex("0002"),
        (1, 5): bytes([1]), (2, 5): bytes([1]),
        (1, 7): bytes.fromhex("00004000"), (2, 7): bytes.fromhex("00004100")},
        # eigene Adresse 1.1.19, GAs 1/0/1, 1/0/2; Zuordnungen je 1 Byte
        "tables": {1: [bytes.fromhex("1113"), bytes.fromhex("0801"), bytes.fromhex("0802")],
                   2: [bytes.fromhex("0100"), bytes.fromhex("0203")]}},
    # Elsner Salva: Tabellen über 0xFFFF, erweitertes Lesen bleibt ohne
    # Antwort; Tabellen als Eigenschaft mit 4-Byte-Zuordnungen
    "1.1.21": {"mask": 0x07B0, "no_extended": True, "props": {
        (0, 12): bytes.fromhex("00C9"), (3, 1): bytes.fromhex("0003"),
        (3, 13): bytes.fromhex("00C9020110"),
        (1, 1): bytes.fromhex("0001"), (2, 1): bytes.fromhex("0002"),
        (1, 5): bytes([1]), (2, 5): bytes([1]),
        (1, 7): bytes.fromhex("00013000"), (2, 7): bytes.fromhex("00013100")},
        "tables": {1: [bytes.fromhex("0A01")], 2: [bytes.fromhex("00010007")]}},
    # gibt die Kennung beim ersten Mal nicht heraus (Hager 1.1.15)
    "1.1.25": {"mask": 0x0701, "flaky_props": 1, "props": {
        (0, 12): bytes.fromhex("0009"), (3, 1): bytes.fromhex("0003"),
        (3, 13): bytes.fromhex("0009123410")}},
    # Feller: Bestellnummer leer (lauter FF), Seriennummer aus Nullen
    "1.1.27": {"mask": 0x0021, "props": {
        (0, 12): bytes.fromhex("001E"), (0, 11): bytes.fromhex("001E00000000"),
        (0, 15): bytes.fromhex("FFFFFFFFFFFFFFFFFFFF"),
        (3, 1): bytes.fromhex("0003"), (3, 13): bytes.fromhex("001E370810")}},
    # schweigt beim ersten Mal (Buslast), antwortet beim zweiten Versuch
    "1.1.23": {"mask": 0x07B0, "flaky": 1, "props": {(0, 12): bytes.fromhex("0083")}},
    # BCU 2 (ABB, Chalet): Zeiger 0x0112 = 0x0C unbrauchbar, KO-Tabelle direkt
    # hinter der Zuordnungstabelle
    "1.1.29": {"mask": 0x0021, "props": {(0, 12): bytes.fromhex("0002")}, "memory": {
        0x0104: bytes.fromhex("02470111"),
        0x0110: bytes.fromhex("00" "50" "0C" "00" "00" "00"),
        0x0116: bytes.fromhex("02" "111D" "0801"),
        0x0150: bytes.fromhex("01" "0100"),
        0x0153: bytes.fromhex("01" "C0" "201400")}},
    # Adresse vergeben, Applikation entladen
    "1.1.17": {"mask": 0x0701, "props": {
        (0, 12): bytes.fromhex("0000"), (0, 11): bytes.fromhex("FFFBFFFFFFFF"),
        (3, 1): bytes.fromhex("0003"), (3, 13): bytes.fromhex("00B1000101"),
        (3, 5): bytes([0]),
        (1, 1): bytes.fromhex("0001"), (2, 1): bytes.fromhex("0002"),
        (1, 5): bytes([2]), (2, 5): bytes([2])}},
}


def _device_tunnel_server(sock, stop, log):
    """Tunnelserver mit Geräten: L_Data.con negativ für Adressen ohne Gerät
    (niemand quittiert), sonst Transportschicht wie ein Gerät (T_ACK,
    Antwort mit eigener Folgenummer)."""
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.knxip import (
        HPAI, ConnectionStateResponse, ConnectResponse, ConnectResponseData,
        DisconnectResponse, KNXIPFrame, KNXIPServiceType, TunnellingAck, TunnellingRequest,
    )
    from xknx.telegram import Telegram, TelegramDirection
    from xknx.telegram import apci
    from xknx.telegram.address import IndividualAddress
    from xknx.telegram.tpci import TAck, TDataConnected

    client, counter = None, 0
    sequence: dict[str, int] = {}

    def tunnel(raw: bytes) -> None:
        nonlocal counter
        sock.sendto(KNXIPFrame.init_from_body(TunnellingRequest(
            communication_channel_id=7, sequence_counter=counter, raw_cemi=raw)).to_knx(),
            client)
        counter = (counter + 1) % 256

    def send_from(device: str, tpci, payload=None) -> None:
        telegram = Telegram(destination_address=IndividualAddress("1.1.250"),
                            source_address=IndividualAddress(device),
                            direction=TelegramDirection.INCOMING, tpci=tpci, payload=payload)
        tunnel(CEMIFrame(code=CEMIMessageCode.L_DATA_IND,
                         data=CEMILData.init_from_telegram(telegram)).to_knx())

    def answer(device: str, request):
        spec = _DEVICES[device]
        if isinstance(request, apci.DeviceDescriptorRead):
            if spec.get("flaky"):
                spec["flaky"] -= 1
                return None
            return apci.DeviceDescriptorResponse(descriptor=0, value=spec["mask"])
        if isinstance(request, apci.PropertyValueRead) and request.property_id == 23 \
                and request.object_index in spec.get("tables", {}):
            elements = spec["tables"][request.object_index]
            if request.start_index == 0:
                data, count = len(elements).to_bytes(2, "big"), 1
            else:
                part = elements[request.start_index - 1:
                                request.start_index - 1 + request.count]
                data, count = b"".join(part), len(part)
            return apci.PropertyValueResponse(
                object_index=request.object_index, property_id=23, count=count,
                start_index=request.start_index, data=data)
        if isinstance(request, apci.PropertyValueRead) and spec.get("flaky_props") \
                and (request.object_index, request.property_id) == (0, 12):
            spec["flaky_props"] -= 1
            return None
        if isinstance(request, apci.PropertyValueRead):
            data = spec.get("props", {}).get((request.object_index, request.property_id))
            return apci.PropertyValueResponse(
                object_index=request.object_index, property_id=request.property_id,
                count=1 if data else 0, start_index=request.start_index, data=data or b"")
        if isinstance(request, (apci.MemoryRead, apci.MemoryExtendedRead)):
            memory = {}
            for start, block in spec.get("memory", {}).items():
                for offset, value in enumerate(block):
                    memory[start + offset] = value
            data = bytes(memory.get(request.address + i, 0) for i in range(request.count))
            if spec.get("memory_locked"):
                return apci.MemoryResponse(address=request.address, data=b"")
            if isinstance(request, apci.MemoryExtendedRead):
                if spec.get("no_extended"):
                    return None
                return apci.MemoryExtendedReadResponse(return_code=0, address=request.address,
                                                       data=data)
            if request.address + request.count - 1 > 0xFFFF:
                return None
            return apci.MemoryResponse(address=request.address, data=data)
        return None

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
            telegram = CEMIFrame.from_knx(raw).data.telegram()
            target = str(telegram.destination_address)
            log.append((target, type(telegram.tpci).__name__,
                        type(telegram.payload).__name__ if telegram.payload else ""))
            confirm = bytearray(raw)
            confirm[0] = 0x2E
            if target not in _DEVICES:
                confirm[2] |= 0x01                     # L_Data.con negativ
            tunnel(bytes(confirm))
            spec = _DEVICES.get(target)
            if type(telegram.tpci).__name__ == "TConnect":
                sequence[target] = 0               # neue Verbindung: Folgenummer 0
            if spec is None or spec.get("silent") or not isinstance(telegram.tpci,
                                                                     TDataConnected):
                continue
            send_from(target, TAck(sequence_number=telegram.tpci.sequence_number))
            response = answer(target, telegram.payload)
            if response is not None:
                number = sequence.get(target, 0)
                sequence[target] = (number + 1) % 16
                send_from(target, TDataConnected(sequence_number=number), response)
        elif service == KNXIPServiceType.CONNECTIONSTATE_REQUEST:
            sock.sendto(KNXIPFrame.init_from_body(
                ConnectionStateResponse(communication_channel_id=7)).to_knx(), addr)
        elif service == KNXIPServiceType.DISCONNECT_REQUEST:
            sock.sendto(KNXIPFrame.init_from_body(
                DisconnectResponse(communication_channel_id=7)).to_knx(), addr)


def test_scan_over_tunnel():
    from tests.test_bus_send import _wait
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop, log = threading.Event(), []
    server = threading.Thread(target=_device_tunnel_server, args=(sock, stop, log),
                              daemon=True)
    server.start()
    connection = BusConnection(lambda t: None, lambda s, t: None)
    with pytest.raises(BusSendError, match="Nicht verbunden"):
        connection.run_on_bus(lambda x: None)
    progress, found = [], []
    try:
        connection.start(ConnectionSettings(kind=TUNNEL_UDP, host="127.0.0.1",
                                            port=sock.getsockname()[1]), Secrets())
        assert _wait(lambda: connection.connected)
        assert connection.can_access_devices
        future = connection.run_on_bus(lambda x: ds.scan_line(
            x, [(1, 1)], on_progress=progress.append, on_found=found.append,
            addresses=[3, 5, 7, 9, 11, 250], timeout=1.0))
        findings = future.result(timeout=60)
        # GA- und Zuordnungstabellen der lesbaren Geräte (FA-3108b)
        read = []
        tables = connection.run_on_bus(lambda x: ds.read_all_links(
            x, findings, on_read=read.append, timeout=1.0)).result(timeout=60)
    finally:
        connection.stop()
        stop.set()
        server.join(2)
        sock.close()
    by_address = {f.address: f for f in findings}
    assert set(by_address) == {"1.1.5", "1.1.7", "1.1.9", "1.1.250"}
    system_b = by_address["1.1.5"]
    assert (system_b.mask, system_b.manufacturer_id, system_b.serial_number,
            system_b.program, system_b.order_info) == (
        0x07B0, "M-0002", "0002:11223344", "4701-11", "GH Q631")
    assert system_b.hardware_type == "000000000047"
    bcu1 = by_address["1.1.7"]
    assert (bcu1.manufacturer_id, bcu1.program) == ("M-001E", "1022-05")
    assert by_address["1.1.9"].locked and by_address["1.1.9"].errors
    assert by_address["1.1.250"].own
    assert progress[-1].done == 6 and progress[-1].found == 4 and len(found) == 4
    # nur gelesen: an die Geräte ging nichts Schreibendes
    written = {p for _t, _tp, p in log if "Write" in p}
    assert not written
    # Verbindungen sauber abgebaut
    assert ("1.1.5", "TDisconnect", "") in log
    # Tabellen: eigene Adresse wird nicht gelesen, das gesperrte Gerät versucht
    by_table = {t.address: t for t in tables}
    assert set(by_table) == {"1.1.5", "1.1.7", "1.1.9"} and len(read) == 3
    assert not by_table["1.1.9"].ok
    assert by_table["1.1.5"].ok, by_table["1.1.5"].error
    assert by_table["1.1.5"].table_format == "System B"
    assert by_table["1.1.5"].group_addresses == ["1/0/1", "1/0/2", "2/1/5"]
    assert by_table["1.1.5"].links == {0: ["1/0/1", "2/1/5"], 4: ["1/0/2"]}
    assert by_table["1.1.7"].table_format == "BCU"
    assert by_table["1.1.7"].links == {0: ["1/0/1"], 1: ["1/0/3"]}
    # Flags aus der KO-Tabelle (FA-3108d)
    assert by_table["1.1.5"].flags == {0: "K-SÜ--", 4: "K-S---"}
    assert by_table["1.1.7"].flags == {0: "K-SÜ--", 1: "KLS---"}
    # auch beim Tabellenlesen nichts Schreibendes
    assert not {p for _t, _tp, p in log if "Write" in p}


def test_parse_tables_check_themselves():
    # BCU: eigene Adresse an Platz 0, sonst nicht lesbar statt falsch
    good = ds.parse_bcu_tables("1.1.7", bytes.fromhex("03110708010803"),
                               bytes.fromhex("0201000201"))
    assert good.ok and good.links == {0: ["1/0/1"], 1: ["1/0/3"]}
    wrong = ds.parse_bcu_tables("1.1.8", bytes.fromhex("03110708010803"),
                                bytes.fromhex("0201000201"))
    assert not wrong.ok and "eigene Adresse" in wrong.error
    # System B: Verweis ausserhalb der Adresstabelle
    bad = ds.parse_system_b_tables("1.1.5", bytes.fromhex("00010801"),
                                   bytes.fromhex("000100050000"))
    assert not bad.ok and not bad.links
    assert ds.group_address_text(0x1105) == "2/1/5" and ds.individual_raw("1.1.7") == 0x1107
    assert not ds.readable_for_links(ds.ScanFinding("1.1.0", True, 0x091A, "M-0002"))
    assert ds.readable_for_links(ds.ScanFinding("1.1.9", True, 0x07B0))      # gesperrt: versuchen
    assert not ds.readable_for_links(ds.ScanFinding("1.1.250", True, own=True))


def test_adopt_links_creates_gas_and_compares():
    from knix_arranger.models.project import KnxProject
    from knix_arranger.models.topology import Area, CommunicationObject, Device, Line
    project = KnxProject()
    actor = Device(physical_address="1.1.5", device_type="actor", communication_objects=[
        CommunicationObject(object_number=0, name="Ausgang A", object_function="Schalten",
                            data_type="DPST-1-1"),
        CommunicationObject(object_number=0, name="Ausgang A", object_function="Dauer-Ein"),
        CommunicationObject(object_number=1, name="Ausgang A", object_function="Status")])
    sensor = Device(physical_address="1.1.7", device_type="sensor", communication_objects=[
        CommunicationObject(object_number=0, name="Taste 1", object_function="Schalten",
                            data_type="DPST-1-1")])
    known = Device(physical_address="1.1.9", communication_objects=[
        CommunicationObject(object_number=0, name="X", connected_gas=["1/0/1", "1/0/9"])])
    project.topology.areas.append(Area(area_number=1, lines=[
        Line(line_number=1, devices=[actor, sensor, known])]))
    tables = [
        ds.LinkTables("1.1.5", ["1/0/1", "2/1/5"], {0: ["1/0/1"], 1: ["2/1/5"], 7: ["1/0/1"]}),
        ds.LinkTables("1.1.7", ["1/0/1"], {0: ["1/0/1"]}),
        ds.LinkTables("1.1.9", ["1/0/1", "1/0/2"], {0: ["1/0/1", "1/0/2"]}),
        ds.LinkTables("1.1.20", ["3/0/0"], {0: ["3/0/0"]}),
        ds.LinkTables("1.1.21", error="keine Antwort"),
    ]
    result = ds.adopt_links(project, tables)
    assert result.devices_linked == ["1.1.5", "1.1.7"] and result.devices_kept == ["1.1.9"]
    assert result.devices_missing == ["1.1.20"] and result.unreadable == ["1.1.21"]
    assert (result.gas_added, result.links_added, result.unknown_objects) == (2, 4, 1)
    assert sorted(result.differences) == [("1.1.9", 0, "1/0/2", "nur Anlage"),
                                          ("1.1.9", 0, "1/0/9", "nur Projekt")]
    # erstes KO mit der Nummer wird verknüpft, unbekannte Nummer als «KO 7»
    assert actor.communication_objects[0].connected_gas == ["1/0/1"]
    assert not actor.communication_objects[1].connected_gas
    assert [co.name for co in actor.communication_objects if co.object_number == 7] == ["KO 7"]
    assert known.communication_objects[0].connected_gas == ["1/0/1", "1/0/9"]   # unverändert
    gas = {g.address: g for g in project.group_addresses.all_addresses()}
    # Name nach dem empfangenden Aktor-KO, DPT von dort
    assert (gas["1/0/1"].designation, gas["1/0/1"].datapoint_type) == (
        "Ausgang A Schalten (1.1.5)", "DPST-1-1")
    assert gas["2/1/5"].designation == "Ausgang A Status (1.1.5)"
    assert "Abweichungen" in result.text() and "1.1.20" in result.text()
    # Spalte im Vergleich
    findings = [ds.ScanFinding(a, True, 0x07B0) for a in ("1.1.5", "1.1.9")]
    rows = {r.address: r for r in ds.compare(project, findings, [(1, 1)],
                                             {t.address: t for t in tables})}
    assert rows["1.1.5"].links.startswith("stimmt")
    assert rows["1.1.9"].links.startswith("2 Abweichungen")
    assert "KO 0 – 1/0/2: nur Anlage" in rows["1.1.9"].link_details


def test_usb_does_not_scan():
    connection = BusConnection(lambda t: None, lambda s, t: None)
    connection.connected = True
    connection._settings = ConnectionSettings(kind="usb")
    assert not connection.can_access_devices
    with pytest.raises(BusSendError, match="USB"):
        connection.run_on_bus(lambda x: None)


# ── Ansicht ────────────────────────────────────────────────────────────────

def test_view_without_connection_and_with_rows():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.views.device_scan_view import FILTER_PROBLEMS, DeviceScanView

    class Monitor(QObject):
        state_changed = Signal(str)
        can_access_devices = False
        listening = False
        connection_label = ""

    view = DeviceScanView()
    monitor = Monitor()
    view.set_bus_monitor(monitor)
    project = _project([_device("1.1.1"), _device("1.2.4")])
    project.name = "Test"
    view.set_project(project)
    assert view._lines_edit.text() == "1.1, 1.2"
    assert not view._start_btn.isEnabled() and "Nicht verbunden" in view._connection.text()
    monitor.can_access_devices, monitor.connection_label = True, "Tunnel 1.2.3.4"
    monitor.state_changed.emit("connected")
    assert view._start_btn.isEnabled() and "Tunnel" in view._connection.text()
    # Ergebnis wie nach einer Suche
    view._lines = [(1, 1), (1, 2)]
    view._findings = [ds.ScanFinding("1.1.1", True, 0x07B0, "M-0002", program="4701-11")]
    view._compare()
    assert view._table.rowCount() == 2 and "1 stimmt" in view._summary.text()
    view._filter.setCurrentIndex(view._filter.findData(FILTER_PROBLEMS))
    assert view._table.rowCount() == 1 and view._table.item(0, 0).text() == "1.2.4"


# ── Ins Projekt übernehmen (FA-3108a) ──────────────────────────────────────

class _Catalog:
    """Katalog mit drei Produkten: eindeutig, zwei mit derselben Applikation."""

    def __init__(self):
        from knix_arranger.services.product_search_service import ProductSuggestion
        cos = [{"number": 0, "name": "Ausgang A", "function_text": "Schalten",
                "flags": "C-W---", "dpt": "DPST-1-1", "size": "1 Bit"}]
        self.products = [
            ProductSuggestion(manufacturer="ABB", manufacturer_id="M-0002",
                              hw2prog_id="M-0002_H-1_HP-4701-11-952C",
                              order_number="SA/S8.16.5", product_name="Schaltaktor 8-fach",
                              category="actor", com_objects=cos, co_count=1),
            ProductSuggestion(manufacturer="Feller", manufacturer_id="M-001E",
                              application_program_id="M-001E_A-1022-05-AAAA",
                              order_number="3401-4.FMI", product_name="EDIZIOdue 4-fach",
                              category="sensor"),
            ProductSuggestion(manufacturer="Feller", manufacturer_id="M-001E",
                              application_program_id="M-001E_A-1022-05-AAAA",
                              order_number="3401-8.FMI", product_name="EDIZIOdue 8-fach",
                              category="sensor"),
        ]

    def search_all(self, query="", include_hidden=False):
        return list(self.products)


def test_match_product():
    index = ds.catalog_index(_Catalog())
    abb = ds.ScanFinding("1.1.5", True, manufacturer_id="M-0002", program="4701-11")
    prod, unsure = ds.match_product(index, abb)
    assert prod.order_number == "SA/S8.16.5" and not unsure
    # gelesene Bestellnummer passt nicht zum einzigen Produkt: prüfen
    abb.order_info = "GH Q631 0074"
    assert ds.match_product(index, abb)[1]
    # unlesbare Bestellnummer (Hex) zählt nicht
    abb.order_info = "00112233445566778899"
    assert not ds.match_product(index, abb)[1]
    feller = ds.ScanFinding("1.1.7", True, manufacturer_id="M-001E", program="1022-05",
                            order_info="3401-8.FMI")
    prod, unsure = ds.match_product(index, feller)
    assert prod.product_name == "EDIZIOdue 8-fach" and not unsure
    feller.order_info = ""
    assert ds.match_product(index, feller)[1]                      # mehrdeutig
    assert ds.match_product(index, ds.ScanFinding("1.1.9", True, manufacturer_id="M-0002",
                                                  program="9999-01")) == (None, False)


def test_adopt_into_empty_project(tmp_path):
    from knix_arranger.models.project import KnxProject
    project = KnxProject()
    findings = [
        ds.ScanFinding("1.1.0", True, 0x091A, "M-0002", program="", order_info="LK"),
        ds.ScanFinding("1.1.5", True, 0x07B0, "M-0002", "0002:11223344", program="4701-11",
                       program_manufacturer="M-0002"),
        ds.ScanFinding("1.1.7", True, 0x0012, "M-001E", program="1022-05"),
        ds.ScanFinding("1.2.3", True, 0x07B0, "M-00C9", program="0101-10"),
        ds.ScanFinding("1.1.9", True, 0x07B0),                     # gesperrt
        ds.ScanFinding("1.1.250", True, own=True),                 # eigene Adresse
        ds.ScanFinding("1.1.11", False),
    ]
    result = ds.adopt_findings(project, findings, _Catalog())
    assert result.added == ["1.1.0", "1.1.5", "1.1.7", "1.1.9", "1.2.3"]
    assert result.lines_added == ["1.1", "1.2"]
    assert result.with_product == ["1.1.5", "1.1.7"] and result.ambiguous == ["1.1.7"]
    assert result.without_product == ["1.1.0", "1.2.3"] and result.locked == ["1.1.9"]
    assert project.topology.is_imported
    devices = {d.physical_address: d for d in ds.project_devices(project)}
    actor = devices["1.1.5"]
    assert (actor.manufacturer, actor.order_number, actor.product, actor.device_type,
            actor.serial_number, actor.is_programmed) == (
        "ABB", "SA/S8.16.5", "Schaltaktor 8-fach", "actor", "0002:11223344", True)
    assert [co.name for co in actor.communication_objects] == ["Ausgang A"]
    assert devices["1.1.0"].device_type == "coupler"
    assert devices["1.1.9"].product.startswith("Unbekannt")
    assert devices["1.2.3"].manufacturer == "Elsner"
    assert "Herstellerdatei" in result.text() and "1.2.3" in result.text()
    # gespeichert und wieder geladen: der Vergleich stimmt
    path = tmp_path / "rek.knxarr"
    project.save(str(path))
    again = KnxProject.load(str(path))
    rows = {r.address: r.status for r in ds.compare(again, findings, [(1, 1), (1, 2)])}
    assert rows["1.1.5"] == ds.STATUS_OK and rows["1.1.9"] == ds.STATUS_LOCKED


def test_adopt_completes_but_never_overwrites():
    from knix_arranger.models.project import KnxProject
    from knix_arranger.models.topology import Area, Device, Line
    project = KnxProject()
    kept = Device(physical_address="1.1.5", manufacturer="MDT", manufacturer_id="M-0083",
                  order_number="AKS-0816", hw2prog_id="M-0083_H-1_HP-0001-01-AAAA",
                  serial_number="0083:00000001")
    empty = Device(physical_address="1.1.6")
    project.topology.areas.append(Area(area_number=1, lines=[
        Line(line_number=1, devices=[kept, empty])]))
    findings = [
        ds.ScanFinding("1.1.5", True, 0x07B0, "M-0002", "0002:11223344", program="4701-11"),
        ds.ScanFinding("1.1.6", True, 0x07B0, "M-0002", "0002:55667788", program="4701-11"),
    ]
    result = ds.adopt_findings(project, findings, _Catalog())
    assert result.added == [] and result.completed == ["1.1.6"]
    assert (kept.order_number, kept.serial_number) == ("AKS-0816", "0083:00000001")
    assert (empty.order_number, empty.serial_number) == ("SA/S8.16.5", "0002:55667788")
    assert not project.topology.is_imported          # war nicht leer


def test_view_adopts_with_confirmation(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    from knix_arranger.models.project import KnxProject
    from knix_arranger.ui.views.device_scan_view import DeviceScanView
    asked, shown, adopted = [], [], []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    view = DeviceScanView()
    view.catalog = _Catalog()
    view.adopted.connect(lambda: adopted.append(True))
    project = KnxProject()
    view.set_project(project)
    assert not view._adopt_btn.isEnabled()
    view._lines = [(1, 1)]
    view._findings = [ds.ScanFinding("1.1.5", True, 0x07B0, "M-0002", program="4701-11")]
    view._compare()
    view._update_controls()
    assert view._adopt_btn.isEnabled()
    view._adopt_btn.click()
    assert "1 Geräte neu anlegen" in asked[0] and "bestehende Anlage" in asked[0]
    assert adopted and "1 Geräte angelegt" in shown[0]
    assert view._rows[0].status == ds.STATUS_OK


def test_adopt_switches_to_256_participants():
    from knix_arranger.models.project import KnxProject
    project = KnxProject()
    project.topology.topology_mode = "TP-64"
    ds.adopt_findings(project, [ds.ScanFinding("1.1.5", True, 0x07B0)], None)
    assert project.topology.topology_mode == "TP-64"
    ds.adopt_findings(project, [ds.ScanFinding("1.1.200", True, 0x07B0)], None)
    assert project.topology.topology_mode == "TP-256"


def test_adopt_links_chooses_variant_by_partners():
    from knix_arranger.models.project import KnxProject
    from knix_arranger.models.topology import Area, CommunicationObject, Device, Line
    project = KnxProject()
    actor = Device(physical_address="1.1.1", device_type="actor", communication_objects=[
        CommunicationObject(object_number=7, name="Ausgang H", object_function="UND-Verknüpfung"),
        CommunicationObject(object_number=7, name="Ausgang H", object_function="Schalten")])
    button = Device(physical_address="1.1.2", device_type="sensor", communication_objects=[
        CommunicationObject(object_number=0, name="Taste 1", object_function="Schalten")])
    project.topology.areas.append(Area(area_number=1, lines=[
        Line(line_number=1, devices=[actor, button])]))
    result = ds.adopt_links(project, [ds.LinkTables("1.1.1", ["1/0/1"], {7: ["1/0/1"]}),
                                      ds.LinkTables("1.1.2", ["1/0/1"], {0: ["1/0/1"]})])
    assert result.variants_chosen == 1
    assert [co.object_function for co in actor.communication_objects if co.connected_gas] == [
        "Schalten"]


def test_product_later_keeps_links_and_renames():
    """Herstellerdatei nachträglich: erneut übernehmen behält die
    Verknüpfungen und benennt «KO n»-GAs nach dem Produkt."""
    from knix_arranger.models.project import KnxProject
    project = KnxProject()
    finding = ds.ScanFinding("1.1.5", True, 0x07B0, "M-0002", program="4701-11")
    ds.adopt_findings(project, [finding], None)                # ohne Katalog
    ds.adopt_links(project, [ds.LinkTables("1.1.5", ["1/0/1"], {0: ["1/0/1"]})])
    ga = project.group_addresses.all_addresses()[0]
    assert ga.designation == "KO 0 (1.1.5)"
    result = ds.adopt_findings(project, [finding], _Catalog())  # jetzt mit Produkt
    assert result.completed == ["1.1.5"]
    device = ds.project_devices(project)[0]
    linked = [co for co in device.communication_objects if co.connected_gas]
    assert [(co.name, co.connected_gas) for co in linked] == [("Ausgang A", ["1/0/1"])]
    assert ga.designation == "Ausgang A Schalten (1.1.5)"


def test_plant_cases_from_chalet():
    """Befunde aus dem Chalet (2026-11-23): Tabellen über 0xFFFF, ABB 0701
    mit Tabellen an der BCU-2-Lage, Hersteller 0000, Seriennummer aus Nullen,
    entladene Applikation."""
    from tests.test_bus_send import _wait
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop, log = threading.Event(), []
    server = threading.Thread(target=_device_tunnel_server, args=(sock, stop, log),
                              daemon=True)
    server.start()
    connection = BusConnection(lambda t: None, lambda s, t: None)
    try:
        connection.start(ConnectionSettings(kind=TUNNEL_UDP, host="127.0.0.1",
                                            port=sock.getsockname()[1]), Secrets())
        assert _wait(lambda: connection.connected)
        findings = connection.run_on_bus(lambda x: ds.scan_line(
            x, [(1, 1)], addresses=[13, 15, 17], timeout=1.0)).result(timeout=60)
        tables = connection.run_on_bus(lambda x: ds.read_all_links(
            x, findings, timeout=1.0)).result(timeout=60)
    finally:
        connection.stop()
        stop.set()
        server.join(2)
        sock.close()
    found = {f.address: f for f in findings}
    abb = found["1.1.15"]
    # Hersteller 0000 gilt als unbekannt, der der Applikation zählt
    assert (abb.manufacturer_id, abb.program, abb.serial_number) == ("M-0002", "A002-12", "")
    by = {t.address: t for t in tables}
    assert by["1.1.13"].ok and by["1.1.13"].links == {2: ["1/0/1"], 3: ["1/2/5"]}
    assert by["1.1.15"].ok and by["1.1.15"].table_format == "BCU (feste Lage)"
    assert by["1.1.15"].links == {5: ["1/0/3"]}
    assert not by["1.1.17"].ok and "nicht geladen" in by["1.1.17"].error
    assert found["1.1.17"].serial_number == ""
    # entladen: Zufallskennung verworfen, nicht «gesperrt»
    entladen = found["1.1.17"]
    assert (entladen.unloaded, entladen.program, entladen.manufacturer_id,
            entladen.locked) == (True, "", "", False)
    rows = {r.address: r for r in ds.compare(None, findings, [(1, 1)], by)}
    assert rows["1.1.17"].links == "Applikation entladen"
    assert "keine geladene Applikation" in rows["1.1.17"].note


def test_parse_property_tables():
    ok = ds.parse_property_tables("1.1.19", 3, bytes.fromhex("111308010802"),
                                  2, bytes.fromhex("01000203"))
    assert ok.ok and ok.group_addresses == ["1/0/1", "1/0/2"]
    assert ok.links == {0: ["1/0/1"], 3: ["1/0/2"]}
    wide = ds.parse_property_tables("1.1.21", 1, bytes.fromhex("0A01"),
                                    1, bytes.fromhex("00010007"))
    assert wide.ok and wide.links == {7: ["1/2/1"]}
    assert not ds.parse_property_tables("1.1.21", 1, bytes.fromhex("0A01"),
                                        1, bytes.fromhex("00020007")).ok
    assert not ds.parse_property_tables("1.1.21", 1, bytes.fromhex("0A0101"), 0, b"").ok


def test_second_run_cases_from_chalet():
    """Zweiter Lauf im Chalet: ABB 0701 (Speicher gesperrt) und Salva
    (erweitertes Lesen ohne Antwort) über PID_TABLE, schweigendes Gerät
    beim zweiten Versuch gefunden."""
    import copy
    from tests.test_bus_send import _wait
    saved = copy.deepcopy(_DEVICES)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop, log = threading.Event(), []
    server = threading.Thread(target=_device_tunnel_server, args=(sock, stop, log),
                              daemon=True)
    server.start()
    connection = BusConnection(lambda t: None, lambda s, t: None)
    try:
        connection.start(ConnectionSettings(kind=TUNNEL_UDP, host="127.0.0.1",
                                            port=sock.getsockname()[1]), Secrets())
        assert _wait(lambda: connection.connected)
        findings = connection.run_on_bus(lambda x: ds.scan_line(
            x, [(1, 1)], addresses=[19, 21, 23, 25], timeout=1.0,
            retry={"1.1.23", "1.1.25"})).result(timeout=60)
        tables = connection.run_on_bus(lambda x: ds.read_all_links(
            x, [f for f in findings if f.address not in ("1.1.23", "1.1.25")],
            timeout=1.0)).result(timeout=90)
    finally:
        connection.stop()
        stop.set()
        server.join(2)
        sock.close()
        _DEVICES.clear()
        _DEVICES.update(saved)
    assert {f.address for f in findings} == {"1.1.19", "1.1.21", "1.1.23", "1.1.25"}
    hager = next(f for f in findings if f.address == "1.1.25")
    assert not hager.locked and hager.program == "1234-10"
    by = {t.address: t for t in tables}
    assert by["1.1.19"].ok, by["1.1.19"].error
    assert by["1.1.19"].table_format == "Eigenschaft"
    assert by["1.1.19"].links == {0: ["1/0/1"], 3: ["1/0/2"]}
    assert by["1.1.21"].ok, by["1.1.21"].error
    assert by["1.1.21"].links == {7: ["1/2/1"]}


def test_abb_address_table_with_ffff():
    """ABB System 7 (0701) schreibt FFFF statt der eigenen Adresse an Platz 0
    (Chalet 1.1.12, Bytes aus dem Anlagentest)."""
    tables = ds.parse_bcu_tables("1.1.12", bytes.fromhex("02FFFF130F"),
                                 bytes.fromhex("01010B"))
    assert tables.ok and tables.links == {11: ["2/3/15"]}
    first = ds.parse_bcu_tables(
        "1.1.10", bytes.fromhex("03FFFF02320233"), bytes.fromhex("02010A020B"))
    assert first.links == {10: ["0/2/50"], 11: ["0/2/51"]}


def test_view_offers_adoption_after_reading_links(monkeypatch):
    """RekChalet1: Geräte waren übernommen, die gelesenen GAs nicht. Nach dem
    Lesen fragt die Ansicht gleich, ob sie übernommen werden sollen."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    from knix_arranger.models.project import KnxProject
    from knix_arranger.ui.views.device_scan_view import DeviceScanView
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    view = DeviceScanView()
    view.catalog = _Catalog()
    project = KnxProject()
    view.set_project(project)
    view._lines = [(1, 1)]
    view._findings = [ds.ScanFinding("1.1.5", True, 0x07B0, "M-0002", program="4701-11")]
    ds.adopt_findings(project, view._findings, _Catalog())      # Geräte schon da
    view._compare()
    view._on_links_finished([ds.LinkTables("1.1.5", ["1/0/1"], {0: ["1/0/1"]})], "")
    assert len(asked) == 1 and "Gelesen: 1 GAs von 1 Geräten" in asked[0]
    assert [g.address for g in project.group_addresses.all_addresses()] == ["1/0/1"]
    assert view._rows[0].links.startswith("stimmt")
    # nochmals gelesen: nichts mehr anzubieten
    view._on_links_finished([ds.LinkTables("1.1.5", ["1/0/1"], {0: ["1/0/1"]})], "")
    assert len(asked) == 1


def test_empty_project_retry_and_feller_order():
    """RekChalet2 (leeres Projekt): ein Gerät, das beim ersten Mal schweigt,
    kommt über den zweiten Durchgang (quittiert, keine Antwort); Feller mit
    leerer Bestellnummer (FF) gilt nicht als entladen."""
    import copy
    from tests.test_bus_send import _wait
    saved = copy.deepcopy(_DEVICES)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop, log = threading.Event(), []
    server = threading.Thread(target=_device_tunnel_server, args=(sock, stop, log),
                              daemon=True)
    server.start()
    connection = BusConnection(lambda t: None, lambda s, t: None)
    try:
        connection.start(ConnectionSettings(kind=TUNNEL_UDP, host="127.0.0.1",
                                            port=sock.getsockname()[1]), Secrets())
        assert _wait(lambda: connection.connected)
        findings = connection.run_on_bus(lambda x: ds.scan_line(
            x, [(1, 1)], addresses=[23, 27, 28], timeout=1.0)).result(timeout=60)
    finally:
        connection.stop()
        stop.set()
        server.join(2)
        sock.close()
        _DEVICES.clear()
        _DEVICES.update(saved)
    found = {f.address: f for f in findings}
    assert set(found) == {"1.1.23", "1.1.27"}          # 1.1.28: niemand quittiert
    feller = found["1.1.27"]
    assert (feller.unloaded, feller.program, feller.order_info, feller.serial_number) == (
        False, "3708-10", "", "")


def test_flags_from_config_and_choice():
    assert ds.flags_from_config(0x54) == "K-SÜ--"
    assert ds.flags_from_config(0xDC) == "KLSÜA-"
    assert ds.flags_from_config(0x2C, read_on_init=True) == "KL---I"
    assert ds.flags_from_config(0x2C) == "KL----"
    # Konfiguration an zweiter Stelle, KO 1 zuerst (Eintrag 0 = KO 1)
    entries = [bytes([0x07, 0x54]), bytes([0x00, 0x14]), bytes([0x07, 0x00])]
    assert ds.choose_flags(entries, [1, 2]) == {1: "K-SÜ--", 2: "K-S---"}
    # nichts plausibel: verknüpfte KOs ohne Kommunikation
    assert ds.choose_flags([bytes([0x00, 0x00])] * 4, [0, 1, 2]) is None


def test_adopt_links_takes_device_flags():
    from knix_arranger.models.project import KnxProject
    from knix_arranger.models.topology import Area, CommunicationObject, Device, Line
    project = KnxProject()
    actor = Device(physical_address="1.1.6", device_type="actor", communication_objects=[
        CommunicationObject(object_number=0, name="Ausgang 1", object_function="Schalten",
                            flags="KLS---")])
    project.topology.areas.append(Area(area_number=1, lines=[Line(line_number=1,
                                                                  devices=[actor])]))
    table = ds.LinkTables("1.1.6", ["3/0/70"], {0: ["3/0/70"]}, flags={0: "K-S---"})
    result = ds.adopt_links(project, [table])
    assert actor.communication_objects[0].flags == "K-S---"
    assert result.flags_from_device == 1 and "Flags von 1 KOs" in result.text()
    # schon übernommen, Flags danach geändert: erneut übernehmen holt die
    # Geräte-Flags (Rekonstruktion ohne ETS-Projekt)
    actor.communication_objects[0].flags = "KLS---"
    rows = {r.address: r for r in ds.compare(project, [ds.ScanFinding("1.1.6", True)],
                                             [(1, 1)], {"1.1.6": table})}
    assert "Flags 1× anders" in rows["1.1.6"].links
    assert "KO 0 Flags: Anlage K-S---, Projekt KLS---" in rows["1.1.6"].link_details
    again = ds.adopt_links(project, [table])
    assert again.flags_from_device == 1 and actor.communication_objects[0].flags == "K-S---"
    # ETS-Projekt: Flags der ETS bleiben
    project.ets_project_id = "P-0001"
    actor.communication_objects[0].flags = "KLS---"
    ds.adopt_links(project, [table])
    assert actor.communication_objects[0].flags == "KLS---"
    # ohne lesbare Flags: Herstellerdaten, gekennzeichnet
    other = Device(physical_address="1.1.8", communication_objects=[
        CommunicationObject(object_number=0, name="X")])
    project.topology.areas[0].lines[0].devices.append(other)
    plain = ds.adopt_links(project, [ds.LinkTables("1.1.8", ["3/0/1"], {0: ["3/0/1"]})])
    assert plain.flags_catalog == ["1.1.8"] and "Herstellerdaten" in plain.text()


def test_flags_behind_association_table():
    """BCU 2 mit unbrauchbarem Zeiger 0x0112: KO-Tabelle hinter der
    Zuordnungstabelle; die Diagnose nennt den Zeiger."""
    import copy
    from tests.test_bus_send import _wait
    saved = copy.deepcopy(_DEVICES)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop, log = threading.Event(), []
    server = threading.Thread(target=_device_tunnel_server, args=(sock, stop, log),
                              daemon=True)
    server.start()
    connection = BusConnection(lambda t: None, lambda s, t: None)
    try:
        connection.start(ConnectionSettings(kind=TUNNEL_UDP, host="127.0.0.1",
                                            port=sock.getsockname()[1]), Secrets())
        assert _wait(lambda: connection.connected)
        tables = connection.run_on_bus(lambda x: ds.read_all_links(
            x, [ds.ScanFinding("1.1.29", True, 0x0021, "M-0002", program="4701-11")],
            timeout=1.0)).result(timeout=60)
    finally:
        connection.stop()
        stop.set()
        server.join(2)
        sock.close()
        _DEVICES.clear()
        _DEVICES.update(saved)
    table = tables[0]
    assert table.ok and table.links == {0: ["1/0/1"]}
    assert table.flags == {0: "K-S---"}, table.flags_error


def test_find_object_table_behind_reserved_associations():
    """Chalet Theben HTS/Siemens: hinter den belegten Zuordnungen weitere
    Paare («05 04 06 05 …»), die KO-Tabelle beginnt weiter hinten."""
    junk = bytes.fromhex("0504060507060807090A0B0C")
    table = bytes([3, 0xC0]) + bytes.fromhex("205400" "211400" "224C01")
    found = ds.find_object_table(junk + table + bytes(20), [0, 1, 2])
    assert found == ({0: "K-SÜ--", 1: "K-S---", 2: "KL-Ü--"}, len(junk))
    # Typbyte ungültig: keine Tabelle (kein Zufallstreffer)
    assert ds.find_object_table(bytes([3, 0]) + bytes.fromhex("205440" "211440" "224C40"),
                                [0, 1]) is None


def test_object_table_address_from_knxprod(tmp_path):
    """Lage der KO-Tabelle aus der Herstellerdatei (Static/ComObjectTable)."""
    import zipfile
    from knix_arranger.services import knxprod_tables as kt
    app = ('<ApplicationProgram Id="M-0002_A-4701-11-952C"><Static><Code>'
           '<AbsoluteSegment Id="M-0002_A-4701-11-952C_AS-01AE" Address="430" Size="60"/>'
           '</Code><ComObjectTable CodeSegment="M-0002_A-4701-11-952C_AS-01AE" Offset="2">'
           '</ComObjectTable></Static></ApplicationProgram>')
    path = tmp_path / "ABB (M-0002).knxprod"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("M-0002/M-0002_A-4701-11-952C.xml", app)
    kt._CACHE.clear()
    assert kt.object_table_address("M-0002", "4701-11", [str(path)]) == 432
    assert kt.object_table_address("M-0002", "9999-01", [str(path)]) is None
    # ohne Segment-Element: Adresse aus der Kennung
    assert kt.table_address('<ComObjectTable CodeSegment="X_AS-4400" Offset="0">') == 0x4400
    kt._CACHE.clear()


def test_flags_at_knxprod_location_system7():
    """System 7 mit 4-Byte-Einträgen (Wert-Zeiger 2 Byte) an der Lage aus der
    Herstellerdatei."""
    import asyncio

    memory = bytes([2, 0x40, 0x00]) + bytes.fromhex("4500" "54" "00" "4501" "1C" "00")

    class Conn:
        pass

    async def fake_tolerant(conn, start, size, timeout):
        return memory[:size]

    result = ds.LinkTables("1.1.10", ["1/0/1", "1/0/2"], {0: ["1/0/1"], 1: ["1/0/2"]})
    original = ds._memory_tolerant
    ds._memory_tolerant = fake_tolerant
    try:
        asyncio.run(ds._read_flags(Conn(), "1.1.10", 0x0701, result, 1.0, table_hint=0x4400))
    finally:
        ds._memory_tolerant = original
    assert result.flags == {0: "K-SÜ--", 1: "KLS---"}, result.flags_error


# ── Linien finden (FA-3108e) ─────────────────────────────────────────────

def test_find_couplers_over_tunnel():
    """Nur antwortende Kopplerplätze zählen; leere Plätze quittiert niemand."""
    import copy
    from tests.test_bus_send import _wait
    saved = copy.deepcopy(_DEVICES)
    _DEVICES["1.0.0"] = {"mask": 0x0910, "props": {}}       # Bereichskoppler
    _DEVICES["1.2.0"] = {"mask": 0x0910, "props": {}}       # Linienkoppler
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.1)
    stop, log = threading.Event(), []
    server = threading.Thread(target=_device_tunnel_server, args=(sock, stop, log),
                              daemon=True)
    server.start()
    connection = BusConnection(lambda t: None, lambda s, t: None)
    progress = []
    try:
        connection.start(ConnectionSettings(kind=TUNNEL_UDP, host="127.0.0.1",
                                            port=sock.getsockname()[1]), Secrets())
        assert _wait(lambda: connection.connected)
        couplers = connection.run_on_bus(lambda x: ds.find_couplers(
            x, on_progress=progress.append, areas=[1], timeout=1.0)).result(timeout=60)
    finally:
        connection.stop()
        stop.set()
        server.join(2)
        sock.close()
        _DEVICES.clear()
        _DEVICES.update(saved)
    assert [f.address for f in couplers] == ["1.0.0", "1.2.0"]
    assert couplers[1].mask == 0x0910
    assert progress[-1].done == 16 and progress[-1].total == 16


def test_line_candidates_from_three_sources():
    from types import SimpleNamespace
    telegrams = [SimpleNamespace(source=s) for s in
                 ("1.1.12", "1.1.12", "1.1.30", "1.2.15", "1.1.70", "kaputt")]
    senders = ds.senders_per_line(telegrams, own="1.1.70")
    assert senders == {(1, 1): 2, (1, 2): 1}
    couplers = [ds.ScanFinding(address="1.0.0", answered=True, mask=0x0910),
                ds.ScanFinding(address="1.2.0", answered=True, mask=0x0910),
                ds.ScanFinding(address="1.3.0", answered=True, mask=0x0910)]
    found = {c.line: c for c in ds.line_candidates("1.1.70", senders, couplers)}
    assert list(found) == [(1, 0), (1, 1), (1, 2), (1, 3)]
    assert found[(1, 1)].interface and found[(1, 1)].preselected
    assert found[(1, 2)].coupler == "1.2.0 Linienkoppler" and found[(1, 2)].senders == 1
    assert found[(1, 0)].coupler == "1.0.0 Bereichskoppler"
    assert found[(1, 3)].preselected                        # stille Linie mit Koppler
    assert not found[(1, 0)].preselected                    # Bereichslinie
    assert "Bereichslinie" in found[(1, 0)].origin()
    assert "Linie der Schnittstelle" in found[(1, 1)].origin()
    assert ds.line_of("15.15.255") == (15, 15) and ds.line_of("16.1.1") is None
    assert ds.duration_text(3) == "ca. 9 Minuten"
    assert ds.duration_text(40) == "ca. 2,0 Stunden"


def test_line_choice_dialog():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.line_choice_dialog import LineChoiceDialog
    candidates = [ds.LineCandidate((1, 0), coupler="1.0.0 Koppler"),
                  ds.LineCandidate((1, 1), interface=True, senders=3)]
    dialog = LineChoiceDialog(candidates)
    assert dialog.selected_lines() == [(1, 1)]
    assert "ca. 3 Minuten" in dialog._summary.text()
    dialog._extra.setText("2.1, 1.0")
    dialog._add_extra()
    assert dialog.selected_lines() == [(1, 0), (1, 1), (2, 1)]
    for i in range(dialog._list.count()):
        dialog._list.item(i).setCheckState(Qt.Unchecked)
    assert not dialog._ok.isEnabled()
    # ohne antwortenden Koppler: Hinweis auf Fernzugang
    quiet = LineChoiceDialog([ds.LineCandidate((1, 1), interface=True)])
    from PySide6.QtWidgets import QLabel
    assert any("Kein Koppler" in label.text() for label in quiet.findChildren(QLabel))


def test_view_search_without_lines_finds_lines_first():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.models.project import KnxProject
    from knix_arranger.ui.views.device_scan_view import DeviceScanView
    view = DeviceScanView()
    view.set_project(KnxProject())
    calls = []
    view._find_lines = lambda: calls.append("find")
    view.bus_monitor = SimpleNamespace(
        local_address="1.1.70", run_on_bus=lambda f: None,
        history=lambda: [SimpleNamespace(source="1.2.4")])
    view._lines_edit.setText("")
    view._start()
    assert calls == ["find"]
    lines = [c.line for c in view.line_candidates(
        [ds.ScanFinding(address="1.3.0", answered=True, mask=0x0910)])]
    assert lines == [(1, 1), (1, 2), (1, 3)]
