"""
Verweise zwischen den Teilen eines Projekts prüfen: zeigt jede ID, Adresse
und GA-Bezeichnung auf etwas, das es gibt?

Entstanden aus der Datenstruktur-Prüfung 2026-10-16 (Projekt_23): Geräte,
Bedienelemente und Tasten bekamen bei jeder Neuberechnung neue IDs, Verweise
darauf (Secure-Archiv, Materialliste, DALI, Checklisten) gingen ins Leere,
ohne dass es auffiel. Die Prüfung liest nur.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrityIssue:
    kind: str       # Art des Verweises, z.B. "Secure: Gerät fehlt"
    detail: str     # betroffenes Element


def check_integrity(project) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []

    def bad(kind: str, detail: str) -> None:
        issues.append(IntegrityIssue(kind, detail))

    imported = project.topology.is_imported
    rooms = {r.id: r for r in project.all_rooms}
    lines = {l.id: l for a in project.topology.areas for l in a.lines}
    devices = [d for l in lines.values() for d in l.devices]
    # Speisegeräte von Haupt- und Bereichslinie stehen nicht in line.devices
    devices += [sv for sv in [a.backbone_power_supply for a in project.topology.areas]
                + [project.topology.backbone_power_supply] if sv is not None]
    device_ids = {d.id for d in devices}
    gas = project.group_addresses.all_addresses()
    ga_ids = {g.id for g in gas}
    ga_addresses = {g.address for g in gas}
    ga_designations = {g.designation for g in gas}

    def ga_known(text: str) -> bool:
        if not text:
            return True
        return text.split()[0] in ga_addresses or text in ga_designations

    # Nicht hier, weil die Validierung sie schon meldet: doppelte Adressen
    # (FA-612), KO auf fehlende GA (FA-611), Zeitprogramm auf fehlende GA (FA-3306)
    for g in gas:
        if g.room_id and g.room_id not in rooms:
            bad("GA: Raum fehlt", g.address)
    for d in devices:
        if d.room_id and d.room_id not in rooms:
            bad("Gerät: Raum fehlt", d.physical_address)
    line_of_room = Counter(rid for l in lines.values() for rid in l.assigned_room_ids)
    for l in lines.values():
        for rid in l.assigned_room_ids:
            if rid not in rooms:
                bad("Linie: Raum fehlt", l.coupler_address)

    for r in project.all_rooms:
        for be in r.bedienelemente:
            if be.suppressed:
                continue
            here = f"{r.number} {r.name}: {be.element_type}".strip()
            if be.participant_number:
                same = [d for d in devices if d.physical_address == be.participant_number]
                if not same:
                    bad("Bedienelement: Gerät fehlt", f"{here} {be.participant_number}")
                elif not imported and all(d.room_id != r.id for d in same):
                    bad("Bedienelement: Gerät in anderem Raum", f"{here} {be.participant_number}")
                elif not imported and same[0].product and same[0].product != be.element_type:
                    bad("Bedienelement: anderer Gerätetyp",
                        f"{here} / {same[0].product} {be.participant_number}")
            elif not imported and line_of_room.get(r.id):
                bad("Bedienelement: ohne Gerät", here)
            sf_ids = {sf.id for sf in be.funktionen}
            for sf in be.funktionen:
                if sf.source_room_id and sf.source_room_id not in rooms:
                    bad("Taste: Raum fehlt", here)
                if sf.press_of and sf.press_of not in sf_ids:
                    bad("Langer Tastendruck: Taste fehlt", here)
                if sf.scene_id and not any(s.id == sf.scene_id for s in project.scenes):
                    bad("Taste: Szene fehlt", here)
                if sf.ga_designation and not sf.scene_id and not ga_known(sf.ga_designation):
                    bad("Taste: GA fehlt", f"{here} {sf.ga_designation}")
                for extra in sf.extra_gas:
                    if not ga_known(extra.ga_designation):
                        bad("Taste: weitere GA fehlt", f"{here} {extra.ga_designation}")
            for fa in be.function_assignments:
                if fa.sf_id and fa.sf_id not in sf_ids:
                    bad("Zuordnung: Taste fehlt", here)
                if fa.function_ga and not ga_known(fa.function_ga):
                    bad("Zuordnung: GA fehlt", f"{here} {fa.function_ga}")
        for a in r.gewerk_assignments:
            refs = list(a.linked_ga_ids.values()) + [
                gid for m in a.linked_ga_ids_by_element.values() for gid in m.values()]
            if any(gid not in ga_ids for gid in refs):
                bad("Gewerk: verknüpfte GA fehlt", f"{r.number} {r.name}: {a.gewerk_code}")

    for s in project.scenes:
        for act in s.actions:
            for value in (act.ga_address, act.group_address):
                if value and not ga_known(value):
                    bad("Szene: GA fehlt", f"{s.name}: {value}")
    for gw in project.dali_configs.values():
        if gw.gateway_device_id and gw.gateway_device_id not in device_ids:
            bad("DALI: Gateway fehlt", gw.gateway_address or gw.name)
        for dd in gw.devices:
            if dd.room_id and dd.room_id not in rooms:
                bad("DALI: Raum fehlt", dd.name)
    for device_id, info in project.knx_secure.device_infos.items():
        # Ohne FDSK räumt update_device_compatibility den Eintrag auf; mit
        # FDSK bleibt er im Archiv, gehört aber zu keinem Gerät mehr
        if device_id not in device_ids and info.fdsk:
            bad("Secure: FDSK ohne Gerät", f"{info.physical_address} {info.device_name}".strip())
    for e in project.material_list.entries:
        if e.device_id and e.device_id not in device_ids:
            bad("Materialliste: Gerät fehlt", e.product_name or e.device_type)
    be_ids = {be.id for r in project.all_rooms for be in r.bedienelemente}
    for cl in project.checklists:
        if cl.room_id and cl.room_id not in rooms:
            bad("Checkliste: Raum fehlt", cl.room_name)
        for item in cl.items:
            if item.be_id and item.be_id not in be_ids:
                bad("Checkliste: Bedienelement fehlt", f"{cl.room_name} {item.be_type}")
    verteiler_ids = {v.id for r in project.all_rooms for v in r.verteiler}
    for l in lines.values():
        if l.verteiler_id and l.verteiler_id not in verteiler_ids:
            bad("Linie: Verteiler fehlt", l.coupler_address)
    return issues
