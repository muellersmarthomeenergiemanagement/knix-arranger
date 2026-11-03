"""
Umbau-Variante einer Linie auswerten (FA-609c).

Eine Linie mit zu vielen Teilnehmern oder zu hohem Busstrom (FA-609b,
FA-613b) wird aufgeteilt: Geräte kommen in eine neue Linie (Linienkoppler,
neue physikalische Adressen) oder in ein neues Segment derselben Linie
(Linienverstärker, Adressen bleiben). Optional bekommt die bestehende Linie
einen eigenen Linienkoppler und Geräte wie die Schnittstelle einer
Visualisierung kommen auf die Hauptlinie.

Ausgewertet werden je Teil Teilnehmer und Busstrom, die neue Hardware, die
Umadressierung (alt -> neu) und die Filtertabellen der Koppler danach. Ein
Koppler lässt eine GA durch, wenn sie mit einem Gerät seiner Linie verknüpft
ist -- für verknüpfte Geräte stimmen die Tabellen damit von selbst. Geräte
ohne Verknüpfungen im Projekt (externe Geräte, z.B. ein Visualisierungs-
server) erreichen hinter einem filternden Koppler nur die GAs, die in ihrer
eigenen Linie verknüpft sind; das prüft external_checks.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from ..models.line_plan import TARGET_MAIN, TARGET_NEW, LinePlan
from ..models.topology import line_coupler, line_power_supplies
from .bus_current import (
    DEFAULT_DEVICE_MA, DEFAULT_SUPPLY_MA, RESERVE_LIMIT, device_current, is_consumer,
    supply_capacity,
)
from .line_segments import SEGMENT_DEVICES, is_line_repeater
from .report_sorting import physical_address_key

SOURCE = "source"


def find_line(project, key: str):
    """(Bereich, Linie) zu "B.L", sonst (None, None)."""
    for area in project.topology.areas:
        for line in area.lines:
            if f"{area.area_number}.{line.line_number}" == key:
                return area, line
    return None, None


def plan_for(project, key: str) -> LinePlan | None:
    return next((p for p in project.line_plans if p.source == key), None)


def free_line_number(area) -> int:
    """Erste Liniennummer 1-15 ohne Geräte (leere Linien zählen als frei)."""
    used = {l.line_number for l in area.lines if l.devices}
    return next((n for n in range(1, 16) if n not in used), 0)


def has_coupler(area, line) -> bool:
    return line_coupler(area, line) is not None


@dataclass
class PlanPart:
    key: str                      # SOURCE, TARGET_NEW, TARGET_MAIN
    label: str                    # "Linie 1.1", "Linie 1.3 (neu)", "Hauptlinie 1.0"
    devices: list = field(default_factory=list)
    added: list[str] = field(default_factory=list)   # neue Busteilnehmer ("Linienkoppler 1.3.0")
    segments: int = 1
    current_ma: float = 0.0
    estimated_ma: float = 0.0
    supply_ma: int = 0
    new_supply: bool = False      # Spannungsversorgung neu vorsehen

    @property
    def count(self) -> int:
        return len(self.devices) + len(self.added)

    @property
    def capacity(self) -> int:
        return SEGMENT_DEVICES * self.segments

    @property
    def load(self) -> float | None:
        return self.current_ma / self.supply_ma if self.supply_ma else None

    @property
    def worst(self) -> float:
        """Höhere Auslastung aus Teilnehmern und Busstrom."""
        return max(self.count / self.capacity, self.load or 0.0)

    @property
    def status(self) -> str:
        if self.worst > 1.0:
            return "überlastet"
        if self.worst > RESERVE_LIMIT:
            return "knapp"
        return "ok"


@dataclass
class Readdress:
    device: object
    old: str
    new: str


@dataclass
class FilterTable:
    coupler: str                  # "1.3.0"
    line: str                     # "Linie 1.3"
    ga_count: int
    new: bool                     # Koppler kommt neu dazu
    changed: bool                 # Tabelle ändert sich durch den Umbau


@dataclass
class ExternalCheck:
    device: object
    where: str                    # Teil nach dem Umbau
    behind_coupler: bool
    blocked: list[str]            # GAs, die das Gerät nicht erreichen
    blocked_now: list[str]        # dasselbe im Ist-Stand
    observed: list[str] = field(default_factory=list)   # laut Busmonitor gesendet
    confirmed: list[str] = field(default_factory=list)  # davon gesperrt: sicher betroffen


@dataclass
class PlanResult:
    plan: LinePlan
    area: object
    line: object
    before: PlanPart
    parts: list[PlanPart]
    hardware: list[str]
    readdress: list[Readdress]
    filters: list[FilterTable]
    externals: list[ExternalCheck]
    crossing: int                 # GAs, die neu zwischen alter und neuer Linie laufen
    hints: list[str]

    @property
    def ok(self) -> bool:
        return all(p.status != "überlastet" for p in self.parts)


def target_of(plan: LinePlan, device, main_available: bool) -> str:
    target = plan.targets.get(device.id, SOURCE)
    if target == TARGET_MAIN and not main_available:
        return SOURCE
    return target


def main_available(plan: LinePlan, area, line) -> bool:
    """Eine Hauptlinie gibt es physisch, wenn die Linie einen Koppler hat
    oder einen bekommt."""
    return plan.main_line or has_coupler(area, line)


def _load(part: PlanPart, catalog) -> PlanPart:
    for device in part.devices:
        current, from_data = device_current(device, catalog)
        part.current_ma += current
        if not from_data:
            part.estimated_ma += current
    # Neue Koppler und Verstärker mit dem Richtwert
    part.current_ma += DEFAULT_DEVICE_MA * len(part.added)
    part.estimated_ma += DEFAULT_DEVICE_MA * len(part.added)
    return part


def _supply(devices) -> int:
    return sum(supply_capacity(d)[0] for d in devices)


def _repeater_address(line, area, taken: set[str]) -> str:
    """Linienverstärker üblich auf B.L.64, .128, .192."""
    prefix = f"{area.area_number}.{line.line_number}."
    for t in (64, 128, 192, *range(1, 256)):
        if f"{prefix}{t}" not in taken:
            return f"{prefix}{t}"
    return f"{prefix}?"


def _new_address(prefix: str, participant: int, taken: set[str]) -> str:
    """Gleiche Teilnehmernummer in der neuen Linie (1.1.37 -> 1.3.37), sonst
    die nächste freie."""
    for t in (participant, *range(1, 256)):
        if t and f"{prefix}{t}" not in taken:
            taken.add(f"{prefix}{t}")
            return f"{prefix}{t}"
    return f"{prefix}?"


def _participant(address: str) -> int:
    tail = address.rsplit(".", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def evaluate(project, plan: LinePlan, catalog=None) -> PlanResult | None:
    area, line = find_line(project, plan.source)
    if line is None:
        return None
    a, l = area.area_number, line.line_number
    main_ok = main_available(plan, area, line)
    consumers = [d for d in line.devices if is_consumer(d)]
    sv_now = _supply(line_power_supplies(line))
    main_line = next((x for x in area.lines if x.line_number == 0), None)
    main_devices = [d for d in (main_line.devices if main_line else []) if is_consumer(d)]

    before = _load(PlanPart(SOURCE, f"Linie {a}.{l}", devices=list(consumers),
                            segments=1 + sum(1 for d in consumers if is_line_repeater(d)),
                            supply_ma=sv_now), catalog)

    by_target: dict[str, list] = {SOURCE: [], TARGET_NEW: [], TARGET_MAIN: []}
    for device in consumers:
        by_target[target_of(plan, device, main_ok)].append(device)

    hardware: list[str] = []
    hints: list[str] = []
    taken = {d.physical_address for x in area.lines for d in x.devices}

    source = PlanPart(SOURCE, f"Linie {a}.{l}", devices=by_target[SOURCE], supply_ma=sv_now,
                      segments=1 + sum(1 for d in by_target[SOURCE] if is_line_repeater(d)))
    new_coupler_source = plan.main_line and not has_coupler(area, line)
    if new_coupler_source:
        source.added.append(f"Linienkoppler {a}.{l}.0")
        hardware.append(f"Linienkoppler {a}.{l}.0 für Linie {a}.{l}")
    parts = [source]

    new_prefix = ""
    if by_target[TARGET_NEW]:
        if plan.mode == "segment":
            repeater = _repeater_address(line, area, taken)
            new = PlanPart(TARGET_NEW, f"Linie {a}.{l}, neues Segment",
                           devices=by_target[TARGET_NEW], added=[f"Linienverstärker {repeater}"],
                           supply_ma=DEFAULT_SUPPLY_MA, new_supply=True)
            hardware.append(f"Linienverstärker {repeater} (neues Segment der Linie {a}.{l})")
            hardware.append("Spannungsversorgung mit Drossel für das neue Segment")
        else:
            n = plan.new_line or free_line_number(area)
            new_prefix = f"{a}.{n}."
            name = f" {plan.new_name}" if plan.new_name else ""
            new = PlanPart(TARGET_NEW, f"Linie {a}.{n}{name} (neu)",
                           devices=by_target[TARGET_NEW], added=[f"Linienkoppler {a}.{n}.0"],
                           supply_ma=DEFAULT_SUPPLY_MA, new_supply=True,
                           segments=1 + sum(1 for d in by_target[TARGET_NEW]
                                            if is_line_repeater(d)))
            hardware.append(f"Linienkoppler {a}.{n}.0 für die neue Linie {a}.{n}")
            hardware.append(f"Spannungsversorgung mit Drossel für Linie {a}.{n}")
        parts.append(new)

    if main_ok and (by_target[TARGET_MAIN] or new_coupler_source):
        main_supply = _supply(line_power_supplies(main_line)) if main_line else 0
        if not main_supply and area.backbone_power_supply is not None:
            main_supply = supply_capacity(area.backbone_power_supply)[0]
        main = PlanPart(TARGET_MAIN, f"Hauptlinie {a}.0",
                        devices=main_devices + by_target[TARGET_MAIN],
                        supply_ma=main_supply or DEFAULT_SUPPLY_MA, new_supply=not main_supply)
        if main.new_supply:
            hardware.append(f"Spannungsversorgung mit Drossel für die Hauptlinie {a}.0")
        parts.append(main)
        if new_coupler_source:
            others = [f"{x.area_number}.{y.line_number}.0" for x in [area] for y in x.lines
                      if y is not line and y.line_number and has_coupler(area, y)]
            if others:
                hints.append(
                    "Bisher hängt die Linie direkt an der Primärseite von "
                    f"{', '.join(others)}: "
                    + ("diesen Koppler" if len(others) == 1 else "diese Koppler")
                    + " an die neue Hauptlinie anschliessen.")

    for part in parts:
        _load(part, catalog)

    # Umadressierung
    readdress = []
    for device in sorted(by_target[TARGET_NEW] if new_prefix else [],
                         key=lambda d: physical_address_key(d.physical_address)):
        readdress.append(Readdress(device, device.physical_address,
                                   _new_address(new_prefix, _participant(device.physical_address),
                                                taken)))
    for device in sorted(by_target[TARGET_MAIN],
                         key=lambda d: physical_address_key(d.physical_address)):
        readdress.append(Readdress(device, device.physical_address,
                                   _new_address(f"{a}.0.", _participant(device.physical_address),
                                                taken)))
    if any(r.device.external for r in readdress):
        hints.append("Externe Geräte (z.B. die Schnittstelle einer Visualisierung) erhalten "
                     "die neue Adresse in ihrer eigenen Konfiguration, nicht über die ETS.")
    if any(p.new_supply for p in parts):
        hints.append("Jede Linie, jedes Segment und die Hauptlinie brauchen eine eigene "
                     "Spannungsversorgung mit Drossel.")

    filters, crossing = _filters(project, plan, area, line, by_target, new_prefix,
                                 new_coupler_source)
    externals = _external_checks(project, plan, area, line, by_target, new_prefix,
                                 new_coupler_source)
    return PlanResult(plan, area, line, before, parts, hardware, readdress, filters,
                      externals, crossing, hints)


# ── Filtertabellen ───────────────────────────────────────────────────────

def _gas(devices) -> set[str]:
    return {ga for d in devices for co in d.communication_objects for ga in co.connected_gas}


def _lines_after(project, area, line, by_target, new_prefix) -> dict[str, list]:
    """Linie "B.L" -> Geräte nach dem Umbau (alle Bereiche); ein Segment
    gehört zur bestehenden Linie."""
    result: dict[str, list] = {}
    for x in project.topology.areas:
        for y in x.lines:
            key = f"{x.area_number}.{y.line_number}"
            if y is line:
                result.setdefault(key, []).extend(by_target[SOURCE])
                if not new_prefix:
                    result[key].extend(by_target[TARGET_NEW])
            else:
                result.setdefault(key, []).extend(d for d in y.devices if is_consumer(d))
    if new_prefix:
        result.setdefault(new_prefix.rstrip("."), []).extend(by_target[TARGET_NEW])
    result.setdefault(f"{area.area_number}.0", []).extend(by_target[TARGET_MAIN])
    return result


def _couplers_after(project, area, line, new_prefix, new_coupler_source) -> set[str]:
    """Linien "B.L" mit (künftigem) Linienkoppler."""
    keys = {f"{x.area_number}.{y.line_number}" for x in project.topology.areas
            for y in x.lines if y.line_number and has_coupler(x, y)}
    if new_coupler_source:
        keys.add(f"{area.area_number}.{line.line_number}")
    if new_prefix:
        keys.add(new_prefix.rstrip("."))
    return keys


def _filters(project, plan, area, line, by_target, new_prefix, new_coupler_source):
    before = {f"{x.area_number}.{y.line_number}": _gas(y.devices)
              for x in project.topology.areas for y in x.lines}
    after = _lines_after(project, area, line, by_target, new_prefix)
    couplers_now = _couplers_after(project, area, line, "", False)
    tables = []
    for key in sorted(_couplers_after(project, area, line, new_prefix, new_coupler_source),
                      key=lambda k: tuple(int(p) for p in k.split("."))):
        gas = _gas(after.get(key, []))
        tables.append(FilterTable(f"{key}.0", f"Linie {key}", len(gas),
                                  new=key not in couplers_now,
                                  changed=gas != before.get(key, set())))
    crossing = 0
    if new_prefix:
        crossing = len(_gas(by_target[SOURCE]) & _gas(by_target[TARGET_NEW]))
    return tables, crossing


# ── Externe Geräte ───────────────────────────────────────────────────────

def _blocked(all_gas: set[str], own_gas: set[str], behind: bool) -> list[str]:
    from .report_sorting import group_address_key
    if not behind:
        return []
    return sorted(all_gas - own_gas, key=group_address_key)


def _external_checks(project, plan, area, line, by_target, new_prefix, new_coupler_source):
    """Externe Geräte haben im Projekt keine Verknüpfungen. Ein Visualisierungs-
    server bedient aber fast alle GAs: hinter einem filternden Koppler erreicht
    er nur die GAs, die in seiner Linie verknüpft sind."""
    all_gas = _gas(d for x in project.topology.areas for y in x.lines for d in y.devices)
    now_lines = {f"{x.area_number}.{y.line_number}": [d for d in y.devices if is_consumer(d)]
                 for x in project.topology.areas for y in x.lines}
    after = _lines_after(project, area, line, by_target, new_prefix)
    couplers_now = _couplers_after(project, area, line, "", False)
    couplers = _couplers_after(project, area, line, new_prefix, new_coupler_source)
    observed = _observed_sends(project)
    checks = []
    for key_after, devices in sorted(after.items()):
        for device in devices:
            if not device.external:
                continue
            key_now = next(k for k, ds in now_lines.items() if device in ds)
            main = key_after.endswith(".0")
            blocked = _blocked(all_gas, _gas(devices), key_after in couplers)
            sent = observed.get(device.physical_address, [])
            checks.append(ExternalCheck(
                device, f"Hauptlinie {key_after}" if main else f"Linie {key_after}",
                behind_coupler=key_after in couplers,
                blocked=blocked,
                blocked_now=_blocked(all_gas, _gas(now_lines[key_now]), key_now in couplers_now),
                observed=sent, confirmed=[ga for ga in sent if ga in set(blocked)]))
    return checks


def _observed_sends(project) -> dict[str, list[str]]:
    """Absender -> GAs, auf die er laut Busmonitor-Mitschnitten gesendet hat."""
    from .report_sorting import group_address_key
    sends: dict[str, set[str]] = {}
    for rec in project.bus_recordings:
        for src, dst, service, *_rest in rec.get("pairs", []):
            if "/" in dst and service in ("Write", "Response"):
                sends.setdefault(src, set()).add(dst)
    return {src: sorted(gas, key=group_address_key) for src, gas in sends.items()}


# ── Gruppierung für die Auswahl ──────────────────────────────────────────

def device_groups(project, line) -> list[tuple[str, list[tuple[str, list]]]]:
    """Busteilnehmer der Linie nach Stockwerk (von unten nach oben) und
    Einbauort: [(Stockwerk, [(Einbauort, [Geräte])])]."""
    from .report_sorting import floors_bottom_up
    floor_of_room = {}
    floors = floors_bottom_up(project.areal.all_floors)
    for floor in floors:
        for apt in floor.apartments:
            for room in apt.rooms:
                floor_of_room[room.id] = floor.name or floor.short_code or "?"
    order = [f.name or f.short_code or "?" for f in floors]
    grouped: dict[str, dict[str, list]] = {}
    for device in line.devices:
        if not is_consumer(device):
            continue
        floor = floor_of_room.get(device.room_id, "Ohne Stockwerk")
        location = " ".join((device.installation_location or "").split()) or "Ohne Einbauort"
        grouped.setdefault(floor, {}).setdefault(location, []).append(device)
    result = []
    for floor in sorted(grouped, key=lambda f: order.index(f) if f in order else len(order)):
        locations = grouped[floor]
        result.append((floor, [
            (loc, sorted(locations[loc], key=lambda d: physical_address_key(d.physical_address)))
            for loc in sorted(locations)]))
    return result
