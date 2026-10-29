"""
Tote Verweise bereinigen, die KNiX selbst erzeugt hat (FA-624).

Beim Öffnen eines Projekts: Verweise auf GAs, Geräte, Bedienelemente,
Räume und Verteiler, die es nicht mehr gibt -- Reste früherer KNiX-Versionen
(z.B. neue Geräte- und Bedienelement-IDs bei jeder Neuberechnung bis
2026-10-16) oder gelöschter Elemente. Wo möglich wird neu verbunden, sonst
nur der Verweis entfernt; Einträge selbst (Prüfergebnisse, Materialliste,
FDSK) bleiben immer erhalten.

Nicht hier: was aus der ETS kommt. Das ändert KNiX nicht, es erscheint in
der Validierung (FA-625) und wird über die Korrekturschicht korrigiert.
"""
from __future__ import annotations


def clean_references(project) -> list[str]:
    """Bereinigt und gibt je Art eine Zeile für das Änderungsprotokoll zurück."""
    counts: dict[str, int] = {}

    def count(text: str, n: int = 1) -> None:
        if n:
            counts[text] = counts.get(text, 0) + n

    rooms = {r.id: r for r in project.all_rooms}
    ga_ids = {g.id for g in project.group_addresses.all_addresses()}
    lines = [l for a in project.topology.areas for l in a.lines]
    devices = [d for l in lines for d in l.devices]
    # Speisegeräte von Haupt- und Bereichslinie stehen nicht in line.devices
    devices += [sv for sv in [a.backbone_power_supply for a in project.topology.areas]
                + [project.topology.backbone_power_supply] if sv is not None]
    device_ids = {d.id for d in devices}
    verteiler_ids = {v.id for r in project.all_rooms for v in r.verteiler}

    for room in project.all_rooms:
        for a in room.gewerk_assignments:
            before = len(a.linked_ga_ids)
            a.linked_ga_ids = {k: g for k, g in a.linked_ga_ids.items() if g in ga_ids}
            count("Verknüpfung Gewerk → GA entfernt (GA gibt es nicht mehr)",
                  before - len(a.linked_ga_ids))
            for nr, links in list(a.linked_ga_ids_by_element.items()):
                kept = {k: g for k, g in links.items() if g in ga_ids}
                count("Verknüpfung Gewerk → GA entfernt (GA gibt es nicht mehr)",
                      len(links) - len(kept))
                if kept:
                    a.linked_ga_ids_by_element[nr] = kept
                else:
                    del a.linked_ga_ids_by_element[nr]

    for line in lines:
        before = len(line.assigned_room_ids)
        line.assigned_room_ids = [rid for rid in line.assigned_room_ids if rid in rooms]
        count("Linie: Zuteilung eines gelöschten Raums entfernt",
              before - len(line.assigned_room_ids))
        if line.verteiler_id and line.verteiler_id not in verteiler_ids:
            line.verteiler_id = ""
            count("Linie: Verweis auf gelöschten Verteiler entfernt")
        for actor_type, vt_id in list(line.actor_verteiler.items()):
            if vt_id not in verteiler_ids:
                del line.actor_verteiler[actor_type]
                count("Linie: Verweis auf gelöschten Verteiler entfernt")

    if not project.topology.is_imported:
        count("Sensor mit seinem Bedienelement verbunden (Datei vor 2026-10-16)",
              _index_legacy_sensors(project, devices))

    secure = project.knx_secure
    if not secure.is_locked:
        for device_id in [k for k, info in secure.device_infos.items()
                          if k not in device_ids and not info.fdsk]:
            del secure.device_infos[device_id]
            count("Secure: leerer Eintrag eines entfernten Geräts entfernt")

    for entry in project.material_list.entries:
        if entry.device_id and entry.device_id not in device_ids:
            entry.device_id = ""   # die Materialliste ordnet dann über die Adresse zu
            count("Materialliste: Verweis auf nicht mehr vorhandenes Gerät entfernt")

    # Checklisten gelöschter Räume: Ergebnisse über die Adresse dem Raum des
    # Geräts zuordnen, leere entfernen; der Rest bleibt für die Validierung
    from .checklist_repair import adopt_orphan_checklists
    moved, removed = adopt_orphan_checklists(project)
    count("Checkliste: Prüfergebnis über die Adresse dem heutigen Raum zugeordnet", moved)
    count("Checkliste eines nicht mehr vorhandenen Raums ohne Prüfergebnis entfernt", removed)

    # Checklisten: Prüfpunkt wieder mit dem Bedienelement verbinden (Typ und
    # Adresse im Raum), sonst nur den Verweis lösen -- das Prüfergebnis bleibt
    be_ids = {be.id for r in project.all_rooms for be in r.bedienelemente}
    for checklist in project.checklists:
        room = rooms.get(checklist.room_id)
        for item in checklist.items:
            if not item.be_id or item.be_id in be_ids:
                continue
            match = next((be for be in (room.bedienelemente if room else [])
                          if not be.suppressed and be.element_type == item.be_type
                          and be.participant_number == item.be_number), None)
            if match is not None:
                item.be_id = match.id
                count("Checkliste: Prüfpunkt wieder mit seinem Bedienelement verbunden")
            else:
                item.be_id = ""
                count("Checkliste: Verweis auf entferntes Bedienelement gelöst")

    return [f"{text}: {n}" for text, n in counts.items()]


def _index_legacy_sensors(project, devices) -> int:
    """Sensoren älterer Dateien kennen ihr Bedienelement nicht
    (Device.taster_index = 0): je Raum und Typ der Reihe nach zuordnen, wie
    es die Neuberechnung tut, und das Bedienelement mit der Adresse seines
    Geräts verbinden (link_bedienelemente_to_devices)."""
    from .sensor_service import link_bedienelemente_to_devices
    by_room_type: dict[tuple, list] = {}
    for d in devices:
        if d.device_type == "sensor" and d.room_id and not d.taster_index \
                and not d.manually_added:
            by_room_type.setdefault((d.room_id, d.product), []).append(d)
    if not by_room_type:
        return 0
    indexed = 0
    for room in project.all_rooms:
        bes: dict[str, list] = {}
        for be in room.bedienelemente:
            if not be.suppressed:
                bes.setdefault(be.element_type, []).append(be)
        for element_type, group in bes.items():
            legacy = by_room_type.get((room.id, element_type), [])
            for device, be in zip(legacy, sorted(group, key=lambda b: b.taster_index)):
                device.taster_index = be.taster_index
                indexed += 1
    link_bedienelemente_to_devices(project.topology, project.all_rooms)
    return indexed
