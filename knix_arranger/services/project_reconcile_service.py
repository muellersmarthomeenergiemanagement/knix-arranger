"""
Projekt-Abgleich nach Re-Import (FA-521/FA-511/FA-519b).

Gilt gleichermassen für alle Import-Wege, die Topologie/Gebäudestruktur eines
laufenden Projekts ersetzen -- .knxproj (ETS6-Projektdatei) UND XLSX
(Topologie-/GA-Report) --, daher hier als eigenständiger, formatunabhängiger
Service statt an einen bestimmten Importservice gebunden.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from ..models.project import KnxProject
from ..models.group_address import GroupAddress, MainGroup, MiddleGroup
from ..models.building import Room


@dataclass
class ReimportDiff:
    """Ergebnis von reconcile_reimport() -- Zusammenfassung, was sich seit dem
    letzten Import/Re-Import geändert hat (für Statusmeldung, Warndialog und
    Änderungsprotokoll)."""
    devices_matched: int = 0
    devices_new: list[str] = field(default_factory=list)       # physikalische Adressen
    devices_removed: list[str] = field(default_factory=list)   # physikalische Adressen
    rooms_matched: int = 0
    rooms_new: list[str] = field(default_factory=list)         # Raumnummern
    rooms_removed: list[str] = field(default_factory=list)     # Raumnummern
    manual_gas_restored: int = 0
    manual_gas_conflicts: list[str] = field(default_factory=list)  # Adressen "HG/MG/UG"

    @property
    def has_removed(self) -> bool:
        """True wenn Geräte/Räume aus dem alten Projekt im neuen Import nicht
        mehr gefunden wurden -- der riskante Fall, in dem KNiX-Planungsdaten
        (Gewerke, Bedienelemente, Materialliste, ...) verwaist sein könnten
        (z.B. durch Umbenennung/Löschung in ETS/Excel)."""
        return bool(self.devices_removed or self.rooms_removed)

    @property
    def has_ga_conflicts(self) -> bool:
        """True wenn manuell hinzugefügte GAs wegen einer Adresskollision mit
        dem frischen Import nicht wiederhergestellt werden konnten."""
        return bool(self.manual_gas_conflicts)

    def summary_line(self) -> str:
        """Kurze einzeilige Zusammenfassung für Statusleiste/Änderungsprotokoll."""
        parts = [f"{self.devices_matched} Geräte / {self.rooms_matched} Räume wiedererkannt"]
        if self.devices_new:
            parts.append(f"{len(self.devices_new)} neue Geräte")
        if self.devices_removed:
            parts.append(f"{len(self.devices_removed)} Geräte nicht mehr gefunden")
        if self.rooms_new:
            parts.append(f"{len(self.rooms_new)} neue Räume")
        if self.rooms_removed:
            parts.append(f"{len(self.rooms_removed)} Räume nicht mehr gefunden")
        if self.manual_gas_restored:
            parts.append(f"{self.manual_gas_restored} manuelle GA(s) wiederhergestellt")
        if self.manual_gas_conflicts:
            parts.append(f"{len(self.manual_gas_conflicts)} manuelle GA(s) mit Adresskonflikt")
        return " | ".join(parts)

    def details_text(self) -> str:
        """Mehrzeilige Detailauflistung der neuen/entfernten Geräte und Räume
        sowie GA-Adresskonflikte (für den Warndialog bei has_removed /
        has_ga_conflicts)."""
        lines = []
        if self.rooms_removed:
            lines.append("Räume nicht mehr gefunden: " + ", ".join(self.rooms_removed))
        if self.devices_removed:
            lines.append("Geräte nicht mehr gefunden: " + ", ".join(self.devices_removed))
        if self.rooms_new:
            lines.append("Neue Räume: " + ", ".join(self.rooms_new))
        if self.devices_new:
            lines.append("Neue Geräte: " + ", ".join(self.devices_new))
        if self.manual_gas_conflicts:
            lines.append(
                "Manuelle Gruppenadressen mit Adresskonflikt (nicht übernommen, "
                "da der Import inzwischen eine andere GA auf dieser Adresse anlegt): "
                + ", ".join(self.manual_gas_conflicts)
            )
        return "\n".join(lines)


def _rooms_by_floor_and_number(project: KnxProject) -> dict[tuple[str, str], Room]:
    """Nummerierte Räume, indiziert über (Stockwerk-Kurzcode, Raumnummer).

    Raumnummern werden pro Stockwerk vergeben und wiederholen sich über
    Stockwerke hinweg (z.B. Raum "01" auf UG UND EG) -- die Nummer allein
    ist daher kein stabiler Matching-Key, siehe reconcile_reimport()."""
    result: dict[tuple[str, str], Room] = {}
    for building in project.areal.buildings:
        for wing in building.wings:
            for floor in wing.floors:
                for apartment in floor.apartments:
                    for room in apartment.rooms:
                        if room.number:
                            result[(floor.short_code, room.number)] = room
    return result


def _room_label(floor_code: str, number: str) -> str:
    """Menschenlesbares Label für rooms_new/rooms_removed. Ohne Stockwerk-
    Kurzcode (z.B. bei Projekten ohne Stockwerk-Zuordnung) bleibt es die
    reine Raumnummer, wie zuvor."""
    return f"{floor_code}/{number}" if floor_code else number


def reconcile_reimport(old_project: KnxProject, new_project: KnxProject) -> ReimportDiff:
    """Gleicht einen frisch importierten/neu abgeleiteten Projektstand mit dem
    bisherigen ab (.knxproj-Re-Import ODER erneuter XLSX-Import).

    Ein reiner Neu-Import (egal ob .knxproj oder XLSX) vergibt für jeden Raum
    und jedes Gerät neue, zufällige interne IDs. Ohne Abgleich würden bei
    jedem erneuten Import (Export → Anpassung in ETS/Excel → Re-Import, ggf.
    mehrfach) alle darauf aufbauenden Verknüpfungen verwaisen: Materialliste
    (MaterialEntry.device_id), KNX-Secure-Archiv (DeviceSecureInfo.device_id),
    DALI-Gateway-Zuordnung (DaliConfig.gateway_device_id) sowie sämtliche
    raumgebundene KNiX-Planungsdaten (Gewerk-Zuweisungen, Bedienelemente/
    Tastereinheiten, Verteiler, Bauherr-Notizen) -- weder ETS noch der
    XLSX-Report kennen diese Konzepte, der neu geparste Raum enthält sie
    daher nicht.

    Matching: Geräte über die physikalische Adresse, Räume über Stockwerk +
    Raumnummer -- beide bleiben über Export/Re-Import-Zyklen stabil, im
    Gegensatz zu den intern vergebenen UUIDs. Das Stockwerk ist Teil des
    Room-Matching-Keys, da Raumnummern pro Stockwerk neu vergeben werden und
    sich über Stockwerke hinweg wiederholen (z.B. Raum "01" auf UG UND EG) --
    ein reiner Nummer-Abgleich würde solche gleichnummerigen Räume auf
    denselben alten Raum zusammenführen und Geräte des einen Raums fälschlich
    im anderen erscheinen lassen.

    Mutiert new_project in place (übernimmt alte IDs + KNiX-Zusatzdaten in
    die frisch geparsten Objekte). Gibt einen ReimportDiff zurück
    (Statusmeldung, Warndialog bei entfernten Geräten/Räumen, Änderungs-
    protokoll-Eintrag).
    """
    old_devices_by_addr = {
        d.physical_address: d
        for area in old_project.topology.areas
        for line in area.lines
        for d in line.devices
        if d.physical_address
    }
    new_addrs: set[str] = set()
    devices_matched = 0
    for area in new_project.topology.areas:
        for line in area.lines:
            for new_dev in line.devices:
                new_addrs.add(new_dev.physical_address)
                old_dev = old_devices_by_addr.get(new_dev.physical_address)
                if not old_dev:
                    continue
                devices_matched += 1
                new_dev.id = old_dev.id
                # Rein KNiX-seitige Felder, die weder ETS noch XLSX liefern -- immer übernehmen
                new_dev.datasheets = old_dev.datasheets
                new_dev.manually_split = old_dev.manually_split
                new_dev.manually_added = old_dev.manually_added
                new_dev.manual_functions = old_dev.manual_functions
                # Produktzuweisung aus der Materialliste (product_name wird nie
                # vom Import gesetzt) inkl. der dazugehörigen Hersteller-/
                # Bestellnummer übernehmen -- sonst würden die generischen
                # Hardware-Werte aus dem Import die zugewiesenen Produktdaten
                # überschreiben
                if old_dev.product_name:
                    new_dev.product_name = old_dev.product_name
                    new_dev.manufacturer = old_dev.manufacturer
                    new_dev.manufacturer_id = old_dev.manufacturer_id
                    new_dev.order_number = old_dev.order_number
                # Felder, die der Import liefern kann, aber nicht muss: neuen
                # Wert übernehmen wenn vorhanden, sonst alten behalten
                if not new_dev.installation_location:
                    new_dev.installation_location = old_dev.installation_location
                if not new_dev.serial_number:
                    new_dev.serial_number = old_dev.serial_number
    devices_new = sorted(new_addrs - old_devices_by_addr.keys())
    devices_removed = sorted(old_devices_by_addr.keys() - new_addrs)

    old_rooms_by_floor_nr = _rooms_by_floor_and_number(old_project)
    # Räume ohne Nummer (z.B. per XLSX aus dem Einbauort abgeleitete
    # Verteiler-Räume "HV"/"UV1" -- siehe XlsxImportService.create_verteiler_rooms)
    # werden über ihren Namen wiedererkannt, da sie keine Raumnummer haben.
    old_unnumbered_by_name = {
        r.name: r for r in old_project.all_rooms if not r.number and r.name
    }
    new_keys: set[tuple[str, str]] = set()
    new_unnumbered_names: set[str] = set()
    rooms_matched = 0
    # (frische Raum-ID vor dem Überschreiben) -> (alte, wiederhergestellte ID).
    # Wird gebraucht, weil link_rooms_to_lines() VOR reconcile_reimport()
    # läuft (siehe XlsxImportService.link_rooms_to_lines/main_window.py) und
    # device.room_id/line.assigned_room_ids daher schon auf die frische ID
    # zeigen, bevor wir sie hier unten auf die alte umbiegen -- ohne Remap
    # blieben diese Verweise auf einer ID hängen, die kein Raum mehr trägt
    # (betrifft v.a. unnummerierte Verteiler-Räume "HV"/"UV1"/..., die bei
    # jedem Import neu angelegt werden, siehe create_verteiler_rooms).
    room_id_remap: dict[str, str] = {}
    for building in new_project.areal.buildings:
        for wing in building.wings:
            for floor in wing.floors:
                for apartment in floor.apartments:
                    for room in apartment.rooms:
                        if room.number:
                            key = (floor.short_code, room.number)
                            new_keys.add(key)
                            old_room = old_rooms_by_floor_nr.get(key)
                        else:
                            if room.name:
                                new_unnumbered_names.add(room.name)
                            old_room = (
                                old_unnumbered_by_name.get(room.name) if room.name else None
                            )
                        if not old_room:
                            continue
                        rooms_matched += 1
                        if room.id != old_room.id:
                            room_id_remap[room.id] = old_room.id
                        room.id = old_room.id
                        room.gewerk_assignments = old_room.gewerk_assignments
                        room.bedienelemente = old_room.bedienelemente
                        room.verteiler = old_room.verteiler
                        room.te_types = old_room.te_types
                        room.te_count = old_room.te_count
                        room.bauherr_notes = old_room.bauherr_notes
                        room.planned_sensors = old_room.planned_sensors
                        room.planned_actors = old_room.planned_actors
                        if not room.name:
                            room.name = old_room.name
    rooms_new = sorted(
        _room_label(fc, nr) for fc, nr in (new_keys - old_rooms_by_floor_nr.keys())
    ) + sorted(new_unnumbered_names - old_unnumbered_by_name.keys())
    rooms_removed = sorted(
        _room_label(fc, nr) for fc, nr in (old_rooms_by_floor_nr.keys() - new_keys)
    ) + sorted(old_unnumbered_by_name.keys() - new_unnumbered_names)

    if room_id_remap:
        for area in new_project.topology.areas:
            for line in area.lines:
                line.assigned_room_ids = [
                    room_id_remap.get(rid, rid) for rid in line.assigned_room_ids
                ]
                for dev in line.devices:
                    if dev.room_id in room_id_remap:
                        dev.room_id = room_id_remap[dev.room_id]

    # Manuell hinzugefügte Gruppenadressen (is_manual=True) übernehmen -- der
    # frische Import ersetzt new_project.group_addresses vollständig und kennt
    # diese GAs nicht (weder ETS noch der XLSX-Report liefern sie). Nur bei
    # Adresskollision mit einer frisch importierten GA wird sie ausgelassen,
    # um deren echte ETS-Daten nicht zu überschreiben.
    manual_gas_restored = 0
    manual_gas_conflicts: list[str] = []
    for ga in old_project.group_addresses.all_addresses():
        if not ga.is_manual:
            continue
        if new_project.group_addresses.find_address(ga.main_group, ga.middle_group, ga.sub_group):
            manual_gas_conflicts.append(ga.address)
            continue
        _insert_ga(new_project.group_addresses, ga)
        manual_gas_restored += 1

    return ReimportDiff(
        devices_matched=devices_matched, devices_new=devices_new, devices_removed=devices_removed,
        rooms_matched=rooms_matched, rooms_new=rooms_new, rooms_removed=rooms_removed,
        manual_gas_restored=manual_gas_restored, manual_gas_conflicts=manual_gas_conflicts,
    )


def _insert_ga(structure, ga: GroupAddress) -> None:
    """Fügt eine GA in die passende HG/MG der Struktur ein (legt sie an falls nötig)."""
    hg = next((h for h in structure.main_groups if h.number == ga.main_group), None)
    if not hg:
        hg = MainGroup(number=ga.main_group, name=f"HG {ga.main_group}")
        structure.main_groups.append(hg)
        structure.main_groups.sort(key=lambda h: h.number)

    mg = next((m for m in hg.middle_groups if m.number == ga.middle_group), None)
    if not mg:
        mg = MiddleGroup(number=ga.middle_group, name=f"MG {ga.middle_group}")
        hg.middle_groups.append(mg)
        hg.middle_groups.sort(key=lambda m: m.number)

    mg.group_addresses.append(ga)
    mg.group_addresses.sort(key=lambda g: g.sub_group)
