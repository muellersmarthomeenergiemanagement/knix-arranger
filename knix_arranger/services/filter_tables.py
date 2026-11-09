"""
Filtertabellen der Koppler nachrechnen (FA-643).

Die ETS trägt eine GA in die Filtertabelle eines Linienkopplers nur ein,
wenn sie in seiner Linie verknüpft ist und ausserhalb davon gebraucht wird
(Bereichskoppler entsprechend für den Bereich). Geräte, die die ETS nicht
kennt (externe Geräte, FA-609b, z.B. ein Visualisierungsserver), zählen dabei
nicht: eine GA, die nur hinter einem Koppler verknüpft ist, erreicht sie nicht
-- auch dann nicht, wenn ihre eigene Linie keinen Koppler hat.

Chalet: Linie 1.1 ohne Koppler, Revox 1.2.7 hinter LK 1.2.0. GAs, die nur
die Revox verknüpft hat, sperrt der 1.2.0 für den Z-Server 1.1.200 in beiden
Richtungen (Lesen ohne Antwort im Mitschnitt); GAs, die auch ein Gerät in
Linie 1.1 verknüpft hat, kommen durch. Abhilfe: Dummy mit der Adresse des
externen Geräts in seiner Linie, mit diesen GAs verbunden, und die
sperrenden Koppler programmieren.

Grenzen: Parameter der Koppler (Gruppentelegramme weiterleiten/sperren,
Hauptgruppen ab 14) kennt KNiX nicht; angenommen wird "filtern".
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..models.topology import area_coupler, line_coupler


def line_of(address: str) -> str:
    """"1.1.200" -> "1.1"."""
    return address.rsplit(".", 1)[0]


def is_unfiltered(ga) -> bool:
    """GA mit «Linienkoppler passieren» (Durchgang) -- jeder Koppler lässt sie durch."""
    return ga is not None and str(ga.unfiltered).strip().lower() in ("true", "1", "ja")


class CouplerFilters:
    """Modell der Koppler: welche GA lässt welcher Koppler durch."""

    def __init__(self, lines: dict[str, list], line_couplers: set[str],
                 area_couplers: set[str] = frozenset(), unfiltered: set[str] = frozenset()):
        # lines: "B.L" -> Geräte; line_couplers: "B.L" mit LK B.L.0;
        # area_couplers: "B" mit BK B.0.0
        self.line_couplers = set(line_couplers)
        self.area_couplers = set(area_couplers)
        self.unfiltered = set(unfiltered)
        self.linked: dict[str, set[str]] = defaultdict(set)    # GA -> Linien "B.L"
        for key, devices in lines.items():
            for device in devices:
                if getattr(device, "external", False):
                    continue
                for co in device.communication_objects:
                    for ga in co.connected_gas:
                        self.linked[ga].add(key)

    @classmethod
    def from_project(cls, project) -> "CouplerFilters":
        lines, line_couplers, area_couplers = {}, set(), set()
        for area in project.topology.areas:
            if area_coupler(area) is not None:
                area_couplers.add(str(area.area_number))
            for line in area.lines:
                key = f"{area.area_number}.{line.line_number}"
                lines.setdefault(key, []).extend(line.devices)
                if line.line_number and line_coupler(area, line) is not None:
                    line_couplers.add(key)
        unfiltered = {g.address for g in project.group_addresses.all_addresses()
                      if is_unfiltered(g)}
        return cls(lines, line_couplers, area_couplers, unfiltered)

    # ── Tabellen ─────────────────────────────────────────────────────────

    def in_line_table(self, key: str, ga: str) -> bool:
        lines = self.linked.get(ga, set())
        return key in lines and bool(lines - {key})

    def in_area_table(self, area: str, ga: str) -> bool:
        areas = {k.split(".")[0] for k in self.linked.get(ga, set())}
        return area in areas and bool(areas - {area})

    def table(self, key: str) -> list[str]:
        """Filtertabelle des Linienkopplers der Linie "B.L" (wie von der ETS erzeugt)."""
        from .report_sorting import group_address_key
        return sorted((ga for ga in self.linked if self.in_line_table(key, ga)),
                      key=group_address_key)

    # ── Weg eines Telegramms ─────────────────────────────────────────────

    def blocking(self, source: str, ga: str) -> list[str]:
        """Koppler, die ein Gruppentelegramm auf `ga` aus der Linie `source`
        ("B.L") nicht zu allen Linien durchlassen, in denen die GA verknüpft
        ist (Antworten laufen denselben Weg zurück)."""
        if ga in self.unfiltered:
            return []
        area, line = source.split(".")
        found: list[str] = []

        def add(coupler: str) -> None:
            if coupler not in found:
                found.append(coupler)

        for target in sorted(self.linked.get(ga, set())):
            if target == source:
                continue
            t_area, t_line = target.split(".")
            if line != "0" and source in self.line_couplers \
                    and not self.in_line_table(source, ga):
                add(f"{source}.0")
            if t_area != area:
                if area in self.area_couplers and not self.in_area_table(area, ga):
                    add(f"{area}.0.0")
                if t_area in self.area_couplers and not self.in_area_table(t_area, ga):
                    add(f"{t_area}.0.0")
            if t_line != "0" and target in self.line_couplers \
                    and not self.in_line_table(target, ga):
                add(f"{target}.0")
        return found

    def blocked(self, source: str, gas) -> dict[str, list[str]]:
        """GA -> sperrende Koppler, nur gesperrte GAs."""
        result = {}
        for ga in gas:
            couplers = self.blocking(source, ga)
            if couplers:
                result[ga] = couplers
        return result


# ── Externe Geräte gegen Mitschnitte ─────────────────────────────────────

@dataclass
class DummyNeed:
    """Ein externes Gerät erreicht GAs nicht, die es laut Mitschnitt anspricht."""
    device: object
    line: str                                   # "1.1"
    gas: list[str]                              # gesperrte GAs (sortiert)
    couplers: list[str]                         # zu programmieren
    by_ga: dict[str, list[str]] = field(default_factory=dict)

    @property
    def task(self) -> str:
        return (f"Dummy {self.device.physical_address} in Linie {self.line} anlegen, "
                f"mit {len(self.gas)} GA(s) verbinden: {', '.join(self.gas)}; "
                f"{', '.join(self.couplers)} programmieren (Filtertabelle).")


def observed_targets(project) -> dict[str, set[str]]:
    """Absender -> GAs, die er laut Busmonitor-Mitschnitten angesprochen hat
    (Schreiben, Lesen, Antworten)."""
    targets: dict[str, set[str]] = defaultdict(set)
    for rec in project.bus_recordings:
        for src, dst, *_rest in rec.get("pairs", []):
            if "/" in dst:
                targets[src].add(dst)
    return targets


def dummy_needs(project, filters: CouplerFilters | None = None,
                targets: dict[str, set[str]] | None = None) -> list[DummyNeed]:
    """Je externem Gerät die angesprochenen GAs, die ein Koppler sperrt."""
    from .report_sorting import group_address_key, physical_address_key
    filters = filters or CouplerFilters.from_project(project)
    targets = observed_targets(project) if targets is None else targets
    needs = []
    for area in project.topology.areas:
        for line in area.lines:
            key = f"{area.area_number}.{line.line_number}"
            for device in line.devices:
                if not device.external:
                    continue
                addresses = targets.get(device.physical_address, set())
                for extra in device.additional_addresses:
                    addresses = addresses | targets.get(extra, set())
                blocked = filters.blocked(key, addresses)
                if not blocked:
                    continue
                couplers = sorted({c for cs in blocked.values() for c in cs},
                                  key=physical_address_key)
                needs.append(DummyNeed(device, key, sorted(blocked, key=group_address_key),
                                       couplers, blocked))
    return sorted(needs, key=lambda n: physical_address_key(n.device.physical_address))
