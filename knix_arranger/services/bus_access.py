"""
Buszugriff (FA-3101 ff.): KNiX verbindet sich selbst mit der Anlage, ohne ETS.

Etappe 1a: Live-Gruppenmonitor über KNXnet/IP (FA-3102a, FA-3103) --
Tunnel (UDP/TCP), Secure-Tunnel (Benutzer + Passwort oder Schlüsseldatei der
ETS, .knxkeys), Routing (auch Secure). Gesendet wird nur auf ausdrücklichen
Befehl des Anwenders: Wert schreiben oder GA lesen (FA-3102b,
BusConnection.send); Gerätezugriffe (Adressen, Applikationen) nie.

Aufbau:
- ConnectionSettings: Verbindung ohne Passwörter, im Projekt gespeichert
  (project.bus_connection). Passwörter gibt der Anwender je Verbindung ein.
- LiveTelegram: ein Gruppentelegramm, unabhängig von der Bibliothek.
- MonitorContext: ordnet ein Telegramm dem Projekt zu (Bezeichnung, Wert nach
  DPT wie die Busanalyse, Gewerk, Raum, Stockwerk, Absender).
- BusConnection: betreibt xknx in einem eigenen Thread mit asyncio-Schleife;
  Rückrufe kommen aus diesem Thread (die Ansicht reicht sie per Qt-Signal
  in den Hauptthread weiter).

Ohne Qt; die Netzwerkverbindung selbst lässt sich nur an einer Anlage testen.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import csv
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

logger = logging.getLogger("knix_arranger.bus_access")

# Verbindungsarten (Schlüssel, Anzeige)
TUNNEL_UDP = "tunnel_udp"
TUNNEL_TCP = "tunnel_tcp"
TUNNEL_SECURE = "tunnel_secure"
ROUTING = "routing"
ROUTING_SECURE = "routing_secure"
USB = "usb"
USB_BUSMONITOR = "usb_busmonitor"
KINDS = [
    (TUNNEL_UDP, "Tunnel (UDP), z.B. Fernzugang, ältere IP-Schnittstellen"),
    (TUNNEL_TCP, "Tunnel (TCP)"),
    (TUNNEL_SECURE, "Secure-Tunnel (TCP)"),
    (ROUTING, "Routing (Multicast, IP-Router im lokalen Netz)"),
    (ROUTING_SECURE, "Secure-Routing"),
    (USB, "USB-Schnittstelle (Gruppenmonitor)"),
    (USB_BUSMONITOR, "USB-Busmonitor (mit Quittungen und Wiederholungen)"),
]
USB_KINDS = (USB, USB_BUSMONITOR)
SECURE_KINDS = (TUNNEL_SECURE, ROUTING_SECURE)
DEFAULT_PORT = 3671

# Monitor: so viele Zeilen höchstens, ältere fallen weg
MAX_ROWS = 20000


@dataclass
class ConnectionSettings:
    """Verbindung zur Anlage, ohne Passwörter (die gibt der Anwender je
    Verbindung ein)."""
    kind: str = TUNNEL_UDP
    host: str = ""
    port: int = DEFAULT_PORT
    # Tunnel über NAT (Fernzugang, VPN): Antworten an die Absenderadresse
    route_back: bool = False
    # Secure: Schlüsseldatei der ETS (.knxkeys) oder Benutzer-ID des Tunnels
    keyring_path: str = ""
    user_id: int = 0
    # gewünschte Tunneladresse (leer = die Schnittstelle wählt); bei USB die
    # Adresse der Schnittstelle (Linie für den Hinweis auf nicht sichtbare GAs)
    individual_address: str = ""
    # USB: Gerät «VID:PID:Seriennummer» (knx_usb.UsbDevice.key)
    usb_device: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "host": self.host, "port": self.port,
                "route_back": self.route_back, "keyring_path": self.keyring_path,
                "user_id": self.user_id, "individual_address": self.individual_address,
                "usb_device": self.usb_device}

    @classmethod
    def from_dict(cls, data: dict | None) -> ConnectionSettings:
        data = data or {}
        kinds = {k for k, _ in KINDS}
        return cls(
            kind=data.get("kind") if data.get("kind") in kinds else TUNNEL_UDP,
            host=data.get("host", ""),
            port=int(data.get("port") or DEFAULT_PORT),
            route_back=bool(data.get("route_back", False)),
            keyring_path=data.get("keyring_path", ""),
            user_id=int(data.get("user_id") or 0),
            individual_address=data.get("individual_address", ""),
            usb_device=data.get("usb_device", ""),
        )

    @property
    def is_routing(self) -> bool:
        return self.kind in (ROUTING, ROUTING_SECURE)

    @property
    def is_secure(self) -> bool:
        return self.kind in SECURE_KINDS

    @property
    def is_usb(self) -> bool:
        return self.kind in USB_KINDS

    def problems(self, secrets: Secrets | None = None) -> list[str]:
        """Was für eine Verbindung fehlt (leer = vollständig)."""
        found = []
        if self.is_usb:
            if not self.usb_device:
                found.append("Keine USB-Schnittstelle gewählt.")
            return found
        if not self.is_routing and not self.host.strip():
            found.append("Adresse der Schnittstelle (IP oder Name) fehlt.")
        if not 0 < self.port < 65536:
            found.append("Port muss zwischen 1 und 65535 liegen.")
        if self.is_secure:
            secrets = secrets or Secrets()
            if self.keyring_path:
                if not secrets.keyring_password:
                    found.append("Passwort der Schlüsseldatei fehlt.")
            elif self.kind == ROUTING_SECURE:
                if not secrets.backbone_key:
                    found.append("Backbone-Schlüssel oder Schlüsseldatei fehlt.")
            elif not (self.user_id and secrets.user_password):
                found.append("Benutzer-ID und Passwort des Tunnels "
                             "oder eine Schlüsseldatei angeben.")
        return found

    def label(self) -> str:
        kind = dict(KINDS).get(self.kind, self.kind).split(" (")[0].split(",")[0]
        if self.is_usb:
            return f"{kind} · {self.usb_device.split(':')[0]}:{self.usb_device.split(':')[1]}" \
                if self.usb_device.count(":") >= 1 else kind
        target = "Multicast" if self.is_routing else f"{self.host}:{self.port}"
        return f"{kind} · {target}"


@dataclass
class Secrets:
    """Passwörter einer Verbindung; nur im Speicher, nie im Projekt."""
    user_password: str = ""
    device_authentication_password: str = ""
    keyring_password: str = ""
    backbone_key: str = ""


@dataclass
class LiveTelegram:
    """Ein Gruppentelegramm vom Bus."""
    time: datetime
    source: str             # physikalische Adresse "1.1.12"
    destination: str        # Gruppenadresse "1/2/3"
    service: str            # "Write", "Read", "Response"
    payload: str = ""       # Hex, wie in der Busanalyse
    size: int | None = None  # 0 = Wert im APCI (bis 6 Bit), sonst Anzahl Byte
    secure: bool = False    # KNX Data Secure (entschlüsselt)
    # nur Busmonitor: Wiederholung und Quittung danach ("ack", "nak", "busy",
    # "nak_busy"; "" = keine bzw. unbekannt)
    repeat: bool = False
    ack: str = ""
    busmonitor: bool = False
    # von KNiX gesendet (FA-3102b), von der Schnittstelle bestätigt
    sent: bool = False


def telegram_from_xknx(telegram, now: datetime | None = None) -> LiveTelegram | None:
    """xknx-Telegramm -> LiveTelegram; None für alles ausser Gruppentelegrammen
    (Gerätezugriffe der ETS u.ä.)."""
    from xknx.dpt import DPTArray, DPTBinary
    from xknx.telegram.address import GroupAddress
    from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

    if not isinstance(telegram.destination_address, GroupAddress):
        return None
    payload = telegram.payload
    services = {GroupValueWrite: "Write", GroupValueResponse: "Response",
                GroupValueRead: "Read"}
    service = services.get(type(payload))
    if service is None:
        return None
    data, size = "", None
    value = getattr(payload, "value", None)
    if isinstance(value, DPTBinary):
        data, size = f"{value.value:02X}", 0
    elif isinstance(value, DPTArray):
        data, size = bytes(value.value).hex().upper(), len(value.value)
    return LiveTelegram(
        time=now or datetime.now(),
        source=str(telegram.source_address),
        destination=str(telegram.destination_address),
        service=service, payload=data, size=size,
        secure=telegram.data_secure is True)


# ── Zuordnung zum Projekt ──────────────────────────────────────────────────

@dataclass
class MonitorRow:
    telegram: LiveTelegram
    sender: str = ""        # "1.1.12 Taster EDIZIOdue"
    designation: str = ""
    dpt: str = ""
    value: str = ""
    gewerk: str = ""
    room: str = ""
    floor: str = ""
    known: bool = True      # GA im Projekt

    def cells(self) -> list[str]:
        """Anzeige- und CSV-Spalten in der Reihenfolge von COLUMNS."""
        t = self.telegram
        service = _SERVICE_LABELS.get(t.service, t.service)
        if t.repeat:
            service += " (Wdh.)"
        ack = _ACK_LABELS.get(t.ack, "") if t.busmonitor else ""
        if t.busmonitor and not t.ack:
            ack = "keine"
        return [t.time.strftime("%H:%M:%S.%f")[:-3], self.sender, t.destination,
                self.designation, service, self.value, self.gewerk, self.room, self.floor,
                ack]

    def search_cells(self) -> list[str]:
        return [self.telegram.source, self.telegram.destination, self.sender,
                self.designation, self.value, self.gewerk, self.room, self.floor]


COLUMNS = ["Zeit", "Absender", "GA", "Bezeichnung", "Dienst", "Wert", "Gewerk",
           "Raum", "Stockwerk", "Quittung"]
_SERVICE_LABELS = {"Write": "Schreiben", "Read": "Lesen", "Response": "Antwort"}
_ACK_LABELS = {"ack": "ACK", "nak": "NAK", "busy": "BUSY", "nak_busy": "NAK+BUSY"}


class MonitorContext:
    """Nachschlagetabellen eines Projekts für den Monitor (einmal aufbauen,
    nach Projektänderungen neu)."""

    def __init__(self, project):
        from .building_service import BuildingService
        from .report_service import ReportService

        self.gas = {g.address: g for g in project.group_addresses.all_addresses()}
        self.devices = {d.physical_address: d for a in project.topology.areas
                        for ln in a.lines for d in ln.devices if d.physical_address}
        for d in list(self.devices.values()):
            for extra in getattr(d, "additional_addresses", []) or []:
                self.devices.setdefault(extra, d)
        catalog = project.gewerk_catalog
        floor_of_room, room_label = {}, {}
        for floor in project.all_floors:
            for room in floor.all_rooms:
                floor_of_room[room.id] = BuildingService.floor_label(project.areal, floor)
                room_label[room.id] = " ".join(p for p in (room.number, room.name) if p)
        report = ReportService(project)
        try:
            index = report.gewerk_index()        # GA -> [(Raum-ID, Gewerk, Element)]
        except Exception:
            logger.exception("Gewerke je GA nicht ermittelbar")
            index = {}
        try:
            rooms_text = report._ga_rooms()      # GA -> "05 Küche" (wie Raumbuch)
        except Exception:
            logger.exception("Räume je GA nicht ermittelbar")
            rooms_text = {}
        self.gewerk: dict[str, str] = {}
        # GA -> Gewerk-Codes (Vorsicht beim Senden)
        self.gewerk_codes: dict[str, list[str]] = {}
        self._catalog = catalog
        self.room: dict[str, str] = dict(rooms_text)
        self.floor: dict[str, str] = {}
        for address, entries in index.items():
            codes = list(dict.fromkeys(code for _r, code, _e in entries if code))
            self.gewerk_codes[address] = codes
            self.gewerk[address] = ", ".join(_gewerk_text(catalog, c) for c in codes)
            floors = list(dict.fromkeys(floor_of_room[r] for r, _c, _e in entries
                                        if r in floor_of_room))
            if floors:
                self.floor[address] = ", ".join(floors)
            if address not in self.room:
                names = list(dict.fromkeys(room_label[r] for r, _c, _e in entries
                                           if r in room_label))
                if names:
                    self.room[address] = ", ".join(names)
        for address, ga in self.gas.items():
            if address not in self.gewerk and ga.gewerk_code:
                self.gewerk[address] = _gewerk_text(catalog, ga.gewerk_code)
                self.gewerk_codes[address] = [ga.gewerk_code]
            if address not in self.floor and ga.room_id in floor_of_room:
                self.floor[address] = floor_of_room[ga.room_id]

    def caution(self, address: str) -> str:
        """Warum Senden auf diese GA besondere Vorsicht braucht ("" = keine
        besondere): Alarm, Wetteralarm, Tore und Türen (FA-3102b)."""
        ga = self.gas.get(address)
        catalog = self._catalog
        reasons = []
        for code in self.gewerk_codes.get(address, []):
            gewerk = catalog.get(code) if catalog else None
            category = getattr(gewerk, "category", "") if gewerk else ""
            if category == "alarm" or code in CAUTION_GEWERKE:
                reasons.append(_gewerk_text(catalog, code))
        name = (ga.designation or "") if ga else ""
        if not reasons and "alarm" in name.lower():
            reasons.append(f"«{' '.join(name.split())}»")
        if not reasons:
            return ""
        return (f"{', '.join(reasons)}: Ein Telegramm kann Alarme auslösen oder "
                "zurücksetzen, Antriebe bewegen oder Schutzfunktionen aufheben. Nur senden, "
                "wenn vor Ort niemand gefährdet ist und die Betroffenen Bescheid wissen.")

    def row(self, telegram: LiveTelegram) -> MonitorRow:
        from .dpt_values import decode_value
        ga = self.gas.get(telegram.destination)
        dpt = ga.datapoint_type if ga else ""
        value = ""
        if telegram.service != "Read":
            value = (decode_value(dpt, telegram.payload, telegram.size)
                     if dpt else telegram.payload)
            if telegram.secure:
                value += " (Secure)"
        device = self.devices.get(telegram.source)
        name = (device.product_name or device.product or "") if device else ""
        if telegram.sent:
            name = "KNiX (gesendet)"
        return MonitorRow(
            telegram=telegram,
            sender=" ".join(p for p in (telegram.source, name) if p),
            designation=" ".join((ga.designation or "").split()) if ga else "",
            dpt=dpt, value=value,
            gewerk=self.gewerk.get(telegram.destination, ""),
            room=self.room.get(telegram.destination, ""),
            floor=self.floor.get(telegram.destination, ""),
            known=ga is not None)


def _gewerk_text(catalog, code: str) -> str:
    gewerk = catalog.get(code) if catalog else None
    return f"{code} {gewerk.name}" if gewerk and gewerk.name else code


def row_matches(row: MonitorRow, query: str = "", gewerk: str = "",
                floor: str = "") -> bool:
    """Filter des Monitors (FA-3103): Suchtext wie in der Busanalyse (GA,
    Adresse, Bezeichnung, Raum ...), dazu Gewerk und Stockwerk."""
    from .bus_monitor import text_matches
    if gewerk and gewerk not in [part.split(" ")[0] for part in row.gewerk.split(", ")]:
        return False
    if floor and floor not in row.floor.split(", "):
        return False
    return text_matches(query, row.search_cells())


def export_csv(rows: list[MonitorRow], path: str) -> int:
    """Aufzeichnung als CSV (Semikolon, UTF-8 mit BOM für Excel); Zeit mit
    Datum. Gibt die Zahl der Zeilen zurück."""
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["Datum"] + COLUMNS + ["Daten (Hex)", "DPT"])
        for row in rows:
            writer.writerow([row.telegram.time.strftime("%d.%m.%Y")] + row.cells()
                            + [row.telegram.payload, row.dpt])
    return len(rows)


# ── Was die Schnittstelle nicht sieht ──────────────────────────────────────

@dataclass
class Visibility:
    """GAs, deren Telegramme die Linie der Schnittstelle nie erreichen
    (Filtertabellen der Koppler, Regel FA-643)."""
    line: str                                   # "1.1"
    hidden: dict[str, list[str]] = field(default_factory=dict)  # GA -> Koppler

    def by_coupler(self) -> dict[str, list[str]]:
        from .report_sorting import group_address_key
        result: dict[str, list[str]] = {}
        for ga, couplers in self.hidden.items():
            result.setdefault(", ".join(couplers), []).append(ga)
        return {k: sorted(v, key=group_address_key) for k, v in sorted(result.items())}

    def text(self) -> str:
        if not self.hidden:
            return ""
        couplers = sorted({c for cs in self.hidden.values() for c in cs})
        kind = "Koppler" if len(couplers) > 1 else (
            "Bereichskoppler" if couplers[0].endswith(".0.0") else "Linienkoppler")
        return (f"Über diese Schnittstelle (Linie {self.line}) nicht sichtbar: "
                f"{len(self.hidden)} GAs – {kind} {', '.join(couplers)} lässt sie nicht "
                "durch (Filtertabelle).")


def visibility(project, address: str) -> Visibility | None:
    """Welche GAs des Projekts an der Adresse `address` (Tunneladresse der
    Schnittstelle) nie ankommen; None ohne verwertbare Adresse."""
    from .filter_tables import CouplerFilters, line_of
    line = line_of(address or "")
    if not line or project is None:
        return None
    # nur Linien des Projekts (Routing ohne Adresse: 15.15.250 o.ä.)
    lines = {f"{a.area_number}.{ln.line_number}" for a in project.topology.areas
             for ln in a.lines}
    if line not in lines:
        return None
    filters = CouplerFilters.from_project(project)
    gas = [g.address for g in project.group_addresses.all_addresses()]
    return Visibility(line, filters.invisible_at(line, gas))


# ── Übernahme in die Busanalyse ────────────────────────────────────────────

def live_recording(frames: list[tuple[str, datetime]], label: str = "",
                   connection: str = "") -> dict:
    """Aufgezeichnete rohe cEMI-Rahmen (Hex, Zeit) als Mitschnitt für die
    Busanalyse (project.bus_recordings), ausgewertet wie ein ETS-Mitschnitt
    (bus_monitor.add_frames): über einen Tunnel Gruppenmonitor ohne
    Wiederholungen und Quittungen, über den USB-Busmonitor mit beidem; mit
    Routing-Zähler und Rahmenlänge. BusLogError ohne auswertbare Telegramme."""
    from .bus_monitor import Recording, add_frames, summarize
    times = [when for _raw, when in frames if when]
    start = min(times, default=None)
    if not label:
        label = f"Live-Monitor {start:%d.%m.%Y %H:%M}" if start else "Live-Monitor"
    rec = Recording(
        file=label,
        start=start, stop=max(times, default=None), connection=connection,
        mode="Gruppenmonitor (KNiX Live-Monitor)")
    rec = add_frames(rec, frames)
    if rec.busmon:
        rec.mode = "Busmonitor (KNiX Live-Monitor)"
    return summarize(rec)


# ── Senden und Lesen (FA-3102b) ────────────────────────────────────────────

# Gewerke, bei denen ein Telegramm mehr als Licht oder Storen bewegt: neben
# der Kategorie "alarm" (A, FK, RK, TK) die Wetterstation (Wind-/Regenalarm
# schützt die Storen), Garagentor und Türe
CAUTION_GEWERKE = ("W", "G", "TE")
# so lange wartet "GA lesen" auf die Antwort
READ_TIMEOUT = 3.0
# Bestätigung der Schnittstelle (L_Data.con) nach dem Senden
CONFIRM_TIMEOUT = 3.0
SERVICES = ("Write", "Read", "Response")
_APCI = {"Read": 0x00, "Response": 0x40, "Write": 0x80}
_MSG_DATA_REQ, _MSG_DATA_CON, _MSG_DATA_IND = 0x11, 0x2E, 0x29


class BusSendError(RuntimeError):
    """Senden nicht möglich oder von der Schnittstelle nicht bestätigt."""


def group_address_raw(address: str) -> int:
    """"1/2/3" (dreistufig) bzw. "1/515" (zweistufig) -> 16-Bit-Adresse."""
    parts = address.strip().split("/")
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        numbers = []
    if len(numbers) == 3 and numbers[0] <= 31 and numbers[1] <= 7 and numbers[2] <= 255:
        return numbers[0] << 11 | numbers[1] << 8 | numbers[2]
    if len(numbers) == 2 and numbers[0] <= 31 and numbers[1] <= 2047:
        return numbers[0] << 11 | numbers[1]
    raise BusSendError(f"«{address}» ist keine Gruppenadresse (H/M/U).")


def group_cemi(destination: str, service: str, payload: str = "",
               size: int | None = None) -> bytes:
    """cEMI L_Data.req für ein Gruppentelegramm (Standardrahmen, Priorität
    niedrig, Routing-Zähler 6). Quelladresse 0.0.0: die Schnittstelle setzt
    ihre eigene ein."""
    if service not in _APCI:
        raise BusSendError(f"Dienst «{service}» unbekannt.")
    data = bytes.fromhex(payload) if payload and service != "Read" else b""
    if service == "Read" or size == 0:
        value = data[0] & 0x3F if data else 0
        tpdu = bytes([0x00, _APCI[service] | value])
    else:
        tpdu = bytes([0x00, _APCI[service]]) + data
    dst = group_address_raw(destination)
    return bytes([_MSG_DATA_REQ, 0x00, 0xBC, 0xE0, 0x00, 0x00, dst >> 8, dst & 0xFF,
                  len(tpdu) - 1]) + tpdu


def _confirmed_as_indication(raw: bytes) -> bytes | None:
    """Positive Bestätigung (L_Data.con) -> derselbe Rahmen als L_Data.ind,
    damit das eigene Telegramm in die Aufzeichnung für die Busanalyse kommt;
    None bei negativer Bestätigung."""
    if len(raw) < 3 or raw[0] != _MSG_DATA_CON:
        return None
    ctrl1 = raw[2 + raw[1]] if len(raw) > 2 + raw[1] else 0x01
    if ctrl1 & 0x01:
        return None
    return bytes([_MSG_DATA_IND]) + raw[1:]


class PendingReads:
    """Leseanfragen, die auf ihre Antwort warten (GA lesen). Die Antwort
    kommt als Response-Telegramm auf dieselbe GA; ohne Antwort innerhalb
    READ_TIMEOUT gilt die Anfrage als unbeantwortet. Zeiten in Sekunden
    (time.monotonic)."""

    def __init__(self, timeout: float = READ_TIMEOUT):
        self.timeout = timeout
        self._waiting: list[tuple[str, float, Callable]] = []

    def __len__(self) -> int:
        return len(self._waiting)

    def add(self, address: str, callback: Callable, now: float) -> None:
        """Vor dem Senden vormerken: eine schnelle Antwort kann eintreffen,
        bevor die Bestätigung der eigenen Anfrage verarbeitet ist."""
        self._waiting.append((address, now + self.timeout, callback))

    def cancel(self, address: str, callback: Callable) -> bool:
        """Vormerkung zurücknehmen (Anfrage nicht gesendet)."""
        before = len(self._waiting)
        self._waiting = [w for w in self._waiting
                         if not (w[0] == address and w[2] == callback)]
        return len(self._waiting) < before

    def answered(self, telegram: LiveTelegram) -> list[Callable]:
        """Rückrufe, deren Anfrage dieses Telegramm beantwortet (und
        entfernen). Die eigene Leseanfrage zählt nicht."""
        if telegram.service != "Response" or telegram.sent:
            return []
        hit = [w for w in self._waiting if w[0] == telegram.destination]
        self._waiting = [w for w in self._waiting if w[0] != telegram.destination]
        return [callback for _a, _d, callback in hit]

    def expired(self, now: float) -> list[tuple[str, Callable]]:
        gone = [(a, c) for a, deadline, c in self._waiting if deadline <= now]
        self._waiting = [w for w in self._waiting if w[1] > now]
        return gone


# ── Verbindung ─────────────────────────────────────────────────────────────

STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_DISCONNECTED = "disconnected"
STATE_ERROR = "error"


def connection_config(settings: ConnectionSettings, secrets: Secrets):
    """ConnectionConfig für xknx aus Einstellungen und Passwörtern."""
    from xknx.io import ConnectionConfig, ConnectionType, SecureConfig

    types = {TUNNEL_UDP: ConnectionType.TUNNELING,
             TUNNEL_TCP: ConnectionType.TUNNELING_TCP,
             TUNNEL_SECURE: ConnectionType.TUNNELING_TCP_SECURE,
             ROUTING: ConnectionType.ROUTING,
             ROUTING_SECURE: ConnectionType.ROUTING_SECURE}
    secure = None
    if settings.is_secure:
        if settings.keyring_path:
            secure = SecureConfig(
                knxkeys_file_path=settings.keyring_path,
                knxkeys_password=secrets.keyring_password,
                user_id=settings.user_id or None,
                user_password=secrets.user_password or None)
        else:
            secure = SecureConfig(
                user_id=settings.user_id or None,
                user_password=secrets.user_password or None,
                device_authentication_password=(
                    secrets.device_authentication_password or None),
                backbone_key=secrets.backbone_key or None)
    elif settings.keyring_path and secrets.keyring_password:
        # ungesicherter Tunnel, aber Data Secure entschlüsseln (GA-Schlüssel)
        secure = SecureConfig(knxkeys_file_path=settings.keyring_path,
                              knxkeys_password=secrets.keyring_password)
    kwargs = {}
    if not settings.is_routing:
        kwargs.update(gateway_ip=settings.host.strip(), gateway_port=settings.port,
                      route_back=settings.route_back and settings.kind == TUNNEL_UDP)
    if settings.individual_address.strip():
        kwargs["individual_address"] = settings.individual_address.strip()
    return ConnectionConfig(connection_type=types[settings.kind], secure_config=secure,
                            auto_reconnect=True, **kwargs)


@dataclass
class ConnectionStats:
    """Wohin die Rahmen einer Verbindung gingen -- zeigt, ob und wo
    Telegramme fehlen. Zähler werden im Verbindungs-Thread erhöht und im
    Hauptthread gelesen (einzelne int-Zuweisungen, unter dem GIL sicher)."""
    frames: int = 0             # rohe Rahmen von der Schnittstelle
    group: int = 0              # Gruppentelegramme, an die Anzeige gegeben
    secure_undecoded: int = 0   # gesichert (Data Secure), kein passender Schlüssel
    unreadable: int = 0         # Rahmen, die xknx nicht lesen konnte
    sequence_lost: int = 0      # verworfen wegen falscher Folgenummer (UDP-Verlust)
    reconnects: int = 0         # Verbindung abgebrochen und neu aufgebaut
    # nur Busmonitor
    repeats: int = 0
    acks: int = 0
    naks: int = 0
    busys: int = 0
    unacked: int = 0            # Datenrahmen ohne Quittung

    @property
    def other(self) -> int:
        """Gerätezugriffe (z.B. ETS programmiert) und übrige Rahmen ohne
        Gruppentelegramm."""
        return max(0, self.frames - self.group - self.secure_undecoded - self.unreadable)

    @property
    def lossy(self) -> bool:
        return bool(self.secure_undecoded or self.unreadable or self.sequence_lost
                    or self.reconnects)

    def text(self) -> str:
        parts = [f"{self.frames} Rahmen empfangen", f"{self.group} Gruppentelegramme"]
        if self.other:
            parts.append(f"{self.other} Gerätezugriffe/übrige")
        if self.secure_undecoded:
            parts.append(f"{self.secure_undecoded} gesichert ohne Schlüssel")
        if self.unreadable:
            parts.append(f"{self.unreadable} nicht lesbar")
        if self.sequence_lost:
            parts.append(f"{self.sequence_lost} verloren (Folgenummer)")
        if self.reconnects:
            parts.append(f"{self.reconnects}× neu verbunden")
        if self.acks or self.naks or self.busys or self.repeats or self.unacked:
            parts.append(f"Quittungen: {self.acks} ACK, {self.naks} NAK, {self.busys} BUSY, "
                         f"{self.unacked} ohne")
            parts.append(f"{self.repeats} Wiederholungen")
        return " · ".join(parts)


class _SequenceLossCounter(logging.Handler):
    """Zählt die Meldung von xknx, dass ein Tunnel-Rahmen mit falscher
    Folgenummer verworfen wurde (Paket verloren, typisch über Internet/VPN)."""

    def __init__(self, stats: ConnectionStats):
        super().__init__(level=logging.WARNING)
        self.stats = stats

    def emit(self, record: logging.LogRecord) -> None:
        if "sequence number not equal" in record.getMessage():
            self.stats.sequence_lost += 1


class BusConnection:
    """Verbindung im eigenen Thread. on_telegram(LiveTelegram),
    on_state(Zustand, Text) und on_raw(Hex, Zeit) werden aus diesem Thread
    aufgerufen; on_raw bekommt jeden rohen cEMI-Rahmen (für die Busanalyse,
    gesicherte Telegramme verschlüsselt)."""

    def __init__(self, on_telegram: Callable[[LiveTelegram], None],
                 on_state: Callable[[str, str], None],
                 on_raw: Callable[[str, datetime], None] | None = None):
        self._on_telegram = on_telegram
        self._report_state = on_state
        self._on_raw = on_raw
        self.stats = ConnectionStats()
        # eigene Adresse am Bus (Tunneladresse, z.B. "1.1.72"), sobald verbunden
        self.local_address = ""
        self.connected = False
        self._settings: ConnectionSettings | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._xknx = None
        # USB: zu sendende Rahmen (cEMI, Telegramm, Future), vom Lese-Thread verschickt
        self._usb_out: queue.Queue = queue.Queue()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _on_state(self, state: str, text: str) -> None:
        self.connected = state == STATE_CONNECTED
        self._report_state(state, text)

    @property
    def can_send(self) -> bool:
        return (self.connected and self._settings is not None
                and self._settings.kind != USB_BUSMONITOR)

    def send(self, destination: str, service: str = "Write", payload: str = "",
             size: int | None = None) -> concurrent.futures.Future:
        """Gruppentelegramm senden (FA-3102b): Wert schreiben ("Write",
        payload/size wie dpt_values.encode_value) oder GA lesen ("Read").
        Das Future liefert das gesendete LiveTelegram, sobald die Schnittstelle
        es bestätigt hat (dann geht es auch an on_telegram), sonst
        BusSendError. Aufruf aus jedem Thread."""
        if service not in SERVICES:
            raise BusSendError(f"Dienst «{service}» unbekannt.")
        group_address_raw(destination)          # prüft die Adresse
        if not self.connected or self._settings is None:
            raise BusSendError("Nicht verbunden.")
        if self._settings.kind == USB_BUSMONITOR:
            raise BusSendError("Im Busmonitor-Modus sendet die Schnittstelle nicht – "
                               "als «USB-Schnittstelle (Gruppenmonitor)» verbinden.")
        live = LiveTelegram(time=datetime.now(), source=self.local_address or "",
                            destination=destination.strip(), service=service,
                            payload=payload if service != "Read" else "",
                            size=size if service != "Read" else None, sent=True)
        result: concurrent.futures.Future = concurrent.futures.Future()
        if self._settings.is_usb:
            frame = group_cemi(destination, service, payload, size)
            self._usb_out.put((frame, live, result))
            return result
        loop, xknx = self._loop, self._xknx
        if loop is None or xknx is None or loop.is_closed():
            raise BusSendError("Nicht verbunden.")
        telegram = _xknx_telegram(live)

        async def send_and_report() -> None:
            await xknx.cemi_handler.send_telegram(telegram)
            # gleich nach der Bestätigung melden, vor einer Antwort darauf
            live.secure = telegram.data_secure is True
            live.time = datetime.now()
            self._on_telegram(live)

        future = asyncio.run_coroutine_threadsafe(send_and_report(), loop)

        def done(f: concurrent.futures.Future) -> None:
            exc = f.exception() if not f.cancelled() else BusSendError("abgebrochen")
            if exc is not None:
                result.set_exception(BusSendError(_send_error_text(exc)))
            else:
                result.set_result(live)
        future.add_done_callback(done)
        return result

    def start(self, settings: ConnectionSettings, secrets: Secrets) -> None:
        if self.running:
            return
        self.stats = ConnectionStats()
        self.local_address = ""
        self.connected = False
        self._settings = settings
        self._usb_out = queue.Queue()
        if settings.is_usb:
            self._usb_stop = threading.Event()
            self._thread = threading.Thread(target=self._run_usb, args=(settings,),
                                            name="knx-usb", daemon=True)
            self._thread.start()
            return
        config = connection_config(settings, secrets)
        self._thread = threading.Thread(target=self._run, args=(config, settings.label()),
                                        name="knx-bus", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        usb_stop = getattr(self, "_usb_stop", None)
        if usb_stop is not None:
            usb_stop.set()
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stop.set)
            except RuntimeError:
                pass
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    def _run(self, config, label: str) -> None:
        try:
            asyncio.run(self._main(config, label))
        except Exception as exc:     # Verbindung nicht möglich, Passwort falsch ...
            logger.warning("Busverbindung %s: %s", label, exc)
            self._on_state(STATE_ERROR, _error_text(exc))
        finally:
            self._loop = self._stop = self._xknx = None
            self.connected = False

    def _run_usb(self, settings: ConnectionSettings) -> None:
        label = settings.label()
        session = None
        try:
            self._on_state(STATE_CONNECTING, label)
            session = _usb_session(settings, getattr(self, "hid_module", None))
            session.setup(busmonitor=settings.kind == USB_BUSMONITOR)
            # Adresse der USB-Schnittstelle liefert sie nicht; für den Hinweis
            # auf nicht sichtbare GAs gilt die eingetragene
            self.local_address = settings.individual_address.strip()
            self._on_state(STATE_CONNECTED, label)
            _usb_loop(self, settings, session, self._usb_stop)
        except Exception as exc:
            logger.warning("USB-Verbindung %s: %s", label, exc)
            self._on_state(STATE_ERROR, str(exc))
            return
        finally:
            self.connected = False
            _fail_pending(self._usb_out, "Verbindung getrennt")
            if session is not None:
                session.close()
        self._on_state(STATE_DISCONNECTED, label)

    async def _main(self, config, label: str) -> None:
        from xknx import XKNX
        from xknx.core import XknxConnectionState

        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        states = {XknxConnectionState.CONNECTED: STATE_CONNECTED,
                  XknxConnectionState.CONNECTING: STATE_CONNECTING,
                  XknxConnectionState.DISCONNECTED: STATE_DISCONNECTED}

        stats = self.stats
        connected_once = False

        def received(telegram) -> None:
            live = telegram_from_xknx(telegram)
            if live is not None:
                stats.group += 1
                self._on_telegram(live)

        def changed(state) -> None:
            nonlocal connected_once
            if state is XknxConnectionState.CONNECTED:
                if connected_once:
                    stats.reconnects += 1
                connected_once = True
                try:
                    self.local_address = str(xknx.current_address)
                except Exception:
                    self.local_address = ""
            self._on_state(states.get(state, STATE_DISCONNECTED), label)

        xknx = XKNX(connection_config=config, telegram_received_cb=received,
                    connection_state_changed_cb=changed, state_updater=False)
        self._xknx = xknx
        # rohe Rahmen mitlesen und zählen, bevor xknx sie auswertet: die
        # Schnittstelle ruft bei jedem Rahmen xknx.cemi_handler.handle_raw_cemi
        # auf (der Handler hat __slots__, darum eine Unterklasse statt Ersetzen
        # der Methode; vor dem Start, Data Secure richtet xknx beim Start ein)
        xknx.cemi_handler = _tapping_handler(xknx, self._on_raw, stats)
        loss_counter = _SequenceLossCounter(stats)
        xknx_log = logging.getLogger("xknx.log")
        xknx_log.addHandler(loss_counter)
        try:
            self._on_state(STATE_CONNECTING, label)
            await xknx.start()
            try:
                await self._stop.wait()
            finally:
                await xknx.stop()
                self._on_state(STATE_DISCONNECTED, label)
        finally:
            xknx_log.removeHandler(loss_counter)


def _usb_session(settings: ConnectionSettings, hid_module=None):
    """Schnittstelle zum gespeicherten Gerät öffnen (knx_usb)."""
    from .knx_usb import UsbError, UsbLink, UsbSession, find_devices
    devices = find_devices(hid_module)
    device = next((d for d in devices if d.key == settings.usb_device), None)
    if device is None:       # Seriennummer fehlt/anders: gleiche Hersteller- und Produkt-ID
        vid_pid = ":".join(settings.usb_device.split(":")[:2])
        device = next((d for d in devices if d.key.startswith(vid_pid + ":")), None)
    if device is None:
        raise UsbError("USB-Schnittstelle nicht gefunden – angeschlossen?")
    return UsbSession(UsbLink(device, hid_module))


def _usb_loop(connection: "BusConnection", settings: ConnectionSettings, session,
              stop: threading.Event) -> None:
    """Rahmen der USB-Schnittstelle lesen und wie einen Mitschnitt auswerten:
    L_Busmon.ind mit Wiederholungen und Quittungen, sonst L_Data.ind."""
    from .bus_monitor import INVALID, Telegram as BusTelegram, decode
    stats = connection.stats
    busmonitor = settings.kind == USB_BUSMONITOR
    last: LiveTelegram | None = None
    # gesendet, Bestätigung (L_Data.con) ausstehend: (Frist, Telegramm, Future)
    awaiting: list[tuple[float, LiveTelegram, concurrent.futures.Future]] = []
    while not stop.is_set():
        _usb_send_queued(connection, session, awaiting)
        raw = session.frames(50 if awaiting else 200)
        clock = time.monotonic()
        while awaiting and awaiting[0][0] <= clock:
            _deadline, _live, future = awaiting.pop(0)
            future.set_exception(BusSendError(
                "Die Schnittstelle hat das Telegramm nicht bestätigt."))
        if raw is None:
            continue
        hexraw, now = raw.hex().upper(), datetime.now()
        if raw[:1] == bytes([_MSG_DATA_CON]):
            _usb_confirmed(connection, raw, now, awaiting)
            continue
        result = decode(hexraw, now)
        if result is None:
            # Bestätigungen der Schnittstelle (M_Prop…) gehören nicht dazu;
            # alles andere zählen und protokollieren, damit nichts still fehlt
            if raw[:1] not in (b"\xf5", b"\xfb"):
                stats.frames += 1
                stats.unreadable += 1
                logger.info("USB-Rahmen nicht auswertbar: %s", hexraw)
            continue
        if isinstance(result, str) and result != INVALID:    # Quittung
            stats.acks += result == "ack"
            stats.naks += result in ("nak", "nak_busy")
            stats.busys += result in ("busy", "nak_busy")
            if last is not None and not last.ack:
                last.ack = result
                stats.unacked -= 1
            last = None
            if connection._on_raw is not None:
                connection._on_raw(hexraw, now)
            continue
        stats.frames += 1
        if connection._on_raw is not None:
            connection._on_raw(hexraw, now)
        if result == INVALID:
            stats.unreadable += 1
            last = None
            continue
        assert isinstance(result, BusTelegram)
        if busmonitor:
            stats.unacked += 1
            stats.repeats += result.repeat
        if not result.group:
            last = None
            continue
        if result.service not in ("Write", "Read", "Response"):
            stats.secure_undecoded += 1     # Data Secure («Erweiterter Dienst»)
            last = None
            continue
        live = LiveTelegram(time=now, source=result.src, destination=result.dst,
                            service=result.service, payload=result.payload,
                            size=result.size if result.size >= 0 else None,
                            repeat=result.repeat, busmonitor=busmonitor)
        stats.group += 1
        last = live if busmonitor else None
        connection._on_telegram(live)


def _usb_send_queued(connection: "BusConnection", session,
                     awaiting: list) -> None:
    """Wartende Telegramme an die USB-Schnittstelle (aus dem Lese-Thread,
    damit Lesen und Schreiben des HID-Geräts nicht gleichzeitig laufen)."""
    from .knx_usb import CEMI, PROTOCOL_TUNNEL
    while True:
        try:
            frame, live, future = connection._usb_out.get_nowait()
        except queue.Empty:
            return
        if not future.set_running_or_notify_cancel():
            continue
        try:
            session.link.send(PROTOCOL_TUNNEL, CEMI, frame)
        except Exception as exc:
            future.set_exception(BusSendError(f"Senden fehlgeschlagen: {exc}"))
            continue
        awaiting.append((time.monotonic() + CONFIRM_TIMEOUT, live, future))


def _usb_confirmed(connection: "BusConnection", raw: bytes, now: datetime,
                   awaiting: list) -> None:
    """L_Data.con der USB-Schnittstelle: Bestätigung des ältesten
    gesendeten Telegramms (sie bestätigt der Reihe nach)."""
    if not awaiting:
        return
    _deadline, live, future = awaiting.pop(0)
    indication = _confirmed_as_indication(raw)
    if indication is None:
        future.set_exception(BusSendError(
            "Die Schnittstelle meldet einen Fehler beim Senden (keine Quittung vom Bus?)."))
        return
    live.time = now
    if connection._on_raw is not None:
        connection._on_raw(indication.hex().upper(), now)
    connection._on_telegram(live)
    future.set_result(live)


def _fail_pending(out: queue.Queue, reason: str) -> None:
    while True:
        try:
            _frame, _live, future = out.get_nowait()
        except queue.Empty:
            return
        if future.set_running_or_notify_cancel():
            future.set_exception(BusSendError(reason))


def _xknx_telegram(live: LiveTelegram):
    """LiveTelegram -> xknx-Telegramm zum Senden."""
    from xknx.dpt import DPTArray, DPTBinary
    from xknx.telegram import Telegram
    from xknx.telegram.address import GroupAddress
    from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

    address = GroupAddress(group_address_raw(live.destination))
    if live.service == "Read":
        return Telegram(destination_address=address, payload=GroupValueRead())
    data = bytes.fromhex(live.payload or "00")
    value = DPTBinary(data[0] & 0x3F) if live.size == 0 else DPTArray(data)
    apci = GroupValueResponse if live.service == "Response" else GroupValueWrite
    return Telegram(destination_address=address, payload=apci(value))


def _send_error_text(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "confirmation" in lowered or "timed out" in lowered:
        return f"Die Schnittstelle hat das Telegramm nicht bestätigt ({text})"
    if "not connected" in lowered or "no connection" in lowered:
        return "Nicht verbunden – Verbindung abgebrochen?"
    return text


def _tapping_handler(xknx, on_raw: Callable[[str, datetime], None] | None,
                     stats: ConnectionStats | None = None):
    """CEMIHandler von xknx, der jeden rohen Rahmen zuerst an on_raw gibt und
    in stats zählt, was xknx damit tut (nicht lesbar, Schlüssel fehlt)."""
    from xknx.cemi import CEMIHandler

    class TappingCEMIHandler(CEMIHandler):
        def handle_raw_cemi(self, raw_cemi: bytes) -> None:
            if stats is not None:
                stats.frames += 1
            if on_raw is not None:
                # eigenes Telegramm (bestätigt) wie empfangen aufzeichnen
                recorded = _confirmed_as_indication(raw_cemi) or raw_cemi
                try:
                    on_raw(recorded.hex().upper(), datetime.now())
                except Exception:
                    logger.exception("Rohen Rahmen nicht aufgezeichnet")
            manager = self.xknx.connection_manager
            errors = manager.cemi_count_incoming_error
            super().handle_raw_cemi(raw_cemi)
            if stats is not None and manager.cemi_count_incoming_error > errors:
                stats.unreadable += 1

        def handle_data_secure_key_issue(self, cemi_data, received_data_secure) -> None:
            if stats is not None:
                stats.secure_undecoded += 1
            super().handle_data_secure_key_issue(cemi_data, received_data_secure)

    return TappingCEMIHandler(xknx)


def _error_text(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "password" in lowered or "authenticat" in lowered:
        return f"Anmeldung abgelehnt – Passwort oder Benutzer-ID prüfen ({text})"
    if "keyring" in lowered or "knxkeys" in lowered:
        return f"Schlüsseldatei nicht lesbar – Datei und Passwort prüfen ({text})"
    if ("timeout" in lowered or "unreachable" in lowered or "no route" in lowered
            or "could not be established" in lowered or "refused" in lowered):
        return f"Schnittstelle antwortet nicht – Adresse, Port und Netz prüfen ({text})"
    return text
