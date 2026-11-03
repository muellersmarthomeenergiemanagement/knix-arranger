"""
Busmonitor-Mitschnitt einlesen und gegen das Projekt auswerten (FA-640).

Die ETS speichert Mitschnitte aus Bus- und Gruppenmonitor als XML
(CommunicationLog, Namespace http://knx.org/xml/telegrams/01); jedes
Telegramm steht als cEMI-Rahmen in RawData:
- L_Busmon.ind (0x2B): der TP-Rahmen, wie er auf dem Bus lag, mit
  Wiederholungsbit und Quittungen (ACK) als eigene Ein-Byte-Rahmen,
- L_Data.ind (0x29): der Gruppenmonitor, ohne Wiederholungen und Quittungen.

Gespeichert wird je Mitschnitt nur die Zusammenfassung (Absender, Paare
Absender -> Ziel mit Anzahl und Wiederholungen, Spitzenlast); ausgewertet
wird sie jeweils gegen den aktuellen Projektstand (analyze).

Ein Mitschnitt zeigt nur, was am Messpunkt (Linie der Schnittstelle)
ankommt, und nur, was im Zeitraum gesendet wurde. Was ein Gerät liest
(z.B. eine Visualisierung), sieht man nicht.
"""
from __future__ import annotations
import os
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

_NS = "{http://knx.org/xml/telegrams/01}"
_SERVICES = {0x000: "Read", 0x040: "Response", 0x080: "Write"}
_MSG_BUSMON, _MSG_DATA_IND = 0x2B, 0x29
_ACK = 0xCC


class BusLogError(ValueError):
    pass


@dataclass
class Telegram:
    time: datetime
    src: str
    dst: str
    group: bool
    service: str
    payload: str            # Daten als Hex ("" ohne Daten, 1-Bit-Wert als "0".."3F")
    repeat: bool = False


def _group(value: int) -> str:
    return f"{value >> 11}/{(value >> 8) & 7}/{value & 0xFF}"


def _individual(hi: int, lo: int) -> str:
    return f"{hi >> 4}.{hi & 15}.{lo}"


def _tpdu(tpdu: bytes) -> tuple[str, str]:
    """(Dienst, Daten) aus TPCI/APCI und Daten."""
    if len(tpdu) < 2:
        return "Steuerung", ""
    apci = ((tpdu[0] & 0x03) << 8 | tpdu[1]) & 0x3C0
    service = _SERVICES.get(apci, f"APCI {apci:03X}")
    if len(tpdu) == 2:
        return service, "" if service == "Read" else f"{tpdu[1] & 0x3F:X}"
    return service, tpdu[2:].hex().upper()


def decode(raw: str, time: datetime) -> Telegram | None | str:
    """Telegramm, "ack" für eine Quittung oder None (nicht auswertbar)."""
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    code, info = data[0], data[1]
    body = data[2 + info:]
    if code == _MSG_BUSMON:
        if len(body) == 1:
            return "ack" if body[0] == _ACK else None
        if len(body) < 7:
            return None
        ctrl = body[0]
        if ctrl & 0x80:                       # Standardrahmen
            src_hi, src_lo, dst_hi, dst_lo, npci = body[1:6]
            length, tpdu = npci & 0x0F, body[6:]
        else:                                 # erweiterter Rahmen
            npci = body[1]
            src_hi, src_lo, dst_hi, dst_lo, length = body[2:7]
            tpdu = body[7:]
        group = bool(npci & 0x80)
        repeat = not (ctrl & 0x20)
        tpdu = tpdu[:length + 1]
    elif code == _MSG_DATA_IND:
        if len(body) < 7:
            return None
        ctrl2 = body[1]
        src_hi, src_lo, dst_hi, dst_lo, length = body[2:7]
        group = bool(ctrl2 & 0x80)
        repeat = False
        tpdu = body[7:7 + length + 1]
    else:
        return None
    service, payload = _tpdu(tpdu)
    dst = _group(dst_hi << 8 | dst_lo) if group else _individual(dst_hi, dst_lo)
    return Telegram(time, _individual(src_hi, src_lo), dst, group, service, payload, repeat)


def _time(text: str) -> datetime | None:
    if not text:
        return None
    text = text.rstrip("Z")
    if "." in text:                           # .NET schreibt 7 Nachkommastellen
        head, frac = text.split(".", 1)
        text = f"{head}.{frac[:6]}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class Recording:
    file: str
    start: datetime | None
    stop: datetime | None
    connection: str = ""
    mode: str = ""
    telegrams: list[Telegram] = field(default_factory=list)
    acks: int = 0


def parse_log(path: str) -> Recording:
    """ETS-Mitschnitt (Bus- oder Gruppenmonitor) lesen."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise BusLogError(f"Datei nicht lesbar: {exc}") from exc
    if not root.tag.endswith("CommunicationLog"):
        raise BusLogError("Kein Mitschnitt aus dem Bus- oder Gruppenmonitor der ETS")
    start_el = root.find(f"{_NS}RecordStart")
    stop_el = root.find(f"{_NS}RecordStop")
    rec = Recording(
        file=os.path.basename(path),
        start=_time(start_el.get("Timestamp", "")) if start_el is not None else None,
        stop=_time(stop_el.get("Timestamp", "")) if stop_el is not None else None,
        connection=start_el.get("ConnectionName", "") if start_el is not None else "",
        mode=start_el.get("Mode", "") if start_el is not None else "")
    for el in root.iter(f"{_NS}Telegram"):
        when = _time(el.get("Timestamp", ""))
        result = decode(el.get("RawData", ""), when)
        if result == "ack":
            rec.acks += 1
        elif isinstance(result, Telegram):
            rec.telegrams.append(result)
    if not rec.telegrams:
        raise BusLogError("Der Mitschnitt enthält keine auswertbaren Telegramme")
    times = [t.time for t in rec.telegrams if t.time]
    rec.start = rec.start or min(times, default=None)
    rec.stop = rec.stop or max(times, default=None)
    return rec


def summarize(rec: Recording) -> dict:
    """Zusammenfassung zum Speichern im Projekt (project.bus_recordings)."""
    first = [t for t in rec.telegrams if not t.repeat]
    pairs: dict[tuple, dict] = {}
    for t in rec.telegrams:
        key = (t.src, t.dst, t.service)
        entry = pairs.setdefault(key, {"count": 0, "repeats": 0, "sample": t.payload})
        if t.repeat:
            entry["repeats"] += 1
        else:
            entry["count"] += 1
            entry["sample"] = t.payload
    per_second = Counter(t.time.replace(microsecond=0) for t in rec.telegrams if t.time)
    peak_time, peak = max(per_second.items(), key=lambda kv: kv[1], default=(None, 0))
    return {
        "file": rec.file,
        "imported": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "start": rec.start.isoformat() if rec.start else "",
        "stop": rec.stop.isoformat() if rec.stop else "",
        "connection": rec.connection,
        "mode": rec.mode,
        "frames": len(rec.telegrams),
        "telegrams": len(first),
        "repeats": len(rec.telegrams) - len(first),
        "acks": rec.acks,
        "peak_per_second": peak,
        "peak_time": peak_time.isoformat() if peak_time else "",
        "pairs": [[src, dst, service, v["count"], v["repeats"], v["sample"]]
                  for (src, dst, service), v in sorted(pairs.items())],
    }


# ── Auswertung gegen das Projekt ─────────────────────────────────────────

FREQUENT_SECONDS = 60      # ein Ziel öfter als einmal je Minute: auffällig
MIN_SILENT_HOURS = 1.0     # stille Geräte erst ab einer Stunde Mitschnitt


@dataclass
class SenderRow:
    address: str
    device: object | None
    telegrams: int
    repeats: int
    targets: int

    @property
    def known(self) -> bool:
        return self.device is not None


@dataclass
class PairRow:
    src: str
    dst: str
    service: str
    count: int
    repeats: int
    sample: str
    designation: str
    sender_linked: bool
    receivers: list[str]


@dataclass
class Finding:
    level: str              # "error", "warning", "info"
    title: str
    detail: str
    items: list[str] = field(default_factory=list)


@dataclass
class BusAnalysis:
    summary: dict
    duration_s: float
    senders: list[SenderRow]
    pairs: list[PairRow]
    unknown: list[SenderRow]
    external_gas: dict[str, list[str]]      # externes Gerät -> gesendete GAs
    unlinked: list[PairRow]                 # Sender in der ETS nicht mit der GA verknüpft
    repeated: list[PairRow]
    frequent: list[PairRow]
    missing_gas: list[PairRow]              # Ziel-GA fehlt im Projekt
    silent: list                            # Geräte ohne Telegramm (ab MIN_SILENT_HOURS)
    findings: list[Finding]

    @property
    def per_minute(self) -> float:
        return self.summary["telegrams"] / (self.duration_s / 60) if self.duration_s else 0.0


def _duration(summary: dict) -> float:
    try:
        start = datetime.fromisoformat(summary["start"])
        stop = datetime.fromisoformat(summary["stop"])
    except (KeyError, ValueError):
        return 0.0
    return max((stop - start).total_seconds(), 0.0)


def _fmt_duration(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    if seconds >= 60:
        return f"{seconds / 60:.0f} min"
    return f"{seconds:.0f} s"


def analyze(project, summary: dict) -> BusAnalysis:
    from .report_sorting import group_address_key, physical_address_key
    from .bus_current import is_consumer
    devices = {d.physical_address: d for a in project.topology.areas
               for l in a.lines for d in l.devices}
    gas = {g.address: g for g in project.group_addresses.all_addresses()}
    linked: dict[str, set[str]] = defaultdict(set)
    for d in devices.values():
        for co in d.communication_objects:
            for ga in co.connected_gas:
                linked[ga].add(d.physical_address)
    duration = _duration(summary)

    pairs = []
    for src, dst, service, count, repeats, sample in summary["pairs"]:
        group = "/" in dst
        ga = gas.get(dst) if group else None
        pairs.append(PairRow(
            src, dst, service, count, repeats, sample,
            " ".join((ga.designation or "").split()) if ga else "",
            sender_linked=src in linked.get(dst, set()),
            receivers=sorted(linked.get(dst, set()) - {src}, key=physical_address_key)))

    by_sender: dict[str, list[PairRow]] = defaultdict(list)
    for p in pairs:
        by_sender[p.src].append(p)
    senders = sorted(
        (SenderRow(src, devices.get(src), sum(p.count for p in rows),
                   sum(p.repeats for p in rows), len({p.dst for p in rows}))
         for src, rows in by_sender.items()),
        key=lambda s: (-s.telegrams, physical_address_key(s.address)))
    unknown = [s for s in senders if not s.known]

    group_pairs = [p for p in pairs if "/" in p.dst and p.service in ("Write", "Response")]
    external_gas = {
        s.address: sorted({p.dst for p in by_sender[s.address] if "/" in p.dst},
                          key=group_address_key)
        for s in senders if s.device is not None and s.device.external}
    unlinked = [p for p in group_pairs if p.src in devices and not p.sender_linked
                and p.dst in gas]
    repeated = sorted((p for p in pairs if p.repeats), key=lambda p: -p.repeats)
    frequent = sorted((p for p in group_pairs if duration and p.count >= 3
                       and duration / p.count < FREQUENT_SECONDS),
                      key=lambda p: -p.count)
    missing = [p for p in group_pairs if p.dst not in gas]
    silent = []
    if duration >= MIN_SILENT_HOURS * 3600:
        silent = sorted((d for d in devices.values()
                         if is_consumer(d) and not d.external
                         and d.device_type not in ("coupler",)
                         and d.physical_address not in by_sender),
                        key=lambda d: physical_address_key(d.physical_address))

    findings = _findings(summary, duration, senders, unknown, external_gas, unlinked,
                         repeated, frequent, missing, silent)
    return BusAnalysis(summary, duration, senders, pairs, unknown, external_gas, unlinked,
                       repeated, frequent, missing, silent, findings)


def _findings(summary, duration, senders, unknown, external_gas, unlinked, repeated,
              frequent, missing, silent) -> list[Finding]:
    found = []
    if unknown:
        found.append(Finding(
            "warning", f"{len(unknown)} Absender nicht im Projekt",
            "Diese Geräte senden, stehen aber nicht in der ETS. Als externes Gerät "
            "erfassen (z.B. Schnittstelle einer Visualisierung), damit sie bei Teilnehmern, "
            "Busstrom und Linienumbau zählen.",
            [f"{s.address}: {s.telegrams} Telegramm(e) auf {s.targets} Ziel(e)" for s in unknown]))
    for address, sent in external_gas.items():
        found.append(Finding(
            "info", f"Externes Gerät {address} sendet auf {len(sent)} GA(s)",
            "In der ETS mit keinem Gerät dieser Adresse verknüpft. Für Filtertabellen und "
            "Dokumentation einen Dummy mit diesen GAs verknüpfen.", sent))
    others = [p for p in unlinked if p.src not in external_gas]
    if others:
        found.append(Finding(
            "warning", f"{len(others)} Mal sendet ein Gerät auf eine GA, mit der es in der "
                       "ETS nicht verknüpft ist",
            "Projektstand und Anlage weichen ab, oder die Verknüpfung fehlt in der ETS.",
            [f"{p.src} → {p.dst} {p.designation}" for p in others]))
    rep_total = summary.get("repeats", 0)
    if rep_total:
        share = rep_total / summary["frames"] * 100 if summary.get("frames") else 0
        level = "warning" if share >= 10 else "info"
        found.append(Finding(
            level, f"{rep_total} Wiederholungen ({share:.0f} % der Rahmen)",
            "Ein Telegramm wird wiederholt, wenn am Messpunkt niemand quittiert. Ohne Empfänger "
            "auf dieser Linie ist das erklärlich; sonst Empfänger, Koppler und Verbindung "
            "prüfen. Wiederholungen erhöhen die Buslast.",
            [f"{p.src} → {p.dst} {p.designation}: {p.count}× gesendet, {p.repeats} Wiederholungen"
             + ("" if p.receivers else " – kein Empfänger in der ETS") for p in repeated[:30]]))
    peak = summary.get("peak_per_second", 0)
    if peak >= 20:
        found.append(Finding(
            "warning" if peak >= 35 else "info",
            f"Lastspitze {peak} Rahmen pro Sekunde",
            "Eine TP-Linie überträgt höchstens rund 40–50 kurze Telegramme pro Sekunde; in "
            "Spitzen können sich Telegramme verzögern.",
            [f"um {summary.get('peak_time', '')[11:19]}"]))
    if frequent:
        found.append(Finding(
            "info", f"{len(frequent)} GA(s) häufiger als einmal pro Minute",
            "Zyklisches Senden oder kleine Änderungsschwelle prüfen (Buslast).",
            [f"{p.src} → {p.dst} {p.designation}: {p.count}× in {_fmt_duration(duration)}"
             for p in frequent[:30]]))
    if missing:
        found.append(Finding(
            "warning", f"{len(missing)} Ziel-GA(s) fehlen im Projekt",
            "Auf diese Gruppenadressen wird gesendet, sie stehen aber nicht in der ETS.",
            [f"{p.src} → {p.dst}" for p in missing]))
    if duration >= MIN_SILENT_HOURS * 3600 and silent:
        found.append(Finding(
            "info", f"{len(silent)} Gerät(e) haben im Mitschnitt nicht gesendet",
            "Normal für Aktoren ohne Rückmeldung; bei Sensoren und Tastern kann es auf einen "
            "Defekt oder eine fehlende Busverbindung hinweisen.",
            [f"{d.physical_address} {d.product}" for d in silent]))
    elif duration < MIN_SILENT_HOURS * 3600:
        found.append(Finding(
            "info", f"Mitschnitt über {_fmt_duration(duration)}",
            "Für Aussagen über Geräte, die selten oder nie senden, einen Mitschnitt über "
            "mindestens eine Stunde, besser 24 Stunden aufnehmen."))
    return found
