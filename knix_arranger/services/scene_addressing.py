"""
Gemeinsame Namens-/Gruppierungslogik fuer Szenenaufruf-Gruppenadressen.

KNX-Konvention (DPT 17.001/18.001): EINE Gruppenadresse traegt einen
1-Byte-Wert 0-63, ueber den bis zu 64 Szenen adressiert werden (Szene N ->
Wert N-1); welcher Aktor bei welcher Nummer was tut, ist ausschliesslich in
dessen eigenen Parametern hinterlegt, nicht auf Busebene sichtbar. Diese App
bildet das nach, indem alle Szenen mit demselben Geltungsbereich (scope +
scope_id) sich eine gemeinsame Szenenaufruf-GA teilen; Scene.scene_number
wird zum gesendeten Byte-Wert (scene_number - 1).

Wird von zwei Seiten genutzt, die dieselbe Gruppierung/Benennung kennen
muessen:
- address_generator.py: erzeugt die gemeinsame GA beim Generieren (Schritt 7).
- scene_detection_service.py: verhindert, dass diese generierte GA bei einem
  spaeteren "Szenen erkennen" als neue, doppelte Szene auftaucht.
"""
from __future__ import annotations


def build_scope_label_lookup(areal) -> dict[str, str]:
    """id -> Klartextname fuer alle Raeume/Wohnungen/Zonen eines Areals."""
    lookup: dict[str, str] = {}
    for room in areal.all_rooms:
        if room.name:
            lookup[room.id] = room.name
    for floor in areal.all_floors:
        for apt in floor.apartments:
            if apt.name:
                lookup[apt.id] = apt.name
    return lookup


def scene_group_key(scene) -> str:
    """Gruppierungsschluessel: Szenen mit gleichem scope_id teilen eine GA."""
    return scene.scope_id or "central"


def scene_channel_designation(group_key: str, label_lookup: dict[str, str]) -> str:
    """Bezeichnung der gemeinsamen Szenenaufruf-GA fuer eine Gruppe."""
    if group_key == "central":
        return "ZENTRAL Szenenaufruf"
    label = label_lookup.get(group_key, group_key)
    return f"Szenenaufruf {label}"


def scene_value_mapping_text(group_scenes) -> str:
    """Klartext-Zuordnung Bytewert -> Szenenname fuer die description der
    gemeinsamen Szenenaufruf-GA, z.B. '0=Abwesenheit, 1=Dinner' -- macht in
    der GA-Liste sichtbar, welche Szenen sich die generische GA teilen, ohne
    dass man das erst in der Szenen-Ansicht nachschlagen muss."""
    parts = [
        f"{scene.scene_number - 1}={scene.name}"
        for scene in sorted(group_scenes, key=lambda s: s.scene_number)
        if scene.scene_number > 0
    ]
    return ", ".join(parts)


def group_named_scenes(scenes, areal) -> dict[str, tuple[str, list]]:
    """Gruppiert benannte, nicht-erkannte Szenen nach gemeinsamer Ziel-GA.

    Gibt {group_key: (designation, [Scene, ...])} zurueck, sortiert ist die
    Iteration ueber das Ergebnis nicht -- Aufrufer sortieren bei Bedarf
    selbst (z.B. nach group_key) fuer deterministische Ausgabe.
    """
    label_lookup = build_scope_label_lookup(areal) if areal is not None else {}
    groups: dict[str, tuple[str, list]] = {}
    for scene in scenes:
        if not scene.name or scene.is_detected:
            continue
        key = scene_group_key(scene)
        if key not in groups:
            groups[key] = (scene_channel_designation(key, label_lookup), [])
        groups[key][1].append(scene)
    return groups
