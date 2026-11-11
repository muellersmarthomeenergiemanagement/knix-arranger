"""
Buszugriff (FA-3101 ff.): KNiX verbindet sich selbst mit der Anlage, ohne ETS.

Etappe 1a: Live-Gruppenmonitor über KNXnet/IP (FA-3102a, FA-3103) --
Tunnel (UDP/TCP), Secure-Tunnel (Benutzer + Passwort oder Schlüsseldatei der
ETS, .knxkeys), Routing (auch Secure). Der Zugriff liest nur; gesendet wird
nichts (auch keine Leseanfragen).

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
import csv
import logging
import threading
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
KINDS = [
    (TUNNEL_UDP, "Tunnel (UDP), z.B. Fernzugang, ältere IP-Schnittstellen"),
    (TUNNEL_TCP, "Tunnel (TCP)"),
    (TUNNEL_SECURE, "Secure-Tunnel (TCP)"),
    (ROUTING, "Routing (Multicast, IP-Router im lokalen Netz)"),
    (ROUTING_SECURE, "Secure-Routing"),
]
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
    # gewünschte Tunneladresse (leer = die Schnittstelle wählt)
    individual_address: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "host": self.host, "port": self.port,
                "route_back": self.route_back, "keyring_path": self.keyring_path,
                "user_id": self.user_id, "individual_address": self.individual_address}

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
        )

    @property
    def is_routing(self) -> bool:
        return self.kind in (ROUTING, ROUTING_SECURE)

    @property
    def is_secure(self) -> bool:
        return self.kind in SECURE_KINDS

    def problems(self, secrets: Secrets | None = None) -> list[str]:
        """Was für eine Verbindung fehlt (leer = vollständig)."""
        found = []
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
        return [t.time.strftime("%H:%M:%S.%f")[:-3], self.sender, t.destination,
                self.designation, _SERVICE_LABELS.get(t.service, t.service),
                self.value, self.gewerk, self.room, self.floor]

    def search_cells(self) -> list[str]:
        return [self.telegram.source, self.telegram.destination, self.sender,
                self.designation, self.value, self.gewerk, self.room, self.floor]


COLUMNS = ["Zeit", "Absender", "GA", "Bezeichnung", "Dienst", "Wert", "Gewerk",
           "Raum", "Stockwerk"]
_SERVICE_LABELS = {"Write": "Schreiben", "Read": "Lesen", "Response": "Antwort"}


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
        self.room: dict[str, str] = dict(rooms_text)
        self.floor: dict[str, str] = {}
        for address, entries in index.items():
            codes = list(dict.fromkeys(code for _r, code, _e in entries if code))
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
            if address not in self.floor and ga.room_id in floor_of_room:
                self.floor[address] = floor_of_room[ga.room_id]

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


# ── Übernahme in die Busanalyse ────────────────────────────────────────────

def live_recording(frames: list[tuple[str, datetime]], label: str = "",
                   connection: str = "") -> dict:
    """Aufgezeichnete rohe cEMI-Rahmen (Hex, Zeit) als Mitschnitt für die
    Busanalyse (project.bus_recordings), ausgewertet wie ein ETS-Mitschnitt
    (bus_monitor.add_frames): Gruppenmonitor ohne Wiederholungen und
    Quittungen, mit Routing-Zähler und Rahmenlänge. BusLogError ohne
    auswertbare Telegramme."""
    from .bus_monitor import Recording, add_frames, summarize
    times = [when for _raw, when in frames if when]
    start = min(times, default=None)
    if not label:
        label = f"Live-Monitor {start:%d.%m.%Y %H:%M}" if start else "Live-Monitor"
    rec = Recording(
        file=label,
        start=start, stop=max(times, default=None), connection=connection,
        mode="Gruppenmonitor (KNiX Live-Monitor)")
    return summarize(add_frames(rec, frames))


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
        self._on_state = on_state
        self._on_raw = on_raw
        self.stats = ConnectionStats()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, settings: ConnectionSettings, secrets: Secrets) -> None:
        if self.running:
            return
        config = connection_config(settings, secrets)
        self.stats = ConnectionStats()
        self._thread = threading.Thread(target=self._run, args=(config, settings.label()),
                                        name="knx-bus", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
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
            self._loop = self._stop = None

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
            self._on_state(states.get(state, STATE_DISCONNECTED), label)

        xknx = XKNX(connection_config=config, telegram_received_cb=received,
                    connection_state_changed_cb=changed, state_updater=False)
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
                try:
                    on_raw(raw_cemi.hex().upper(), datetime.now())
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
