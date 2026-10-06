"""
Gruppenadressen neu ordnen (FA-701 bis FA-706) – nur für mit KNiX geplante Projekte.

Die normale Neuberechnung hält Adressen stabil: unveränderte Blöcke bleiben
an ihrer Stelle, geänderte werden angehängt. Das ist ab der ETS-Übertragung
nötig, führt in der Planung aber zu Lücken und versetzten Blöcken. Hier wird
die Struktur der Stockwerk-Hauptgruppen frisch und lückenlos aufgebaut:

- Sortierung und Blöcke wie bei einer Erstgenerierung (FA-701, FA-702),
  Variante-B-Rückmeldungen deckungsgleich zu ihren Befehlen.
- HG 0 (Zentraladressen) wird nicht umgeordnet (FA-703).
- Jede GA behält ihre id sowie Central/Unfiltered/Security, Beschreibung und
  Kommentar (FA-705); Bezeichnungen folgen dem Bezeichnungskonzept (FA-706).
- Verweise auf Adressen (Taster mit direkter GA, Szenen, DALI,
  Kommunikationsobjekte) werden auf die neuen Adressen nachgeführt.

Bei aus der ETS importierten Projekten ist die ETS massgebend – dort wird
nicht umgeordnet (Entscheid 2026-10-06).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

from ..models.group_address import GroupAddress, GroupAddressStructure
from .address_generator import AddressGenerator, insert_ga
from .scene_addressing import normalize_scene_scopes

# Felder, die eine GA über das Neuordnen mitnimmt (FA-705)
_KEPT_FIELDS = ("id", "central", "unfiltered", "security", "description", "comment")

_LEADING_ADDRESS = re.compile(r"^(\d{1,2}/\d/\d{1,3})(?=\s|$)")


@dataclass
class RenumberChange:
    old_address: str
    new_address: str
    old_designation: str
    new_designation: str


@dataclass
class RenumberPlan:
    """Vorschau des Neuordnens (FA-704); `apply_renumbering` setzt sie um."""
    structure: GroupAddressStructure
    address_map: dict[str, str] = field(default_factory=dict)   # alt -> neu
    changes: list[RenumberChange] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    gaps_before: int = 0
    gaps_after: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.changes or self.added or self.removed)


def can_renumber(project) -> bool:
    """Neu ordnen nur bei geplanten Projekten (bei importierten gilt die ETS)."""
    return not project.topology.is_imported


def _match_key(ga: GroupAddress) -> tuple:
    """Fachliche Identität einer GA: dieselbe Funktion desselben Elements im
    selben Raum. Nicht über assignment_id -- ältere Projekte führen sie an den
    GAs noch nicht. HG 0 wird nicht umgeordnet: dort gilt die Adresse."""
    if ga.main_group == 0:
        return ("central", ga.address)
    if ga.gewerk_code and ga.room_number and ga.function_name:
        return ("fn", ga.main_group, ga.gewerk_code, ga.room_number,
                ga.element_number, ga.function_name)
    return ("name", ga.main_group, ga.designation)


def _floor_gaps(structure: GroupAddressStructure) -> int:
    """Unbelegte Untergruppen vor der letzten belegten Adresse je Mittelgruppe
    der Stockwerk-Hauptgruppen. Reserve-Platzhalter der Blöcke zählen als
    belegt -- sie gehören zur Blockstruktur (FA-434)."""
    gaps = 0
    for hg in structure.main_groups:
        if hg.number == 0:
            continue
        for mg in hg.middle_groups:
            subs = {ga.sub_group for ga in mg.group_addresses}
            if subs:
                gaps += max(subs) + 1 - len(subs)
    return gaps


def plan_renumbering(project) -> RenumberPlan:
    """Berechnet die neu geordnete Struktur, ohne das Projekt zu verändern."""
    normalize_scene_scopes(project)
    old = project.group_addresses

    # Nur HG 0 als Bestand: feste Zentraladressen und Astro-GAs behalten
    # Bezeichnung und id, alle Stockwerk-HGs werden frisch aufgebaut.
    central_only = GroupAddressStructure(variant=old.variant)
    central_only.main_groups = [hg for hg in old.main_groups if hg.number == 0]

    gen = AddressGenerator(project.gewerk_catalog, variant=project.config.mg_variant)
    structure = gen.generate(
        project.areal, scenes=project.scenes, project=project, existing=central_only,
    )

    old_real = [ga for ga in old.all_addresses() if not ga.is_placeholder]
    manual = [ga for ga in old_real if ga.is_manual]
    by_key: dict[tuple, GroupAddress] = {}
    for ga in old_real:
        if not ga.is_manual:
            by_key.setdefault(_match_key(ga), ga)

    plan = RenumberPlan(structure=structure)
    matched: set[str] = set()
    for ga in structure.all_addresses():
        if ga.is_placeholder:
            continue
        prev = by_key.pop(_match_key(ga), None)
        if prev is None:
            plan.added.append(f"{ga.address} {ga.designation}")
            continue
        for name in _KEPT_FIELDS:
            setattr(ga, name, getattr(prev, name))
        matched.add(prev.id)
        if prev.address != ga.address:
            plan.address_map[prev.address] = ga.address
        if prev.address != ga.address or prev.designation != ga.designation:
            plan.changes.append(RenumberChange(
                prev.address, ga.address, prev.designation, ga.designation))

    # Manuelle GAs bleiben an ihrer Adresse (wie bei der Neuberechnung)
    for ga in manual:
        insert_ga(structure, ga)
        matched.add(ga.id)

    plan.removed = [f"{ga.address} {ga.designation}" for ga in old_real
                    if ga.id not in matched]
    plan.changes.sort(key=lambda c: _address_sort_key(c.new_address))
    plan.gaps_before = _floor_gaps(old)
    plan.gaps_after = _floor_gaps(structure)
    return plan


def _address_sort_key(address: str) -> tuple:
    return tuple(int(p) for p in address.split("/"))


def apply_renumbering(project, plan: RenumberPlan) -> int:
    """Übernimmt die neu geordnete Struktur und führt alle Verweise nach.
    Gibt die Anzahl nachgeführter Verweise zurück."""
    project.group_addresses = plan.structure
    return remap_ga_references(project, plan.address_map)


def remap_ga_references(project, address_map: dict[str, str]) -> int:
    """Ersetzt alte durch neue Adressen in allen Verweisen des Projekts.
    Gleichzeitige Zuordnung (kein Verketten), z.B. 2/0/5→2/0/0 und 2/0/0→2/0/3."""
    if not address_map:
        return 0
    count = 0

    def swap(value: str) -> str:
        nonlocal count
        m = _LEADING_ADDRESS.match(value or "")
        if not m or m.group(1) not in address_map:
            return value
        count += 1
        return address_map[m.group(1)] + value[m.end(1):]

    for room in project.all_rooms:
        for be in room.bedienelemente:
            for sf in be.funktionen:
                sf.ga_designation = swap(sf.ga_designation)
                for extra in sf.extra_gas:
                    extra.ga_designation = swap(extra.ga_designation)
            for fa in be.function_assignments:
                fa.function_ga = swap(fa.function_ga)

    for scene in project.scenes:
        scene.source_ga_addresses = [swap(a) for a in scene.source_ga_addresses]
        for action in scene.actions:
            action.ga_address = swap(action.ga_address)

    for gw in project.dali_configs.values():
        for name in ("ga_switch_broadcast", "ga_dim_broadcast", "ga_scene",
                     "ga_status_value", "ga_status_fault"):
            setattr(gw, name, swap(getattr(gw, name)))
        for group in gw.groups:
            for name in ("ga_switch", "ga_dim", "ga_value"):
                setattr(group, name, swap(getattr(group, name)))

    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                for co in device.communication_objects:
                    co.connected_gas = [swap(a) for a in co.connected_gas]

    return count
