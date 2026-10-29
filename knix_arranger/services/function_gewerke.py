"""
Gewerke der Funktionen (FA-530c): Anzeige "J Jalousie" in der Ansicht
"ETS-Funktionen" und im Dialog "Funktion".

Eingelesene Funktionen: Gewerk der GA (mit Korrektur, "G Gerät (statt T
Taster)"). Von der ETS angelegte GAs (HG 12, "Schalten") haben keines --
dann zählt das Gewerk der Element-GAs auf denselben Aktor-KOs ("abgeleitet").
"""
from __future__ import annotations

from dataclasses import dataclass

from .ets_corrections import effective_gewerk, ets_gewerk


@dataclass
class GewerkCell:
    text: str = ""
    tooltip: str = ""
    derived: bool = False     # aus den Element-GAs am Aktorkanal abgeleitet


def gewerk_label(project, code: str) -> str:
    """"J Jalousie"; unbekannter Code nur "J"."""
    gewerk = project.gewerk_catalog.get(code) if code else None
    return f"{code} {gewerk.name}".strip() if gewerk else code


def gewerk_cell(project, codes, derived: bool = False) -> GewerkCell:
    """Ein Gewerk mit Name, mehrere nur als Codes (Namen im Tooltip)."""
    codes = list(dict.fromkeys(c for c in codes if c))
    if not codes:
        return GewerkCell("–")
    if len(codes) == 1:
        text, tooltip = gewerk_label(project, codes[0]), ""
    else:
        text = ", ".join(codes)
        tooltip = ", ".join(gewerk_label(project, c) for c in codes)
    if derived:
        note = "abgeleitet aus den Element-GAs am Aktorkanal"
        tooltip = f"{tooltip} – {note}" if tooltip else note
    return GewerkCell(text, tooltip, derived)


class EtsGewerke:
    """Gewerk je GA der eingelesenen Funktionen."""

    def __init__(self, project):
        self._project = project
        self._by_address = {ga.address: ga
                            for ga in project.group_addresses.all_addresses()
                            if not ga.is_placeholder}
        self._neighbours: dict[str, set[str]] = {}
        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    for co in device.communication_objects:
                        for address in co.connected_gas:
                            self._neighbours.setdefault(address, set()).update(
                                a for a in co.connected_gas if a != address)

    def codes(self, address: str) -> tuple[list[str], bool]:
        """(Gewerke, abgeleitet?) einer GA."""
        ga = self._by_address.get(address)
        code = effective_gewerk(self._project, ga) if ga is not None else ""
        if code:
            return [code], False
        derived = []
        for other in sorted(self._neighbours.get(address, ())):
            neighbour = self._by_address.get(other)
            if neighbour is None:
                continue
            code = effective_gewerk(self._project, neighbour)
            if code and code not in derived:
                derived.append(code)
        return derived, bool(derived)

    def cell(self, address: str) -> GewerkCell:
        codes, derived = self.codes(address)
        cell = gewerk_cell(self._project, codes, derived)
        ga = self._by_address.get(address)
        if ga is not None and not derived and codes:
            original = ets_gewerk(ga)
            if original and original != codes[0]:
                cell.text += f" (statt {gewerk_label(self._project, original)})"
        return cell

    def function_cell(self, addresses) -> GewerkCell:
        """Gewerke aller GAs einer Funktion; abgeleitet nur, wenn keine GA
        selbst ein Gewerk trägt."""
        own, derived = [], []
        for address in addresses:
            codes, is_derived = self.codes(address)
            (derived if is_derived else own).extend(codes)
        if own:
            return gewerk_cell(self._project, own)
        return gewerk_cell(self._project, derived, bool(derived))
