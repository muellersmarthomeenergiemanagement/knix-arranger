"""
Korrekturschicht für importierte ETS-Projekte (siehe models/ets_corrections).

Wirksamer Wert = Korrektur, falls vorhanden, sonst das, was die ETS liefert.
"""
from __future__ import annotations
from dataclasses import dataclass

from .gewerk_service import GewerkService


def ets_gewerk(ga) -> str:
    """Gewerk, wie es aus dem ETS-Namen folgt ("T.EG.01.03_ea" -> "T")."""
    matched = GewerkService._match_ga_designation(ga.designation or "")
    return matched[0] if matched else ""


def effective_gewerk(project, ga) -> str:
    override = project.ets_corrections.gewerk_by_address.get(ga.address)
    return override or ga.gewerk_code or ets_gewerk(ga)


def apply_ets_corrections(project) -> int:
    """Setzt die korrigierten Gewerke auf die GAs (nach Öffnen, Import,
    Neuaufbau). Idempotent; gibt die Anzahl korrigierter GAs zurück."""
    overrides = project.ets_corrections.gewerk_by_address
    if not overrides:
        return 0
    n = 0
    for ga in project.group_addresses.all_addresses():
        code = overrides.get(ga.address)
        if code:
            ga.gewerk_code = code
            n += 1
    return n


def set_gewerk(project, addresses: list[str], code: str) -> int:
    """Gewerk für GAs festlegen; code "" hebt die Korrektur auf (zurück zum
    ETS-Namen). Eine Korrektur gleich dem ETS-Kürzel wird nicht gespeichert."""
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    overrides = project.ets_corrections.gewerk_by_address
    changed = 0
    for addr in addresses:
        ga = by_address.get(addr)
        if ga is None:
            continue
        original = ets_gewerk(ga)
        if code and code != original:
            overrides[addr] = code
            ga.gewerk_code = code
        else:
            overrides.pop(addr, None)
            ga.gewerk_code = original or ga.gewerk_code
        changed += 1
    return changed


@dataclass
class Deviation:
    address: str
    designation: str
    field: str        # "Gewerk"
    ets_value: str
    knix_value: str


def deviations(project) -> list[Deviation]:
    """Alle Korrekturen gegenüber der ETS, nach Adresse sortiert."""
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    result = []
    for addr, code in project.ets_corrections.gewerk_by_address.items():
        ga = by_address.get(addr)
        if ga is None:
            continue
        result.append(Deviation(addr, ga.designation, "Gewerk", ets_gewerk(ga) or "–", code))
    result.sort(key=lambda d: tuple(int(p) if p.isdigit() else 0 for p in d.address.split("/")))
    return result


def gewerk_display(ga) -> str:
    """Anzeige in den GA-Ansichten: "G (statt T)", wenn vom ETS-Namen abweichend."""
    original = ets_gewerk(ga)
    if ga.gewerk_code and original and ga.gewerk_code != original:
        return f"{ga.gewerk_code} (statt {original})"
    return ga.gewerk_code
