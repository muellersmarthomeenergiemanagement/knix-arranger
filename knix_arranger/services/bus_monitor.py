"""
Busmonitor-Mitschnitt einlesen und gegen das Projekt auswerten (FA-640).

Die ETS speichert Mitschnitte aus Bus- und Gruppenmonitor als XML
(CommunicationLog, Namespace http://knx.org/xml/telegrams/01); jedes
Telegramm steht als cEMI-Rahmen in RawData:
- L_Busmon.ind (0x2B): der TP-Rahmen, wie er auf dem Bus lag, mit
  Wiederholungsbit und Quittungen (ACK, NAK, BUSY) als eigene Ein-Byte-Rahmen,
- L_Data.ind (0x29): der Gruppenmonitor, ohne Wiederholungen und Quittungen.

Die Quittung trägt keine Adresse; sie gehört zum unmittelbar vorangehenden
Datenrahmen (Zuordnung über die Reihenfolge im Mitschnitt). Quittiert wird
von jedem Empfänger auf der Linie des Messpunkts und vom Koppler, der das
Telegramm weiterleitet; überlagerte Quittungen ergeben die dominante
(NAK vor ACK, BUSY vor ACK, NAK+BUSY = 0x00).

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
# Dienste an Einzeladressen (Gerätezugriff, meist ETS) -- 4-Bit-APCI bzw.
# bei 0x2C0/0x3C0 die vollen 10 Bit
MANAGEMENT_SERVICES = {
    0x0C0: "Adresse schreiben", 0x100: "Adresse lesen", 0x140: "Adresse Antwort",
    0x180: "ADC lesen", 0x1C0: "ADC Antwort",
    0x200: "Speicher lesen", 0x240: "Speicher Antwort", 0x280: "Speicher schreiben",
    0x2C0: "Benutzerspeicher lesen", 0x2C1: "Benutzerspeicher Antwort",
    0x2C2: "Benutzerspeicher schreiben", 0x2C5: "Herstellerinfo lesen",
    0x2C6: "Herstellerinfo Antwort", 0x2C7: "Funktionseigenschaft",
    0x300: "Gerätebeschreibung lesen", 0x340: "Gerätebeschreibung Antwort", 0x380: "Neustart",
    0x3C0: "Erweiterter Dienst",
    0x3D1: "Autorisieren", 0x3D2: "Autorisieren Antwort", 0x3D3: "Schlüssel schreiben",
    0x3D4: "Schlüssel Antwort", 0x3D5: "Eigenschaft lesen", 0x3D6: "Eigenschaft Antwort",
    0x3D7: "Eigenschaft schreiben", 0x3D8: "Eigenschaftsbeschreibung lesen",
    0x3D9: "Eigenschaftsbeschreibung Antwort", 0x3DC: "Adresse über Seriennummer lesen",
    0x3DD: "Adresse über Seriennummer Antwort", 0x3DE: "Adresse über Seriennummer schreiben",
}
_CONTROL = {0x80: "Verbindung aufbauen", 0x81: "Verbindung trennen"}
INVALID = "invalid"         # decode(): Rahmen mit falscher Prüfsumme oder Länge


def _checksum(data: bytes) -> int:
    value = 0
    for b in data:
        value ^= b
    return ~value & 0xFF


def service_label(service: str) -> str:
    """Gespeicherte Dienstbezeichnung lesbar ("APCI 200" älterer Mitschnitte
    -> "Speicher lesen", "Steuerung" -> "Verbindung")."""
    if service.startswith("APCI "):
        try:
            code = int(service[5:], 16)
        except ValueError:
            return service
        return MANAGEMENT_SERVICES.get(code, service)
    if service == "Steuerung":
        return "Verbindung"
    return service


def is_management(service: str) -> bool:
    """Dienst eines Gerätezugriffs (nicht Gruppenkommunikation)."""
    return service not in ("Read", "Response", "Write")
_MSG_BUSMON, _MSG_DATA_IND = 0x2B, 0x29
_ACKS = {0xCC: "ack", 0x0C: "nak", 0xC0: "busy", 0x00: "nak_busy"}

# Belegung der TP-Leitung (9600 bit/s): je Zeichen 11 Bit plus 2 Bit Pause,
# vor jedem Rahmen 50 Bit Ruhe, die Quittung nach 15 Bit Pause
TP_BITS_PER_SECOND = 9600
_FRAME_GAP_BITS, _CHAR_BITS, _ACK_BITS = 50, 13, 15 + 11


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
    ack: str = ""           # Quittung danach: ack, nak, busy, nak_busy; "" keine
    size: int = -1          # Datenlänge: 0 = bis 6 Bit im APCI-Byte, sonst Byte; -1 keine
    hops: int = -1          # Routing-Zähler beim Messpunkt (6 = auf dieser Linie gesendet)
    octets: int = 0         # Länge des Rahmens auf dem Bus (Busbelegung)


def _group(value: int) -> str:
    return f"{value >> 11}/{(value >> 8) & 7}/{value & 0xFF}"


def _individual(hi: int, lo: int) -> str:
    return f"{hi >> 4}.{hi & 15}.{lo}"


def _tpdu(tpdu: bytes) -> tuple[str, str, int]:
    """(Dienst, Daten, Datenlänge) aus TPCI/APCI und Daten; Länge 0 = Wert
    im APCI-Byte (bis 6 Bit), -1 = ohne Daten."""
    if len(tpdu) < 2:
        control = tpdu[0] if tpdu else 0
        if control in _CONTROL:
            return _CONTROL[control], "", -1
        if control & 0xC3 == 0xC2:
            return "Verbindung bestätigen", "", -1
        if control & 0xC3 == 0xC3:
            return "Verbindung ablehnen", "", -1
        return "Verbindung", "", -1
    full = (tpdu[0] & 0x03) << 8 | tpdu[1]
    apci = full & 0x3C0
    service = (_SERVICES.get(apci) or MANAGEMENT_SERVICES.get(full)
               or MANAGEMENT_SERVICES.get(apci) or f"APCI {full:03X}")
    if len(tpdu) == 2:
        if service == "Read":
            return service, "", -1
        return service, f"{tpdu[1] & 0x3F:X}", 0
    return service, tpdu[2:].hex().upper(), len(tpdu) - 2


def decode(raw: str, time: datetime) -> Telegram | None | str:
    """Telegramm, Quittung ("ack", "nak", "busy", "nak_busy"), INVALID
    (Busmonitor-Rahmen mit falscher Prüfsumme oder Länge) oder None
    (nicht auswertbar)."""
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
            return _ACKS.get(body[0])
        if len(body) < 7:
            return None
        ctrl = body[0]
        if ctrl & 0x80:                       # Standardrahmen
            src_hi, src_lo, dst_hi, dst_lo, npci = body[1:6]
            length, tpdu = npci & 0x0F, body[6:]
            expected = length + 8             # Kopf 6, TPDU length+1, Prüfsumme 1
        else:                                 # erweiterter Rahmen
            npci = body[1]
            src_hi, src_lo, dst_hi, dst_lo, length = body[2:7]
            tpdu = body[7:]
            expected = length + 9
        # Der TP-Rahmen endet mit der Prüfsumme (bitweise invertiertes XOR aller
        # Bytes). Falsche Prüfsumme oder Länge: gestörter Rahmen bzw. Artefakt
        # der Schnittstelle (Chalet über ise-Fernzugang: KNXnet/IP-Kopf
        # 06 10 04 20 ... als «Quelle 0.6.16, Ziel 0.4.32»)
        if len(body) != expected or _checksum(body[:-1]) != body[-1]:
            return INVALID
        group = bool(npci & 0x80)
        hops = (npci >> 4) & 0x07
        repeat = not (ctrl & 0x20)
        tpdu = tpdu[:length + 1]
        octets = len(body)
    elif code == _MSG_DATA_IND:
        if len(body) < 7:
            return None
        ctrl2 = body[1]
        src_hi, src_lo, dst_hi, dst_lo, length = body[2:7]
        group = bool(ctrl2 & 0x80)
        hops = (ctrl2 >> 4) & 0x07
        repeat = False
        tpdu = body[7:7 + length + 1]
        octets = length + 8                   # TP-Rahmen: 7 Byte Kopf + TPDU + Prüfsumme
    else:
        return None
    service, payload, size = _tpdu(tpdu)
    dst = _group(dst_hi << 8 | dst_lo) if group else _individual(dst_hi, dst_lo)
    return Telegram(time, _individual(src_hi, src_lo), dst, group, service, payload, repeat,
                    size=size, hops=hops, octets=octets)


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
    naks: int = 0
    busys: int = 0
    busmon: bool = False    # Busmonitor: Quittungen sind im Mitschnitt enthalten
    invalid: int = 0        # Rahmen mit falscher Prüfsumme oder Länge
    invalid_samples: list = field(default_factory=list)   # [Zeit, RawData] der ersten
    # je Minute: [Rahmen, belegte Bit] (Busbelegung)
    load: dict = field(default_factory=lambda: defaultdict(lambda: [0, 0]))


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
    waiting: Telegram | None = None           # Datenrahmen, der auf die Quittung wartet
    for el in root.iter(f"{_NS}Telegram"):
        raw = el.get("RawData", "")
        when = _time(el.get("Timestamp", ""))
        result = decode(raw, when)
        minute = when.replace(second=0, microsecond=0) if when else None
        if result == INVALID:
            rec.invalid += 1
            if len(rec.invalid_samples) < 10:
                rec.invalid_samples.append([when.isoformat(timespec="seconds") if when else "",
                                            raw])
            waiting = None
            continue
        if isinstance(result, str):
            rec.acks += result == "ack"
            rec.naks += result in ("nak", "nak_busy")
            rec.busys += result in ("busy", "nak_busy")
            if waiting is not None:
                waiting.ack = result
            waiting = None
            if minute:
                rec.load[minute][1] += _ACK_BITS
        elif isinstance(result, Telegram):
            rec.telegrams.append(result)
            if minute:
                rec.load[minute][0] += 1
                rec.load[minute][1] += _FRAME_GAP_BITS + result.octets * _CHAR_BITS
            busmon = raw[:2].upper() == "2B"
            rec.busmon = rec.busmon or busmon
            waiting = result if busmon else None
        else:
            waiting = None
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
        entry = pairs.setdefault(key, {"count": 0, "repeats": 0, "sample": t.payload,
                                       "ack": Counter(), "sizes": set(), "hops": set()})
        entry["ack"][t.ack] += 1
        if t.size >= 0:
            entry["sizes"].add(t.size)
        if not t.repeat and t.hops >= 0:
            entry["hops"].add(t.hops)
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
        "naks": rec.naks,
        "busys": rec.busys,
        "ack_known": rec.busmon,
        "invalid": rec.invalid,
        "invalid_samples": rec.invalid_samples,
        "unacked": sum(1 for t in rec.telegrams if not t.ack) if rec.busmon else 0,
        "peak_per_second": peak,
        "peak_time": peak_time.isoformat() if peak_time else "",
        # Busbelegung je Minute: [Minute, Rahmen, belegte Bit]
        "minutes": [[m.isoformat(timespec="minutes"), n, bits]
                    for m, (n, bits) in sorted(rec.load.items())],
        # je Paar: ..., Quittungen über alle Rahmen [ACK, NAK, BUSY, keine],
        # Datenlängen (0 = bis 6 Bit) und Routing-Zähler der Erstsendungen
        "pairs": [[src, dst, service, v["count"], v["repeats"], v["sample"],
                   _ack_counts(v["ack"]) if rec.busmon else None,
                   {"sizes": sorted(v["sizes"]), "hops": sorted(v["hops"])}]
                  for (src, dst, service), v in sorted(pairs.items())],
    }


def ack_summary(summary: dict) -> str:
    """Quittungen eines Mitschnitts für Kopfzeile und Bericht."""
    if not summary.get("ack_known", summary.get("acks", 0) > 0):
        return "Quittungen nicht im Mitschnitt"
    text = f"{summary.get('acks', 0)} Quittungen"
    if summary.get("naks"):
        text += f", NAK {summary['naks']}"
    if summary.get("busys"):
        text += f", BUSY {summary['busys']}"
    if summary.get("unacked"):
        text += f", {summary['unacked']} Rahmen ohne Quittung"
    return text


def _ack_counts(counter: Counter) -> list[int]:
    return [counter["ack"], counter["nak"] + counter["nak_busy"],
            counter["busy"] + counter["nak_busy"], counter[""]]


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
    via: str = ""           # Zusatzadresse des Geräts, z.B. "Tunneling 2"

    @property
    def name(self) -> str:
        """Anzeige: Produkt, bei Zusatzadressen «Tunneling 2 von 1.1.70 Produkt»."""
        if self.device is None:
            return "nicht im Projekt"
        name = self.device.product or "Gerät"
        if self.via:
            name = f"{self.via} von {self.device.physical_address} {name}"
        return name + (" (nicht im ETS-Projekt)" if self.device.external else "")

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
    acks: list[int] | None = None   # [ACK, NAK, BUSY, keine]; None: nicht im Mitschnitt
    sizes: list[int] | None = None  # Datenlängen (0 = bis 6 Bit); None: ältere Mitschnitte
    hops: list[int] | None = None   # Routing-Zähler der Erstsendungen
    dpt: str = ""                   # DPT der Ziel-GA
    value: str = ""                 # letzter Wert, nach DPT lesbar (sonst Hex)

    @property
    def frames(self) -> int:
        return self.count + self.repeats

    @property
    def unacked(self) -> bool:
        """Kein Rahmen quittiert (weder ACK noch NAK/BUSY) und der Sender hat
        wiederholt -- erst die Wiederholung belegt, dass auf dem Bus niemand
        quittiert hat; sonst hat nur die Schnittstelle die Quittung nicht
        weitergegeben."""
        return self.acks is not None and self.acks[3] == self.frames and self.repeats > 0

    @property
    def missed(self) -> int:
        """Rahmen ohne aufgezeichnete Quittung, obwohl der Sender nicht wiederholt hat."""
        return self.acks[3] if self.acks is not None and not self.repeats else 0

    @property
    def ack_text(self) -> str:
        if self.acks is None:
            return "–"
        ack, nak, busy, _none = self.acks
        if self.unacked:
            return "keine"
        text = "alle" if ack == self.frames else f"{ack} von {self.frames}"
        return text + (f", NAK {nak}" if nak else "") + (f", BUSY {busy}" if busy else "")


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
    unacked: list[PairRow]                  # kein Rahmen quittiert (nur Busmonitor)
    disturbed: list[PairRow]                # mit NAK oder BUSY
    frequent: list[PairRow]
    missing_gas: list[PairRow]              # Ziel-GA fehlt im Projekt
    silent: list                            # Geräte ohne Telegramm (ab MIN_SILENT_HOURS)
    findings: list[Finding]
    # bus_checks (FA-640c ff.)
    size_issues: list = field(default_factory=list)
    unanswered: list = field(default_factory=list)
    multi_response: list = field(default_factory=list)
    multi_senders: list = field(default_factory=list)
    measuring_line: str = ""
    forwarded: list = field(default_factory=list)
    hop_issues: list = field(default_factory=list)
    load: list = field(default_factory=list)

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
    # Zusatzadressen (Tunneling) -> Gerät; eine echte Geräteadresse geht vor
    owners = {x: d for d in devices.values() for x in d.additional_addresses
              if x not in devices}
    gas = {g.address: g for g in project.group_addresses.all_addresses()}
    linked: dict[str, set[str]] = defaultdict(set)
    for d in devices.values():
        for co in d.communication_objects:
            for ga in co.connected_gas:
                linked[ga].add(d.physical_address)
    duration = _duration(summary)

    pairs = []
    # Quittungen nur, wenn der Busmonitor überhaupt welche aufgezeichnet hat
    ack_known = bool(summary.get("ack_known")) and summary.get("acks", 0) > 0
    from .dpt_values import decode_value
    for src, dst, service, count, repeats, sample, *rest in summary["pairs"]:
        service = service_label(service)
        group = "/" in dst
        ga = gas.get(dst) if group else None
        extra = rest[1] if len(rest) > 1 and isinstance(rest[1], dict) else {}
        sizes = extra.get("sizes")
        dpt = ga.datapoint_type if ga else ""
        size = sizes[-1] if sizes else None
        pairs.append(PairRow(
            src, dst, service, count, repeats, sample,
            " ".join((ga.designation or "").split()) if ga else "",
            sender_linked=src in linked.get(dst, set()),
            receivers=sorted(linked.get(dst, set()) - {src}, key=physical_address_key),
            acks=list(rest[0]) if rest and rest[0] is not None and ack_known else None,
            sizes=sizes, hops=extra.get("hops"), dpt=dpt,
            value=decode_value(dpt, sample, size) if dpt and sample else sample))

    by_sender: dict[str, list[PairRow]] = defaultdict(list)
    for p in pairs:
        by_sender[p.src].append(p)
    senders = sorted(
        (SenderRow(src, devices.get(src) or owners.get(src), sum(p.count for p in rows),
                   sum(p.repeats for p in rows), len({p.dst for p in rows}),
                   owners[src].additional_label(src) if src in owners else "")
         for src, rows in by_sender.items()),
        key=lambda s: (-s.telegrams, physical_address_key(s.address)))
    unknown = [s for s in senders if not s.known]

    group_pairs = [p for p in pairs if "/" in p.dst and p.service in ("Write", "Response")]
    external_gas = {
        s.address: sorted({p.dst for p in by_sender[s.address] if "/" in p.dst},
                          key=group_address_key)
        for s in senders if s.device is not None and s.device.external and not s.via}
    unlinked = [p for p in group_pairs if p.src in devices and not p.sender_linked
                and p.dst in gas]
    repeated = sorted((p for p in pairs if p.repeats), key=lambda p: -p.repeats)
    unacked = sorted((p for p in pairs if p.unacked), key=lambda p: -p.frames)
    disturbed = sorted((p for p in pairs if p.acks and (p.acks[1] or p.acks[2])),
                       key=lambda p: -(p.acks[1] + p.acks[2]))
    frequent = sorted((p for p in group_pairs if duration and p.count >= 3
                       and duration / p.count < FREQUENT_SECONDS),
                      key=lambda p: -p.count)
    missing = [p for p in group_pairs if p.dst not in gas]
    silent = []
    active = set(by_sender) | {owners[x].physical_address for x in by_sender if x in owners}
    if duration >= MIN_SILENT_HOURS * 3600:
        silent = sorted((d for d in devices.values()
                         if is_consumer(d) and not d.external
                         and d.device_type not in ("coupler",)
                         and d.physical_address not in active),
                        key=lambda d: physical_address_key(d.physical_address))

    findings = _findings(summary, duration, senders, unknown, external_gas, unlinked,
                         repeated, frequent, missing, silent, unacked, disturbed,
                         sum(p.missed for p in pairs))
    result = BusAnalysis(summary, duration, senders, pairs, unknown, external_gas, unlinked,
                         repeated, unacked, disturbed, frequent, missing, silent, findings)
    _extend(result, gas, devices)
    return result


def _extend(a: BusAnalysis, gas: dict, devices: dict) -> None:
    """Weitere Auswertungen (services/bus_checks) und ihre Befunde."""
    from . import bus_checks as bc
    a.size_issues = bc.size_issues(a.pairs, gas)
    a.unanswered, a.multi_response = bc.read_issues(a.pairs, gas, devices)
    a.multi_senders = bc.multi_senders(a.pairs, gas)
    a.measuring_line = bc.measuring_line(a.pairs)
    a.forwarded = bc.forwarded_without_receiver(a.pairs, gas, devices, a.measuring_line)
    a.hop_issues = bc.hop_issues(a.pairs)
    a.load = bc.load_series(a.summary)
    extra = bc.findings(a, Finding)
    # Fehler zuerst, der Hinweis zur Mitschnittdauer bleibt am Schluss
    tail = [f for f in a.findings if f.title.startswith("Mitschnitt über")]
    body = [f for f in a.findings if f not in tail]
    order = {"error": 0, "warning": 1, "info": 2}
    a.findings[:] = sorted(body + extra, key=lambda f: order[f.level]) + tail


def _findings(summary, duration, senders, unknown, external_gas, unlinked, repeated,
              frequent, missing, silent, unacked=(), disturbed=(), missed=0) -> list[Finding]:
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
             + ("" if p.receivers else " – kein Empfänger in der ETS")
             + (" – keine Quittung" if p.unacked else "") for p in repeated[:30]]))
    found.extend(_ack_findings(summary, unacked, disturbed, missed))
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


def _ack_findings(summary, unacked, disturbed, missed=0) -> list[Finding]:
    """Befunde aus den Quittungen (nur Busmonitor-Mitschnitte)."""
    found = []
    if summary.get("ack_known") and summary.get("frames") and not summary.get("acks"):
        found.append(Finding(
            "info", "Keine Quittungen im Mitschnitt",
            "Der Busmonitor hat keine einzige Quittung aufgezeichnet. Manche Schnittstellen "
            "liefern sie nicht; die Auswertung der Quittungen entfällt."))
        return found
    naks = summary.get("naks", 0)
    if naks:
        found.append(Finding(
            "warning", f"{naks} Mal NAK (Telegramm gestört empfangen)",
            "Ein Empfänger hat den Rahmen fehlerhaft empfangen; der Sender wiederholt. "
            "Hinweis auf Störungen auf der Linie: Leitungslänge, Abstand zur "
            "Spannungsversorgung, Busspannung, Fremdspannung oder Schirmung prüfen.",
            [f"{p.src} → {p.dst} {p.designation}: {p.acks[1]}× NAK bei {p.frames} Rahmen"
             for p in disturbed if p.acks[1]][:30]))
    busys = summary.get("busys", 0)
    if busys:
        found.append(Finding(
            "warning", f"{busys} Mal BUSY (Empfänger ausgelastet)",
            "Ein Empfänger oder Koppler konnte das Telegramm nicht annehmen (Puffer voll). "
            "Tritt bei Lastspitzen auf; Buslast senken (zyklisches Senden, "
            "Änderungsschwellen), Koppler und Filtertabellen prüfen.",
            [f"{p.src} → {p.dst} {p.designation}: {p.acks[2]}× BUSY bei {p.frames} Rahmen"
             for p in disturbed if p.acks[2]][:30]))
    with_receivers = [p for p in unacked if p.receivers]
    if with_receivers:
        found.append(Finding(
            "warning", f"{len(with_receivers)} Ziel(e) mit Empfänger in der ETS, aber ohne "
                       "Quittung",
            "Am Messpunkt quittiert jeder Empfänger der Linie und der Koppler, der das "
            "Telegramm weiterleitet. Bleibt die Quittung aus, obwohl die ETS Empfänger kennt: "
            "Empfänger ohne Busverbindung oder nicht programmiert, Filtertabelle des Kopplers "
            "nicht geladen oder Koppler sperrt die Hauptgruppe.",
            [f"{p.src} → {p.dst} {p.designation}: {p.frames} Rahmen ohne Quittung, "
             f"Empfänger {', '.join(p.receivers[:5])}" for p in with_receivers[:30]]))
    # Ziele ohne Empfänger und ohne Quittung stehen schon bei den Wiederholungen
    if missed:
        found.append(Finding(
            "info", f"{missed} Rahmen ohne aufgezeichnete Quittung, aber ohne Wiederholung",
            "Der Sender hat nicht wiederholt, die Quittung lag also auf dem Bus; die "
            "Schnittstelle hat sie nicht weitergegeben (häufig über Tunneling oder "
            "Fernzugang). Diese Rahmen gelten nicht als Befund; für eine lückenlose "
            "Aufzeichnung der Quittungen eine Schnittstelle direkt an der Linie verwenden."))
    return found


# ── Filter für Ansicht und Bericht ───────────────────────────────────────

PAIR_FILTERS = [
    ("all", "Alle Telegramme"),
    ("notable", "Alle Auffälligkeiten"),
    ("repeated", "Wiederholungen"),
    ("unacked", "Ohne Quittung"),
    ("disturbed", "NAK / BUSY"),
    ("unknown", "Absender nicht im Projekt"),
    ("unlinked", "Sender in der ETS nicht verknüpft"),
    ("missing", "Ziel-GA fehlt im Projekt"),
    ("frequent", "Häufiger als einmal pro Minute"),
    ("size", "Datenlänge passt nicht zum DPT"),
    ("read", "Lesen ohne Antwort / mehrere Antworten"),
    ("multi", "Mehrere Sender auf eine GA"),
    ("forwarded", "Weitergeleitet ohne Empfänger"),
    ("hops", "Routing-Zähler 7 oder 0"),
    ("management", "Gerätezugriff (ETS, Einzeladressen)"),
]


def pair_flags(a: BusAnalysis) -> dict[int, set[str]]:
    """Auffälligkeiten je Paar (Schlüssel id(PairRow)) für den Filter."""
    groups = {"repeated": a.repeated, "unacked": a.unacked, "disturbed": a.disturbed,
              "unlinked": a.unlinked, "missing": a.missing_gas, "frequent": a.frequent}
    unknown = {s.address for s in a.unknown}
    flags: dict[int, set[str]] = {id(p): set() for p in a.pairs}
    for key, rows in groups.items():
        for p in rows:
            flags[id(p)].add(key)
    for p in a.pairs:
        if p.src in unknown:
            flags[id(p)].add("unknown")
    for issue in a.size_issues:
        flags[id(issue.pair)].add("size")
    for p in a.pairs:
        if "/" not in p.dst and is_management(p.service):
            flags[id(p)].add("management")
    for key, rows in (("forwarded", a.forwarded), ("hops", a.hop_issues)):
        for p in rows:
            flags[id(p)].add(key)
    read_gas = {i.ga for i in a.unanswered + a.multi_response}
    multi = {m.ga: set(m.senders) for m in a.multi_senders}
    for p in a.pairs:
        if p.dst in read_gas and p.service in ("Read", "Response"):
            flags[id(p)].add("read")
        if p.service == "Write" and p.src in multi.get(p.dst, ()):
            flags[id(p)].add("multi")
    return flags


def pair_matches(flags: set[str], category: str) -> bool:
    if category == "all":
        return True
    if category == "notable":
        return bool(flags)
    return category in flags


def line_of(address: str) -> str:
    """Linie einer physikalischen Adresse ("1.2.7" -> "1.2")."""
    return address.rsplit(".", 1)[0] if address.count(".") == 2 else ""


def text_matches(query: str, cells) -> bool:
    """Suchbegriffe (durch Leerzeichen getrennt) müssen alle vorkommen.
    Adressen ("1.1.200", "1/5", "1.2") passen nur auf ganze Adressen oder
    deren Anfang bis zum Trennzeichen -- "1/5/1" findet nicht "1/5/10";
    Text passt als Teilstück, ohne Gross-/Kleinschreibung."""
    tokens = [t for t in query.replace("→", " ").split() if t]
    if not tokens:
        return True
    cells = [str(c) for c in cells if c not in (None, "")]
    lowered = " ".join(cells).lower()
    words = [w.strip(",") for c in cells for w in c.split()]
    for token in tokens:
        sep = "/" if "/" in token else "." if token.replace(".", "").isdigit() and "." in token \
            else ""
        if sep:
            if not any(w == token or w.startswith(token + sep) for w in words):
                return False
        elif token.lower() not in lowered:
            return False
    return True
