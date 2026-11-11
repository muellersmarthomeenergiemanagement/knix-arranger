"""
Erweiterung im Bestand auswerten (FA-642).

Je Element (Raum, Gewerk, Anzahl) schlägt KNiX vor:

- Adressen: die Mittelgruppe, in der die Anlage das Gewerk auf diesem
  Stockwerk schon führt (Hauptgruppe des Stockwerks, floor_main_groups),
  darin ein freier zusammenhängender Block -- bevorzugt direkt nach den
  Elementen desselben Raums, sonst nach der letzten belegten Adresse.
- Namen: nach dem Schema der Anlage, abgeleitet vom letzten Element des
  Gewerks in dieser Mittelgruppe (Chalet "J.OG.02.01_move  ( Bibliothek )"
  -> "J.OG.03.02_move  ( Fenster West )"): Stockwerk, Raumnummer und
  Elementnummer werden ersetzt, Funktionen, DPT und Abstände übernommen.
  Ohne erkennbare Vorlage (oder auf Wunsch) KNX Swiss mit dem Blockschema
  des Gewerks. Die neuen GAs tragen den Kommentar der Erweiterung, damit sie
  in der ETS erkennbar sind, ohne dass das Namensschema bricht.
- Aktorkanäle: freie Kanäle der Aktoren, die das Gewerk schon schalten,
  zuerst auf demselben Stockwerk; was fehlt, ist ein neuer Aktor.

Die Erweiterung verändert das Projekt nicht; die ETS setzt sie um (GA-Liste
als CSV, Verknüpfungen von Hand), ein Re-Import übernimmt sie.
"""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass, field

from ..models.extension_plan import NAMING_PLANT, NAMING_SWISS, ExtensionItem, ExtensionPlan

# Elementcode am Anfang einer Bezeichnung: bis zur letzten Ziffernfolge vor
# Trenner und Funktionstext ("J.OG.02.01_move", "J_OG_02_01 AUF/AB")
_CODE_RE = re.compile(r"^(?P<code>[^\s(]*?\d+)(?P<sep>[ _]+)(?=[A-Za-zÄÖÜäöü])")
_PAREN_RE = re.compile(r"\((\s*)[^)]*?(\s*)\)")
_SEP_RE = re.compile(r"([._\-])")


@dataclass
class NewGA:
    address: str
    designation: str
    dpt: str
    function: str
    item: int                 # Index der Position in plan.items
    element: int
    naming: str               # "Anlage" oder "KNX Swiss"
    label: str = ""           # Klartext des Elements, z.B. "Rotten"

    @property
    def parts(self) -> tuple[int, int, int]:
        return tuple(int(x) for x in self.address.split("/"))


@dataclass
class ActorUse:
    item: int
    device: object
    channels: int


@dataclass
class ItemResult:
    item: ExtensionItem
    room: object
    floor: object
    gewerk: object
    middle_group: str = ""        # "3/1"
    template: str = ""            # Vorlage für das Schema der Anlage
    gas: list[NewGA] = field(default_factory=list)
    actors: list[ActorUse] = field(default_factory=list)
    missing_channels: int = 0
    problems: list[str] = field(default_factory=list)


@dataclass
class ExtensionResult:
    plan: ExtensionPlan
    items: list[ItemResult]

    @property
    def gas(self) -> list[NewGA]:
        return [ga for r in self.items for ga in r.gas]

    @property
    def problems(self) -> list[str]:
        return [p for r in self.items for p in r.problems]

    def new_actors(self) -> dict[str, int]:
        """Gewerk -> fehlende Kanäle (neuer Aktor nötig)."""
        need: dict[str, int] = defaultdict(int)
        for r in self.items:
            if r.missing_channels:
                need[r.gewerk.name if r.gewerk else r.item.gewerk_code] += r.missing_channels
        return dict(need)


# ── Hilfen ───────────────────────────────────────────────────────────────

def _rooms(project) -> dict[str, tuple]:
    return {room.id: (room, floor) for floor in project.areal.all_floors
            for apt in floor.apartments for room in apt.rooms}


def split_designation(designation: str) -> tuple[str, str, str] | None:
    """(Elementcode, Trenner, Rest) oder None ohne erkennbaren Code."""
    m = _CODE_RE.match(designation or "")
    if not m:
        return None
    return m.group("code"), m.group("sep"), designation[m.end():]


def _tokens(code: str) -> list[str]:
    return _SEP_RE.split(code)


def _numeric_positions(tokens: list[str]) -> list[int]:
    return [i for i, t in enumerate(tokens) if i % 2 == 0 and t.isdigit()]


def _fit(value: str, like: str) -> str:
    """Raum- bzw. Elementnummer in der Breite der Vorlage ("3" -> "03")."""
    return value.zfill(len(like)) if value.isdigit() and like.isdigit() else value


@dataclass
class _Template:
    code: str
    tokens: list[str]
    floor_pos: int | None
    room_pos: int
    element_pos: int
    entries: list[tuple[int, str, str, str]]   # (Abstand, Trenner, Rest, DPT)
    span: int


def _template(gas: list) -> _Template | None:
    """Letztes Element (höchste Adresse) als Vorlage; braucht im Code Raum-
    und Elementnummer (zwei Ziffernfolgen)."""
    blocks: dict[str, list] = {}
    for ga in sorted(gas, key=lambda g: g.sub_group):
        parts = split_designation(ga.designation)
        if parts:
            blocks.setdefault(parts[0], []).append((ga, parts))
    if not blocks:
        return None
    code, members = max(blocks.items(), key=lambda kv: kv[1][-1][0].sub_group)
    tokens = _tokens(code)
    numeric = _numeric_positions(tokens)
    if len(numeric) < 2:
        return None
    start = members[0][0].sub_group
    entries = [(ga.sub_group - start, sep, rest, ga.datapoint_type)
               for ga, (_c, sep, rest) in members]
    floor_pos = next((i for i in range(0, numeric[-2], 2)
                      if tokens[i].isalpha() and i > 0), None)
    return _Template(code, tokens, floor_pos, numeric[-2], numeric[-1], entries,
                     span=max(e[0] for e in entries) + 1)


def _plant_code(t: _Template, floor_code: str, room_number: str, element: int) -> str:
    tokens = list(t.tokens)
    if t.floor_pos is not None and floor_code:
        tokens[t.floor_pos] = floor_code
    tokens[t.room_pos] = _fit(room_number, t.tokens[t.room_pos])
    tokens[t.element_pos] = _fit(str(element), t.tokens[t.element_pos])
    return "".join(tokens)


def _with_label(rest: str, label: str) -> str:
    """Klartext in Klammern ersetzen, Abstände der Vorlage behalten."""
    return _PAREN_RE.sub(lambda m: f"({m.group(1)}{label}{m.group(2)})", rest, count=1)


def _free_block(used: set[int], size: int, after: int) -> int | None:
    """Erste Untergruppe ab 'after' mit 'size' freien Adressen in Folge."""
    for start in list(range(max(after, 0), 256 - size + 1)) + list(range(0, 256 - size + 1)):
        if all(s not in used for s in range(start, start + size)):
            return start
    return None


# ── Auswertung ───────────────────────────────────────────────────────────

def evaluate(project, plan: ExtensionPlan) -> ExtensionResult:
    from .address_generator import AddressGenerator
    from .ets_function_plan import floor_main_groups
    from .naming_engine import NamingEngine, label_floor_code
    from .plant_check import actor_channels

    rooms = _rooms(project)
    hg_of_floor = floor_main_groups(project)
    structure = project.group_addresses
    used: dict[tuple[int, int], set[int]] = defaultdict(set)
    gas_by_mg: dict[tuple[int, int], list] = defaultdict(list)
    for hg in structure.main_groups:
        for mg in hg.middle_groups:
            for ga in mg.group_addresses:
                used[(hg.number, mg.number)].add(ga.sub_group)
                gas_by_mg[(hg.number, mg.number)].append(ga)
    all_codes = {split_designation(g.designation)[0]
                 for g in structure.all_addresses() if split_designation(g.designation)}
    generator = AddressGenerator(project.gewerk_catalog, project.config.mg_variant)
    free_channels = {pa: total - used_ch for pa, (used_ch, total)
                     in actor_channels(project).items()}
    devices = {d.physical_address: d for a in project.topology.areas
               for l in a.lines for d in l.devices}
    ga_gewerk = {g.address: g.gewerk_code for g in structure.all_addresses()}
    ga_hg = {g.address: g.main_group for g in structure.all_addresses()}

    results = []
    for index, item in enumerate(plan.items):
        room, floor = rooms.get(item.room_id, (None, None))
        gewerk = project.gewerk_catalog.get(item.gewerk_code)
        result = ItemResult(item, room, floor, gewerk)
        results.append(result)
        if room is None or gewerk is None:
            result.problems.append("Raum bzw. Gewerk fehlt im Projekt.")
            continue
        hg = hg_of_floor.get(floor.id)
        # Mittelgruppe: wo die Anlage das Gewerk auf diesem Stockwerk führt
        candidates = [(key, len([g for g in gas if g.gewerk_code == gewerk.code]))
                      for key, gas in gas_by_mg.items() if hg is None or key[0] == hg]
        candidates = [c for c in candidates if c[1]]
        if candidates:
            key = max(candidates, key=lambda c: c[1])[0]
        elif hg is not None:
            key = (hg, gewerk.home_middle_group(project.config.mg_variant))
        else:
            result.problems.append(f"Keine Hauptgruppe für Stockwerk {floor.name} – "
                                   "Adresse in der ETS von Hand wählen.")
            continue
        result.middle_group = f"{key[0]}/{key[1]}"
        gewerk_gas = [g for g in gas_by_mg[key] if g.gewerk_code == gewerk.code]
        template = None if plan.naming == NAMING_SWISS else _template(gewerk_gas)
        if template is None and plan.naming == NAMING_PLANT:
            result.problems.append("Kein Schema der Anlage erkennbar – KNX Swiss verwendet.")
        if template is not None:
            result.template = template.code
            entries = template.entries
            span = template.span
        else:
            schema = generator._base_schema(gewerk)
            entries = [(e.offset, " ", e.function, e.dpt) for e in schema.entries
                       if not e.is_reserve]
            span = schema.block_size
        floor_code = floor.short_code or floor.name
        # Raum: nach seinen bisherigen Elementen dieses Gewerks einfügen
        room_codes = []
        for code in all_codes:
            if template is not None:
                tokens = _tokens(code)
                if (len(tokens) == len(template.tokens)
                        and tokens[template.room_pos] == _fit(room.number, template.tokens[template.room_pos])
                        and (template.floor_pos is None
                             or tokens[template.floor_pos] == floor_code)
                        and tokens[0] == template.tokens[0]):
                    room_codes.append((code, int(tokens[template.element_pos]))
                                      if tokens[template.element_pos].isdigit() else (code, 0))
            elif code.startswith(f"{gewerk.code}_"):
                swiss = NamingEngine.create_designation(
                    gewerk.code, room.number, 1, "", "",
                    label_floor_code(floor_code, room.number)).split(" ")[0][:-2]
                if code.startswith(swiss) and code[len(swiss):].isdigit():
                    room_codes.append((code, int(code[len(swiss):])))
        element = max((n for _c, n in room_codes), default=0)
        room_subs = [g.sub_group for g in gas_by_mg[key]
                     if (split_designation(g.designation) or ("",))[0]
                     in {c for c, _n in room_codes}]
        after = (max(room_subs) + 1) if room_subs else (max(used[key]) + 1 if used[key] else 0)
        for label in item.labels(room.name):
            element += 1
            start = _free_block(used[key], span, after)
            if start is None:
                result.problems.append(f"Mittelgruppe {key[0]}/{key[1]} ist voll.")
                break
            after = start + span
            for offset, sep, rest, dpt in entries:
                sub = start + offset
                used[key].add(sub)
                if template is not None:
                    code = _plant_code(template, floor_code, room.number, element)
                    designation = code + sep + _with_label(rest, label)
                    naming = "Anlage"
                    function = rest.split("(")[0].strip()
                else:
                    designation = NamingEngine.create_designation(
                        gewerk.code, room.number, element, rest, label,
                        label_floor_code(floor_code, room.number))
                    naming = "KNX Swiss"
                    function = rest
                result.gas.append(NewGA(f"{key[0]}/{key[1]}/{sub}", designation, dpt,
                                        function, index, element, naming, label))
            all_codes.add(split_designation(result.gas[-1].designation)[0]
                          if split_designation(result.gas[-1].designation) else "")

        # Aktorkanäle: Aktoren, die das Gewerk schalten, zuerst auf dem Stockwerk.
        # Ein Systemsensor (Wetterstation) braucht keine.
        need = 0 if gewerk.interface_type == "system_sensor" else max(item.count, 1)
        serving = []
        for pa, free in free_channels.items():
            device = devices.get(pa)
            linked = [a for co in device.communication_objects for a in co.connected_gas]
            if not any(ga_gewerk.get(a) == gewerk.code for a in linked):
                continue
            same_floor = sum(1 for a in linked
                             if ga_gewerk.get(a) == gewerk.code and ga_hg.get(a) == key[0])
            serving.append((same_floor, free, pa))
        for _same, _free, pa in sorted(serving, reverse=True):
            if need <= 0:
                break
            take = min(free_channels[pa], need)
            if take > 0:
                result.actors.append(ActorUse(index, devices[pa], take))
                free_channels[pa] -= take
                need -= take
        result.missing_channels = need
    return ExtensionResult(plan, results)


def new_ga_structure(project, result: ExtensionResult):
    """Nur die neuen GAs als GA-Struktur (Namen der Haupt- und Mittelgruppen
    wie im Projekt) -- für den CSV-Import in die ETS."""
    from ..models.group_address import (
        GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
    )
    names = {(hg.number, None): hg.name for hg in project.group_addresses.main_groups}
    names.update({(hg.number, mg.number): mg.name for hg in project.group_addresses.main_groups
                  for mg in hg.middle_groups})
    structure = GroupAddressStructure()
    for ga in result.gas:
        h, m, s = ga.parts
        hg = next((x for x in structure.main_groups if x.number == h), None)
        if hg is None:
            hg = MainGroup(number=h, name=names.get((h, None), ""))
            structure.main_groups.append(hg)
        mg = next((x for x in hg.middle_groups if x.number == m), None)
        if mg is None:
            mg = MiddleGroup(number=m, name=names.get((h, m), ""))
            hg.middle_groups.append(mg)
        mg.group_addresses.append(GroupAddress(
            main_group=h, middle_group=m, sub_group=s, designation=ga.designation,
            datapoint_type=ga.dpt, description=result.plan.comment))
    structure.main_groups.sort(key=lambda x: x.number)
    for hg in structure.main_groups:
        hg.middle_groups.sort(key=lambda x: x.number)
        for mg in hg.middle_groups:
            mg.group_addresses.sort(key=lambda g: g.sub_group)
    return structure
