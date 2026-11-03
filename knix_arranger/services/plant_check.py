"""
Anlagen-Check (FA-641): Zustand einer Anlage auf einen Blick.

Bündelt, was KNiX ohnehin prüft und rechnet -- Teilnehmer und Busstrom je
Linie, Reserven an Aktorkanälen, Gruppenadressen ohne Verknüpfung, Sender
oder Empfänger, Validierung, KNX Secure, Dokumentationsgrad, Busanalyse und
Umbau-Varianten -- zu einer Liste von Prüfpunkten mit Bewertung. Grundlage
für die Ansicht und den Bericht «Anlagen-Check» (Servicevertrag,
Sanierungsangebot, Übergabe).
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass

OK, ATTENTION, CRITICAL, INFO = "ok", "beachten", "kritisch", "info"


@dataclass
class CheckItem:
    area: str           # Bereich, z.B. "Topologie"
    title: str          # Prüfpunkt
    value: str          # Ergebnis, z.B. "64 / 64 Teilnehmer"
    rating: str         # OK, ATTENTION, CRITICAL, INFO
    hint: str = ""      # Empfehlung
    nav_key: str = ""   # Ansicht zum Weiterarbeiten


def _devices(project) -> list:
    return [d for a in project.topology.areas for l in a.lines for d in l.devices]


def actor_channels(project) -> dict[str, tuple[int, int]]:
    """Physikalische Adresse -> (belegt, Kanalzahl) je Aktor mit erkennbarer
    Kanalzahl -- wie der Abschnitt «Freie Kanäle» im Bericht Aktoren und
    Gateways: Kanalzahl aus der Produktbezeichnung, belegt ist ein Kanal mit GA."""
    from .belegungsplan_service import BelegungsplanService, group_actor_rows_by_channel
    from .report_service import _channel_total, _report_channel_label
    rows_by_addr = defaultdict(list)
    if not project.topology.is_imported:
        for r in BelegungsplanService().generate(project).actor_rows:
            rows_by_addr[r.physical_address].append(r)
    result = {}
    for device in _devices(project):
        if device.device_type != "actor":
            continue
        total = _channel_total(device.product)
        if not total:
            continue
        rows = rows_by_addr.get(device.physical_address, [])
        if rows and any(r.gewerk_code for r in rows):
            used = sum(1 for ch, _ in group_actor_rows_by_channel(rows) if ch != "?")
        else:
            used = len({_report_channel_label(co.name) for co in device.communication_objects
                        if co.connected_gas and _report_channel_label(co.name)})
        result[device.physical_address] = (min(used, total), total)
    return result


def actor_channel_reserve(project) -> tuple[int, int, int]:
    """(frei, belegt, Aktoren ohne erkennbare Kanalzahl) über alle Aktoren."""
    channels = actor_channels(project)
    actors = sum(1 for d in _devices(project) if d.device_type == "actor")
    return (sum(total - used for used, total in channels.values()),
            sum(used for used, _total in channels.values()),
            actors - len(channels))


def run_check(project, validation_counts: tuple[int, int] | None = None) -> list[CheckItem]:
    """Alle Prüfpunkte. validation_counts: (Fehler, Warnungen) der laufenden
    Prüfung, sonst wird die Validierung hier ausgeführt."""
    from .bus_current import is_consumer, line_current, shared_catalog_or_none
    from .ko_links import TRANSMIT, parse_flags
    from .line_segments import segment_load
    items: list[CheckItem] = []
    devices = _devices(project)
    consumers = [d for d in devices if is_consumer(d)]
    catalog = shared_catalog_or_none()

    # ── Topologie ────────────────────────────────────────────────────────
    lines = [(a, l) for a in project.topology.areas for l in a.lines if l.devices]
    for area, line in lines:
        key = f"{area.area_number}.{line.line_number}"
        seg = segment_load(line)
        current = line_current(line, catalog)
        rating = (CRITICAL if seg.overloaded or current.overloaded
                  else ATTENTION if seg.low_reserve or current.low_reserve else OK)
        value = seg.summary()
        if current.consumer_count:
            value += f", Busstrom {current.summary()}"
        hint = ""
        if rating != OK:
            hint = "Reserve fehlt: Linie aufteilen oder Segment ergänzen (Umbau-Varianten)."
        if current.estimated_count:
            hint = " ".join(p for p in (hint, f"Busstrom: {current.estimate_note()}.") if p)
        items.append(CheckItem("Topologie", f"Linie {key}", value, rating, hint, "renovation"))
    no_supply = [f"{a.area_number}.{l.line_number}" for a, l in lines
                 if not any(d.device_type == "power_supply" for d in l.devices)]
    if no_supply:
        items.append(CheckItem("Topologie", "Spannungsversorgungen",
                               f"nicht erfasst für Linie {', '.join(no_supply)}", INFO,
                               "In der ETS fehlen oft Spannungsversorgungen ohne Busanschluss; "
                               "für den Busstrom 640 mA angenommen.", "topology"))
    external = [d for d in consumers if d.external]
    if external:
        items.append(CheckItem("Topologie", "Geräte ausserhalb des ETS-Projekts",
                               ", ".join(f"{d.physical_address} {d.product}" for d in external),
                               ATTENTION,
                               "Mit einem Dummy in der ETS dokumentieren (Filtertabellen).",
                               "renovation"))

    # ── Reserven ─────────────────────────────────────────────────────────
    free, used, unknown = actor_channel_reserve(project)
    if free or used:
        share = free / (free + used) * 100 if free + used else 0
        items.append(CheckItem(
            "Reserven", "Freie Aktorkanäle", f"{free} von {free + used} frei ({share:.0f} %)",
            ATTENTION if share < 10 else OK,
            "Wenige Reserven: Erweiterungen brauchen zusätzliche Aktoren." if share < 10
            else (f"{unknown} Aktor(en) ohne erkennbare Kanalzahl nicht gezählt." if unknown
                  else ""), "material_list"))

    # ── Gruppenadressen ──────────────────────────────────────────────────
    gas = [g for g in project.group_addresses.all_addresses() if not g.is_placeholder]
    linked: dict[str, int] = defaultdict(int)
    senders: set[str] = set()
    for d in devices:
        for co in d.communication_objects:
            for ga in co.connected_gas:
                linked[ga] += 1
            if co.connected_gas and TRANSMIT in parse_flags(co.flags):
                senders.add(co.connected_gas[0])
    unlinked = [g for g in gas if g.address not in linked]
    items.append(CheckItem("Gruppenadressen", "Anzahl", str(len(gas)), INFO, "", "addresses"))
    if gas:
        items.append(CheckItem(
            "Gruppenadressen", "Ohne Verknüpfung", f"{len(unlinked)} ({len(unlinked) / len(gas) * 100:.0f} %)",
            ATTENTION if len(unlinked) > 0.2 * len(gas) else OK if not unlinked else INFO,
            "Reserven, Altlasten oder GAs einer Visualisierung; aufräumen oder als Reserve "
            "kennzeichnen." if unlinked else "", "validation"))
        no_sender = [g for g in gas if g.address in linked and g.address not in senders]
        items.append(CheckItem(
            "Gruppenadressen", "Mit Empfängern, aber ohne sendendes Gerät",
            str(len(no_sender)), INFO,
            "Werden von aussen geschrieben (Visualisierung, Logik, ETS) oder nur gelesen; "
            "mit einem Busmonitor-Mitschnitt prüfen." if no_sender else "", "bus_analysis"))

    # ── Geräte ───────────────────────────────────────────────────────────
    knx = [d for d in consumers if not d.external and d.device_type != "coupler"]
    by_type = defaultdict(int)
    for d in knx:
        by_type[d.device_type] += 1
    labels = {"actor": "Aktoren", "sensor": "Sensoren", "gateway": "Gateways",
              "other": "weitere"}
    items.append(CheckItem("Geräte", "Busteilnehmer", f"{len(knx)} (" + ", ".join(
        f"{n} {labels.get(t, t)}" for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]))
        + ")", INFO, "", "topology"))
    idle = [d for d in knx if d.communication_objects
            and not any(co.connected_gas for co in d.communication_objects)]
    if idle:
        items.append(CheckItem("Geräte", "Ohne verknüpfte Gruppenadresse",
                               ", ".join(d.physical_address for d in idle[:12])
                               + (" …" if len(idle) > 12 else ""), ATTENTION,
                               "Gerät ohne Funktion im Projekt – prüfen, ob es noch "
                               "gebraucht wird.", "topology"))

    # ── Validierung ──────────────────────────────────────────────────────
    if validation_counts is None:
        from .validation_engine import ValidationEngine
        issues = ValidationEngine(project.gewerk_catalog).validate(project.group_addresses, project)
        validation_counts = (sum(1 for i in issues if i.level == "error"),
                             sum(1 for i in issues if i.level == "warning"))
    errors, warnings = validation_counts
    items.append(CheckItem("Validierung", "Fehler und Warnungen",
                           f"{errors} Fehler, {warnings} Warnungen",
                           CRITICAL if errors else ATTENTION if warnings else OK,
                           "Einzelheiten in der Validierung." if errors or warnings else "",
                           "validation"))

    # ── KNX Secure ───────────────────────────────────────────────────────
    capable = sum(1 for d in knx if d.secure_supported)
    items.append(CheckItem("KNX Secure", "Secure-fähige Geräte (laut Produktdaten)",
                           f"{capable} von {len(knx)}", INFO,
                           f"Für durchgehend KNX Secure wären {len(knx) - capable} Geräte zu "
                           "ersetzen." if capable < len(knx) else "", "knx_secure"))

    # ── Dokumentation ────────────────────────────────────────────────────
    if knx:
        located = sum(1 for d in knx if d.installation_location or d.room_id)
        product = sum(1 for d in knx if d.order_number)
        doc = min(located, product) / len(knx)
        items.append(CheckItem(
            "Dokumentation", "Einbauort bzw. Raum erfasst", f"{located} von {len(knx)}",
            OK if located == len(knx) else ATTENTION, "", "topology"))
        items.append(CheckItem(
            "Dokumentation", "Produktdaten (Bestellnummer)", f"{product} von {len(knx)}",
            OK if product == len(knx) else ATTENTION if doc < 0.9 else INFO, "", "material_list"))

    # ── Busanalyse ───────────────────────────────────────────────────────
    if project.bus_recordings:
        from .bus_monitor import analyze
        rec = project.bus_recordings[-1]
        a = analyze(project, rec)
        share = rec["repeats"] / rec["frames"] * 100 if rec.get("frames") else 0
        items.append(CheckItem(
            "Busanalyse", f"Mitschnitt {rec['start'][:10]}",
            f"{a.per_minute:.0f} Telegramme/min, Spitze {rec['peak_per_second']}/s, "
            f"{share:.0f} % Wiederholungen",
            ATTENTION if share >= 10 or rec["peak_per_second"] >= 35 or a.unknown else OK,
            (f"{len(a.unknown)} unbekannte(r) Absender. " if a.unknown else "")
            + ("Wiederholungen: Empfänger bzw. Quittierung prüfen." if share >= 10 else ""),
            "bus_analysis"))
    else:
        items.append(CheckItem("Busanalyse", "Mitschnitt", "keiner eingelesen", INFO,
                               "Ein Busmonitor-Mitschnitt (ideal 24 h) zeigt Buslast, "
                               "Wiederholungen und Geräte ausserhalb des Projekts.",
                               "bus_analysis"))

    # ── Umbau ────────────────────────────────────────────────────────────
    plans = [f"Linie {p.source}" for p in project.line_plans]
    plans += [f"Erweiterung {p.name}" for p in project.extension_plans]
    if plans:
        items.append(CheckItem("Umbau", "Geplante Änderungen", ", ".join(plans), INFO, "",
                               "renovation"))
    return items


def rating_counts(items: list[CheckItem]) -> dict[str, int]:
    counts = defaultdict(int)
    for item in items:
        counts[item.rating] += 1
    return dict(counts)
