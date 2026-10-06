"""
Topologie-Prüfungen der Validierung (FA-609, FA-611 bis FA-613).

- FA-609: Geräteanzahl je Linie (Warnung > 85, Fehler > 100 bzw. über dem
  Maximum des Topologie-Modus TP-64/TP-256).
- FA-611: An Kommunikationsobjekten verknüpfte GAs, die es in der
  GA-Struktur nicht gibt; bei importierten Projekten umgekehrt GAs, die mit
  keinem Kommunikationsobjekt verknüpft sind (Hinweis).
- FA-612: Physikalische Adressen: gültiges Format, passend zu Bereich und
  Linie, nicht doppelt, Teilnehmer 0 nur für Koppler (FA-223).
- FA-613: Jede Linie mit Busteilnehmern hat eine Spannungsversorgung.
"""
from __future__ import annotations
import re

from .validation_engine import ValidationIssue

_PA = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{1,3})$")


def _bus_devices(line) -> list:
    """Busteilnehmer der Linie (Spannungsversorgungen zählen nicht)."""
    return [d for d in line.devices if d.device_type != "power_supply"]


def _line_label(area, line) -> str:
    # Generische Namen ("Linie", "Linie 1.1") nicht wiederholen
    name = f" {line.name}" if line.name and not line.name.lower().startswith("linie") else ""
    return f"Linie {area.area_number}.{line.line_number}{name}"


def _device_label(device) -> str:
    return device.product_name or device.product or device.order_number or "Gerät"


def check_topology(project) -> list[ValidationIssue]:
    topology = project.topology
    if not topology.areas:
        return []
    issues: list[ValidationIssue] = []
    issues += _check_line_load(topology)
    issues += _check_physical_addresses(topology)
    issues += _check_power_supplies(topology)
    issues += _check_co_links(project)
    return issues


def _check_line_load(topology) -> list[ValidationIssue]:
    """FA-609"""
    issues = []
    limit = min(topology.MAX_REALIZED_DEVICES, topology.max_devices_per_line)
    for area in topology.areas:
        for line in area.lines:
            count = len(_bus_devices(line))
            where = f"{area.area_number}.{line.line_number}"
            if count > limit:
                issues.append(ValidationIssue(
                    "error", "FA-609",
                    f"{_line_label(area, line)}: {count} Geräte (max. {limit})",
                    where, "Linie aufteilen oder Geräte auf eine andere Linie verschieben",
                    details={"count": count, "limit": limit}))
            elif count > topology.RECOMMENDED_DEVICES:
                issues.append(ValidationIssue(
                    "warning", "FA-609",
                    f"{_line_label(area, line)}: {count} Geräte "
                    f"(empfohlen max. {topology.RECOMMENDED_DEVICES})",
                    where, "Reserve für Erweiterungen einplanen",
                    details={"count": count, "limit": topology.RECOMMENDED_DEVICES}))
    return issues


def _check_physical_addresses(topology) -> list[ValidationIssue]:
    """FA-612"""
    issues = []
    seen: dict[str, str] = {}
    for area in topology.areas:
        for line in area.lines:
            for device in _bus_devices(line):
                pa = device.physical_address.strip()
                if not pa:
                    continue
                label = _device_label(device)
                m = _PA.match(pa)
                if not m:
                    issues.append(ValidationIssue(
                        "error", "FA-612", f"{label}: ungültige physikalische Adresse «{pa}»",
                        pa, "Adresse im Format Bereich.Linie.Teilnehmer vergeben"))
                    continue
                a, l, t = (int(x) for x in m.groups())
                if (a, l) != (area.area_number, line.line_number):
                    issues.append(ValidationIssue(
                        "error", "FA-612",
                        f"{label} {pa} liegt in {_line_label(area, line)}",
                        pa, f"Adresse {area.area_number}.{line.line_number}.x vergeben "
                            "oder Gerät in die passende Linie verschieben"))
                if t == 0 and device.device_type != "coupler":
                    issues.append(ValidationIssue(
                        "error", "FA-612",
                        f"{label} {pa}: Teilnehmer 0 ist dem Koppler vorbehalten",
                        pa, "Freie Teilnehmeradresse ab 1 vergeben"))
                if pa in seen:
                    issues.append(ValidationIssue(
                        "error", "FA-612",
                        f"{pa} doppelt vergeben: {seen[pa]} und {label}",
                        pa, "Einem der Geräte eine freie Adresse geben"))
                else:
                    seen[pa] = label
    return issues


def _check_power_supplies(topology) -> list[ValidationIssue]:
    """FA-613. Bei importierten Projekten nur Hinweis: Spannungsversorgungen
    ohne Busanschluss fehlen in vielen ETS-Projekten, obwohl sie verbaut sind."""
    level = "info" if topology.is_imported else "warning"
    issues = []
    for area in topology.areas:
        for line in area.lines:
            if line.line_number == 0 and area.backbone_type == "IP":
                continue  # IP-Hauptlinie: keine TP-Speisung
            if not _bus_devices(line):
                continue
            if any(d.device_type == "power_supply" for d in line.devices):
                continue
            issues.append(ValidationIssue(
                level, "FA-613",
                f"{_line_label(area, line)}: keine Spannungsversorgung",
                f"{area.area_number}.{line.line_number}",
                "Spannungsversorgung (mit Drossel) in der Linie vorsehen bzw. erfassen"))
    return issues


def _check_co_links(project) -> list[ValidationIssue]:
    """FA-611"""
    devices = [d for area in project.topology.areas for line in area.lines
               for d in line.devices]
    linked: set[str] = set()
    for d in devices:
        for co in d.communication_objects:
            linked.update(a for a in co.connected_gas if a)
    if not linked:
        return []

    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()
                  if not ga.is_placeholder}
    issues = []
    reported: set[tuple[str, str]] = set()
    for d in devices:
        for co in d.communication_objects:
            for addr in co.connected_gas:
                if addr and addr not in by_address and (d.id, addr) not in reported:
                    reported.add((d.id, addr))
                    issues.append(ValidationIssue(
                        "warning", "FA-611",
                        f"{_device_label(d)} {d.physical_address}, KO {co.object_number}: "
                        f"verknüpfte GA {addr} fehlt in der GA-Struktur",
                        addr, "GA anlegen oder Verknüpfung in der ETS entfernen"))

    if project.topology.is_imported:
        for addr, ga in sorted(by_address.items()):
            if addr not in linked:
                issues.append(ValidationIssue(
                    "info", "FA-611", "mit keinem Kommunikationsobjekt verknüpft",
                    addr, "Verknüpfen oder als Reserve belassen",
                    designation=ga.designation))
    return issues
