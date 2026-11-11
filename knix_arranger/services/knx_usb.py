"""
KNX-USB-Schnittstellen (FA-3101, Etappe 1b), z.B. Siemens OCI702.

KNX-USB-Schnittstellen sind HID-Geräte (KNX-Spezifikation 9/3, «KNX USB
Interface»). Je HID-Bericht 64 Byte:

    [0] Report-ID 0x01
    [1] Folgenummer (oberes Halbbyte, 1..5) | Pakettyp (unteres: 1 Start,
        2 Ende, 4 Teil; ein Bericht allein = 3)
    [2] Anzahl Datenbytes in diesem Bericht (höchstens 61)
    [3..] im ersten Bericht der Transfer-Kopf (8 Byte): Version 0, Kopflänge 8,
          Länge des Inhalts (2 Byte), Protokoll (1 KNX-Tunnel, 0x0F
          Geräteeigenschaften), EMI-Typ bzw. Dienst, Herstellercode (2 Byte, 0)
          danach der Inhalt (cEMI-Rahmen bzw. Eigenschaft)

Ablauf: unterstützte EMI-Typen abfragen, cEMI einschalten, für den
Busmonitor den Kommunikationsmodus (cEMI-Server, Eigenschaft 52) auf 1 setzen
-- dann liefert die Schnittstelle jeden Rahmen auf der Leitung als
L_Busmon.ind (0x2B), mit Wiederholungen und Quittungen (ACK, NAK, BUSY),
ausgewertet wie ein ETS-Busmonitor-Mitschnitt (bus_monitor.decode). Im
Gruppenmonitor-Modus (Sicherungsschicht) kommen L_Data.ind (0x29).

Die Schnittstelle liest nur; KNiX sendet keine Telegramme auf den Bus.
Schnittstellen nur mit EMI1/EMI2 (ohne cEMI) werden noch nicht unterstützt.

Ohne Qt. Der Zugriff auf das Gerät läuft über die Bibliothek hidapi
(Modul `hid`) und lässt sich für Tests durch ein Ersatzgerät ersetzen.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

logger = logging.getLogger("knix_arranger.knx_usb")

REPORT_ID = 0x01
REPORT_SIZE = 64
_MAX_DATA = REPORT_SIZE - 3            # Datenbytes je Bericht
_HEADER = 8                            # Transfer-Kopf im ersten Bericht

PROTOCOL_TUNNEL = 0x01
PROTOCOL_FEATURE = 0x0F
EMI1, EMI2, CEMI = 0x01, 0x02, 0x03

FEATURE_GET, FEATURE_RESPONSE, FEATURE_SET, FEATURE_INFO = 0x01, 0x02, 0x03, 0x04
FEATURE_SUPPORTED_EMI = 0x01
FEATURE_BUS_STATUS = 0x03
FEATURE_ACTIVE_EMI = 0x05

# cEMI: Eigenschaft schreiben/bestätigen, Kommunikationsmodus des cEMI-Servers
M_PROP_WRITE_REQ, M_PROP_WRITE_CON = 0xF6, 0xF5
M_PROP_READ_REQ, M_PROP_READ_CON = 0xFC, 0xFB
CEMI_SERVER_OBJECT = 0x0008
PID_COMM_MODE = 52
COMM_MODE_DATA_LINK, COMM_MODE_BUSMONITOR = 0x00, 0x01

# Hersteller-IDs (USB) bekannter KNX-Schnittstellen; daneben zählen der
# Produktname («KNX») und die KNX-Verwendungsseite 0xFFA0
KNX_USB_VENDORS = {
    0x0E77: "Weinzierl", 0x0681: "Siemens", 0x0908: "Siemens", 0x147B: "ABB",
    0x135E: "Hager", 0x145C: "Busch-Jaeger", 0x16D0: "MDT", 0x28C2: "Zennio",
}
KNX_USAGE_PAGE = 0xFFA0


class UsbError(RuntimeError):
    pass


# ── Berichte bauen und zusammensetzen ─────────────────────────────────────

def build_reports(protocol: int, emi_or_service: int, body: bytes) -> list[bytes]:
    """Inhalt in 64-Byte-Berichte mit Transfer-Kopf aufteilen."""
    payload = bytes([0x00, _HEADER]) + len(body).to_bytes(2, "big") \
        + bytes([protocol, emi_or_service, 0x00, 0x00]) + body
    chunks = [payload[i:i + _MAX_DATA] for i in range(0, len(payload), _MAX_DATA)] or [b""]
    reports = []
    for number, chunk in enumerate(chunks, start=1):
        # allein 0x03; mehrteilig: Start 0x05, Mitte 0x04, Ende 0x06
        kind = (1 if number == 1 else 0) | (2 if number == len(chunks) else 0) \
            | (4 if len(chunks) > 1 else 0)
        report = bytes([REPORT_ID, (number << 4) | kind, len(chunk)]) + chunk
        reports.append(report.ljust(REPORT_SIZE, b"\x00"))
    return reports


@dataclass
class Transfer:
    """Ein vollständig empfangener Inhalt."""
    protocol: int
    emi_or_service: int
    body: bytes


class Reassembler:
    """Setzt HID-Berichte zu Inhalten zusammen (Start bis Ende)."""

    def __init__(self):
        self._buffer = bytearray()
        self._active = False

    def feed(self, report: bytes) -> Transfer | None:
        if len(report) < 3:
            return None
        if report[0] != REPORT_ID:
            raise UsbError(f"Unerwartete Report-ID {report[0]:#04x}")
        kind, length = report[1] & 0x0F, report[2]
        data = bytes(report[3:3 + length])
        if kind & 1:                       # Start
            self._buffer = bytearray(data)
            self._active = True
        elif self._active:
            self._buffer.extend(data)
        else:
            return None                    # Teil ohne Anfang verworfen
        if not kind & 2:
            return None
        self._active = False
        payload = bytes(self._buffer)
        if len(payload) < _HEADER or payload[1] != _HEADER:
            raise UsbError(f"Ungültiger Transfer-Kopf: {payload[:8].hex()}")
        size = int.from_bytes(payload[2:4], "big")
        return Transfer(payload[4], payload[5], payload[_HEADER:_HEADER + size])


def comm_mode_request(mode: int) -> bytes:
    """cEMI M_PropWrite.req: Kommunikationsmodus des cEMI-Servers."""
    return bytes([M_PROP_WRITE_REQ, CEMI_SERVER_OBJECT >> 8, CEMI_SERVER_OBJECT & 0xFF,
                  0x01, PID_COMM_MODE, 0x10, 0x01, mode])


def comm_mode_read_request() -> bytes:
    """cEMI M_PropRead.req: Kommunikationsmodus lesen (Probe auf cEMI)."""
    return bytes([M_PROP_READ_REQ, CEMI_SERVER_OBJECT >> 8, CEMI_SERVER_OBJECT & 0xFF,
                  0x01, PID_COMM_MODE, 0x10, 0x01])


def supported_emi_text(value: int) -> str:
    names = [name for bit, name in ((1, "EMI1"), (2, "EMI2"), (4, "cEMI")) if value & bit]
    return ", ".join(names) or "keine"


# ── Geräte finden ─────────────────────────────────────────────────────────

@dataclass
class UsbDevice:
    path: bytes
    vendor_id: int
    product_id: int
    product: str = ""
    manufacturer: str = ""
    serial: str = ""

    @property
    def key(self) -> str:
        """Zum Wiederfinden im Projekt: «VID:PID:Seriennummer»."""
        return f"{self.vendor_id:04X}:{self.product_id:04X}:{self.serial}"

    def label(self) -> str:
        maker = self.manufacturer or KNX_USB_VENDORS.get(self.vendor_id, "")
        name = " ".join(p for p in (maker, self.product) if p) or "USB-Gerät"
        return f"{name} ({self.vendor_id:04X}:{self.product_id:04X})"


def find_devices(hid_module=None) -> list[UsbDevice]:
    """Angeschlossene KNX-USB-Schnittstellen: Hersteller-ID, KNX-Verwendungs-
    seite oder «KNX» im Namen."""
    if hid_module is None:
        import hid as hid_module
    found, seen = [], set()
    for info in hid_module.enumerate():
        product = info.get("product_string") or ""
        maker = info.get("manufacturer_string") or ""
        knx = (info.get("vendor_id") in KNX_USB_VENDORS
               or info.get("usage_page") == KNX_USAGE_PAGE
               or "knx" in f"{product} {maker}".lower())
        path = info.get("path")
        if not knx or path in seen:
            continue
        seen.add(path)
        found.append(UsbDevice(path, info.get("vendor_id", 0), info.get("product_id", 0),
                               product, maker, info.get("serial_number") or ""))
    return found


# ── Verbindung ────────────────────────────────────────────────────────────

class UsbLink:
    """Gerät öffnen, Berichte schreiben und lesen (über hidapi)."""

    def __init__(self, device: UsbDevice, hid_module=None):
        if hid_module is None:
            import hid as hid_module
        self._device = hid_module.device()
        try:
            self._device.open_path(device.path)
        except (OSError, IOError) as exc:
            raise UsbError(f"Schnittstelle nicht zu öffnen ({exc}) – von der ETS "
                           "oder einem anderen Programm belegt?") from exc
        self._reassembler = Reassembler()

    def send(self, protocol: int, emi_or_service: int, body: bytes) -> None:
        for report in build_reports(protocol, emi_or_service, body):
            if self._device.write(list(report)) < 0:
                raise UsbError("Schreiben auf die Schnittstelle fehlgeschlagen")

    def receive(self, timeout_ms: int = 200) -> Transfer | None:
        data = self._device.read(REPORT_SIZE, timeout_ms)
        if not data:
            return None
        return self._reassembler.feed(bytes(data))

    def close(self) -> None:
        try:
            self._device.close()
        except Exception:
            pass


class UsbSession:
    """Schnittstelle einrichten (cEMI, Kommunikationsmodus) und Rahmen lesen."""

    def __init__(self, link: UsbLink):
        self.link = link
        self.supported = 0
        self.mode = COMM_MODE_DATA_LINK

    def _await(self, match: Callable[[Transfer], bool], what: str,
               timeout: float = 2.0, keep: list | None = None) -> Transfer:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            transfer = self.link.receive(100)
            if transfer is None:
                continue
            if match(transfer):
                return transfer
            if keep is not None and transfer.protocol == PROTOCOL_TUNNEL:
                keep.append(transfer.body)
        raise UsbError(f"Schnittstelle antwortet nicht auf «{what}»")

    def setup(self, busmonitor: bool) -> None:
        self.link.send(PROTOCOL_FEATURE, FEATURE_GET, bytes([FEATURE_SUPPORTED_EMI]))
        answer = self._await(lambda t: t.protocol == PROTOCOL_FEATURE
                             and t.emi_or_service == FEATURE_RESPONSE
                             and t.body[:1] == bytes([FEATURE_SUPPORTED_EMI]),
                             "unterstützte EMI-Typen")
        self.supported = int.from_bytes(answer.body[1:3] or b"\x00", "big")
        if self.supported and not self.supported & 4:
            raise UsbError("Die Schnittstelle kann kein cEMI (nur "
                           f"{supported_emi_text(self.supported)}) – noch nicht unterstützt.")
        if self.supported & 4:
            # nicht jede Schnittstelle bestätigt das (OCI702 schweigt)
            self.link.send(PROTOCOL_FEATURE, FEATURE_SET, bytes([FEATURE_ACTIVE_EMI, CEMI]))
        else:
            # Siemens OCI702 meldet 0 («keine»), versteht aber cEMI: mit einer
            # Leseabfrage des Kommunikationsmodus prüfen
            self.link.send(PROTOCOL_TUNNEL, CEMI, comm_mode_read_request())
            self._await(lambda t: t.protocol == PROTOCOL_TUNNEL
                        and t.body[:1] == bytes([M_PROP_READ_CON]),
                        "cEMI-Abfrage (Schnittstelle ohne cEMI?)")
        self.set_mode(COMM_MODE_BUSMONITOR if busmonitor else COMM_MODE_DATA_LINK)

    def set_mode(self, mode: int) -> None:
        self.link.send(PROTOCOL_TUNNEL, CEMI, comm_mode_request(mode))
        answer = self._await(lambda t: t.protocol == PROTOCOL_TUNNEL
                             and t.body[:1] == bytes([M_PROP_WRITE_CON]),
                             "Kommunikationsmodus")
        # Bestätigung mit Anzahl 0 = abgelehnt
        if len(answer.body) >= 6 and answer.body[5] >> 4 == 0:
            raise UsbError("Die Schnittstelle lehnt den "
                           f"{'Busmonitor' if mode else 'Gruppenmonitor'}-Modus ab.")
        self.mode = mode

    def frames(self, timeout_ms: int = 200) -> bytes | None:
        """Nächster cEMI-Rahmen (L_Data.ind, L_Busmon.ind) oder None."""
        transfer = self.link.receive(timeout_ms)
        if transfer is None or transfer.protocol != PROTOCOL_TUNNEL:
            return None
        return transfer.body

    def close(self) -> None:
        try:
            if self.mode != COMM_MODE_DATA_LINK:
                self.link.send(PROTOCOL_TUNNEL, CEMI, comm_mode_request(COMM_MODE_DATA_LINK))
        except Exception:
            pass
        self.link.close()
