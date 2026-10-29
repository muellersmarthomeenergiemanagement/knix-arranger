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

import re

#: Feste Szenen-Zentraladresse 0/4/1 trägt SZ_ZE_01, der zentrale
#: Szenenaufruf deshalb SZ_ZE_02 (BZ-07)
CENTRAL_SCENE_CHANNEL = "SZ_ZE_02 SZENE (zentral)"
_GENERATED_CHANNEL_RE = re.compile(r"^SZ_[A-Z0-9][A-Z0-9_.\-]*_\d{2} SZENE \(")


class ScopeLabels(dict):
    """id -> Klartextname; .codes: id -> Ort und Nummer der Szenenaufruf-GA
    ("EG_06_01" für einen Raum, "EG_01" für die erste Zone des Stockwerks)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.codes: dict[str, str] = {}


def build_scope_label_lookup(areal) -> ScopeLabels:
    """id -> Klartextname fuer alle Raeume/Wohnungen/Zonen eines Areals,
    dazu der Ortsteil der Szenenaufruf-GAs (ScopeLabels.codes)."""
    from .naming_engine import label_floor_code
    lookup = ScopeLabels()
    floor_of_apartment = {}
    for building in areal.buildings:
        for floor in building.all_floors:
            for apt in floor.apartments:
                floor_of_apartment[apt.id] = floor
                for room in apt.rooms:
                    number = room.number or "00"
                    code = label_floor_code(floor.short_code, number)
                    lookup.codes[room.id] = f"{code}_{number}_01" if code else f"{number}_01"
    for room in areal.all_rooms:
        if room.name:
            lookup[room.id] = room.name
    multi = len(areal.buildings) > 1
    zones_per_floor: dict[str, int] = {}
    for b_idx, building, name, apts in _zones(areal):
        floor = floor_of_apartment.get(apts[0].id)
        place = (floor.short_code if floor is not None else "") or "ZE"
        zones_per_floor[place] = zones_per_floor.get(place, 0) + 1
        for apt in apts:
            lookup.codes[apt.id] = f"{place}_{zones_per_floor[place]:02d}"
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
    if ga is None or ga.function_name != "SZENE" or ga.gewerk_code or ga.is_manual:
        return False
    designation = ga.designation or ""
    # Bis 1.4.27 «Szenenaufruf Studio», seither «SZ_EG_06_01 SZENE (Studio)»;
    # 0/4/1 (SZ_ZE_01) ist die feste Zentraladresse
    return "Szenenaufruf" in designation or (
        bool(_GENERATED_CHANNEL_RE.match(designation)) and ga.address != "0/4/1")


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
    """Szene, die ein Taster gezielt aufrufen kann (Schritt 11,
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
    """Bezeichnung der gemeinsamen Szenenaufruf-GA fuer eine Gruppe (BZ-07):
    "SZ_EG_06_01 SZENE (Studio)", zentral "SZ_ZE_02 SZENE (zentral)". Ohne
    Ortsteil (label_lookup kein ScopeLabels) die Bezeichnung vor 1.4.28."""
    if group_key == "central":
        return CENTRAL_SCENE_CHANNEL
    code = getattr(label_lookup, "codes", {}).get(group_key)
    if not code:
        return legacy_channel_designation(group_key, label_lookup)
    return f"SZ_{code} SZENE ({label_lookup.get(group_key, group_key)})"


def legacy_channel_designation(group_key: str, label_lookup: dict[str, str]) -> str:
    """Bezeichnung bis 1.4.27 ("Szenenaufruf Studio"), für die Umstellung."""
    if group_key == "central":
        return "ZENTRAL Szenenaufruf"
    return f"Szenenaufruf {label_lookup.get(group_key, group_key)}"


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


def adopt_bz07_designations(project) -> int:
    """Bezeichnungen bis 1.4.27 auf BZ-07 umstellen ("ZENTRAL Alle Lichter
    AUS" -> "L_ZE_01 AUS (alle Lichter)", "Szenenaufruf Studio" ->
    "SZ_EG_06_01 SZENE (Studio)"): die GAs und alles, was eine GA über ihre
    Bezeichnung findet (Tasten, Szenen-Aktionen, Checklisten). Nur geplante
    Projekte -- importierte Bezeichnungen stammen aus der ETS. Gibt die
    Anzahl umgestellter GAs zurück."""
    topology = getattr(project, "topology", None)
    if topology is not None and topology.is_imported:
        return 0
    from .address_generator import _FIXED_CENTRAL_ADDRESSES, LEGACY_CENTRAL_DESIGNATIONS
    labels = build_scope_label_lookup(project.areal)
    channels = {legacy_channel_designation(key, labels): scene_channel_designation(key, labels)
                for key in [*labels.codes, "central"]}
    renamed: dict[str, str] = {}
    by_address: dict[str, str] = {}
    for ga in project.group_addresses.all_addresses():
        old = ga.designation or ""
        if ga.address in _FIXED_CENTRAL_ADDRESSES and old in LEGACY_CENTRAL_DESIGNATIONS:
            new = LEGACY_CENTRAL_DESIGNATIONS[old]
        elif old in channels and is_generated_scene_channel(ga):
            new = channels[old]
        else:
            continue
        ga.designation = renamed[old] = new
        by_address[ga.address] = new
    if not renamed:
        return 0

    def follow(text: str) -> str:
        # "Szenenaufruf Studio" oder mit Adresse "0/4/2  Szenenaufruf Studio"
        if text in renamed:
            return renamed[text]
        address, sep, rest = text.partition(" ")
        rest = rest.lstrip()
        if sep and rest in renamed and by_address.get(address) == renamed[rest]:
            return text[:len(text) - len(rest)] + renamed[rest]
        return text

    for room in project.all_rooms:
        for be in room.bedienelemente:
            for fa in be.function_assignments:
                fa.function_ga = follow(fa.function_ga)
            for sf in be.funktionen:
                sf.ga_designation = follow(sf.ga_designation)
                for extra in sf.extra_gas:
                    extra.ga_designation = follow(extra.ga_designation)
    for scene in project.scenes:
        for action in scene.actions:
            action.group_address = follow(action.group_address)
    for checklist in getattr(project, "checklists", []):
        for item in checklist.items:
            item.function_ga = follow(item.function_ga)
    return len(renamed)


def channel_scope_keys(scenes, areal) -> dict[str, str]:
    """Bezeichnung der Szenenaufruf-GA -> Geltungsbereich, für jede Gruppe
    benannter Szenen; auch die Bezeichnung bis 1.4.27 (noch nicht
    umgestellte Daten, z.B. ältere Sicherungen)."""
    labels = build_scope_label_lookup(areal) if areal is not None else {}
    result = {}
    for key, (designation, _scenes) in group_named_scenes(scenes, areal).items():
        result[designation] = key
        result.setdefault(legacy_channel_designation(key, labels), key)
    return result
