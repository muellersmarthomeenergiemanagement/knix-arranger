"""
Eine GA in Szenen aufnehmen (FA-1816): je Szene der Wert, den das Element
beim Aufruf annimmt, z.B. Rohrbegleitheizung 4/2/0 in "Anwesend" = Ein.

Die Szene erreicht das Element, wenn ihr Geltungsbereich den Raum der GA
umfasst (Raum, Zone/Wohnung über alle Stockwerke) oder zentral ist; nur über
diese Szenen-GA bekommt der Aktor den Aufruf.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models.scene import SceneAction
from .scene_addressing import zone_room_ids
from .scene_overview import build_scene_overview


@dataclass
class SceneSlot:
    scene: object            # Scene
    address: str             # Szenen-GA, "" wenn noch nicht erzeugt
    address_label: str      # Bezeichnung der Szenen-GA
    value: str | None        # Wert der GA in dieser Szene, None = nicht drin
    reaches: bool            # Geltungsbereich umfasst den Raum der GA


def _matches(action, ga) -> bool:
    return bool((action.ga_address and action.ga_address == ga.address)
                or (ga.designation and action.group_address == ga.designation))


def _reaches(project, scene, ga) -> bool:
    if scene.scope in ("", "central") or not scene.scope_id:
        return True
    if not ga.room_id:
        return False
    if scene.scope == "room":
        return scene.scope_id == ga.room_id
    rooms = zone_room_ids(project.areal, scene.scope_id)
    return rooms is not None and ga.room_id in rooms


def scene_slots(project, ga) -> list[SceneSlot]:
    """Alle Szenen (nach Szenen-GA geordnet) mit dem Wert der GA darin."""
    slots = []
    for group in build_scene_overview(project).addresses:
        for scene in group.scenes:
            value = next((a.value for a in scene.actions if _matches(a, ga)), None)
            slots.append(SceneSlot(
                scene=scene,
                address=group.ga.address if group.ga is not None else "",
                address_label=group.designation,
                value=value,
                reaches=_reaches(project, scene, ga),
            ))
    return slots


def set_scene_values(project, ga, values: dict) -> int:
    """values: Scene.id -> Wert (None = aus der Szene nehmen). Anzahl
    geänderter Szenen."""
    changed = 0
    for scene in project.scenes:
        if scene.id not in values:
            continue
        value = values[scene.id]
        mine = [a for a in scene.actions if _matches(a, ga)]
        if value is None:
            if mine:
                scene.actions = [a for a in scene.actions if not _matches(a, ga)]
                changed += 1
            continue
        if mine:
            if mine[0].value != value or mine[0].ga_address != ga.address:
                mine[0].value = value
                mine[0].ga_address = ga.address
                mine[0].group_address = ga.designation or mine[0].group_address
                changed += 1
            continue
        scene.actions.append(SceneAction(
            group_address=ga.designation or ga.address, ga_address=ga.address, value=value))
        changed += 1
    return changed


def value_choices(ga) -> list[str]:
    """Vorschläge für den Szenenwert nach DPT der GA."""
    dpt = (ga.datapoint_type or "").upper().replace("DPST-", "DPT-")
    main = dpt.split("-")[1] if dpt.count("-") >= 1 else ""
    if main == "1":
        return ["Ein", "Aus"]
    if main == "5":
        return ["100%", "75%", "50%", "25%", "0%"]
    if main == "9":
        return ["21 °C", "20 °C", "18 °C", "16 °C"]
    return []
