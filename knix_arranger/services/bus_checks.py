"""
Weitere Auswertungen der Busanalyse (FA-640c ff.), ergänzend zu
services/bus_monitor.analyze:

- Datenlänge gegen den DPT der GA (FA-640c), Wert lesbar (dpt_values)
- Leseanfragen ohne Antwort, mehrere Antwortende gegen die L-Flags (FA-640d)
- mehrere Sender auf eine GA (FA-640e)
- Messpunkt aus dem Routing-Zähler, Koppler leitet ohne Empfänger auf der
  Linie weiter, Routing-Zähler 7 bzw. 0 (FA-640f)
- Busbelegung je Minute (FA-640g)
- Vergleich zweier Mitschnitte (FA-640h)

Alles arbeitet auf der gespeicherten Zusammenfassung; Mitschnitte älterer
Versionen ohne Datenlänge, Routing-Zähler oder Minuten werden für diese
Punkte übersprungen.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .dpt_values import expected_size, size_text

LOCAL_HOPS = 6              # Routing-Zähler beim Senden; 6 am Messpunkt = gleiche Linie
LOAD_HINT, LOAD_WARN = 30, 50   # Busbelegung einer Minute in %
_MEASUREMENT_DPTS = {7, 8, 9, 12, 13, 14}


def _line(address: str) -> str:
    return address.rsplit(".", 1)[0] if address.count(".") == 2 else ""


def _flags(co) -> frozenset:
    from .ko_links import parse_flags
    return parse_flags(getattr(co, "flags", "") or "")


def _addr_key(text: str):
    try:
        return tuple(int(x) for x in text.replace("/", ".").split("."))
    except ValueError:
        return (999,)


# ── Datenlänge gegen DPT ────────────────────────────────────────────────

@dataclass
class SizeIssue:
    pair: object
    dpt: str
    expected: int
    found: list[int]

    @property
    def text(self) -> str:
        p = self.pair
        found = ", ".join(size_text(s) for s in self.found)
        return (f"{p.src} → {p.dst} {p.designation}: {found} gesendet, "
                f"DPT {self.dpt} erwartet {size_text(self.expected)}")


def size_issues(pairs, gas) -> list[SizeIssue]:
    found = []
    for p in pairs:
        ga = gas.get(p.dst)
        if ga is None or not p.sizes or p.service not in ("Write", "Response"):
            continue
        expected = expected_size(ga.datapoint_type)
        if expected is None:
            continue
        wrong = [s for s in p.sizes if s != expected]
        if wrong:
            found.append(SizeIssue(p, ga.datapoint_type, expected, wrong))
    return found


# ── Lesen und Antworten ─────────────────────────────────────────────────

@dataclass
class ReadIssue:
    ga: str
    designation: str
    readers: list[str]          # wer gelesen hat
    responders: list[str]       # wer geantwortet hat (im Mitschnitt)
    read_flags: list[str]       # Geräte mit L-Flag an einem KO dieser GA (ETS)

    @property
    def text(self) -> str:
        flags = ", ".join(self.read_flags) or "keines"
        if self.responders:
            return (f"{self.ga} {self.designation}: Antwort von {', '.join(self.responders)}"
                    f"; L-Flag in der ETS: {flags}")
        return (f"{self.ga} {self.designation}: gelesen von {', '.join(self.readers)}, "
                f"keine Antwort; L-Flag in der ETS: {flags}")


def read_issues(pairs, gas, devices) -> tuple[list[ReadIssue], list[ReadIssue]]:
    """(Leseanfragen ohne Antwort, GAs mit mehreren Antwortenden)."""
    read_flags: dict[str, set[str]] = defaultdict(set)
    for d in devices.values():
        for co in d.communication_objects:
            if "L" in _flags(co):
                for ga in co.connected_gas:
                    read_flags[ga].add(d.physical_address)
    readers: dict[str, set[str]] = defaultdict(set)
    responders: dict[str, set[str]] = defaultdict(set)
    for p in pairs:
        if "/" not in p.dst:
            continue
        if p.service == "Read":
            readers[p.dst].add(p.src)
        elif p.service == "Response":
            responders[p.dst].add(p.src)

    def issue(ga_address: str) -> ReadIssue:
        ga = gas.get(ga_address)
        return ReadIssue(
            ga_address, " ".join((ga.designation or "").split()) if ga else "",
            sorted(readers[ga_address], key=_addr_key),
            sorted(responders[ga_address], key=_addr_key),
            sorted(read_flags.get(ga_address, set()), key=_addr_key))

    unanswered = [issue(ga) for ga in sorted(readers, key=_addr_key) if not responders[ga]]
    multiple = [issue(ga) for ga in sorted(readers, key=_addr_key) if len(responders[ga]) > 1]
    return unanswered, multiple


# ── Mehrere Sender ──────────────────────────────────────────────────────

@dataclass
class MultiSender:
    ga: str
    designation: str
    senders: list[str]
    critical: bool              # Rückmeldung oder Messwert: nur ein Sender sinnvoll
    reason: str

    @property
    def text(self) -> str:
        return (f"{self.ga} {self.designation}: {', '.join(self.senders)}"
                + (f" ({self.reason})" if self.reason else ""))


def multi_senders(pairs, gas) -> list[MultiSender]:
    from .dpt_values import dpt_parts
    from .ko_plausibility import is_feedback_function
    senders: dict[str, set[str]] = defaultdict(set)
    for p in pairs:
        if "/" in p.dst and p.service == "Write":
            senders[p.dst].add(p.src)
    found = []
    for address, srcs in senders.items():
        if len(srcs) < 2:
            continue
        ga = gas.get(address)
        designation = " ".join((ga.designation or "").split()) if ga else ""
        reason = ""
        if ga is not None:
            if is_feedback_function(ga.function_name) or is_feedback_function(
                    designation.split("_", 1)[-1]):
                reason = "Rückmeldung"
            elif dpt_parts(ga.datapoint_type)[0] in _MEASUREMENT_DPTS:
                reason = "Messwert"
        found.append(MultiSender(address, designation, sorted(srcs, key=_addr_key),
                                 bool(reason), reason))
    return sorted(found, key=lambda m: (not m.critical, _addr_key(m.ga)))


# ── Messpunkt, Koppler, Routing-Zähler ──────────────────────────────────

def measuring_line(pairs) -> str:
    """Linie der Schnittstelle: dort gesendete Telegramme kommen mit dem
    unverminderten Routing-Zähler 6 an."""
    local = Counter()
    for p in pairs:
        if p.hops and LOCAL_HOPS in p.hops:
            local[_line(p.src)] += p.count
    return local.most_common(1)[0][0] if local else ""


def forwarded_without_receiver(pairs, gas, devices, line: str) -> list:
    """Gruppentelegramme, die ein Koppler in die Linie des Messpunkts
    weitergeleitet hat (Routing-Zähler < 6), obwohl dort kein Gerät die GA
    verknüpft hat. Nicht für Haupt- und Bereichslinien (x.0) und GAs mit
    Durchgang (unfiltered)."""
    if not line or line.endswith(".0"):
        return []
    on_line: dict[str, set[str]] = defaultdict(set)
    for d in devices.values():
        if _line(d.physical_address) != line:
            continue
        for co in d.communication_objects:
            for ga in co.connected_gas:
                on_line[ga].add(d.physical_address)
    found = []
    for p in pairs:
        if "/" not in p.dst or not p.hops or max(p.hops) >= LOCAL_HOPS:
            continue
        ga = gas.get(p.dst)
        if ga is not None and str(ga.unfiltered).lower() in ("true", "1", "ja"):
            continue
        if not on_line.get(p.dst):
            found.append(p)
    return found


def hop_issues(pairs) -> list:
    """Routing-Zähler 7 (wird nie vermindert, Schleifen möglich) oder 0
    (Telegramm ist durch viele Koppler gelaufen)."""
    return [p for p in pairs if p.hops and (7 in p.hops or 0 in p.hops)]


# ── Busbelegung ─────────────────────────────────────────────────────────

@dataclass
class LoadPoint:
    minute: str                 # "2026-11-05T08:42"
    frames: int
    percent: float


def load_series(summary: dict) -> list[LoadPoint]:
    from .bus_monitor import TP_BITS_PER_SECOND
    return [LoadPoint(m, n, bits / (TP_BITS_PER_SECOND * 60) * 100)
            for m, n, bits in summary.get("minutes", [])]


def load_buckets(points: list[LoadPoint], max_bars: int = 240) -> list[LoadPoint]:
    """Für Diagramme zusammenfassen: je Balken mehrere Minuten, Höchstwert."""
    if len(points) <= max_bars:
        return points
    step = -(-len(points) // max_bars)
    out = []
    for i in range(0, len(points), step):
        chunk = points[i:i + step]
        top = max(chunk, key=lambda p: p.percent)
        out.append(LoadPoint(chunk[0].minute, sum(p.frames for p in chunk), top.percent))
    return out


# ── Befunde ─────────────────────────────────────────────────────────────

def findings(a, Finding) -> list:
    """Zusätzliche Befunde zu einer BusAnalysis (Klasse Finding übergeben,
    um Kreisimporte zu vermeiden)."""
    found = []
    if a.size_issues:
        found.append(Finding(
            "error", f"{len(a.size_issues)} Mal passt die Datenlänge nicht zum DPT der GA",
            "Der Sender schreibt einen anderen Datentyp, als die GA in der ETS trägt; "
            "Empfänger mit dem richtigen Typ verwerfen das Telegramm oder lesen einen "
            "falschen Wert. KO des Senders und DPT der GA prüfen.",
            [i.text for i in a.size_issues[:30]]))
    if a.unanswered:
        found.append(Finding(
            "warning", f"{len(a.unanswered)} Leseanfrage(n) ohne Antwort",
            "Auf diese GAs wird gelesen, im Mitschnitt antwortet niemand. Ohne L-Flag in der "
            "ETS fehlt es an einem KO (beim Sender des Status setzen); mit L-Flag antwortet "
            "das Gerät nicht (nicht programmiert, nicht am Bus, Koppler filtert).",
            [i.text for i in a.unanswered[:30]]))
    if a.multi_response:
        found.append(Finding(
            "warning", f"{len(a.multi_response)} GA(s) mit mehreren Antwortenden",
            "Auf eine Leseanfrage antworten mehrere Geräte, womöglich mit verschiedenen "
            "Werten. Das L-Flag nur an einem KO je GA setzen (beim Gerät mit dem gültigen "
            "Zustand).",
            [i.text for i in a.multi_response[:30]]))
    critical = [m for m in a.multi_senders if m.critical]
    if critical:
        found.append(Finding(
            "warning", f"{len(critical)} Rückmeldung(en) oder Messwert(e) mit mehreren Sendern",
            "Mehrere Geräte schreiben auf dieselbe Status- oder Messwert-GA; der Wert springt "
            "je nach letztem Sender. Je Sender eine eigene GA verwenden.",
            [m.text for m in critical[:30]]))
    others = [m for m in a.multi_senders if not m.critical]
    if others:
        found.append(Finding(
            "info", f"{len(others)} GA(s) mit mehreren Sendern",
            "Üblich bei Bedienungen (mehrere Taster, Visualisierung, Zentral). Bei "
            "Zuständen prüfen, ob alle Sender denselben Wert meinen.",
            [m.text for m in others[:30]]))
    if a.measuring_line and a.forwarded:
        found.append(Finding(
            "info", f"{len(a.forwarded)} GA(s) ohne Empfänger auf Linie {a.measuring_line} "
                    "weitergeleitet",
            f"Diese Telegramme kommen über einen Koppler (Routing-Zähler unter 6) in die Linie "
            f"{a.measuring_line} des Messpunkts, obwohl dort kein Gerät die GA verknüpft hat. "
            "Filtertabelle des Linienkopplers laden bzw. «Gruppentelegramme: filtern» "
            "einstellen; das senkt die Buslast der Linie. Geräte ausserhalb der ETS "
            "(Visualisierung) brauchen die GA ggf. doch.",
            [f"{p.src} → {p.dst} {p.designation}: {p.count}×" for p in a.forwarded[:30]]))
    if a.hop_issues:
        found.append(Finding(
            "warning", f"{len(a.hop_issues)} Mal Routing-Zähler 7 oder 0",
            "Zähler 7 wird von Kopplern nie vermindert: bei einer Schleife kreist das "
            "Telegramm. Zähler 0 kommt nach vielen Kopplern an und wird nicht mehr "
            "weitergeleitet. Parametrierung des Senders bzw. Topologie prüfen.",
            [f"{p.src} → {p.dst} {p.designation}: Zähler {', '.join(map(str, p.hops))}"
             for p in a.hop_issues[:30]]))
    if a.load:
        top = max(a.load, key=lambda p: p.percent)
        if top.percent >= LOAD_HINT:
            found.append(Finding(
                "warning" if top.percent >= LOAD_WARN else "info",
                f"Busbelegung bis {top.percent:.0f} % in einer Minute",
                f"Anteil der Zeit, in der die Linie belegt war (Rahmen und Quittungen, "
                f"geschätzt). Richtwert: dauerhaft unter {LOAD_HINT} %, kurzzeitig unter "
                f"{LOAD_WARN} %. Zyklisches Senden und Änderungsschwellen prüfen.",
                [f"{p.minute[11:16]}: {p.percent:.0f} % ({p.frames} Rahmen)"
                 for p in sorted(a.load, key=lambda p: -p.percent)[:5]]))
    return found


# ── Vergleich zweier Mitschnitte ────────────────────────────────────────

@dataclass
class Comparison:
    reference: dict
    current: dict
    metrics: list[tuple[str, str, str]]                 # (Kennzahl, Referenz, aktuell)
    new_senders: list[str] = field(default_factory=list)
    gone_senders: list[str] = field(default_factory=list)
    new_targets: list[str] = field(default_factory=list)
    gone_targets: list[str] = field(default_factory=list)
    changed: list[tuple[str, float, float]] = field(default_factory=list)  # Paar, je h vorher/nachher
    findings_ref: list[str] = field(default_factory=list)
    findings_cur: list[str] = field(default_factory=list)

    @property
    def new_findings(self) -> list[str]:
        known = {_kind(f) for f in self.findings_ref}
        return [f for f in self.findings_cur if _kind(f) not in known]

    @property
    def resolved_findings(self) -> list[str]:
        known = {_kind(f) for f in self.findings_cur}
        return [f for f in self.findings_ref if _kind(f) not in known]


def _hours(summary: dict) -> float:
    try:
        start = datetime.fromisoformat(summary["start"])
        stop = datetime.fromisoformat(summary["stop"])
    except (KeyError, ValueError):
        return 0.0
    return max((stop - start).total_seconds(), 0.0) / 3600


def _kind(title: str) -> str:
    """Befundtitel ohne Zahlen, damit «12 Wiederholungen» und «3 Wiederholungen»
    als derselbe Befund gelten."""
    words = [w for w in title.split() if not any(c.isdigit() for c in w)]
    return " ".join(words)


def compare(project, current: dict, reference: dict) -> Comparison:
    from .bus_monitor import analyze
    a, r = analyze(project, current), analyze(project, reference)
    h_cur, h_ref = _hours(current) or 1e-9, _hours(reference) or 1e-9

    def pct(n, d):
        return f"{n / d * 100:.0f} %" if d else "–"

    def peak(an):
        return f"{max((p.percent for p in an.load), default=0):.0f} %" if an.load else "–"

    metrics = [
        ("Mitschnitt", f"{reference['start'][:16].replace('T', ' ')} ({r.duration_s / 60:.0f} min)",
         f"{current['start'][:16].replace('T', ' ')} ({a.duration_s / 60:.0f} min)"),
        ("Telegramme pro Minute", f"{r.per_minute:.1f}", f"{a.per_minute:.1f}"),
        ("Wiederholungen", pct(reference.get("repeats", 0), reference.get("frames", 0)),
         pct(current.get("repeats", 0), current.get("frames", 0))),
        ("NAK / BUSY", f"{reference.get('naks', 0)} / {reference.get('busys', 0)}",
         f"{current.get('naks', 0)} / {current.get('busys', 0)}"),
        ("Spitze Rahmen pro Sekunde", str(reference.get("peak_per_second", 0)),
         str(current.get("peak_per_second", 0))),
        ("Höchste Busbelegung (Minute)", peak(r), peak(a)),
        ("Absender", str(len(r.senders)), str(len(a.senders))),
        ("Absender nicht im Projekt", str(len(r.unknown)), str(len(a.unknown))),
        ("Befunde (Fehler/Warnung)",
         str(sum(f.level in ("error", "warning") for f in r.findings)),
         str(sum(f.level in ("error", "warning") for f in a.findings))),
    ]
    senders_cur = {s.address for s in a.senders}
    senders_ref = {s.address for s in r.senders}
    targets_cur = {p.dst for p in a.pairs if "/" in p.dst}
    targets_ref = {p.dst for p in r.pairs if "/" in p.dst}

    def rates(an, hours):
        out: dict[str, float] = defaultdict(float)
        for p in an.pairs:
            out[f"{p.src} → {p.dst}"] += p.count / hours
        return out

    rc, rr = rates(a, h_cur), rates(r, h_ref)
    changed = []
    for key in set(rc) | set(rr):
        before, after = rr.get(key, 0.0), rc.get(key, 0.0)
        if max(before, after) < 6:                          # unter 6 je Stunde: unerheblich
            continue
        if not before or not after or after / before >= 2 or after / before <= 0.5:
            changed.append((key, before, after))
    changed.sort(key=lambda c: -abs(c[2] - c[1]))
    return Comparison(
        reference, current, metrics,
        sorted(senders_cur - senders_ref, key=_addr_key),
        sorted(senders_ref - senders_cur, key=_addr_key),
        sorted(targets_cur - targets_ref, key=_addr_key),
        sorted(targets_ref - targets_cur, key=_addr_key),
        changed,
        [f.title for f in r.findings if f.level != "info"],
        [f.title for f in a.findings if f.level != "info"])
