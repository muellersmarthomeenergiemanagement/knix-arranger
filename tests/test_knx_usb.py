"""
USB-Schnittstellen (FA-3101, Etappe 1b): HID-Berichte, Einrichten, Busmonitor.
Testdaten: echte Antworten und Busmonitor-Rahmen einer Siemens OCI702
(0908:02DC) an der Anlage, 11.11.2026.
"""
from __future__ import annotations

import threading
from datetime import datetime

import pytest

from knix_arranger.services.knx_usb import (
    CEMI, FEATURE_GET, PROTOCOL_FEATURE, PROTOCOL_TUNNEL, Reassembler, UsbDevice, UsbError,
    UsbSession, build_reports, comm_mode_request, find_devices,
)

# Antworten der OCI702 (HID-Bericht bis zum Ende der Daten)
OCI_SUPPORTED_EMI = "01130b000800030f020000010000"        # «keine» EMI-Typen gemeldet
OCI_COMM_MODE_READ = "0113100008000801030000fb000801341001ff"   # Modus 0xFF
OCI_COMM_MODE_WRITE_CON = "01130f0008000701030000f5000801341001"   # Modus geschrieben
# Busmonitor: Rahmen mit Quittung danach
OCI_BUSMON = [
    "01131c00080014010300002b09030100060400900490bc113d100fe1008110",   # 1.1.61 -> 2/0/15 = 1
    "0113140008000c010300002b090301010604009005e2cc",                   # ACK
    "01131e00080016010300002b0903010406040091ee14bc1120027ae30080141c61",  # 1.1.32 -> 0/2/122
    "0113140008000c010300002b0903010506040091efaacc",                   # ACK
    "01131d00080015010300002b0903010006040092797abc11c8101be20080ff0c",  # 1.1.200 -> 2/0/27
]


def _report(hex_text: str) -> bytes:
    return bytes.fromhex(hex_text).ljust(64, b"\x00")


def test_reports_round_trip_single_and_multi():
    (single,) = build_reports(PROTOCOL_FEATURE, FEATURE_GET, b"\x01")
    assert single[:3] == bytes([0x01, 0x13, 9]) and len(single) == 64
    assert single[3:12] == bytes([0, 8, 0, 1, 0x0F, 0x01, 0, 0, 0x01])
    body = bytes(range(120))
    reports = build_reports(PROTOCOL_TUNNEL, CEMI, body)
    assert [r[1] for r in reports] == [0x15, 0x24, 0x36]        # Start, Teil, Ende
    reassembler = Reassembler()
    results = [reassembler.feed(r) for r in reports]
    assert results[:2] == [None, None]
    assert (results[2].protocol, results[2].emi_or_service, results[2].body) == (
        PROTOCOL_TUNNEL, CEMI, body)


def test_real_oci702_frames_decode_with_ack():
    from knix_arranger.services.bus_monitor import decode
    reassembler = Reassembler()
    decoded = [decode(reassembler.feed(_report(h)).body.hex().upper(), datetime.now())
               for h in OCI_BUSMON[:4]]
    assert (decoded[0].src, decoded[0].dst, decoded[0].service, decoded[0].payload) == (
        "1.1.61", "2/0/15", "Write", "1")
    assert decoded[1] == "ack" and decoded[3] == "ack"
    assert decoded[2].dst == "0/2/122" and decoded[2].payload == "141C"


class _FakeLink:
    """Ersatz für UsbLink: Antworten wie die OCI702, danach Busmonitor-Rahmen."""

    def __init__(self, frames=()):
        self.sent: list[tuple[int, int, bytes]] = []
        self.queue: list[bytes] = []
        self.frames = [_report(h) for h in frames]
        self.reassembler = Reassembler()
        self.closed = False

    def send(self, protocol, emi_or_service, body):
        self.sent.append((protocol, emi_or_service, body))
        if protocol == PROTOCOL_FEATURE and body[:1] == b"\x01":
            self.queue.append(_report(OCI_SUPPORTED_EMI))
        elif protocol == PROTOCOL_TUNNEL and body[:1] == b"\xfc":
            self.queue.append(_report(OCI_COMM_MODE_READ))
        elif protocol == PROTOCOL_TUNNEL and body[:1] == b"\xf6":
            self.queue.append(_report(OCI_COMM_MODE_WRITE_CON))
            if body[-1] == 1:
                self.queue.extend(self.frames)

    def receive(self, timeout_ms=200):
        if not self.queue:
            return None
        return self.reassembler.feed(self.queue.pop(0))

    def close(self):
        self.closed = True


def test_setup_like_oci702_probes_cemi_and_sets_busmonitor():
    link = _FakeLink()
    session = UsbSession(link)
    session.setup(busmonitor=True)
    assert session.supported == 0                   # OCI702 meldet keine EMI-Typen
    assert link.sent[1][2][:1] == b"\xfc"           # stattdessen cEMI-Probe
    assert link.sent[-1] == (PROTOCOL_TUNNEL, CEMI, comm_mode_request(1))
    session.close()
    assert link.sent[-1][2] == comm_mode_request(0) and link.closed   # zurück


def test_setup_without_cemi_is_reported():
    class OnlyEmi1(_FakeLink):
        def send(self, protocol, emi_or_service, body):
            self.sent.append((protocol, emi_or_service, body))
            if protocol == PROTOCOL_FEATURE:
                self.queue.append(_report("01130b000800030f020000010001"))   # nur EMI1
    with pytest.raises(UsbError, match="kein cEMI"):
        UsbSession(OnlyEmi1()).setup(busmonitor=True)


def test_usb_loop_assigns_acks_and_counts():
    from knix_arranger.services.bus_access import (
        USB_BUSMONITOR, BusConnection, ConnectionSettings, _usb_loop,
    )
    link = _FakeLink(OCI_BUSMON)
    session = UsbSession(link)
    session.setup(busmonitor=True)
    received, raw = [], []
    connection = BusConnection(received.append, lambda s, t: None,
                               lambda r, w: raw.append((r, w)))
    stop = threading.Event()
    original = session.frames

    def frames(timeout_ms=200):
        frame = original(timeout_ms)
        if frame is None:
            stop.set()
        return frame
    session.frames = frames
    _usb_loop(connection, ConnectionSettings(kind=USB_BUSMONITOR), session, stop)
    assert [(t.source, t.destination, t.ack) for t in received] == [
        ("1.1.61", "2/0/15", "ack"), ("1.1.32", "0/2/122", "ack"), ("1.1.200", "2/0/27", "")]
    stats = connection.stats
    assert (stats.frames, stats.group, stats.acks, stats.unacked) == (3, 3, 2, 1)
    assert "Quittungen: 2 ACK, 0 NAK, 0 BUSY, 1 ohne" in stats.text()
    # Übernahme in die Busanalyse: Busmonitor mit Quittungen
    from knix_arranger.services.bus_access import live_recording
    summary = live_recording(raw)
    assert summary["ack_known"] and summary["acks"] == 2
    assert summary["mode"].startswith("Busmonitor")


def test_find_devices_recognises_oci702():
    class FakeHid:
        @staticmethod
        def enumerate():
            return [
                {"vendor_id": 0x203A, "product_id": 0xFFFB, "path": b"kbd",
                 "product_string": "Virtual Keyboard", "usage_page": 1},
                {"vendor_id": 0x0908, "product_id": 0x02DC, "path": b"oci",
                 "manufacturer_string": "Siemens", "product_string": "OCI702 KNX Interface",
                 "serial_number": "00FD10D02779", "usage_page": 0xFF00},
            ]
    (device,) = find_devices(FakeHid)
    assert device.key == "0908:02DC:00FD10D02779"
    assert device.label() == "Siemens OCI702 KNX Interface (0908:02DC)"


def test_connection_dialog_usb(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.services import knx_usb
    from knix_arranger.services.bus_access import USB_BUSMONITOR, ConnectionSettings
    monkeypatch.setattr(knx_usb, "find_devices", lambda hid_module=None: [
        UsbDevice(b"oci", 0x0908, 0x02DC, "OCI702 KNX Interface", "Siemens", "00FD10D02779")])
    from knix_arranger.ui.dialogs.bus_connection_dialog import BusConnectionDialog
    dialog = BusConnectionDialog(ConnectionSettings(kind=USB_BUSMONITOR,
                                                    usb_device="0908:02DC:ANDERE"))
    assert dialog._usb.isVisibleTo(dialog) and not dialog._host.isVisibleTo(dialog)
    assert dialog.settings().usb_device == "0908:02DC:00FD10D02779"   # gleiches Modell
    assert dialog.settings().problems() == []
    assert not dialog._form.isRowVisible(dialog._keyring_widget)
