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
    multi = len(areal.buildings) > 1
    for b_idx, building, name, apts in _zones(areal):
        if name:
            label = f"{building.name} / {name}" if multi and b_idx > 0 else name
            for apt in apts:
                lookup[apt.id] = label
    return lookup


def _zones(areal):
    """(Gebäude, Zonenname, [Apartment je Stockwerk]) je Zone und Flügel.

    Eine Zone über mehrere Stockwerke (Maisonette, EFH) besteht aus einem
    Apartment je Stockwerk mit gleichem Namen; massgebend ist das erste.
    """
    for b_idx, building in enumerate(areal.buildings):
        for wing in building.wings:
            zones: dict[str, list] = {}
            for floor in wing.floors:
                for apt in floor.apartments:
                    zones.setdefault(apt.name, []).append(apt)
            for name, apts in zones.items():
                yield b_idx, building, name, apts


def zone_choices(areal) -> list[tuple[str, str]]:
    """(Anzeige, scope_id) je Zone -- jede Zone einmal, auch wenn sie über
    mehrere Stockwerke geht; bei Nebengebäuden mit Gebäudename."""
    multi = len(areal.buildings) > 1
    return [
        (f"{building.name} / {name}" if multi and b_idx > 0 else name, apts[0].id)
        for b_idx, building, name, apts in _zones(areal) if name
    ]


def canonical_zone_id(areal, apt_id: str) -> str:
    """scope_id einer Zone: id des ersten Apartments gleichen Namens im
    selben Flügel (alle Stockwerke einer Zone teilen sich eine Szenen-GA)."""
    for _b_idx, _building, _name, apts in _zones(areal):
        if any(a.id == apt_id for a in apts):
            return apts[0].id
    return apt_id


def zone_room_ids(areal, apt_id: str) -> set[str] | None:
    """room_ids aller Stockwerke der Zone, zu der apt_id gehört (Maisonette,
    EFH: ein Apartment je Stockwerk mit gleichem Namen). None, wenn apt_id
    kein Apartment ist."""
    for _b_idx, _building, _name, apts in _zones(areal):
        if any(a.id == apt_id for a in apts):
            return {r.id for a in apts for r in a.rooms}
    return None


def normalize_scene_scopes(project) -> int:
    """Vereinheitlicht Zonen-Geltungsbereiche: scope "apartment" und die
    scope_id der Zone (nicht eines einzelnen Stockwerks). Gibt die Anzahl
    geänderter Szenen zurück."""
    changed = 0
    for scene in project.scenes:
        if scene.scope not in ("apartment", "zone") or not scene.scope_id:
            continue
        zone_id = canonical_zone_id(project.areal, scene.scope_id)
        if (scene.scope, scene.scope_id) != ("apartment", zone_id):
            scene.scope, scene.scope_id = "apartment", zone_id
            changed += 1
    return changed


def scene_group_key(scene) -> str:
    """Gruppierungsschluessel: Szenen mit gleichem scope_id teilen eine GA."""
    return scene.scope_id or "central"


def is_bound_scene(scene) -> bool:
    """Von Hand angelegte Szene, die eine bereits bestehende Szenen-GA
    mitbenutzt (z.B. weitere Szenennummer auf der importierten GA
    "LDA_M01_01 SZENE"). Erkennbar an source_ga_addresses bei
    is_detected=False -- für sie wird beim Generieren keine eigene
    Szenenaufruf-GA erzeugt."""
    return not scene.is_detected and bool(scene.source_ga_addresses)


def is_generated_scene_channel(ga) -> bool:
    """Von KNiX erzeugte Szenenaufruf-GA eines Geltungsbereichs («Szenenaufruf
    Studio», «ZENTRAL Szenenaufruf»): Funktion SZENE, ohne Gewerk-Element,
    nicht von Hand angelegt. Ihre Adresse folgt bei jeder GA-Generierung dem
    Geltungsbereich -- eine Szene bindet man nie an sie (feste
    Zentraladressen wie «ZENTRAL Anwesenheit Komplex» und Szenen-Eingänge
    der Gewerk-Elemente schon)."""
    return (ga is not None and ga.function_name == "SZENE" and not ga.gewerk_code
            and not ga.is_manual and "Szenenaufruf" in (ga.designation or ""))


def release_generated_bindings(project) -> int:
    """Geplante Szenen, die an eine selbst erzeugte Szenenaufruf-GA gebunden
    sind, wieder ihrem Geltungsbereich folgen lassen. Früher band
    «Übernehmen» in der Szenen-Verwaltung jede Szene an ihre aktuelle GA;
    die nächste GA-Generierung vergab die Adresse dann an einen anderen
    Geltungsbereich (Projekt_23: Studio-Szenen auf 0/4/2, das danach
    «Szenenaufruf Wohnung» hiess; 0/4/3 der Wohnung fiel weg). Die Aktion
    auf die eigene Szenen-Adresse zeigt wieder auf den eigenen Szenenaufruf.
    Nur geplante Projekte. Gibt die Anzahl gelöster Szenen zurück."""
    topology = getattr(project, "topology", None)
    if topology is not None and topology.is_imported:
        return 0
    by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    labels = build_scope_label_lookup(project.areal)
    released = 0
    for scene in project.scenes:
        if scene.is_detected or not scene.source_ga_addresses:
            continue
        gas = [by_address.get(a) for a in scene.source_ga_addresses]
        if not all(is_generated_scene_channel(ga) for ga in gas):
            continue
        own = scene_channel_designation(scene_group_key(scene), labels)
        bound = set(scene.source_ga_addresses)
        for action in scene.actions:
            if action.ga_address in bound:
                action.group_address, action.ga_address = own, ""
        scene.source_ga_addresses = []
        released += 1
    return released


def is_callable_scene(scene) -> bool:
    """Szene, die ein Taster gezielt aufrufen kann (Schritt 8,
    Bauherren-Formular): benannt und -- falls aus dem Import erkannt -- mit
    Szenennummer. Erkannte Szenen ohne Nummer (Nr. 0) sind nur der
    Szenenaufruf-Kanal selbst (z.B. "ZENTRAL Szenenaufruf")."""
    return bool(scene.name) and (not scene.is_detected or scene.scene_number > 0)


def scene_target_designation(scene, label_lookup: dict[str, str],
                             group_addresses=None) -> str:
    """Bezeichnung der GA, über die eine Szene aufgerufen wird: bei an eine
    bestehende GA gebundenen (oder erkannten) Szenen deren Bezeichnung,
    sonst die der gemeinsamen, generierten Szenenaufruf-GA."""
    if scene.source_ga_addresses and group_addresses is not None:
        by_addr = {ga.address: ga for ga in group_addresses.all_addresses()}
        for addr in scene.source_ga_addresses:
            if addr in by_addr:
                return by_addr[addr].designation
    return scene_channel_designation(scene_group_key(scene), label_lookup)


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
    An eine bestehende GA gebundene Szenen (is_bound_scene) brauchen keine
    generierte GA und fehlen daher.

    Gibt {group_key: (designation, [Scene, ...])} zurueck, sortiert ist die
    Iteration ueber das Ergebnis nicht -- Aufrufer sortieren bei Bedarf
    selbst (z.B. nach group_key) fuer deterministische Ausgabe.
    """
    label_lookup = build_scope_label_lookup(areal) if areal is not None else {}
    groups: dict[str, tuple[str, list]] = {}
    for scene in scenes:
        if not scene.name or scene.is_detected or is_bound_scene(scene):
            continue
        key = scene_group_key(scene)
        if key not in groups:
            groups[key] = (scene_channel_designation(key, label_lookup), [])
        groups[key][1].append(scene)
    return groups
