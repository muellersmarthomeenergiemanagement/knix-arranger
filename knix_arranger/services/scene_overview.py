"""
Szenen nach Szenen-Gruppenadresse gliedern (FA-1811, FA-1812).

Gemeinsame Grundlage für die Szenen-Verwaltung und den Szenenreport: die
Szenen-GA überträgt die Szenennummer (DPT 17.001/18.001, Szene 1–64 = Bytewert
0–63), Aktoren und Taster sind mit ihr verknüpft. Deshalb steht die Adresse
zuoberst, darunter die Szenennummern.

Einteilung:
- Szenen-Adressen: bestehende GA mit Szenen-DPT, Szenennummern oder geplanten
  Szenen; geplante Szenen ohne generierte GA bilden eine "künftige" Adresse
  je Geltungsbereich (entsteht beim Generieren),
- Visualisierung: über einzelne Schalt-Adressen ausgelöste Szenen (z.B.
  UniPro H/M/L/0) – keine KNX-Szenenadressen,
- nicht eindeutig: beim Import erkannte Adressen ohne Szenen-DPT und ohne
  Szenennummern (zur Fehlersuche).
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .dpt_suggestion import dpt_number
from .report_sorting import group_address_key, physical_address_key, room_order
from .scene_addressing import (
    build_scope_label_lookup, is_generated_scene_channel, scene_channel_designation,
    scene_group_key,
)

SCOPE_LABELS = {
    "room": "Raum",
    "apartment": "Wohnung/Zone",
    "zone": "Zone",
    "central": "Zentral",
}


def is_scene_dpt(datapoint_type: str) -> bool:
    """DPT-Nummer 17.xxx/18.xxx (knxproj) oder Anzeigetext aus dem GA-Report
    ("Szenennummer", "Szenensteuerung", "Szene")."""
    dpt = datapoint_type or ""
    return dpt_number(dpt).split(".")[0] in ("17", "18") or dpt.lower().startswith("szene")


@dataclass
class LinkedDevice:
    device: object
    sends: bool                 # Taster/Sensor/Visu-Gateway sendet, Aktor empfängt
    objects: list[str]          # "17: Ausgang A - 8-Bit-Szene"

    @property
    def role(self) -> str:
        return "sendet" if self.sends else "empfängt"


@dataclass
class SceneAddress:
    """Eine Szenen-Gruppenadresse mit ihren Szenen."""
    key: str                            # GA-Adresse oder "geplant:<Bezeichnung>"
    designation: str
    ga: object = None                   # GroupAddress, None = noch nicht generiert
    scenes: list = field(default_factory=list)   # Szenennummer >= 1, sortiert
    channel: object = None              # Kanal-Eintrag der Erkennung (Nr. 0)

    @property
    def planned(self) -> bool:
        return self.ga is None

    @property
    def all_scenes(self) -> list:
        return ([self.channel] if self.channel else []) + self.scenes

    @property
    def anchor_scene(self):
        """Szene, deren Geltungsbereich für die Adresse gilt."""
        return self.channel or (self.scenes[0] if self.scenes else None)

    @property
    def dpt_ok(self) -> bool:
        return self.ga is None or is_scene_dpt(self.ga.datapoint_type)

    def free_number(self) -> int:
        used = {s.scene_number for s in self.scenes}
        return next((n for n in range(1, 65) if n not in used), 0)


@dataclass
class SceneOverview:
    addresses: list[SceneAddress] = field(default_factory=list)
    visu: list = field(default_factory=list)
    unclear: list[SceneAddress] = field(default_factory=list)

    def address_of(self, scene):
        for group in self.addresses + self.unclear:
            if any(s is scene for s in group.all_scenes):
                return group
        return None


def scene_scope_sort_key(project):
    """Zentral, Zone, Wohnung, Raum; Räume in Gebäude-Reihenfolge,
    Wohnungen/Zonen nach Name; darin nach Szenennummer."""
    scope_rank = {"central": 0, "zone": 1, "apartment": 2, "room": 3}
    order = room_order(project.areal)
    names = {apt.id: apt.name or "" for floor in project.areal.all_floors
             for apt in floor.apartments}

    def key(scene):
        if scene.scope == "room":
            target = (order.get(scene.scope_id, len(order)), "")
        else:
            target = (0, names.get(scene.scope_id, scene.scope_id or ""))
        return (scope_rank.get(scene.scope, 4), target, scene.scene_number or 0, scene.name or "")
    return key


def scene_target_ga(project, scene, label_lookup: dict, ga_by_address: dict | None = None):
    """Tatsächliche Szenen-GA einer Szene, None wenn (noch) keine existiert:
    gebundene/erkannte Szenen über source_ga_addresses, geplante über die
    generierte Szenenaufruf-GA ihres Geltungsbereichs."""
    if ga_by_address is None:
        ga_by_address = {g.address: g for g in project.group_addresses.all_addresses()}
    if scene.source_ga_addresses:
        return next((ga_by_address[a] for a in scene.source_ga_addresses
                     if a in ga_by_address), None)
    designation = scene_channel_designation(scene_group_key(scene), label_lookup)
    return next((g for g in ga_by_address.values()
                 if g.function_name == "SZENE" and g.designation == designation), None)


def is_fixed_scene_address(ga) -> bool:
    """Bestehende Szenen-GA, an die man Szenen bindet: feste Zentraladresse
    («SZ_ZE_01 SZENE (Abwesenheit)») oder von Hand angelegt -- nicht der
    erzeugte Szenenaufruf eines Geltungsbereichs, keine Reserve und kein
    Szenen-Eingang eines Gewerk-Elements."""
    return (ga.function_name == "SZENE" and not ga.is_placeholder
            and not ga.gewerk_code and not is_generated_scene_channel(ga))


def build_scene_overview(project, include_empty: bool = False) -> SceneOverview:
    """include_empty: feste Szenen-Adressen ohne Szenen mitzeigen (Szenen-
    Verwaltung, damit sich Szenen darauf legen lassen); nur geplante Projekte."""
    label_lookup = build_scope_label_lookup(project.areal)
    ga_by_address = {g.address: g for g in project.group_addresses.all_addresses()}
    groups: dict[str, SceneAddress] = {}
    overview = SceneOverview()

    for scene in project.scenes:
        if not scene.name:
            continue
        if scene.detection_kind == "pattern":
            overview.visu.append(scene)
            continue
        ga = scene_target_ga(project, scene, label_lookup, ga_by_address)
        if ga is not None:
            key, designation = ga.address, ga.designation
        else:
            designation = scene_channel_designation(scene_group_key(scene), label_lookup)
            key = f"geplant:{designation}"
        group = groups.setdefault(key, SceneAddress(key=key, designation=designation, ga=ga))
        if scene.is_detected and not scene.scene_number and group.channel is None:
            group.channel = scene
        else:
            group.scenes.append(scene)

    imported = getattr(getattr(project, "topology", None), "is_imported", False)
    if include_empty and not imported:
        for ga in ga_by_address.values():
            if ga.address not in groups and is_fixed_scene_address(ga):
                groups[ga.address] = SceneAddress(
                    key=ga.address, designation=ga.designation, ga=ga)

    for group in groups.values():
        if not group.all_scenes:
            overview.addresses.append(group)
            continue
        group.scenes.sort(key=lambda s: (s.scene_number or 99, s.name))
        planned_scenes = any(not s.is_detected for s in group.scenes)
        numbered = any(s.scene_number for s in group.scenes)
        if group.planned or is_scene_dpt(group.ga.datapoint_type) or numbered or planned_scenes:
            overview.addresses.append(group)
        else:
            overview.unclear.append(group)

    # Bestehende Adressen numerisch, künftige (geplante) nach Geltungsbereich
    scope_key = scene_scope_sort_key(project)

    def order(group: SceneAddress):
        if group.ga is not None:
            return (0, group_address_key(group.ga.address))
        anchor = group.anchor_scene
        return (1, scope_key(anchor)[:2] if anchor else (), group.designation)
    overview.addresses.sort(key=order)
    overview.unclear.sort(key=order)
    overview.visu.sort(key=lambda s: min(
        (group_address_key(a) for a in s.source_ga_addresses), default=(999,)))
    return overview


def _sends(device, cos) -> bool:
    """Sender oder Empfänger anhand der KNX-Flags der verknüpften Objekte:
    Übertragen (knxproj "U", GA-Report "Ü") = sendet, Schreiben ("S") =
    empfängt. Ohne Flags oder mit beiden entscheidet der Gerätetyp – ein
    DALI-Gateway empfängt Szenen, ein Taster oder Visu-Gateway sendet."""
    from .ko_links import TRANSMIT, WRITE, parse_flags
    flags = set().union(*(parse_flags(co.flags) for co in cos)) if cos else set()
    transmit = TRANSMIT in flags
    write = WRITE in flags
    if transmit != write:
        return transmit
    return device.device_type not in ("actor", "gateway")


def linked_devices(project, address: str) -> list[LinkedDevice]:
    """Geräte, deren Kommunikationsobjekte mit der Adresse verknüpft sind –
    Sender (Taster, Sensoren, Visualisierung) zuerst, danach die Empfänger
    (Aktoren, Gateways); je Gerät die betroffenen Objekte."""
    result = []
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                cos = [co for co in sorted(device.communication_objects,
                                           key=lambda c: c.object_number)
                       if address in co.connected_gas]
                if cos:
                    result.append(LinkedDevice(
                        device=device, sends=_sends(device, cos),
                        objects=[f"{co.object_number}: "
                                 + " – ".join(p for p in (co.name, co.object_function) if p)
                                 for co in cos]))
    result.sort(key=lambda d: (not d.sends, physical_address_key(d.device.physical_address)))
    return result


def scope_text(scene, label_lookup: dict) -> str:
    text = SCOPE_LABELS.get(scene.scope, scene.scope or "Zentral")
    if scene.scope_id:
        text += f": {label_lookup.get(scene.scope_id, scene.scope_id)}"
    return text


def resolve_legacy_scene_id(candidates: list) -> str:
    """Fallback für SensorFunktionen aus der Zeit vor scene_id: 'candidates'
    sind alle Szenen, die sich denselben Szenenaufruf-Kanal (sf.ga_designation)
    teilen. Nur bei genau einer Szene auf dem Kanal ist die Zuordnung sicher.
    Bewusst kein Text-Abgleich auf sf.label bei mehreren Kandidaten: die Szenen
    eines Kanals heissen oft ähnlich ("Anwesend"/"Abwesend") – ein falscher
    Treffer wäre eine stille Falschaussage, schlimmer als eine fehlende Zeile.
    Die Schritt-8-UI markiert mehrdeutige Fälle zum manuellen Neusetzen."""
    return candidates[0].id if len(candidates) == 1 else ""


def scene_trigger_index(project, snapshot: bool = True) -> dict[str, list[str]]:
    """scene.id -> Klartext aller Taster/Bedienelemente, die die Szene per
    SensorFunktion (bedienart "Szene abrufen", Schritt 11) aufrufen, z.B.
    "Raum E01 Wohnen, Taster 1.1.5, Taste 3". Im Unterschied zu Scene.trigger
    (freies Notizfeld) die tatsächlich konfigurierte Zuordnung – auch mehrere
    Taster je Szene. Gemeinsam für Szenen-Verwaltung und Szenenreport.

    snapshot=False liest die Tastenbelegung direkt aus dem Projekt (Anzeige;
    sie ist nach jeder Änderung aktuell) statt aus einer frisch abgeleiteten
    Kopie (Berichte)."""
    from .scene_addressing import scene_target_designation
    from .sensor_service import project_for_export
    label_lookup = build_scope_label_lookup(project.areal)
    scenes_by_channel: dict[str, list] = {}
    for s in project.scenes:
        if not s.name or s.is_detected:
            continue
        designation = scene_target_designation(s, label_lookup, project.group_addresses)
        scenes_by_channel.setdefault(designation, []).append(s)

    # Tastennummern aus einer Kopie mit aktueller Tastenbelegung – liest nur
    # (siehe sensor_service.project_for_export)
    index: dict[str, list[str]] = {}
    for room in (project_for_export(project) if snapshot else project).all_rooms:
        for be in room.bedienelemente:
            if be.suppressed:
                continue
            for sf in be.funktionen:
                scene_id = sf.scene_id
                if not scene_id and sf.bedienart == "Szene abrufen" and sf.ga_designation:
                    scene_id = resolve_legacy_scene_id(
                        scenes_by_channel.get(sf.ga_designation, []))
                if not scene_id:
                    continue
                button = next((fa.button_channel for fa in be.function_assignments
                               if fa.sf_id == sf.id and fa.button_channel), "")
                addr = be.participant_number or "(keine Adresse)"
                parts = [f"Raum {room.number} {room.name}", f"Taster {addr}"]
                if button:
                    parts.append(button)
                index.setdefault(scene_id, []).append(", ".join(parts))
    return index


def scene_triggers(scene, trigger_index: dict[str, list[str]]) -> list[str]:
    """Auslöser einer Szene: konfigurierte Taster, danach die Einträge des
    Notizfelds Scene.trigger (durch "; " getrennt), ohne Doppelte."""
    lines = list(trigger_index.get(scene.id, []))
    lines += [t for t in (scene.trigger or "").split("; ") if t and t not in lines]
    return lines
