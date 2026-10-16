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


def next_taster_index(room) -> int:
    """Nächster freier Index für ein manuell gesetztes Bedienelement --
    weder von einem Gewerk noch von einem manuellen Element belegt."""
    used = {i for a in room.gewerk_assignments for i in a.taster_indices}
    used |= {be.taster_index for be in room.bedienelemente if not be.is_auto}
    return max(used, default=0) + 1


def add_bedienelement(room, element_type: str, channels: int) -> Bedienelement:
    """Bedienelement oder Melder von Hand in den Raum setzen (Bauherren-
    beratung, Gebäude): bleibt bei der Neuberechnung und bekommt dort sein
    Gerät in der Topologie."""
    be = Bedienelement(element_type=element_type, channels=channels, is_auto=False,
                       taster_index=next_taster_index(room))
    room.bedienelemente.append(be)
    return be


def fit_sensor_channels(be: Bedienelement) -> None:
    """Kanalzahl eines Sensors auf seine Funktionen verkleinern: ein
    entfernter oder verschobener Kanal hinterlässt keinen leeren Kanal
    (anders als bei einer Tastereinheit, deren Tasten es physisch gibt)."""
    used = sum(1 for sf in _main_functions(be) if sf.primary_role != "fremdsteuerung")
    if be.channels > max(1, used):
        be.channels = max(1, used)


def move_to_own_device(room, src_be: Bedienelement, sf: SensorFunktion,
                       element_type: str, labels: dict | None = None) -> Bedienelement:
    """Sensorkanal sf auf ein neues, eigenes Gerät element_type im selben
    Raum legen (z.B. Wassermelder neben dem Bewegungsmelder); die
    Neuberechnung gibt ihm eine eigene Teilnehmernummer."""
    new_be = Bedienelement(element_type=element_type, channels=1, is_auto=False,
                           taster_index=next_taster_index(room))
    room.bedienelemente.append(new_be)
    move_button(src_be, sf, new_be, labels=labels)
    fit_sensor_channels(src_be)
    return new_be


def bedienelement_of_device(project, device):
    """(Raum, Bedienelement) hinter einem Sensor-Gerät der Topologie, sonst
    (None, None). Geräte entstehen aus den Bedienelementen -- entfernt wird
    deshalb dort, sonst brächte die Neuberechnung das Gerät zurück."""
    if device.device_type != "sensor" or not device.physical_address:
        return None, None
    room = next((r for r in project.areal.all_rooms if r.id == device.room_id), None)
    if room is None:
        return None, None
    be = next((b for b in room.bedienelemente if not b.suppressed
               and b.participant_number == device.physical_address), None)
    return (room, be) if be is not None else (None, None)


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
