"""
Tasten verschieben und tauschen, Bedienelement entfernen (Bauherrenberatung,
FA-1015 e).

Eine Taste ist eine SensorFunktion in be.funktionen. Ihre Nummer ergibt sich
bei geplanten Projekten aus der Reihenfolge ("Taste 3" = dritte Taste), bei
importierten aus der Bezeichnung ("Taste 2, links"). Verschoben wird deshalb
das SensorFunktion-Objekt selbst; eine Bezeichnung mit Position bleibt an
ihrer Stelle. Mit der Taste wandern
- ihr langer Tastendruck (press_of, bzw. "(langer Tastendruck)" im Namen),
- ihre eigene Bezeichnung für die Bedienungsanleitung
  (ets_corrections.button_labels, Schlüssel nach Taste).
Beide Tasten liegen im selben Raum (source_room_id "" = eigener Raum).
"""
from __future__ import annotations

import re

from ..models.building import Bedienelement, SensorFunktion, long_press_of
from .bedienelement_layout import ButtonKey, parse_button

_POSITION_RE = re.compile(r"^taste\s*\d+\s*,\s*(links|rechts)\b", re.IGNORECASE)


def has_position(label: str) -> bool:
    """Bezeichnung mit physischer Lage, z.B. "Taste 2, links" (ETS-Import)."""
    return bool(_POSITION_RE.match((label or "").strip()))


def _main_functions(be: Bedienelement) -> list[SensorFunktion]:
    return [sf for sf in be.funktionen if not sf.press_of]


def button_keys(be: Bedienelement) -> dict[str, ButtonKey]:
    """Taste je SensorFunktion wie bei der Funktionszuordnung
    (SensorService): Bezeichnung mit Taste, sonst fortlaufende Nummer."""
    keys: dict[str, ButtonKey] = {}
    number = 0
    for sf in _main_functions(be):
        if not (sf.gewerk_code or sf.ga_designation or sf.label):
            continue
        number += 1
        parsed = parse_button(sf.label) if sf.label != sf.ga_designation else None
        keys[sf.id] = parsed[0] if parsed else ButtonKey(number)
    return keys


def _pin_long_presses(be: Bedienelement) -> None:
    """Lange Tastendrücke, die nur über den Namen zu ihrer Taste gehören,
    fest verknüpfen -- der Name kann sich gleich ändern."""
    for sf in _main_functions(be):
        long_sf = long_press_of(be.funktionen, sf)
        if long_sf is not None and not long_sf.press_of:
            long_sf.press_of = sf.id


def _move_long_presses(sf: SensorFunktion, src: Bedienelement, dst: Bedienelement) -> None:
    if src is dst:
        return
    for other in [o for o in src.funktionen if o.press_of == sf.id]:
        src.funktionen.remove(other)
        dst.funktionen.append(other)


def _label_key(be: Bedienelement, key: ButtonKey) -> str:
    from .user_manual import button_label_key
    return button_label_key(be, key)


def _own_labels(be: Bedienelement, labels: dict) -> dict[str, tuple[str, str]]:
    """Eigene Bezeichnungen je SensorFunktion-ID: {sf.id: (Schlüssel, Text)}
    (nur Tasten ohne Variante, wie in der Bauherrenberatung erfasst)."""
    result = {}
    for sf_id, key in button_keys(be).items():
        label_key = _label_key(be, ButtonKey(key.number, key.side))
        if labels.get(label_key):
            result[sf_id] = (label_key, labels[label_key])
    return result


def _apply_own_labels(bes: list[Bedienelement], before: dict[str, tuple[str, str]],
                      labels: dict) -> None:
    """Bezeichnungen den Tasten nachführen: alte Schlüssel weg, unter dem
    neuen Schlüssel der Taste wieder eintragen."""
    for label_key, _text in before.values():
        labels.pop(label_key, None)
    owners = {sf.id: be for be in bes for sf in be.funktionen}
    for sf_id, (_old_key, text) in before.items():
        be = owners.get(sf_id)
        key = button_keys(be).get(sf_id) if be else None
        if key is not None:
            labels[_label_key(be, ButtonKey(key.number, key.side))] = text


def move_button(src_be: Bedienelement, sf: SensorFunktion, dst_be: Bedienelement,
                target: SensorFunktion | None = None, target_label: str = "",
                labels: dict | None = None) -> None:
    """Taste sf auf target legen: belegt = tauschen, None = auf die freie
    Taste verschieben (bei geplanten Projekten ans Ende der Tastereinheit,
    bei importierten an die Position target_label, z.B. "Taste 3, links")."""
    if sf is target:
        return
    labels = labels if labels is not None else {}
    bes = [src_be] if src_be is dst_be else [src_be, dst_be]
    before = {sf_id: entry for be in bes for sf_id, entry in _own_labels(be, labels).items()}
    for be in bes:
        _pin_long_presses(be)

    if target is None:
        src_be.funktionen.remove(sf)
        dst_be.funktionen.append(sf)
        # Position übernehmen; ein Freitext-Wunsch behält seinen Text
        if has_position(sf.label) or (target_label and not sf.label):
            sf.label = target_label
    else:
        i, j = src_be.funktionen.index(sf), dst_be.funktionen.index(target)
        src_be.funktionen[i], dst_be.funktionen[j] = target, sf
        if has_position(sf.label) or has_position(target.label):
            sf.label, target.label = target.label, sf.label
        _move_long_presses(target, dst_be, src_be)
    _move_long_presses(sf, src_be, dst_be)

    for be in bes:
        be.is_auto = False   # bleibt bei der Neuberechnung erhalten
    _apply_own_labels(bes, before, labels)


def remove_bedienelement(room, be: Bedienelement) -> None:
    """Bedienelement entfernen: ein automatisch vorgeschlagenes bleibt
    unterdrückt (sonst schlägt die Neuberechnung es wieder vor), ein
    manuell angelegtes wird gelöscht."""
    if be.is_auto:
        be.is_auto = False
        be.suppressed = True
        be.funktionen = []
        be.function_assignments = []
    elif be in room.bedienelemente:
        room.bedienelemente.remove(be)
