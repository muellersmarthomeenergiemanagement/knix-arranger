"""
Gruppenadressen per Ziehen umsortieren (FA-1015 d) – nur geplante Projekte.

- GA auf eine andere GA derselben Hauptgruppe ziehen: die beiden tauschen
  ihre Adressen.
- GA(s) auf eine Mittelgruppe derselben Hauptgruppe ziehen: sie wandern auf
  die nächsten freien Untergruppen dieser Mittelgruppe.

Jede GA behält ihre id und ihren Inhalt; Verweise auf die Adressen (Taster,
Szenen, DALI, Kommunikationsobjekte) werden nachgeführt. Die Neuberechnung
ordnet bestehende GAs über Element und Funktion zu (address_generator.
_in_slot_order), die neue Position bleibt also erhalten.

Nicht verschiebbar: HG 0 (Zentraladressen, wie beim Neu ordnen, FA-703) und
in Variante B die Rückmeldungen in MG 6/7 – sie liegen deckungsgleich zu
ihrem Befehl und wandern beim Tausch des Befehls mit. Bei aus der ETS
importierten oder in die ETS übertragenen Projekten gilt die ETS.
"""
from __future__ import annotations

from ..models.group_address import GroupAddress, GroupAddressStructure, MiddleGroup
from .renumber_service import remap_ga_references

_FEEDBACK_SUFFIX = ":fb"
_MAX_SUB = 255


def can_reorder(project) -> bool:
    """Ziehen nur bei geplanten Projekten, die noch nicht in der ETS sind."""
    return not project.addresses_fixed


def is_draggable(ga: GroupAddress) -> bool:
    return ga.main_group != 0 and not ga.assignment_id.endswith(_FEEDBACK_SUFFIX)


def can_swap(a: GroupAddress, b: GroupAddress) -> bool:
    return (a is not b and is_draggable(a) and is_draggable(b)
            and a.main_group == b.main_group)


def can_move_to_middle_group(gas: list[GroupAddress], main: int, middle: int) -> bool:
    return (bool(gas) and main != 0
            and all(is_draggable(ga) and ga.main_group == main for ga in gas)
            and any(ga.middle_group != middle for ga in gas))


def _middle_group(structure: GroupAddressStructure, main: int,
                  middle: int) -> MiddleGroup | None:
    hg = next((h for h in structure.main_groups if h.number == main), None)
    if hg is None:
        return None
    return next((m for m in hg.middle_groups if m.number == middle), None)


def _feedback_partner(structure: GroupAddressStructure,
                      ga: GroupAddress) -> GroupAddress | None:
    """Deckungsgleiche Rückmeldung einer Variante-B-Befehls-GA (MG 0/1 →
    MG 6/7, gleiche Untergruppe, gleicher Block)."""
    if structure.variant != "B" or ga.middle_group not in (0, 1) or not ga.assignment_id:
        return None
    mg = _middle_group(structure, ga.main_group, ga.middle_group + 6)
    if mg is None:
        return None
    key = ga.assignment_id + _FEEDBACK_SUFFIX
    return next((fb for fb in mg.group_addresses
                 if fb.sub_group == ga.sub_group and fb.assignment_id == key), None)


def _relocate(structure: GroupAddressStructure, ga: GroupAddress,
              middle: int, sub: int) -> None:
    """Setzt die Adresse einer GA und hängt sie in die richtige MG um."""
    if ga.middle_group != middle:
        old = _middle_group(structure, ga.main_group, ga.middle_group)
        if old is not None and ga in old.group_addresses:
            old.group_addresses.remove(ga)
        new = _middle_group(structure, ga.main_group, middle)
        new.group_addresses.append(ga)
    ga.middle_group = middle
    ga.sub_group = sub


def swap_addresses(project, a: GroupAddress, b: GroupAddress) -> dict[str, str]:
    """Tauscht die Adressen zweier GAs (mit ihren Rückmeldungen in Variante B)
    und führt alle Verweise nach. Gibt die Zuordnung alt → neu zurück."""
    if not can_swap(a, b):
        return {}
    structure = project.group_addresses
    fa, fb = _feedback_partner(structure, a), _feedback_partner(structure, b)
    address_map: dict[str, str] = {}

    def swap(x: GroupAddress, y: GroupAddress) -> None:
        address_map[x.address], address_map[y.address] = y.address, x.address
        (xm, xs), (ym, ys) = (x.middle_group, x.sub_group), (y.middle_group, y.sub_group)
        _relocate(structure, x, ym, ys)
        _relocate(structure, y, xm, xs)

    if fa and fb:
        swap(fa, fb)
    elif (fa or fb) and a.middle_group == b.middle_group:
        # Nur eine Seite hat eine Rückmeldung: sie wandert auf die
        # Untergruppe des Tauschpartners mit
        lone, sub = (fa, b.sub_group) if fa else (fb, a.sub_group)
        address_map[lone.address] = f"{lone.main_group}/{lone.middle_group}/{sub}"
        lone.sub_group = sub
    swap(a, b)
    _sort(structure)
    remap_ga_references(project, address_map)
    return address_map


def move_to_middle_group(project, gas: list[GroupAddress], main: int,
                         middle: int) -> dict[str, str]:
    """Verschiebt GAs auf die nächsten freien Untergruppen einer MG derselben
    HG (in ihrer bisherigen Reihenfolge). Gibt alt → neu zurück; leer, wenn
    nicht möglich (andere HG, MG voll)."""
    if not can_move_to_middle_group(gas, main, middle):
        return {}
    structure = project.group_addresses
    target = _middle_group(structure, main, middle)
    if target is None:
        return {}
    moving = sorted((ga for ga in gas if ga.middle_group != middle),
                    key=lambda g: (g.middle_group, g.sub_group))
    next_sub = max((ga.sub_group for ga in target.group_addresses), default=-1) + 1
    if next_sub + len(moving) - 1 > _MAX_SUB:
        return {}
    address_map: dict[str, str] = {}
    for ga in moving:
        address_map[ga.address] = f"{main}/{middle}/{next_sub}"
        _relocate(structure, ga, middle, next_sub)
        next_sub += 1
    _sort(structure)
    remap_ga_references(project, address_map)
    return address_map


def _sort(structure: GroupAddressStructure) -> None:
    for hg in structure.main_groups:
        for mg in hg.middle_groups:
            mg.group_addresses.sort(key=lambda g: g.sub_group)
