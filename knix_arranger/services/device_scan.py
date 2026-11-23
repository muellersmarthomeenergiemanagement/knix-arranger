"""
Teilnehmer suchen (FA-3108): welche physikalischen Adressen einer Linie
antworten und was für ein Gerät dahinter steckt, über die Verbindung des
Live-Monitors (KNXnet/IP-Tunnel oder Routing).

Nur lesend: je Adresse eine Punkt-zu-Punkt-Verbindung, Gerätebeschreibung
(Maskenversion) und einige Eigenschaften des Geräte- und des Applikations-
objekts (Hersteller, Seriennummer, Hardware-Typ, Bestellnummer,
Applikation), bei BCU 1 ohne Eigenschaften die Kennung im Speicher ab 0x0104.
Nichts wird geschrieben; Parameter und Verknüpfungen liest der Scan nicht.

Ergebnis gegen das Projekt (compare): stimmt, abweichend (Hersteller,
Applikation, Seriennummer), nicht im Projekt, antwortet nicht, Daten gesperrt
(antwortet, gibt aber nichts preis – typisch Secure ohne Schlüssel).

Der Bus-Teil (scan_line) läuft im asyncio-Loop der Busverbindung
(BusConnection.run_on_bus), der Rest ist ohne Bus und ohne Qt testbar.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger("knix_arranger.device_scan")

# Wartezeit je Anfrage; über einen Fernzugang (Internet) dauert eine Antwort
# schon einmal 0.5 s, fehlt ein Gerät hinter einem Koppler, kommt nie etwas
PROBE_TIMEOUT = 3.0
DETAIL_TIMEOUT = 4.0
# gleichzeitig angefragte Adressen: fehlende hinter einem Koppler kosten die
# volle Wartezeit, 4 parallel ergibt rund 3 min je Linie bei wenig Buslast
PARALLEL = 4

# Eigenschaften (KNX Resources 03.05.01)
OBJ_DEVICE = 0
PID_OBJECT_TYPE = 1
PID_SERIAL_NUMBER = 11
PID_MANUFACTURER_ID = 12
PID_PROGRAM_VERSION = 13
PID_ORDER_INFO = 15
PID_HARDWARE_TYPE = 78
OBJECT_TYPE_APPLICATION = 3

STATUS_OK = "ok"
STATUS_DIFFERENT = "different"
STATUS_EXTRA = "extra"
STATUS_MISSING = "missing"
STATUS_LOCKED = "locked"
STATUS_OWN = "own"

STATUS_TEXT = {
    STATUS_OK: "stimmt",
    STATUS_DIFFERENT: "abweichend",
    STATUS_EXTRA: "nicht im Projekt",
    STATUS_MISSING: "antwortet nicht",
    STATUS_LOCKED: "Daten gesperrt",
    STATUS_OWN: "Schnittstelle (KNiX)",
}

COLUMNS = ["Adresse", "Ergebnis", "Hersteller", "Gerät", "Applikation", "Seriennummer",
           "Maske", "Hinweis"]

_LINE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\s*$")


# ── Masken ────────────────────────────────────────────────────────────────

def mask_text(mask: int | None) -> str:
    """Maskenversion (Gerätebeschreibung 0) lesbar: Systemfamilie."""
    if mask is None:
        return ""
    family = ""
    if mask & 0xFFF0 == 0x0010:
        family = "BCU 1"
    elif mask & 0xFFF0 == 0x0020:
        family = "BCU 2"
    elif mask & 0xFFF0 == 0x0700:
        family = "System 7"
    elif mask & 0xFFF0 == 0x07B0:
        family = "System B"
    elif mask & 0xFF00 == 0x0900 or mask & 0xFFF0 == 0x0910:
        family = "Koppler"
    elif mask & 0xFF00 == 0x5700:
        family = "IP"
    elif mask & 0xFF00 == 0x2700:
        family = "RF"
    text = f"{mask:04X}"
    return f"{text} {family}" if family else text


def _is_bcu1(mask: int | None) -> bool:
    """BCU 1 (Maske 001x) kennt keine Eigenschaften, Kennung im Speicher."""
    return mask is not None and mask & 0xFFF0 == 0x0010


# ── Ergebnis je Adresse ───────────────────────────────────────────────────

@dataclass
class ScanFinding:
    """Was eine Adresse am Bus geantwortet hat."""
    address: str
    answered: bool = False
    mask: int | None = None
    manufacturer_id: str = ""        # "M-0002"
    serial_number: str = ""          # "0002:1234ABCD" wie im Projekt
    hardware_type: str = ""          # Hex
    order_info: str = ""             # Text oder Hex
    program: str = ""                # "4701-11" (Applikationsnummer-Version)
    program_manufacturer: str = ""   # Hersteller der Applikation (meist gleich)
    refused: bool = False            # Verbindung abgelehnt (Adresse belegt)
    own: bool = False                # eigene Adresse der Schnittstelle
    errors: list[str] = field(default_factory=list)

    @property
    def locked(self) -> bool:
        """Antwortet, gibt aber weder Hersteller noch Applikation preis."""
        return self.answered and not self.own and not (
            self.manufacturer_id or self.program)


def program_from_bytes(data: bytes) -> tuple[str, str]:
    """PID_PROGRAM_VERSION (5 Byte: Hersteller, Applikationsnummer, Version)
    -> ("M-0002", "4701-11"), wie in der ETS-Kennung A-4701-11."""
    if len(data) < 5:
        return "", ""
    manufacturer = f"M-{int.from_bytes(data[0:2], 'big'):04X}"
    return manufacturer, f"{int.from_bytes(data[2:4], 'big'):04X}-{data[4]:02X}"


def serial_from_bytes(data: bytes) -> str:
    if len(data) != 6:
        return ""
    return f"{data[:2].hex().upper()}:{data[2:].hex().upper()}"


def order_text(data: bytes) -> str:
    """Bestellnummer: meist ASCII, sonst Hex; Füllbytes weg."""
    stripped = data.rstrip(b"\x00 \xff")
    if stripped and all(32 <= b < 127 for b in stripped):
        return stripped.decode("ascii").strip()
    return data.hex().upper() if data.strip(b"\x00\xff") else ""


def bcu1_identity(data: bytes) -> tuple[str, str]:
    """BCU 1, Speicher ab 0x0104: Hersteller (1 Byte), Gerätetyp (2), Version (1)."""
    if len(data) < 4:
        return "", ""
    return f"M-{data[0]:04X}", f"{int.from_bytes(data[1:3], 'big'):04X}-{data[3]:02X}"


def expected_program(device) -> tuple[str, str]:
    """Hersteller und Applikation laut Projekt aus der Hardware2Program-
    Kennung ("M-0002_H-…_HP-4701-11-952C" -> ("M-0002", "4701-11"))."""
    ref = getattr(device, "hw2prog_id", "") or ""
    match = re.search(r"_HP-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{2})", ref)
    manufacturer = getattr(device, "manufacturer_id", "") or (
        ref.split("_")[0] if ref.startswith("M-") else "")
    if not match:
        return manufacturer, ""
    return manufacturer, f"{match.group(1).upper()}-{match.group(2).upper()}"


# ── Linien ────────────────────────────────────────────────────────────────

def parse_lines(text: str) -> list[tuple[int, int]]:
    """"1.1, 1.2" -> [(1, 1), (1, 2)]; ValueError mit Text bei Fehlern."""
    lines: list[tuple[int, int]] = []
    for part in re.split(r"[,;\s]+", text.strip()):
        if not part:
            continue
        match = _LINE.match(part)
        if not match:
            raise ValueError(f"«{part}» ist keine Linie – Bereich.Linie, z.B. 1.1")
        area, line = int(match.group(1)), int(match.group(2))
        if area > 15 or line > 15:
            raise ValueError(f"«{part}»: Bereich und Linie gehen bis 15")
        if (area, line) not in lines:
            lines.append((area, line))
    if not lines:
        raise ValueError("Keine Linie angegeben, z.B. 1.1")
    return lines


def project_devices(project) -> list:
    """Geräte des Projekts mit vergebener Adresse (ohne externe Teilnehmer
    wie Z-Server)."""
    result = []
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                address = device.physical_address or ""
                if getattr(device, "external", False) or not address or address.endswith("-"):
                    continue
                result.append(device)
    return result


def project_lines(project) -> list[tuple[int, int]]:
    """Linien mit Geräten im Projekt, z.B. [(1, 1), (1, 2)]."""
    lines: set[tuple[int, int]] = set()
    for device in project_devices(project):
        parts = device.physical_address.split(".")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            lines.add((int(parts[0]), int(parts[1])))
    return sorted(lines)


def line_text(line: tuple[int, int]) -> str:
    return f"{line[0]}.{line[1]}"


# ── Vergleich mit dem Projekt ─────────────────────────────────────────────

@dataclass
class ScanRow:
    address: str
    status: str
    finding: ScanFinding | None = None
    device: object | None = None
    manufacturer: str = ""
    product: str = ""
    application: str = ""
    serial_number: str = ""
    mask: str = ""
    note: str = ""

    @property
    def status_text(self) -> str:
        return STATUS_TEXT.get(self.status, self.status)

    def cells(self) -> list[str]:
        return [self.address, self.status_text, self.manufacturer, self.product,
                self.application, self.serial_number, self.mask, self.note]


def _address_key(address: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in address.split("."))
    except ValueError:
        return (999,)


def _manufacturer_name(mfr_id: str) -> str:
    if not mfr_id:
        return ""
    from ..utils.manufacturers import manufacturer_display_name
    name = manufacturer_display_name(mfr_id)
    return name or mfr_id


def _device_product(device) -> str:
    return (getattr(device, "product", "") or getattr(device, "product_name", "")
            or getattr(device, "order_number", "") or "")


def compare(project, findings: list[ScanFinding],
            lines: list[tuple[int, int]]) -> list[ScanRow]:
    """Gefundenes gegen die Geräte des Projekts auf den gesuchten Linien.
    Ohne Projekt (None) erscheint alles Gefundene als «nicht im Projekt»."""
    scanned = {line_text(line) for line in lines}
    by_address = {}
    secure_project = False
    if project is not None:
        for device in project_devices(project):
            by_address.setdefault(device.physical_address, device)
        secure_project = bool(getattr(getattr(project, "knx_secure", None), "enabled", False))
    found = {f.address: f for f in findings}
    rows: list[ScanRow] = []
    for address in sorted(set(found) | {a for a in by_address
                                        if a.rsplit(".", 1)[0] in scanned},
                          key=_address_key):
        finding = found.get(address)
        device = by_address.get(address)
        if finding is not None and not finding.answered:
            finding = None
        if finding is None and device is None:
            continue
        rows.append(_row(address, finding, device, secure_project))
    return rows


def _row(address: str, finding: ScanFinding | None, device, secure_project: bool) -> ScanRow:
    row = ScanRow(address=address, status=STATUS_OK, finding=finding, device=device)
    if device is not None:
        row.manufacturer = getattr(device, "manufacturer", "") or _manufacturer_name(
            getattr(device, "manufacturer_id", ""))
        row.product = _device_product(device)
        row.application = getattr(device, "application_program", "") or ""
        row.serial_number = getattr(device, "serial_number", "") or ""
    if finding is None:
        row.status = STATUS_MISSING
        if getattr(device, "secure_supported", False) and secure_project:
            row.note = ("Secure-fähig: im Secure-Betrieb ohne Schlüssel womöglich stumm; "
                        "sonst ausgeschaltet, nicht angeschlossen oder andere Adresse")
        else:
            row.note = "ausgeschaltet, nicht angeschlossen, andere Adresse oder Koppler sperrt"
        return row
    row.mask = mask_text(finding.mask)
    if finding.serial_number:
        row.serial_number = finding.serial_number
    if finding.own:
        row.status = STATUS_OWN
        row.note = "Adresse der Verbindung, über die KNiX sucht"
        return row
    found_mfr = finding.manufacturer_id or finding.program_manufacturer
    if device is None:
        row.status = STATUS_LOCKED if finding.locked else STATUS_EXTRA
        row.manufacturer = _manufacturer_name(found_mfr)
        row.product = finding.order_info
        row.application = finding.program
        row.note = ("antwortet, gibt aber keine Daten preis (Secure ohne Schlüssel?)"
                    if finding.locked else "Gerät am Bus, im Projekt keines mit dieser Adresse")
        if finding.refused:
            row.note = "lehnt die Verbindung ab (Adresse belegt)"
        return row
    if finding.locked:
        row.status = STATUS_LOCKED
        row.note = ("antwortet, gibt aber keine Daten preis – "
                    + ("Secure ohne Schlüssel?" if getattr(device, "secure_supported", False)
                       else "Zugriffsschutz (BAU-Schlüssel)?"))
        return row
    problems: list[str] = []
    want_mfr, want_program = expected_program(device)
    if found_mfr and want_mfr and found_mfr.upper() != want_mfr.upper():
        problems.append(f"Hersteller {_manufacturer_name(found_mfr)} statt "
                        f"{_manufacturer_name(want_mfr)}")
    if finding.program and want_program and not problems:
        have_number, have_version = finding.program.split("-")
        want_number, want_version = want_program.split("-")
        if have_number != want_number:
            problems.append(f"andere Applikation ({finding.program} statt {want_program})")
        elif have_version != want_version:
            problems.append(f"andere Applikationsversion ({have_version} statt {want_version})")
    want_serial = (getattr(device, "serial_number", "") or "").upper()
    if finding.serial_number and want_serial and finding.serial_number.upper() != want_serial:
        problems.append(f"andere Seriennummer (Projekt {want_serial}) – Gerät getauscht?")
    if problems:
        row.status = STATUS_DIFFERENT
        row.note = "; ".join(problems)
    elif finding.serial_number and not want_serial:
        row.note = "Seriennummer im Projekt leer"
    return row


def summary(rows: list[ScanRow]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    order = (STATUS_OK, STATUS_DIFFERENT, STATUS_EXTRA, STATUS_LOCKED, STATUS_MISSING)
    parts = [f"{counts[s]} {STATUS_TEXT[s]}" for s in order if counts.get(s)]
    return ", ".join(parts) if parts else "keine Geräte"


def export_csv(rows: list[ScanRow], path: str) -> int:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(row.cells())
    return len(rows)


# ── Bus ───────────────────────────────────────────────────────────────────

@dataclass
class ScanProgress:
    done: int
    total: int
    found: int
    address: str = ""


async def scan_line(xknx, lines: list[tuple[int, int]],
                    on_progress: Callable[[ScanProgress], None] | None = None,
                    on_found: Callable[[ScanFinding], None] | None = None,
                    stop: threading.Event | None = None,
                    addresses=range(0, 256),
                    parallel: int = PARALLEL,
                    timeout: float = PROBE_TIMEOUT) -> list[ScanFinding]:
    """Adressen der Linien der Reihe nach (parallel einige) anfragen. Läuft
    im Loop der Busverbindung; Rückrufe kommen aus diesem Thread."""
    own = str(getattr(xknx, "current_address", "") or "")
    targets = [f"{a}.{l}.{n}" for a, l in lines for n in addresses]
    findings: list[ScanFinding] = []
    semaphore = asyncio.Semaphore(max(1, parallel))
    done = 0

    async def one(address: str) -> None:
        nonlocal done
        async with semaphore:
            if stop is not None and stop.is_set():
                return
            if address == own:
                finding = ScanFinding(address=address, answered=True, own=True)
            else:
                finding = await probe_device(xknx, address, timeout)
            done += 1
            if finding.answered:
                findings.append(finding)
                if on_found is not None:
                    on_found(finding)
            if on_progress is not None:
                on_progress(ScanProgress(done, len(targets), len(findings), address))

    # xknx meldet jede leere Adresse als Fehler («Establishing connection
    # failed»): während der Suche ist das der Normalfall, nicht ins Protokoll
    quiet = _QuietManagement()
    management_log = logging.getLogger("xknx.management")
    management_log.addFilter(quiet)
    try:
        await asyncio.gather(*(one(address) for address in targets))
    finally:
        management_log.removeFilter(quiet)
    findings.sort(key=lambda f: _address_key(f.address))
    return findings


class _QuietManagement(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno > logging.ERROR


async def probe_device(xknx, address: str, timeout: float = PROBE_TIMEOUT,
                       detail_timeout: float = DETAIL_TIMEOUT) -> ScanFinding:
    """Eine Adresse: verbinden, Gerätebeschreibung, bei Antwort die Daten."""
    from xknx.exceptions import ManagementConnectionError, ManagementConnectionRefused
    from xknx.management.procedures import dmp_connect_r_co
    from xknx.telegram import IndividualAddress

    finding = ScanFinding(address=address)
    target = IndividualAddress(address)
    management = xknx.management
    conn = None
    try:
        conn = await asyncio.wait_for(management.connect(target), timeout)
        finding.mask = await asyncio.wait_for(dmp_connect_r_co(conn), timeout)
        finding.answered = True
    except ManagementConnectionRefused:
        # Abbau durch das Gerät = Adresse belegt (Management Procedures 2.3)
        finding.answered = finding.refused = True
    except (asyncio.TimeoutError, ManagementConnectionError):
        pass     # niemand da (keine Quittung) oder keine Antwort
    except Exception as exc:     # Verbindung weg o.ä.: Adresse als stumm werten
        logger.info("Teilnehmer %s: %s", address, exc)
    try:
        if finding.answered and conn is not None and not finding.refused:
            await _read_details(conn, finding, detail_timeout)
    finally:
        await _close(management, target, conn)
    return finding


async def _read_details(conn, finding: ScanFinding, timeout: float) -> None:
    from xknx.management.procedures import dmp_interface_object_read_r, dmp_mem_read_r_co

    async def prop(obj: int, pid: int) -> bytes:
        try:
            return await asyncio.wait_for(
                dmp_interface_object_read_r(conn, obj, pid), timeout)
        except Exception as exc:
            finding.errors.append(f"Objekt {obj} PID {pid}: {exc.__class__.__name__}")
            return b""

    if _is_bcu1(finding.mask):
        try:
            data = await asyncio.wait_for(dmp_mem_read_r_co(conn, 0x0104, 4), timeout)
            finding.manufacturer_id, finding.program = bcu1_identity(data)
            finding.program_manufacturer = finding.manufacturer_id
        except Exception as exc:
            finding.errors.append(f"Speicher 0104: {exc.__class__.__name__}")
        return
    data = await prop(OBJ_DEVICE, PID_MANUFACTURER_ID)
    if len(data) >= 2:
        finding.manufacturer_id = f"M-{int.from_bytes(data[:2], 'big'):04X}"
    if not data and finding.errors and "Timeout" in finding.errors[-1]:
        return       # gibt nichts preis: nicht jede weitere Eigenschaft abwarten
    finding.serial_number = serial_from_bytes(await prop(OBJ_DEVICE, PID_SERIAL_NUMBER))
    hardware = await prop(OBJ_DEVICE, PID_HARDWARE_TYPE)
    finding.hardware_type = hardware.hex().upper() if hardware.strip(b"\x00") else ""
    finding.order_info = order_text(await prop(OBJ_DEVICE, PID_ORDER_INFO))
    # Applikationsobjekt: meist Index 3, sonst unter den ersten suchen
    for index in (3, 4, 2, 5, 1):
        kind = await prop(index, PID_OBJECT_TYPE)
        if kind and int.from_bytes(kind, "big") == OBJECT_TYPE_APPLICATION:
            finding.program_manufacturer, finding.program = program_from_bytes(
                await prop(index, PID_PROGRAM_VERSION))
            break
        if not kind:
            break        # Objekt fehlt: weiter hinten kommt nichts mehr
    if not finding.manufacturer_id and finding.program_manufacturer:
        finding.manufacturer_id = finding.program_manufacturer


async def _close(management, target, conn) -> None:
    """Verbindung abbauen; bleibt sie in der Verwaltung hängen (Abbau
    misslungen), sie dort entfernen, sonst scheitert der nächste Versuch."""
    if conn is not None:
        try:
            await asyncio.wait_for(management.disconnect(target), 2.0)
        except Exception:
            pass
    connections = getattr(management, "_connections", None)
    if isinstance(connections, dict):
        connections.pop(target, None)
