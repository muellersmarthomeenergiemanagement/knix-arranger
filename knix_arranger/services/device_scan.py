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
# quittiert ohne Antwort: so viele je Linie fragt der zweite Durchgang nach
MAX_MAYBE_PER_LINE = 30

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
           "Maske", "Verknüpfungen", "Hinweis"]

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
    unloaded: bool = False           # ohne geladene Applikation (Werkszustand)
    # Verbindungsaufbau quittiert, aber keine Antwort: da ist vermutlich ein
    # Gerät (auf der eigenen Linie quittiert sonst niemand)
    acknowledged: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def locked(self) -> bool:
        """Antwortet, gibt aber weder Hersteller noch Applikation preis."""
        return self.answered and not self.own and not self.unloaded and not (
            self.manufacturer_id or self.program)


def program_from_bytes(data: bytes) -> tuple[str, str]:
    """PID_PROGRAM_VERSION (5 Byte: Hersteller, Applikationsnummer, Version)
    -> ("M-0002", "4701-11"), wie in der ETS-Kennung A-4701-11."""
    if len(data) < 5:
        return "", ""
    manufacturer = f"M-{int.from_bytes(data[0:2], 'big'):04X}"
    return manufacturer, f"{int.from_bytes(data[2:4], 'big'):04X}-{data[4]:02X}"


def serial_from_bytes(data: bytes) -> str:
    # BCU 2 ohne Seriennummer liefert Nullen (ABB «0000:00000000», Feller
    # «001E:00000000»), entladene Geräte FF: keine Seriennummer
    if len(data) != 6 or data[2:] in (bytes(4), b"\xff" * 4):
        return ""
    return f"{data[:2].hex().upper()}:{data[2:].hex().upper()}"


def order_text(data: bytes) -> str:
    """Bestellnummer als Text, Füllbytes weg; nicht als Text lesbar = keine
    (Hager 1.1.6 liefert 01 02 03 … 09 00, als Gerätename unbrauchbar)."""
    stripped = data.rstrip(b"\x00 \xff")
    if stripped and all(32 <= b < 127 for b in stripped):
        return stripped.decode("ascii").strip()
    return ""


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
    # GA- und Zuordnungstabelle (FA-3108b): Kurztext und Abweichungen
    links: str = ""
    link_details: list[str] = field(default_factory=list)

    @property
    def status_text(self) -> str:
        return STATUS_TEXT.get(self.status, self.status)

    def cells(self) -> list[str]:
        return [self.address, self.status_text, self.manufacturer, self.product,
                self.application, self.serial_number, self.mask, self.links, self.note]


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
            lines: list[tuple[int, int]], tables: dict | None = None) -> list[ScanRow]:
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
        row = _row(address, finding, device, secure_project)
        if tables and address in tables:
            _link_cells(row, tables[address], device)
        rows.append(row)
    return rows


def _link_cells(row: ScanRow, table, device) -> None:
    """Spalte «Verknüpfungen»: gelesen, nicht lesbar, oder bei einem Gerät
    mit Verknüpfungen im Projekt der Vergleich mit der Anlage."""
    if not table.ok:
        if "nicht geladen" in table.error:
            row.links = "Applikation entladen"
            row.note = ("Gerät hat eine Adresse, aber keine geladene Applikation – z.B. "
                        "Ersatzgerät, Programmieren abgebrochen oder in der ETS entladen")
            return
        row.links = f"nicht lesbar: {table.error}"
        return
    count = sum(len(gas) for gas in table.links.values())
    if device is not None and any(co.connected_gas for co in device.communication_objects):
        diff = _differences(device, table)
        row.links = (f"stimmt ({count})" if not diff
                     else f"{len(diff)} Abweichungen ({count} in der Anlage)")
        row.link_details = [f"KO {n} – {ga}: {kind}" for _a, n, ga, kind in diff]
        flags = flag_differences(device, table)
        if flags:
            row.links += f"; Flags {len(flags)}× anders"
            row.link_details += [f"KO {n} Flags: Anlage {plant}, Projekt {own}"
                                 for n, plant, own in flags]
        elif table.flags:
            row.links += "; Flags stimmen"
        elif table.flags_error:
            row.links += f"; Flags: {table.flags_error}"
        return
    row.links = f"{len(table.group_addresses)} GAs, {count} Verknüpfungen – noch nicht übernommen"
    if table.flags_error:
        row.links += f"; Flags: {table.flags_error}"


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
        if finding.unloaded:
            row.note = ("Gerät mit Adresse, aber ohne geladene Applikation – z.B. Ersatzgerät, "
                        "Programmieren abgebrochen oder entladen")
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
                    timeout: float = PROBE_TIMEOUT,
                    retry=None) -> list[ScanFinding]:
    """Adressen der Linien der Reihe nach (parallel einige) anfragen. Läuft
    im Loop der Busverbindung; Rückrufe kommen aus diesem Thread. retry:
    Adressen, die ein zweites Mal gefragt werden, wenn sie schweigen."""
    own = str(getattr(xknx, "current_address", "") or "")
    targets = [f"{a}.{l}.{n}" for a, l in lines for n in addresses]
    findings: list[ScanFinding] = []
    semaphore = asyncio.Semaphore(max(1, parallel))
    done = 0
    maybe: list[str] = []      # quittiert, aber keine Antwort

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
            elif finding.acknowledged:
                maybe.append(address)
            if on_progress is not None:
                on_progress(ScanProgress(done, len(targets), len(findings), address))

    # xknx meldet jede leere Adresse als Fehler («Establishing connection
    # failed»): während der Suche ist das der Normalfall, nicht ins Protokoll
    quiet = _QuietManagement()
    management_log = logging.getLogger("xknx.management")
    management_log.addFilter(quiet)
    try:
        await asyncio.gather(*(one(address) for address in targets))
        # erwartete Geräte (im Projekt) ohne Antwort ein zweites Mal, einzeln
        # und mit längerer Wartezeit: bei Buslast geht eine Antwort verloren
        # (Chalet 1.1.6 fehlte beim ersten Lauf)
        # Ebenso «gesperrte»: Hager 1.1.15 gab einmal keine Kennung, beim
        # nächsten Lauf schon
        # Zweiter Versuch auch ohne Projekt: gesperrte (Siemens 1.1.18 gab
        # einmal keine Kennung) und Adressen, deren Verbindungsaufbau quittiert
        # wurde, die aber nicht antworteten (DALI-Gateway 1.1.8 fehlte in
        # RekChalet2) – Letztere nur, wenn es je Linie wenige sind: hinter
        # einem Koppler quittiert der Koppler jede Adresse
        answered = {f.address for f in findings if not f.locked}
        again = set(retry or ()) | {f.address for f in findings if f.locked}
        per_line: dict[str, list[str]] = {}
        for address in maybe:
            per_line.setdefault(address.rsplit(".", 1)[0], []).append(address)
        for addresses_of_line in per_line.values():
            if len(addresses_of_line) <= MAX_MAYBE_PER_LINE:
                again.update(addresses_of_line)
        for address in sorted(again & set(targets) - answered - {own},
                              key=_address_key):
            if stop is not None and stop.is_set():
                break
            finding = await probe_device(xknx, address, timeout * 2)
            earlier = next((f for f in findings if f.address == address), None)
            if not finding.answered or (earlier is not None and finding.locked):
                continue
            if earlier is not None:
                findings.remove(earlier)
            findings.append(finding)
            if on_found is not None:
                on_found(finding)
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
        finding.acknowledged = True
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
    if len(data) >= 2 and int.from_bytes(data[:2], "big") not in (0, 0xFFFF):
        # 0000 melden manche Geräte (Theben HTS) statt ihrer Kennung: unbekannt
        finding.manufacturer_id = f"M-{int.from_bytes(data[:2], 'big'):04X}"
    if not data and finding.errors and "Timeout" in finding.errors[-1]:
        # gibt nichts preis: nicht jede weitere Eigenschaft abwarten
        await _identity_from_memory(conn, finding, timeout)
        return
    raw_serial = await prop(OBJ_DEVICE, PID_SERIAL_NUMBER)
    finding.serial_number = serial_from_bytes(raw_serial)
    hardware = await prop(OBJ_DEVICE, PID_HARDWARE_TYPE)
    finding.hardware_type = hardware.hex().upper() if hardware.strip(b"\x00") else ""
    raw_order = await prop(OBJ_DEVICE, PID_ORDER_INFO)
    finding.order_info = order_text(raw_order)
    # Applikationsobjekt: meist Index 3, sonst unter den ersten suchen
    for index in (3, 4, 2, 5, 1):
        kind = await prop(index, PID_OBJECT_TYPE)
        if kind and int.from_bytes(kind, "big") == OBJECT_TYPE_APPLICATION:
            finding.program_manufacturer, finding.program = program_from_bytes(
                await prop(index, PID_PROGRAM_VERSION))
            break
        if not kind:
            break        # Objekt fehlt: weiter hinten kommt nichts mehr
    if finding.program_manufacturer in ("M-0000", "M-FFFF"):
        finding.program_manufacturer = ""
    # Seriennummer aus FF oder Bestellnummer aus Füllbytes (FB/FF): Gerät
    # ohne geladene Daten, Applikationskennung und Speicher ab 0x0104 sind
    # Zufall (Chalet 1.1.21 «RTS Automation», 0001-01). Der Ladezustand des
    # Applikationsobjekts taugt nicht dafür: Hager 1.1.15 meldet 0 und
    # arbeitet mit 30 Verknüpfungen
    # nur FB/FF gemischt: lauter FF ist eine leere Bestellnummer (Feller)
    garbage_order = len(raw_order) >= 4 and set(raw_order) == {0xFB, 0xFF}
    unloaded = raw_serial[2:] == b"\xff" * 4 or garbage_order
    if unloaded:
        finding.program = finding.program_manufacturer = ""
        if garbage_order:
            finding.order_info = ""
    if not finding.manufacturer_id and finding.program_manufacturer:
        finding.manufacturer_id = finding.program_manufacturer
    finding.unloaded = unloaded
    if not finding.manufacturer_id and not finding.program and not unloaded:
        await _identity_from_memory(conn, finding, timeout)


async def _identity_from_memory(conn, finding: ScanFinding, timeout: float) -> None:
    """Ohne Eigenschaften (System 7 ohne Geräteobjekt-Daten, Zugriffsschutz):
    Kennung wie bei BCU 1/2 im Speicher ab 0x0104 versuchen. Nur übernehmen,
    wenn sie plausibel ist (Hersteller nicht 00/FF)."""
    if _is_system_b(finding.mask):
        return
    from xknx.management.procedures import dmp_mem_read_r_co
    try:
        data = await asyncio.wait_for(dmp_mem_read_r_co(conn, 0x0104, 4), timeout)
    except Exception as exc:
        finding.errors.append(f"Speicher 0104: {exc.__class__.__name__}")
        return
    if len(data) == 4 and data[0] not in (0, 0xFF):
        finding.manufacturer_id, finding.program = bcu1_identity(data)
        finding.program_manufacturer = finding.manufacturer_id


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


# ── Ins Projekt übernehmen (FA-3108a) ─────────────────────────────────────

@dataclass
class AdoptResult:
    """Was «Ins Projekt übernehmen» getan hat (Adressen)."""
    added: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    with_product: list[str] = field(default_factory=list)
    without_product: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    locked: list[str] = field(default_factory=list)
    lines_added: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.completed)

    def text(self) -> str:
        parts = []
        if self.added:
            parts.append(f"{len(self.added)} Geräte angelegt")
        if self.completed:
            parts.append(f"{len(self.completed)} ergänzt (Seriennummer, Produkt)")
        if self.lines_added:
            parts.append("neue Linien " + ", ".join(self.lines_added))
        lines = ["; ".join(parts) + "." if parts else "Nichts zu übernehmen."]
        if self.with_product:
            lines.append(f"{len(self.with_product)} mit Produkt und Kommunikationsobjekten "
                         "aus dem Produktkatalog.")
        if self.without_product:
            lines.append(f"Ohne Produkt aus dem Katalog: {_short_list(self.without_product)} – "
                         "Herstellerdatei (.knxprod) importieren, dann erneut übernehmen.")
        if self.ambiguous:
            lines.append("Produkt unsicher (Applikation passt, Bestellnummer nicht eindeutig): "
                         f"{_short_list(self.ambiguous)} – in der Materialliste prüfen.")
        if self.locked:
            lines.append(f"Ohne Daten (Secure ohne Schlüssel?): {_short_list(self.locked)} – "
                         "als Platzhalter angelegt.")
        return "\n".join(lines)


def _short_list(addresses: list[str], limit: int = 8) -> str:
    shown = ", ".join(addresses[:limit])
    more = len(addresses) - limit
    return shown + (f" und {more} weitere" if more > 0 else "")


def _program_key(prod) -> tuple[str, str] | None:
    text = " ".join((getattr(prod, "hw2prog_id", "") or "",
                     getattr(prod, "application_program_id", "") or ""))
    match = re.search(r"_(?:HP|A)-([0-9A-Fa-f]{4})-([0-9A-Fa-f]{2})", text)
    mfr = (getattr(prod, "manufacturer_id", "") or "").upper()
    if not match or not mfr:
        return None
    return mfr, f"{match.group(1).upper()}-{match.group(2).upper()}"


def catalog_index(catalog) -> dict[tuple[str, str], list]:
    """Katalogprodukte nach (Hersteller-ID, Applikation "4701-11")."""
    index: dict[tuple[str, str], list] = {}
    if catalog is None:
        return index
    for prod in catalog.search_all("", include_hidden=True):
        key = _program_key(prod)
        if key is not None:
            index.setdefault(key, []).append(prod)
    return index


def match_product(index: dict, finding: ScanFinding):
    """Katalogprodukt zur gelesenen Applikation: (Produkt, mehrdeutig).
    Mehrere Geräte mit derselben Applikation: die Bestellnummer entscheidet,
    sonst das erste mit Kommunikationsobjekten."""
    from ..utils.manufacturers import normalize_order_number
    mfr = (finding.program_manufacturer or finding.manufacturer_id or "").upper()
    candidates = index.get((mfr, finding.program), []) if finding.program else []
    if not candidates:
        return None, False
    # nicht als Text lesbare Bestellnummer (Hex) taugt nicht zum Vergleich
    readable = not re.fullmatch(r"[0-9A-F]{16,}", finding.order_info or "")
    order = normalize_order_number(finding.order_info) if readable else ""

    def fits(prod) -> bool:
        number = normalize_order_number(prod.order_number)
        return bool(number) and (number in order or order in number)

    if len({normalize_order_number(p.order_number) for p in candidates}) == 1:
        # nur ein Produkt mit dieser Applikation; nennt das Gerät eine andere
        # Bestellnummer (gleiche Applikation in anderer Hardware), prüfen
        return candidates[0], bool(order) and not fits(candidates[0])
    if order:
        hits = [prod for prod in candidates if fits(prod)]
        if len({normalize_order_number(p.order_number) for p in hits}) == 1:
            return hits[0], False
    with_cos = [p for p in candidates if getattr(p, "co_count", 0)]
    return (with_cos or candidates)[0], True


def _kind(prod, address: str) -> str:
    if address.endswith(".0"):
        return "coupler"
    if prod is None:
        return "other"
    category = getattr(prod, "category", "")
    if category in ("actor", "sensor"):
        return category
    text = f"{getattr(prod, 'device_type', '')} {getattr(prod, 'product_name', '')}".lower()
    if "koppler" in text or "coupler" in text:
        return "coupler"
    if "gateway" in text or "schnittstelle" in text or "interface" in text:
        return "gateway"
    if "spannungsversorgung" in text or "netzteil" in text or "power supply" in text:
        return "power_supply"
    return "other"


def _line_of(project, area_number: int, line_number: int, result: AdoptResult):
    from ..models.topology import Area, Line
    topology = project.topology
    area = next((a for a in topology.areas if a.area_number == area_number), None)
    if area is None:
        area = Area(area_number=area_number, name=f"Bereich {area_number}")
        topology.areas.append(area)
        topology.areas.sort(key=lambda a: a.area_number)
    line = next((ln for ln in area.lines if ln.line_number == line_number), None)
    if line is None:
        line = Line(line_number=line_number, name=f"Linie {line_number}",
                    coupler_address=f"{area_number}.{line_number}.0" if line_number else "")
        area.lines.append(line)
        area.lines.sort(key=lambda ln: ln.line_number)
        result.lines_added.append(f"{area_number}.{line_number}")
    return line


def _apply_product(device, prod) -> None:
    from .product_capabilities import apply_catalog_product
    apply_catalog_product(device, prod)
    device.product = prod.product_name or device.product


def _apply_product_keeping_links(project, device, prod) -> None:
    """Produkt nachträglich zuweisen (Herstellerdatei inzwischen importiert),
    ohne die gelesenen Verknüpfungen zu verlieren: sie wandern auf die KOs
    des Produkts; GAs mit vorläufigem Namen «KO n (Adresse)» bekommen den
    Namen des KOs."""
    from ..models.topology import CommunicationObject
    links = {co.object_number: list(co.connected_gas)
             for co in device.communication_objects if co.connected_gas}
    _apply_product(device, prod)
    for number, gas in links.items():
        co = next((c for c in device.communication_objects if c.object_number == number), None)
        if co is None:
            co = CommunicationObject(object_number=number, name=f"KO {number}")
            device.communication_objects.append(co)
        co.connected_gas = gas
    device.communication_objects.sort(key=lambda c: c.object_number)
    placeholder = re.compile(rf"KO \d+ \({re.escape(device.physical_address)}\)")
    for ga in project.group_addresses.all_addresses():
        if placeholder.fullmatch(ga.designation or ""):
            name, dpt = _ga_name(project, ga.address)
            ga.designation = name or ga.designation
            ga.datapoint_type = ga.datapoint_type or dpt


def adopt_findings(project, findings: list[ScanFinding], catalog=None) -> AdoptResult:
    """Gefundene Geräte ins Projekt übernehmen: fehlende Bereiche, Linien und
    Geräte anlegen (Hersteller, Seriennummer, Bestellnummer, Applikation;
    Produkt und KOs aus dem Katalog, wenn die Applikation dort steht),
    bestehende Geräte nur ergänzen (leere Seriennummer, fehlendes Produkt) –
    nie überschreiben. Ein leeres Projekt gilt danach als bestehende Anlage
    (Topologie importiert)."""
    from ..models.topology import Device
    result = AdoptResult()
    existing = {d.physical_address: d for d in project_devices(project)}
    was_empty = not existing
    index = catalog_index(catalog)
    for finding in sorted(findings, key=lambda f: _address_key(f.address)):
        if not finding.answered or finding.own:
            continue
        parts = finding.address.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        prod, ambiguous = match_product(index, finding)
        device = existing.get(finding.address)
        if device is not None:
            done = False
            if finding.serial_number and not device.serial_number:
                device.serial_number = finding.serial_number
                done = True
            same_mfr = (prod is None or not device.manufacturer_id
                        or device.manufacturer_id.upper() == prod.manufacturer_id.upper())
            if prod is not None and not device.hw2prog_id and same_mfr:
                _apply_product_keeping_links(project, device, prod)
                if device.device_type in ("", "other", "unknown"):
                    device.device_type = _kind(prod, finding.address)
                result.with_product.append(finding.address)
                done = True
            if done:
                result.completed.append(finding.address)
            continue
        area_number, line_number, _ = (int(p) for p in parts)
        line = _line_of(project, area_number, line_number, result)
        mfr = finding.manufacturer_id or finding.program_manufacturer
        device = Device(
            physical_address=finding.address,
            manufacturer_id=mfr,
            manufacturer=_manufacturer_name(mfr),
            serial_number=finding.serial_number,
            order_number=finding.order_info,
            application_program=f"Applikation {finding.program}" if finding.program else "",
            device_type=_kind(prod, finding.address),
            # die Adresse steht schon im Gerät
            is_programmed=True,
            manually_added=True,
        )
        if finding.unloaded and prod is None:
            device.product = "Unbekannt – Applikation entladen"
            result.locked.append(finding.address)
        elif finding.locked or finding.refused:
            device.product = "Unbekannt – Daten gesperrt"
            result.locked.append(finding.address)
        elif prod is not None:
            _apply_product(device, prod)
            result.with_product.append(finding.address)
            if ambiguous:
                result.ambiguous.append(finding.address)
        else:
            device.product = finding.order_info or (
                f"{device.manufacturer} {finding.program}".strip())
            result.without_product.append(finding.address)
        line.devices.append(device)
        line.devices.sort(key=lambda d: _address_key(d.physical_address))
        if hasattr(line, "update_device_count"):
            line.update_device_count()
        existing[finding.address] = device
        result.added.append(finding.address)
    if was_empty and result.added:
        project.topology.is_imported = True
    # Teilnehmernummern über 63 gibt es nur mit Linien für 256 Teilnehmer:
    # die Anlage hat sie, also nicht mit 64 rechnen (sonst «Linie voll»)
    if any(int(a.rsplit(".", 1)[1]) > 63 for a in result.added) \
            and project.topology.topology_mode == "TP-64":
        project.topology.topology_mode = "TP-256"
    return result


# ── GAs und Verknüpfungen aus den Geräten (FA-3108b) ──────────────────────
#
# Jedes Gerät führt eine GA-Tabelle (Adresstabelle) und eine Zuordnungs-
# tabelle (welches KO an welcher GA). Gelesen wird der Speicher, nur lesend:
#   BCU 1/2 (Maske 001x/002x): Adresstabelle fest ab 0x0116 (1 Byte Anzahl
#     inkl. eigener physikalischer Adresse, dann je 2 Byte), Zeiger auf die
#     Zuordnungstabelle in 0x0111 (+0x0100; 1 Byte Anzahl, je TSAP, ASAP).
#   System 7 (070x): gleiches Format, Lage aus PID_TABLE_REFERENCE der
#     Objekte Adresstabelle (Typ 1) und Zuordnungstabelle (Typ 2).
#   System B (07B0, 57B0): Lage ebenso, 2 Byte Anzahl, GAs ohne eigene
#     Adresse; Zuordnungen je 2 Byte TSAP und ASAP.
# TSAP = Platz in der Adresstabelle (1 = erste GA), ASAP = KO-Nummer. Das
# Format prüft sich selbst (eigene Adresse an Platz 0 bzw. TSAP im Bereich);
# passt es nicht, gilt die Tabelle als nicht lesbar statt falsch.

PID_LOAD_STATE = 5
PID_TABLE_REFERENCE = 7
OBJECT_TYPE_ADDRESS_TABLE = 1
OBJECT_TYPE_ASSOCIATION_TABLE = 2
BCU_ADDRESS_TABLE = 0x0116
BCU_ASSOCIATION_POINTER = 0x0111
MAX_TABLE_ENTRIES = 2000


@dataclass
class LinkTables:
    """GA- und Zuordnungstabelle eines Geräts."""
    address: str
    group_addresses: list[str] = field(default_factory=list)
    # KO-Nummer -> GAs in der Reihenfolge der Zuordnungstabelle
    links: dict[int, list[str]] = field(default_factory=dict)
    table_format: str = ""          # "BCU", "System B"
    error: str = ""
    # nicht lesbar: Lage und erste Bytes der Tabellen (für die Fehlersuche)
    detail: str = ""
    # Flags der verknüpften KOs aus der KO-Tabelle (FA-3108d): KO -> «K-SÜ--»
    flags: dict[int, str] = field(default_factory=dict)
    flags_error: str = ""
    # Ende der Zuordnungstabelle im Speicher (0 = unbekannt): dahinter liegt
    # meist die KO-Tabelle
    association_end: int = 0

    @property
    def ok(self) -> bool:
        return not self.error


def group_address_text(raw: int) -> str:
    return f"{raw >> 11 & 0x1F}/{raw >> 8 & 0x07}/{raw & 0xFF}"


def individual_raw(address: str) -> int:
    area, line, device = (int(p) for p in address.split("."))
    return area << 12 | line << 8 | device


def parse_bcu_tables(address: str, address_table: bytes,
                     associations: bytes) -> LinkTables:
    """Format BCU/System 7: Adresstabelle mit Anzahl (1 Byte) inkl. eigener
    Adresse an Platz 0, Zuordnungen mit Anzahl (1 Byte), je TSAP, ASAP."""
    result = LinkTables(address=address, table_format="BCU")
    if not address_table:
        result.error = "Adresstabelle leer"
        return result
    count = address_table[0]
    entries = [int.from_bytes(address_table[1 + 2 * i:3 + 2 * i], "big")
               for i in range(count) if 3 + 2 * i <= len(address_table)]
    if len(entries) != count or not entries:
        result.error = "Adresstabelle unvollständig"
        return result
    # Platz 0: eigene Adresse; ABB (System 7, 0701) schreibt FFFF hinein
    # (Chalet 1.1.10: «14 FF FF 02 32 02 33 …»)
    if entries[0] not in (individual_raw(address), 0xFFFF):
        result.error = "Adresstabelle passt nicht (eigene Adresse fehlt)"
        return result
    gas = entries[1:]
    result.group_addresses = [group_address_text(g) for g in gas]
    if not associations:
        result.error = "Zuordnungstabelle leer"
        return result
    pairs = associations[0]
    for i in range(pairs):
        if 3 + 2 * i > len(associations):
            result.error = "Zuordnungstabelle unvollständig"
            return result
        tsap, asap = associations[1 + 2 * i], associations[2 + 2 * i]
        if 1 <= tsap <= len(gas):
            result.links.setdefault(asap, []).append(result.group_addresses[tsap - 1])
    return result


def parse_system_b_tables(address: str, address_table: bytes,
                          associations: bytes) -> LinkTables:
    """Format System B: Anzahl je 2 Byte, GAs ohne eigene Adresse,
    Zuordnungen je 2 Byte TSAP und ASAP."""
    result = LinkTables(address=address, table_format="System B")
    if len(address_table) < 2 or len(associations) < 2:
        result.error = "Tabelle leer"
        return result
    count = int.from_bytes(address_table[:2], "big")
    if count > MAX_TABLE_ENTRIES or len(address_table) < 2 + 2 * count:
        result.error = "Adresstabelle passt nicht"
        return result
    result.group_addresses = [group_address_text(int.from_bytes(
        address_table[2 + 2 * i:4 + 2 * i], "big")) for i in range(count)]
    pairs = int.from_bytes(associations[:2], "big")
    if pairs > MAX_TABLE_ENTRIES or len(associations) < 2 + 4 * pairs:
        result.error = "Zuordnungstabelle passt nicht"
        return result
    for i in range(pairs):
        tsap = int.from_bytes(associations[2 + 4 * i:4 + 4 * i], "big")
        asap = int.from_bytes(associations[4 + 4 * i:6 + 4 * i], "big")
        if not 1 <= tsap <= count:
            result.error = "Zuordnungstabelle passt nicht (Verweis ausserhalb)"
            result.links = {}
            return result
        result.links.setdefault(asap, []).append(result.group_addresses[tsap - 1])
    return result


def _is_system_b(mask: int | None) -> bool:
    return mask is not None and mask & 0x0FF0 == 0x07B0


def _uses_fixed_tables(mask: int | None) -> bool:
    return mask is not None and mask & 0xFFF0 in (0x0010, 0x0020)


async def read_links(xknx, address: str, mask: int | None,
                     timeout: float = DETAIL_TIMEOUT,
                     table_hint: int | None = None) -> LinkTables:
    """GA- und Zuordnungstabelle eines Geräts lesen (eigene Verbindung), dazu
    die Flags der verknüpften KOs aus der KO-Tabelle (FA-3108d)."""
    from xknx.telegram import IndividualAddress
    management = xknx.management
    target = IndividualAddress(address)
    holder = {"conn": None}
    try:
        holder["conn"] = await asyncio.wait_for(management.connect(target), timeout)
        if mask is None:
            from xknx.management.procedures import dmp_connect_r_co
            mask = await asyncio.wait_for(dmp_connect_r_co(holder["conn"]), timeout)
        result = await _read_tables(management, target, address, mask, timeout, holder)
        if result.ok and result.links:
            try:
                await _read_flags(holder["conn"], address, mask, result, timeout,
                                  table_hint)
            except Exception as exc:
                result.flags_error = _link_error(exc)
        return result
    except Exception as exc:
        return LinkTables(address=address, error=_link_error(exc))
    finally:
        await _close(management, target, holder["conn"])


async def _read_tables(management, target, address: str, mask: int | None,
                       timeout: float, holder: dict) -> LinkTables:
    """Adress- und Zuordnungstabelle auf allen bekannten Wegen; holder["conn"]
    ist die Verbindung (wird nach einer Zeitüberschreitung erneuert)."""
    conn = holder["conn"]
    if _uses_fixed_tables(mask):
        return await _read_bcu(conn, address, timeout)
    try:
        result = await _read_by_reference(conn, address, mask, timeout)
    except Exception as exc:
        result = LinkTables(address=address, error=_link_error(exc))
        # nach einer Zeitüberschreitung ist die Verbindung nicht mehr sauber
        await _close(management, target, conn)
        holder["conn"] = None
        conn = holder["conn"] = await asyncio.wait_for(management.connect(target),
                                                       timeout)
    if result.ok or "nicht geladen" in result.error:
        return result
    # Tabellen als Eigenschaft PID_TABLE, ohne Speicherzugriff
    try:
        by_property = await _read_property_tables(conn, address, timeout)
    except Exception as exc:
        by_property = LinkTables(address=address, error=_link_error(exc))
    if by_property.ok:
        return by_property
    result.error += f"; Eigenschaft: {by_property.error}"
    if _is_system_b(mask):
        return _with_detail(result)
    # System 7 mit Tabellen an der BCU-2-Lage; prüft sich selbst wie immer
    try:
        fixed = await _read_bcu(conn, address, timeout)
    except Exception as exc:
        result.error += f"; feste Lage: {_link_error(exc)}"
        return _with_detail(result)
    if fixed.ok:
        fixed.table_format = "BCU (feste Lage)"
        return fixed
    result.error += f"; feste Lage: {fixed.error}"
    return _with_detail(result)


# ── Flags aus der KO-Tabelle (FA-3108d) ───────────────────────────────────
#
# Je KO ein Konfigurationsbyte: Bit 2 Kommunikation, 3 Lesen, 4 Schreiben,
# 6 Übertragen, 7 Aktualisieren; bei System B Bit 5 Lesen bei Init (bei
# BCU 2 die Speicherwahl). BCU 1/2: Tabelle über den Zeiger in 0x0112
# (+0x0100): Anzahl, RAM-Zeiger, je KO 3 Byte (Wert-Zeiger, Konfiguration,
# Typ). System 7/B: Objekt Typ 9 (KO-Tabelle) als PID_TABLE oder über
# PID_TABLE_REFERENCE. Lage, Zählweise (KO 0 oder 1 zuerst) und Stelle des
# Konfigurationsbytes prüfen sich an den verknüpften KOs: sie müssen fast
# alle kommunizieren und schreiben oder senden.

OBJECT_TYPE_GROUP_OBJECT_TABLE = 9
BCU_OBJECT_POINTER = 0x0112
MAX_OBJECT_TABLE = 2000
FLAG_PLAUSIBLE = 0.9


def flags_from_config(config: int, read_on_init: bool = False) -> str:
    """Konfigurationsbyte -> Flags wie im Projekt («K-SÜ--»: K L S Ü A I)."""
    return "".join((
        "K" if config & 0x04 else "-",
        "L" if config & 0x08 else "-",
        "S" if config & 0x10 else "-",
        "Ü" if config & 0x40 else "-",
        "A" if config & 0x80 else "-",
        "I" if read_on_init and config & 0x20 else "-",
    ))


def choose_flags(entries: list[bytes], linked: list[int],
                 read_on_init: bool = False) -> dict[int, str] | None:
    """Deutung der KO-Tabelle, die zu den verknüpften KOs passt: Zählweise
    (Eintrag n = KO n oder KO n+1) und Stelle des Konfigurationsbytes im
    Eintrag. None, wenn keine Deutung plausibel ist."""
    return score_flags(entries, linked, read_on_init)[0]


def score_flags(entries: list[bytes], linked: list[int],
                read_on_init: bool = False) -> tuple[dict[int, str] | None, str]:
    """Wie choose_flags, dazu ein Kurztext für die Diagnose («12 Einträge,
    KO bis 20, 85 %»)."""
    if not entries or not linked:
        return None, f"{len(entries)} Einträge"
    width = min(len(e) for e in entries)
    best = None
    for shift in (0, -1):                # KO 0 zuerst bzw. KO 1 zuerst
        for position in range(width):
            hits = total = 0
            for number in linked:
                index = number + shift
                if not 0 <= index < len(entries):
                    continue
                total += 1
                config = entries[index][position]
                hits += bool(config & 0x04 and config & 0x50)
            if total and (best is None or hits / total > best[0]):
                best = (hits / total, shift, position, total)
    info = (f"{len(entries)} Einträge, KO bis {max(linked)}"
            + (f", {best[0]:.0%} von {best[3]} passend" if best else ""))
    if best is None or best[0] < FLAG_PLAUSIBLE or best[3] < len(linked) * 0.8:
        return None, info
    _score, shift, position, _total = best
    return ({number: flags_from_config(entries[number + shift][position], read_on_init)
             for number in linked if 0 <= number + shift < len(entries)}, info)


def _chunks(data: bytes, size: int) -> list[bytes]:
    return [data[i:i + size] for i in range(0, len(data) - size + 1, size)]


async def _read_flags(conn, address: str, mask: int | None, result: LinkTables,
                      timeout: float, table_hint: int | None = None) -> None:
    from xknx.management.procedures import dmp_interface_object_read_r
    linked = sorted(result.links)
    top = max(linked)
    if top > MAX_OBJECT_TABLE:
        result.flags_error = "KO-Tabelle zu gross"
        return
    system_b = _is_system_b(mask)
    notes: list[str] = []          # Diagnose je Versuch

    def take(label: str, entries: list[bytes]) -> bool:
        # festes Format: Konfiguration vor dem Typ (Grösse 0-15) am Schluss;
        # passt das, nur diese Stelle; sonst frei, aber erst ab 3 KOs (mit
        # einem oder zwei KOs träfe Zufall zu leicht)
        width = min((len(e) for e in entries), default=0)
        if width >= 2 and all(e[-1] <= 15 for e in entries):
            flags, info = score_flags([e[-2:-1] for e in entries], linked,
                                      read_on_init=system_b)
        elif len(linked) >= 3:
            flags, info = score_flags(entries, linked, read_on_init=system_b)
        else:
            flags, info = None, f"{len(entries)} Einträge, Format unbekannt"
        if flags:
            result.flags, result.flags_error = flags, ""
            return True
        sample = " ".join(e.hex().upper() for e in entries[:4])
        notes.append(f"{label}: {info} [{sample}]")
        return False

    def take_found(flags: dict[int, str]) -> None:
        result.flags, result.flags_error = flags, ""

    async def table_at(label: str, start: int, strides: tuple[int, ...]) -> bool:
        """Tabelle ab start: Kopf (Anzahl …) 2 Byte, dann je KO stride Byte."""
        try:
            data = await _memory(conn, start + 2, max(strides) * (top + 2), timeout)
        except Exception as exc:
            notes.append(f"{label} {start:#x}: {_link_error(exc)}")
            return False
        return any(take(f"{label} {start:#x} ({stride} Byte)", _chunks(data, stride))
                   for stride in strides)

    # 0) Lage laut Herstellerdatei (so schreibt die ETS): Kopf 1-3 Byte
    # (Anzahl, RAM-Zeiger 1 oder 2 Byte), je KO 3 Byte (BCU: Wert-Zeiger,
    # Konfiguration, Typ), 4 Byte (System 7: Wert-Zeiger 2 Byte) oder 2 Byte
    if table_hint is not None:
        data = await _memory_tolerant(conn, table_hint, 3 + 4 * (top + 2), timeout)
        system7 = mask is not None and mask & 0xFF00 == 0x0700
        layouts = ([(3, 4), (2, 4), (2, 3), (1, 3), (2, 2)] if system7
                   else [(2, 3), (1, 3), (3, 4), (2, 4), (2, 2)])
        for header, stride in layouts:
            if take(f"Herstellerdatei {table_hint:#x} ({header}+{stride} Byte)",
                    _chunks(data[header:], stride)):
                return
        if not data:
            notes.append(f"Herstellerdatei {table_hint:#x}: nicht lesbar")
    # 1) KO-Tabelle als Objekt (Typ 9): Eigenschaft PID_TABLE, sonst Lage
    if not _uses_fixed_tables(mask):
        index = None
        for candidate in range(1, 13):
            try:
                kind = await asyncio.wait_for(
                    dmp_interface_object_read_r(conn, candidate, PID_OBJECT_TYPE), timeout)
            except Exception:
                break
            if int.from_bytes(kind, "big") == OBJECT_TYPE_GROUP_OBJECT_TABLE:
                index = candidate
                break
        if index is not None:
            try:
                raw = await asyncio.wait_for(dmp_interface_object_read_r(
                    conn, index, PID_TABLE, count=1, start_index=0), timeout)
                count = min(int.from_bytes(raw, "big"), top + 2)
                if count:
                    data = await asyncio.wait_for(dmp_interface_object_read_r(
                        conn, index, PID_TABLE, count=count, start_index=1),
                        timeout * 4 + count * 0.5)
                    if take("Eigenschaft", _chunks(data, len(data) // count)):
                        return
            except Exception as exc:
                notes.append(f"Eigenschaft: {_link_error(exc)}")
            try:
                reference = int.from_bytes(await asyncio.wait_for(
                    dmp_interface_object_read_r(conn, index, PID_TABLE_REFERENCE),
                    timeout), "big")
                # System B: 2 Byte Anzahl, je KO 2 Byte; System 7: Anzahl,
                # RAM-Zeiger, je KO 3 Byte – beide ab Lage + 2
                if await table_at("Lage", reference, (2, 3)):
                    return
            except Exception as exc:
                notes.append(f"Lage: {_link_error(exc)}")
        else:
            notes.append("kein KO-Tabellen-Objekt")
    # 2) BCU-Zeiger in 0x0112, nur wenn er hinter die Adresstabelle zeigt
    if not system_b:
        try:
            header = await _memory(conn, 0x0110, 6, timeout)
            start = 0x0100 + header[2]
            if start >= BCU_ADDRESS_TABLE + 3:
                if await table_at("Zeiger", start, (3,)):
                    return
            else:
                notes.append(f"Zeiger 0x0112 = {header[2]:#04x} unplausibel "
                             f"[0110: {header.hex(' ').upper()}]")
        except Exception as exc:
            notes.append(f"Zeiger: {_link_error(exc)}")
    # 3) hinter der Zuordnungstabelle (dort liegt sie meist); oft ist für die
    # Zuordnungen mehr Platz reserviert als belegt (Chalet: Theben HTS, Siemens
    # «05 04 06 05 …»), darum ein Stück absuchen
    if result.association_end:
        if await table_at("nach Zuordnung", result.association_end,
                          (2, 3) if system_b else (3, 2)):
            return
        if not system_b and await _scan_object_table(
                conn, result.association_end, linked, timeout, take_found, notes):
            return
    result.flags_error = "Flags nicht deutbar – " + " | ".join(notes) if notes \
        else "KO-Tabelle nicht gefunden"


SCAN_WINDOW = 320


async def _memory_tolerant(conn, start: int, size: int, timeout: float) -> bytes:
    """So viel Speicher wie lesbar (in Stücken), bis zum ersten verweigerten."""
    data = bytearray()
    while size > 0:
        chunk = min(size, 48)
        try:
            data += await _memory(conn, start, chunk, timeout)
        except Exception:
            break
        start += chunk
        size -= chunk
    return bytes(data)


def find_object_table(data: bytes, linked: list[int]) -> tuple[dict[int, str], int] | None:
    """KO-Tabelle im BCU-/System-7-Format (Anzahl, RAM-Zeiger, je KO 3 Byte)
    irgendwo in data: Anzahl mindestens so gross wie das höchste verknüpfte
    KO, und die verknüpften KOs plausibel (score_flags). (Flags, Versatz)."""
    top = max(linked)
    for offset in range(0, max(0, len(data) - 2)):
        count = data[offset]
        if not top + 1 <= count <= 255:
            continue
        body = data[offset + 2:offset + 2 + 3 * count]
        entries = _chunks(body, 3)
        if len(entries) < count:
            continue
        # festes Format: Typ (Grösse) an dritter Stelle bei allen Einträgen
        # gültig (0-15) – zufällige Bytes erfüllen das kaum
        if any(entry[2] > 15 for entry in entries):
            continue
        flags, _info = score_flags([entry[1:2] for entry in entries], linked)
        if flags:
            return flags, offset
    return None


async def _scan_object_table(conn, start: int, linked: list[int], timeout: float,
                             found, notes: list[str]) -> bool:
    data = await _memory_tolerant(conn, start, SCAN_WINDOW + 3 * (max(linked) + 3), timeout)
    hit = find_object_table(data, linked)
    if hit is None:
        notes.append(f"gesucht ab {start:#x}: {len(data)} Byte, keine KO-Tabelle")
        return False
    found(hit[0])
    return True


def flag_differences(device, table: LinkTables) -> list[tuple[int, str, str]]:
    """Flags laut Gerät gegen Projekt: (KO, Anlage, Projekt) bei Unterschied."""
    from .ko_links import parse_flags
    result = []
    for number, plant in sorted(table.flags.items()):
        co = next((c for c in device.communication_objects
                   if c.object_number == number and c.connected_gas), None)
        if co is not None and parse_flags(plant) != parse_flags(co.flags):
            result.append((number, plant, co.flags or "–"))
    return result


def _link_error(exc: Exception) -> str:
    name = exc.__class__.__name__
    if isinstance(exc, asyncio.TimeoutError) or "Timeout" in name:
        return "keine Antwort"
    if "Refused" in name:
        return "Verbindung abgelehnt"
    text = str(exc)
    if "nr_of_elem=0" in text:
        return "Eigenschaft nicht lesbar (Zugriff gesperrt?)"
    return text or name


async def _memory(conn, start: int, size: int, timeout: float) -> bytes:
    from xknx.management.procedures import dmp_mem_read_r_co
    if size <= 0:
        return b""
    if start + size - 1 > 0xFFFF:
        return await _memory_extended(conn, start, size, timeout)
    # grosse Tabellen: je Anfrage eine eigene Wartezeit
    data = bytearray()
    while size > 0:
        chunk = min(size, 60)
        data += await asyncio.wait_for(dmp_mem_read_r_co(conn, start, chunk), timeout * 4)
        start += chunk
        size -= chunk
    return bytes(data)


# A_MemoryExtended_Read: 3 Byte Adresse; im Standardrahmen (15 Byte APDU)
# passen nach Dienst, Rückgabecode und Adresse 9 Byte Daten
EXTENDED_CHUNK = 8


async def _memory_extended(conn, start: int, size: int, timeout: float) -> bytes:
    """Speicher über 0xFFFF (System B mit 32-Bit-Tabellenlage, z.B. Elsner
    Salva 0x13000, Hörmann 0xF0000) mit A_MemoryExtended_Read."""
    from xknx.telegram import apci
    if start + size - 1 > 0xFFFFFF:
        raise ValueError(f"Speicheradresse {start:#x} ausserhalb von 16 MB")
    data = bytearray()
    while size > 0:
        chunk = min(size, EXTENDED_CHUNK)
        response = await asyncio.wait_for(
            conn.request(apci.MemoryExtendedRead(count=chunk, address=start)), timeout)
        payload = response.payload
        if payload.return_code != 0 or len(payload.data) != chunk:
            raise ValueError(f"Speicher {start:#x}: Rückgabecode {payload.return_code}")
        data += payload.data
        start += chunk
        size -= chunk
    return bytes(data)


async def _read_bcu(conn, address: str, timeout: float) -> LinkTables:
    count = (await _memory(conn, BCU_ADDRESS_TABLE, 1, timeout))[0]
    address_table = bytes([count]) + await _memory(conn, BCU_ADDRESS_TABLE + 1,
                                                   2 * count, timeout)
    pointer = (await _memory(conn, BCU_ASSOCIATION_POINTER, 1, timeout))[0]
    start = 0x0100 + pointer
    pairs = (await _memory(conn, start, 1, timeout))[0]
    associations = bytes([pairs]) + await _memory(conn, start + 1, 2 * pairs, timeout)
    result = parse_bcu_tables(address, address_table, associations)
    result.association_end = start + 1 + 2 * pairs
    return result


async def _table_objects(conn, timeout: float) -> dict[int, int]:
    """Objekttyp -> Index der Adress- und Zuordnungstabelle."""
    from xknx.management.procedures import dmp_interface_object_read_r
    found: dict[int, int] = {}
    for index in range(1, 6):
        try:
            kind = await asyncio.wait_for(
                dmp_interface_object_read_r(conn, index, PID_OBJECT_TYPE), timeout)
        except Exception:
            break
        number = int.from_bytes(kind, "big")
        if number in (OBJECT_TYPE_ADDRESS_TABLE, OBJECT_TYPE_ASSOCIATION_TABLE):
            found.setdefault(number, index)
        if len(found) == 2:
            break
    return found


async def _read_by_reference(conn, address: str, mask: int | None,
                             timeout: float) -> LinkTables:
    from xknx.management.procedures import dmp_interface_object_read_r
    objects = await _table_objects(conn, timeout)
    if len(objects) < 2:
        return LinkTables(address=address, error="Tabellen-Objekte nicht gefunden")
    references = {}
    for kind, index in objects.items():
        state = await asyncio.wait_for(
            dmp_interface_object_read_r(conn, index, PID_LOAD_STATE), timeout)
        if state and state[0] != 1:
            return LinkTables(address=address, error="Tabellen nicht geladen (entladen)")
        reference = await asyncio.wait_for(
            dmp_interface_object_read_r(conn, index, PID_TABLE_REFERENCE), timeout)
        references[kind] = int.from_bytes(reference, "big")
    address_start = references[OBJECT_TYPE_ADDRESS_TABLE]
    association_start = references[OBJECT_TYPE_ASSOCIATION_TABLE]
    samples = []
    for name, start in (("Adresstabelle", address_start), ("Zuordnung", association_start)):
        try:
            head = (await _memory(conn, start, 10, timeout)).hex(" ").upper()
        except Exception as exc:
            head = _link_error(exc)
        samples.append(f"{name} {start:#x}: {head}")
    detail = "; ".join(samples)
    # System B: Anzahl 2 Byte; System 7: 1 Byte (BCU-Format). Zuerst das
    # zur Maske passende Format, das andere als Gegenprobe
    order = ("B", "BCU") if _is_system_b(mask) else ("BCU", "B")
    errors = []
    for kind in order:
        if kind == "B":
            head = await _memory(conn, address_start, 2, timeout)
            count = int.from_bytes(head, "big")
            if count > MAX_TABLE_ENTRIES:
                errors.append("System B: Anzahl unplausibel")
                continue
            table = head + await _memory(conn, address_start + 2, 2 * count, timeout)
            head = await _memory(conn, association_start, 2, timeout)
            pairs = int.from_bytes(head, "big")
            if pairs > MAX_TABLE_ENTRIES:
                errors.append("System B: Zuordnungen unplausibel")
                continue
            links = head + await _memory(conn, association_start + 2, 4 * pairs, timeout)
            result = parse_system_b_tables(address, table, links)
            result.association_end = association_start + 2 + 4 * pairs
        else:
            count = (await _memory(conn, address_start, 1, timeout))[0]
            table = bytes([count]) + await _memory(conn, address_start + 1, 2 * count, timeout)
            pairs = (await _memory(conn, association_start, 1, timeout))[0]
            links = bytes([pairs]) + await _memory(conn, association_start + 1,
                                                   2 * pairs, timeout)
            result = parse_bcu_tables(address, table, links)
            result.association_end = association_start + 1 + 2 * pairs
        if result.ok:
            return result
        errors.append(f"{result.table_format}: {result.error}")
    return LinkTables(address=address, error="; ".join(errors), detail=detail)


def _with_detail(result: LinkTables) -> LinkTables:
    """Lage und erste Bytes an den Fehlertext (erscheint in der Liste und im
    CSV, damit sich das Format eines Geräts nachträglich klären lässt)."""
    if result.detail:
        result.error += f" [{result.detail}]"
    return result


PID_TABLE = 23


async def _read_property_tables(conn, address: str, timeout: float) -> LinkTables:
    """Adress- und Zuordnungstabelle als Eigenschaft PID_TABLE der beiden
    Tabellen-Objekte (Elementanzahl an Index 0, dann die Elemente)."""
    from xknx.management.procedures import dmp_interface_object_read_r
    objects = await _table_objects(conn, timeout)
    if len(objects) < 2:
        return LinkTables(address=address, error="Tabellen-Objekte nicht gefunden")

    async def table(index: int) -> tuple[int, bytes]:
        raw = await asyncio.wait_for(dmp_interface_object_read_r(
            conn, index, PID_TABLE, count=1, start_index=0), timeout)
        count = int.from_bytes(raw, "big")
        if count == 0:
            return 0, b""
        if count > MAX_TABLE_ENTRIES:
            raise ValueError("Anzahl unplausibel")
        data = await asyncio.wait_for(dmp_interface_object_read_r(
            conn, index, PID_TABLE, count=count, start_index=1), timeout * 4 + count * 0.5)
        return count, data

    address_count, address_data = await table(objects[OBJECT_TYPE_ADDRESS_TABLE])
    pair_count, pair_data = await table(objects[OBJECT_TYPE_ASSOCIATION_TABLE])
    return parse_property_tables(address, address_count, address_data,
                                 pair_count, pair_data)


def parse_property_tables(address: str, address_count: int, address_data: bytes,
                          pair_count: int, pair_data: bytes) -> LinkTables:
    """PID_TABLE: GAs je 2 Byte (mit oder ohne eigene Adresse an erster
    Stelle), Zuordnungen je 2 Byte (TSAP, ASAP) oder 4 Byte (je 2 Byte)."""
    result = LinkTables(address=address, table_format="Eigenschaft")
    if address_count and len(address_data) != 2 * address_count:
        result.error = "Adresstabelle: Elementgrösse nicht 2 Byte"
        return result
    entries = [int.from_bytes(address_data[2 * i:2 * i + 2], "big")
               for i in range(address_count)]
    if entries and entries[0] == individual_raw(address):
        entries = entries[1:]
    result.group_addresses = [group_address_text(g) for g in entries]
    if not pair_count:
        return result
    size = len(pair_data) // pair_count
    if size not in (2, 4) or len(pair_data) != size * pair_count:
        result.error = "Zuordnungstabelle: Elementgrösse unbekannt"
        return result
    half = size // 2
    for i in range(pair_count):
        element = pair_data[size * i:size * (i + 1)]
        tsap = int.from_bytes(element[:half], "big")
        asap = int.from_bytes(element[half:], "big")
        if not 1 <= tsap <= len(entries):
            result.error = "Zuordnungstabelle passt nicht (Verweis ausserhalb)"
            result.links = {}
            return result
        result.links.setdefault(asap, []).append(result.group_addresses[tsap - 1])
    return result


async def read_all_links(xknx, findings: list[ScanFinding],
                         on_progress: Callable[[ScanProgress], None] | None = None,
                         on_read: Callable[[LinkTables], None] | None = None,
                         stop: threading.Event | None = None,
                         timeout: float = DETAIL_TIMEOUT,
                         table_hints: dict[str, int] | None = None) -> list[LinkTables]:
    """Tabellen aller lesbaren Geräte nacheinander (eine Verbindung zur Zeit:
    grosse Tabellen brauchen viele Anfragen, parallel bringt wenig).
    table_hints: Adresse -> Lage der KO-Tabelle laut Herstellerdatei
    (object_table_hints, vorher ausserhalb des Bus-Loops ermittelt)."""
    table_hints = table_hints or {}
    targets = [f for f in findings if readable_for_links(f)]
    results: list[LinkTables] = []
    quiet = _QuietManagement()
    management_log = logging.getLogger("xknx.management")
    management_log.addFilter(quiet)
    try:
        for done, finding in enumerate(targets, 1):
            if stop is not None and stop.is_set():
                break
            tables = await read_links(xknx, finding.address, finding.mask, timeout,
                                      table_hints.get(finding.address))
            results.append(tables)
            if on_read is not None:
                on_read(tables)
            if on_progress is not None:
                on_progress(ScanProgress(done, len(targets),
                                         sum(1 for t in results if t.ok), finding.address))
    finally:
        management_log.removeFilter(quiet)
    return results


def object_table_hints(findings: list[ScanFinding], project=None) -> dict[str, int]:
    """Lage der KO-Tabelle je Gerät aus den Herstellerdateien (Hersteller und
    Applikation aus der Suche, sonst aus dem Projekt). Liest Dateien –
    ausserhalb des Bus-Loops aufrufen."""
    from .knxprod_tables import object_table_address
    devices = {d.physical_address: d for d in project_devices(project)} if project else {}
    hints = {}
    for finding in findings:
        if not readable_for_links(finding) or _is_system_b(finding.mask):
            continue
        mfr = finding.program_manufacturer or finding.manufacturer_id
        program = finding.program
        if not program and finding.address in devices:
            mfr, program = expected_program(devices[finding.address])
        address = object_table_address(mfr, program)
        if address is not None:
            hints[finding.address] = address
    return hints


def readable_for_links(finding: ScanFinding) -> bool:
    """Geräte mit Tabellen: geantwortet, keine Koppler (deren Filtertabelle
    ist etwas anderes) und nicht die eigene Adresse. Auch «gesperrte»: ein
    Gerät mit entladener Applikation gibt keine Kennung, aber den Ladezustand."""
    if not finding.answered or finding.own or finding.refused:
        return False
    mask = finding.mask or 0
    return not (mask & 0xFF00 == 0x0900 or finding.address.endswith(".0"))


@dataclass
class LinkAdoptResult:
    """Was das Übernehmen der Tabellen getan hat."""
    devices_linked: list[str] = field(default_factory=list)
    devices_kept: list[str] = field(default_factory=list)      # hatten schon Verknüpfungen
    devices_missing: list[str] = field(default_factory=list)   # nicht im Projekt
    unreadable: list[str] = field(default_factory=list)
    gas_added: int = 0
    links_added: int = 0
    unknown_objects: int = 0          # KO-Nummer ohne KO im Produkt
    variants_chosen: int = 0          # KO-Variante nach den Partnern gewählt
    flags_from_device: int = 0        # KOs mit Flags aus der KO-Tabelle
    flags_catalog: list[str] = field(default_factory=list)   # Flags aus Herstellerdaten
    # Vergleich bei Geräten mit Verknüpfungen: (Adresse, KO, GA, Art)
    differences: list[tuple[str, int, str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.gas_added or self.links_added or self.flags_from_device)

    def text(self) -> str:
        lines = []
        if self.devices_linked:
            lines.append(f"{len(self.devices_linked)} Geräte verknüpft: {self.links_added} "
                         f"Verknüpfungen, {self.gas_added} neue GAs.")
        if self.devices_kept:
            lines.append(f"{len(self.devices_kept)} Geräte hatten schon Verknüpfungen und "
                         "bleiben unverändert" + (
                             f"; {len(self.differences)} Abweichungen zur Anlage."
                             if self.differences else " – stimmen mit der Anlage überein."))
        if self.devices_linked:
            lines.append("KO-Texte stammen aus dem Produktkatalog. Hat ein KO je nach Parameter "
                         "mehrere Bedeutungen, wählt KNiX die, die zu den Partnern an derselben "
                         f"GA passt ({self.variants_chosen}× angepasst) – Parameter liest KNiX "
                         "nicht, im Zweifel vor Ort prüfen.")
        if self.flags_from_device:
            lines.append(f"Flags von {self.flags_from_device} KOs aus den Geräten gelesen.")
        if self.flags_catalog:
            lines.append(f"Flags aus den Herstellerdaten, nicht aus dem Gerät: "
                         f"{_short_list(self.flags_catalog)} – Standardwerte, nicht geprüft.")
        if self.unknown_objects:
            lines.append(f"{self.unknown_objects} KO-Nummern stehen nicht im Produkt – als "
                         "«KO n» angelegt (Produkt fehlt oder andere Applikationsversion).")
        if self.devices_missing:
            lines.append(f"Nicht im Projekt: {_short_list(self.devices_missing)} – zuerst "
                         "«Ins Projekt übernehmen».")
        if self.unreadable:
            lines.append(f"Tabellen nicht lesbar: {_short_list(self.unreadable)}.")
        return "\n".join(lines) or "Nichts zu übernehmen."


def _ga_group(project, main: int, middle: int):
    from ..models.group_address import MainGroup, MiddleGroup
    structure = project.group_addresses
    hg = next((m for m in structure.main_groups if m.number == main), None)
    if hg is None:
        hg = MainGroup(number=main, name=f"Hauptgruppe {main}")
        structure.main_groups.append(hg)
        structure.main_groups.sort(key=lambda m: m.number)
    mg = next((m for m in hg.middle_groups if m.number == middle), None)
    if mg is None:
        mg = MiddleGroup(number=middle, name=f"Mittelgruppe {main}/{middle}")
        hg.middle_groups.append(mg)
        hg.middle_groups.sort(key=lambda m: m.number)
    return mg


def clean_dpt(text: str) -> str:
    """Ein DPT aus dem KO: manche Katalog-KOs führen mehrere («DPT-1
    DPST-1-3»); der genaueste (DPST) gilt."""
    tokens = re.findall(r"DPS?T-\d+(?:-\d+)?", text or "")
    return next((t for t in tokens if t.startswith("DPST-")), tokens[0] if tokens else "")


def _ga_name(project, address: str) -> tuple[str, str]:
    """Vorläufiger Name und DPT einer gelesenen GA aus dem KO, das sie
    empfängt (Aktor, Gateway), sonst dem ersten: «Ausgang A Schalten
    (1.1.5)». Bessere Namen schlägt FA-3105b vor."""
    best = None
    dpts: list[str] = []
    for device in project_devices(project):
        for co in device.communication_objects:
            if address not in co.connected_gas:
                continue
            if clean_dpt(co.data_type):
                dpts.append(clean_dpt(co.data_type))
            rank = 0 if device.device_type in ("actor", "gateway") else 1
            if re.fullmatch(r"KO \d+", co.name or ""):
                rank += 2          # ohne Produkt: Name eines Partners vorziehen
            if best is None or rank < best[0]:
                best = (rank, device, co)
    if best is None:
        return "", ""
    _rank, device, co = best
    text = " ".join(t for t in (co.name, co.object_function) if t) or f"KO {co.object_number}"
    # DPT des empfangenden KOs, sonst eines Partners (genauer: DPST vor DPT)
    own = clean_dpt(co.data_type)
    dpt = own or next((d for d in dpts if d.startswith("DPST-")), "") or next(iter(dpts), "")
    if not dpt and (co.object_size or "").strip().lower() == "1 bit":
        dpt = "DPT-1"          # 1 Bit ist immer Hauptgruppe 1
    return f"{text} ({device.physical_address})", dpt


def adopt_links(project, tables: list[LinkTables]) -> LinkAdoptResult:
    """Gelesene Tabellen ins Projekt: fehlende GAs anlegen, KOs verknüpfen.
    Geräte, die schon Verknüpfungen haben (z.B. aus der ETS), bleiben
    unverändert; ihre Abweichungen zur Anlage stehen im Ergebnis."""
    from ..models.group_address import GroupAddress
    from ..models.topology import CommunicationObject
    result = LinkAdoptResult()
    devices = {d.physical_address: d for d in project_devices(project)}
    known = {ga.address for ga in project.group_addresses.all_addresses()}
    new_gas: list[str] = []
    for table in sorted(tables, key=lambda t: _address_key(t.address)):
        if not table.ok:
            result.unreadable.append(table.address)
            continue
        device = devices.get(table.address)
        if device is None:
            result.devices_missing.append(table.address)
            continue
        if any(co.connected_gas for co in device.communication_objects):
            result.devices_kept.append(table.address)
            link_diff = _differences(device, table)
            result.differences.extend(link_diff)
            # schon übernommene Rekonstruktion (kein ETS-Projekt), Verknüpfungen
            # wie in der Anlage: Flags aus dem Gerät statt aus den Herstellerdaten
            if not link_diff and not getattr(project, "ets_project_id", ""):
                result.flags_from_device += _apply_flags(device, table)
            continue
        linked = False
        for number, gas in sorted(table.links.items()):
            co = next((c for c in device.communication_objects
                       if c.object_number == number), None)
            if co is None:
                co = CommunicationObject(object_number=number, name=f"KO {number}")
                device.communication_objects.append(co)
                result.unknown_objects += 1
            co.connected_gas = list(dict.fromkeys(gas))
            result.links_added += len(co.connected_gas)
            linked = True
            for address in co.connected_gas:
                if address not in known:
                    known.add(address)
                    new_gas.append(address)
        device.communication_objects.sort(key=lambda c: c.object_number)
        if linked:
            result.devices_linked.append(table.address)
    result.variants_chosen = _choose_variants(
        [devices[a] for a in result.devices_linked], project)
    # Flags aus dem Gerät, erst nach der Variantenwahl (sie legt fest, welches
    # KO die Verknüpfung trägt)
    by_address = {t.address: t for t in tables}
    for address in result.devices_linked:
        table = by_address[address]
        if table.flags:
            result.flags_from_device += _apply_flags(devices[address], table)
        else:
            result.flags_catalog.append(address)
    for address in new_gas:
        main, middle, sub = (int(p) for p in address.split("/"))
        name, dpt = _ga_name(project, address)
        _ga_group(project, main, middle).group_addresses.append(GroupAddress(
            main_group=main, middle_group=middle, sub_group=sub,
            designation=name, datapoint_type=dpt))
        result.gas_added += 1
    for hg in project.group_addresses.main_groups:
        for mg in hg.middle_groups:
            mg.group_addresses.sort(key=lambda g: g.sub_group)
    return result


_WORD = re.compile(r"[a-zäöüß]{3,}")


def _words(co) -> set[str]:
    return set(_WORD.findall(f"{co.name} {co.object_function}".lower()))


def _choose_variants(devices: list, project) -> int:
    """KO-Nummern mit mehreren Varianten im Katalog (je nach Parameter, z.B.
    «Schalten» oder «UND-Verknüpfung»): die Verknüpfung auf die Variante
    legen, die am besten zu den Partnern an denselben GAs passt (gemeinsame
    Wörter, gleicher DPT). Ohne Hinweis bleibt die erste. Anzahl Wechsel."""
    partners: dict[str, list] = {}
    for device in project_devices(project):
        for co in device.communication_objects:
            for ga in co.connected_gas:
                partners.setdefault(ga, []).append((device, co))
    changed = 0
    for device in devices:
        by_number: dict[int, list] = {}
        for co in device.communication_objects:
            by_number.setdefault(co.object_number, []).append(co)
        for variants in by_number.values():
            linked = next((co for co in variants if co.connected_gas), None)
            if linked is None or len(variants) < 2:
                continue
            others = [co for ga in linked.connected_gas
                      for d, co in partners.get(ga, []) if d is not device]
            if not others:
                continue
            words = set().union(*(_words(co) for co in others))
            types = {co.data_type for co in others if co.data_type}

            def score(co) -> tuple[int, int]:
                own = _words(co) - _words_common(variants)
                return (len(own & words), int(bool(co.data_type) and co.data_type in types))
            best = max(variants, key=score)
            if best is not linked and score(best) > score(linked):
                best.connected_gas, linked.connected_gas = linked.connected_gas, []
                changed += 1
    return changed


def _words_common(variants: list) -> set[str]:
    """Wörter, die alle Varianten tragen (meist der Kanal), zählen nicht."""
    sets = [_words(co) for co in variants]
    return set.intersection(*sets) if sets else set()


def differences(device, table: LinkTables) -> list[tuple[str, int, str, str]]:
    """Verknüpfungen Projekt gegen Anlage (öffentlich, siehe _differences)."""
    return _differences(device, table)


def _apply_flags(device, table: LinkTables) -> int:
    """Flags aus der KO-Tabelle an die verknüpften KOs; Anzahl geänderter."""
    changed = 0
    for number, flags in table.flags.items():
        co = next((c for c in device.communication_objects
                   if c.object_number == number and c.connected_gas), None)
        if co is not None and co.flags != flags:
            co.flags = flags
            changed += 1
    return changed


def _differences(device, table: LinkTables) -> list[tuple[str, int, str, str]]:
    """Verknüpfungen im Projekt gegen die Anlage: (Adresse, KO, GA, Art) mit
    Art «nur Anlage» bzw. «nur Projekt»."""
    project_links = {(co.object_number, ga) for co in device.communication_objects
                     for ga in co.connected_gas}
    plant_links = {(number, ga) for number, gas in table.links.items() for ga in gas}
    diff = [(device.physical_address, n, ga, "nur Anlage")
            for n, ga in sorted(plant_links - project_links)]
    diff += [(device.physical_address, n, ga, "nur Projekt")
             for n, ga in sorted(project_links - plant_links)]
    return diff
