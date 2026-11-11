"""
KNX-Secure-Prüfungen der Validierung (FA-645), nach dem KNX-Swiss-Leitfaden
«Sichere Gebäudeinformatik / Gebäudetechnik» (Version 1.3, 01/2025):

- FA-645: Eine gesicherte Gruppenadresse (Sicherheit «Ein») muss an allen
  verknüpften KOs gesichert sein -- ein Gerät ohne KNX Secure kann sie weder
  senden noch empfangen («innerhalb derselben Sicherheitsdomäne muss eine
  Gruppenadresse entweder einfach oder sicher für alle verbundenen
  Gruppenobjekte sein»). Die ETS verknüpft sie dann nicht.
- FA-645b: Secure-Geräte hinter einem Linienkoppler ohne KNX Secure: der
  Koppler muss die längeren Secure-Telegramme (Extended Frames) weiterleiten.
- FA-645c: KNX IP Secure: wird ein IP-Router umgestellt, müssen alle
  IP-Router der Anlage umgestellt werden -- alle müssen IP Secure können.
- FA-645d: KNX IP soll stets mit IP-Routern ausgeführt werden, die KNX
  Secure unterstützen (KNX-Swiss-Projektrichtlinien 4.1) -- Hinweis.

Secure-fähig ist ein Gerät laut Produktdaten (Device.secure_supported), dem
Zugangsdaten-Archiv oder -- bei XLSX-Importen ohne Produktdaten -- «secure»
im Produktnamen (wie KnxSecureService.update_device_compatibility).
"""
from __future__ import annotations

import re

from .validation_engine import ValidationIssue


def _label(device) -> str:
    name = device.product_name or device.product or ""
    return " ".join(p for p in (device.physical_address, name) if p)


def is_secure_device(device, project) -> bool:
    from .knx_secure_service import is_secure_product_name
    if device.secure_supported:
        return True
    config = project.knx_secure
    info = config.device_infos.get(device.id) if config else None
    return bool(info and info.secure_supported) or is_secure_product_name(
        device.product_name or device.product)


# "KNX IP Router", "IP-Router", "IPR/S3.5.1" (ABB), "IP-Linienkoppler"
_IP_ROUTER_RE = re.compile(r"\bIP\b|\bIPR\b|\bIPR/", re.IGNORECASE)


def is_ip_router(device) -> bool:
    return device.device_type == "coupler" and bool(
        _IP_ROUTER_RE.search(f"{device.product_name} {device.product}"))


def check_secure(project) -> list[ValidationIssue]:
    issues = _check_secure_gas(project) + _check_ip_routers_secure_capable(project)
    config = project.knx_secure
    if config is not None and config.enabled:
        if config.secure_mode in ("data_secure", "both"):
            issues += _check_couplers(project)
        if config.secure_mode in ("ip_secure", "both"):
            issues += _check_ip_routers(project)
    return issues


def _check_secure_gas(project) -> list[ValidationIssue]:
    """FA-645: GA mit Sicherheit «Ein» an Geräten ohne KNX Secure."""
    secured = {ga.address: ga for ga in project.group_addresses.all_addresses()
               if ga.security == "Ein" and not ga.is_placeholder}
    if not secured:
        return []
    from .ko_links import links_by_ga
    level = "warning" if project.topology.is_imported else "error"
    issues = []
    for address, links in links_by_ga(project).items():
        ga = secured.get(address)
        if ga is None:
            continue
        plain = []
        for link in links:
            if not is_secure_device(link.device, project):
                label = _label(link.device)
                if label not in plain:
                    plain.append(label)
        if plain:
            issues.append(ValidationIssue(
                level, "FA-645",
                "gesichert, aber verknüpft mit Geräten ohne KNX Secure: "
                + ", ".join(plain[:4]) + (" …" if len(plain) > 4 else ""),
                address,
                "Sicherheit auf «Auto»/«Aus» stellen oder die Geräte durch "
                "Secure-Geräte ersetzen.",
                designation=ga.designation,
                details={"devices": plain}))
    return issues


def _check_couplers(project) -> list[ValidationIssue]:
    """FA-645b: Secure-Geräte in einer Linie, deren Linienkoppler kein
    KNX Secure kann (lange Telegramme)."""
    from ..models.topology import line_coupler, line_title
    issues = []
    for area in project.topology.areas:
        for line in area.lines:
            coupler = line_coupler(area, line)
            if coupler is None or is_secure_device(coupler, project):
                continue
            secure = [d for d in line.devices
                      if d is not coupler and is_secure_device(d, project)]
            if secure:
                issues.append(ValidationIssue(
                    "info", "FA-645b",
                    f"{line_title(area, line)}: {len(secure)} Secure-Gerät(e) hinter "
                    f"Koppler {_label(coupler)} ohne KNX Secure",
                    coupler.physical_address,
                    "Prüfen, ob der Koppler lange Telegramme (Extended Frames) "
                    "weiterleitet, sonst einen Secure-Koppler einsetzen.",
                    details={"secure_devices": len(secure)}))
    return issues


def _check_ip_routers(project) -> list[ValidationIssue]:
    """FA-645c: IP Secure nur, wenn alle IP-Router es können."""
    routers = [d for area in project.topology.areas for line in area.lines
               for d in line.devices if is_ip_router(d)]
    plain = [d for d in routers if not is_secure_device(d, project)]
    if len(routers) < 2 or not plain or len(plain) == len(routers):
        return []
    return [ValidationIssue(
        "warning", "FA-645c",
        f"KNX IP Secure: {len(plain)} von {len(routers)} IP-Routern ohne IP Secure: "
        + ", ".join(_label(d) for d in plain[:4]),
        plain[0].physical_address,
        "Wird ein IP-Router auf IP Secure umgestellt, müssen alle umgestellt "
        "werden: die übrigen IP-Router ersetzen.",
        details={"routers": [_label(d) for d in plain]})]


def _check_ip_routers_secure_capable(project) -> list[ValidationIssue]:
    """FA-645d: IP-Router ohne KNX Secure (Hinweis, einer für alle)."""
    plain = [d for area in project.topology.areas for line in area.lines
             for d in line.devices
             if is_ip_router(d) and not d.external and not is_secure_device(d, project)]
    if not plain:
        return []
    return [ValidationIssue(
        "info", "FA-645d",
        f"{len(plain)} IP-Router ohne KNX Secure: "
        + ", ".join(_label(d) for d in plain[:4]) + (" …" if len(plain) > 4 else ""),
        plain[0].physical_address,
        "KNX IP mit Secure-fähigen IP-Routern ausführen (bei Ersatz oder "
        "Erweiterung berücksichtigen).",
        details={"routers": [_label(d) for d in plain]})]
