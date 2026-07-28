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

    @property
    def has_removed(self) -> bool:
        """True wenn Geräte/Räume aus dem alten Projekt im neuen Import nicht
        mehr gefunden wurden -- der riskante Fall, in dem KNiX-Planungsdaten
        (Gewerke, Bedienelemente, Materialliste, ...) verwaist sein könnten
        (z.B. durch Umbenennung/Löschung in ETS/Excel)."""
        return bool(self.devices_removed or self.rooms_removed)

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
        return " | ".join(parts)

    def details_text(self) -> str:
        """Mehrzeilige Detailauflistung der neuen/entfernten Geräte und Räume
        (für den Warndialog bei has_removed)."""
        lines = []
        if self.rooms_removed:
            lines.append("Räume nicht mehr gefunden: " + ", ".join(self.rooms_removed))
        if self.devices_removed:
            lines.append("Geräte nicht mehr gefunden: " + ", ".join(self.devices_removed))
        if self.rooms_new:
            lines.append("Neue Räume: " + ", ".join(self.rooms_new))
        if self.devices_new:
            lines.append("Neue Geräte: " + ", ".join(self.devices_new))
        return "\n".join(lines)


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

    Matching: Geräte über die physikalische Adresse, Räume über die
    Raumnummer -- beide bleiben über Export/Re-Import-Zyklen stabil, im
    Gegensatz zu den intern vergebenen UUIDs.

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
                    new_dev.order_number = old_dev.order_number
                # Felder, die der Import liefern kann, aber nicht muss: neuen
                # Wert übernehmen wenn vorhanden, sonst alten behalten
                if not new_dev.installation_location:
                    new_dev.installation_location = old_dev.installation_location
                if not new_dev.serial_number:
                    new_dev.serial_number = old_dev.serial_number
    devices_new = sorted(new_addrs - old_devices_by_addr.keys())
    devices_removed = sorted(old_devices_by_addr.keys() - new_addrs)

    old_rooms_by_number = {r.number: r for r in old_project.all_rooms if r.number}
    # Räume ohne Nummer (z.B. per XLSX aus dem Einbauort abgeleitete
    # Verteiler-Räume "HV"/"UV1" -- siehe XlsxImportService.create_verteiler_rooms)
    # werden über ihren Namen wiedererkannt, da sie keine Raumnummer haben.
    old_unnumbered_by_name = {
        r.name: r for r in old_project.all_rooms if not r.number and r.name
    }
    new_numbers: set[str] = set()
    new_unnumbered_names: set[str] = set()
    rooms_matched = 0
    for room in new_project.all_rooms:
        if room.number:
            new_numbers.add(room.number)
            old_room = old_rooms_by_number.get(room.number)
        else:
            if room.name:
                new_unnumbered_names.add(room.name)
            old_room = old_unnumbered_by_name.get(room.name) if room.name else None
        if not old_room:
            continue
        rooms_matched += 1
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
        (new_numbers - old_rooms_by_number.keys())
        | (new_unnumbered_names - old_unnumbered_by_name.keys())
    )
    rooms_removed = sorted(
        (old_rooms_by_number.keys() - new_numbers)
        | (old_unnumbered_by_name.keys() - new_unnumbered_names)
    )

    return ReimportDiff(
        devices_matched=devices_matched, devices_new=devices_new, devices_removed=devices_removed,
        rooms_matched=rooms_matched, rooms_new=rooms_new, rooms_removed=rooms_removed,
    )
