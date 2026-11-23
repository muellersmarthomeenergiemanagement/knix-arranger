"""
Projekt neu aus ETS aufbauen (FA-527).

Anders als der Re-Import (project_reconcile_service) übernimmt der Neuaufbau
keine Planungsdaten aus dem bisherigen Stand: Gebäudestruktur, Topologie,
Gruppenadressen, Gewerke, Bedienelemente, Szenen, DALI und Materialliste
entstehen frisch aus den ETS-Dateien. Behalten wird nur, was die ETS nicht
liefert und was der Anwender ausgewählt hat (REBUILD_OPTIONS).
"""
from __future__ import annotations
from dataclasses import dataclass

from ..models.project import KnxProject


@dataclass(frozen=True)
class RebuildOption:
    key: str
    label: str
    detail: str
    default: bool
    attributes: tuple[str, ...]


REBUILD_OPTIONS: tuple[RebuildOption, ...] = (
    RebuildOption(
        "project_info", "Projekteigenschaften",
        "Projektname und -nummer, Adresse, Standort, Einstellungen",
        True, ("name", "project_number", "created", "project_info", "location", "config")),
    RebuildOption(
        "client_profile", "Kundenprofil", "Bauherr, Kontaktdaten, Deckblatt",
        True, ("client_profile",)),
    RebuildOption(
        "ets_corrections", "Korrekturen zur ETS",
        "In KNiX korrigierte Angaben: Gewerk einer GA, Raum eines Geräts, "
        "getrennte Verknüpfungen, Tastenbezeichnungen für den Bauherrn",
        True, ("ets_corrections",)),
    RebuildOption(
        "ets_worklist", "Stand der ETS-Arbeitsliste",
        "Damit der nächste Import zeigt, was in der ETS erledigt wurde",
        True, ("ets_worklist",)),
    RebuildOption(
        "knx_secure", "KNX-Secure-Archiv",
        "Gerätezertifikate (FDSK), Passwörter, Master-Passwort",
        True, ("knx_secure",)),
    RebuildOption(
        "commercial", "Offerten und Lieferanten",
        "Kundenofferten, Lieferanten, Preisanfragen",
        True, ("customer_quotes", "suppliers", "quotation_requests")),
    RebuildOption(
        "custom_gewerke", "Eigene Gewerke und Vorlagen",
        "Selbst angelegte Gewerke und Gewerk-Vorlagen",
        True, ("custom_gewerke", "custom_gewerk_templates")),
    RebuildOption(
        "changelog", "Änderungsprotokoll", "Bisherige Einträge des Protokolls",
        True, ("changelog",)),
    RebuildOption(
        "line_plans", "Umbau-Varianten der Linien",
        "Geplante Aufteilung von Linien (Geräte über die physikalische Adresse wiedererkannt)",
        True, ("line_plans",)),
    RebuildOption(
        "extension_plans", "Erweiterungen im Bestand",
        "Geplante Erweiterungen (Räume über die Raumnummer wiedererkannt)",
        True, ("extension_plans",)),
    RebuildOption(
        "bus_recordings", "Busmonitor-Mitschnitte",
        "Eingelesene Mitschnitte der Busanalyse (Zusammenfassung)",
        True, ("bus_recordings",)),
    RebuildOption(
        "bus_connection", "Busverbindung", "Schnittstelle des Live-Monitors",
        True, ("bus_connection",)),
    RebuildOption(
        "bauherr_notes", "Notizen der Bauherrenberatung",
        "Raumnotizen, Anmerkungen und Datenblätter je Bedienelement "
        "(über Raumnummer bzw. physikalische Adresse wiedererkannt)",
        True, ()),
    RebuildOption(
        "manual_settings", "Anpassungen der Bedienungsanleitung",
        "Eigene Texte, Fotos und Sprache", True, ("manual_settings",)),
    RebuildOption(
        "revisions", "Revisionen", "Verlauf der Revisionspakete",
        True, ("revisions",)),
    RebuildOption(
        "verteiler_rooms", "Zuordnung Verteiler → Raum",
        "In Schritt 3b gewählte Zielräume der Verteiler",
        False, ("verteiler_room_overrides",)),
    RebuildOption(
        "time_programs", "Zeitprogramme", "Selbst angelegte Zeitschaltprogramme",
        False, ("time_programs",)),
    RebuildOption(
        "commissioning", "Inbetriebnahme",
        "Checklisten und Abnahmeprotokoll (beziehen sich auf die bisherigen Geräte)",
        False, ("checklists", "acceptance_protocol")),
)

# Frisch aus den ETS-Dateien, nie übernommen: Gebäudestruktur, Topologie,
# Gruppenadressen, Szenen, DALI, Materialliste, Verteiler-Zuordnungen.
REBUILT_FROM_ETS = (
    "Gebäudestruktur mit Räumen, Gewerken und Bedienelementen",
    "Topologie und Geräte",
    "Gruppenadressen",
    "Szenen",
    "DALI-Konfiguration",
    "Materialliste",
)


def default_keep() -> set[str]:
    return {o.key for o in REBUILD_OPTIONS if o.default}


def adopt_device_ids(old: KnxProject, imported: KnxProject) -> int:
    """Gibt frisch importierten Geräten die ID des bisherigen Geräts mit
    derselben physikalischen Adresse – sonst nichts (anders als der
    Re-Import-Abgleich). Nötig, weil das KNX-Secure-Archiv die Zertifikate
    nach Geräte-ID ablegt, auch im verschlüsselten Teil eines gesperrten
    Archivs; ohne dieselben IDs wären sie nach dem Neuaufbau verwaist.
    Muss direkt nach dem Einlesen laufen, bevor andere Daten die IDs
    verwenden. Gibt die Anzahl übernommener IDs zurück."""
    old_ids = {
        d.physical_address: d.id
        for area in old.topology.areas for line in area.lines for d in line.devices
        if d.physical_address and not d.physical_address.endswith("-")
    }
    adopted = 0
    for area in imported.topology.areas:
        for line in area.lines:
            for device in line.devices:
                old_id = old_ids.get(device.physical_address)
                if old_id:
                    device.id = old_id
                    adopted += 1
    return adopted


def adopt_report_params(old: KnxProject, imported: KnxProject) -> int:
    """Tastenparameter und Szenenwerte aus früher eingelesenen ETS-Reports
    übernehmen, wo die .knxproj sie nicht liefert (siehe keep_report_params).
    Gibt die Anzahl Geräte zurück."""
    from .project_reconcile_service import keep_report_params
    old_devices = {
        d.physical_address: d
        for area in old.topology.areas for line in area.lines for d in line.devices
        if d.physical_address
    }
    kept = 0
    for area in imported.topology.areas:
        for line in area.lines:
            for device in line.devices:
                old_dev = old_devices.get(device.physical_address)
                if old_dev and keep_report_params(old_dev, device):
                    kept += 1
    return kept


def _rooms_by_key(project) -> dict:
    from .ets_corrections import room_key
    return {room_key(floor, room): room
            for building in project.areal.buildings
            for floor in building.all_floors for room in floor.all_rooms}


def _count_bauherr_notes(project) -> int:
    count = 0
    for room in _rooms_by_key(project).values():
        count += bool(room.bauherr_notes)
        count += sum(1 for be in room.bedienelemente
                     if be.participant_number and (be.bauherr_annotation or be.datasheets))
    return count


def adopt_bauherr_notes(old: KnxProject, fresh: KnxProject) -> int:
    """Notizen der Bauherrenberatung nach dem Neuaufbau zurückholen: Raum-
    notizen über den Raumschlüssel ("EG|08"), Anmerkung und Datenblätter
    eines Bedienelements über die physikalische Adresse des Geräts (IDs
    überleben den Neuaufbau nicht). Gibt die Anzahl übernommener Notizen
    zurück."""
    old_rooms = _rooms_by_key(old)
    old_bes = {(be.participant_number, be.taster_index): be
               for room in old_rooms.values() for be in room.bedienelemente
               if be.participant_number}
    adopted = 0
    for key, room in _rooms_by_key(fresh).items():
        old_room = old_rooms.get(key)
        if old_room is not None and old_room.bauherr_notes and not room.bauherr_notes:
            room.bauherr_notes = old_room.bauherr_notes
            adopted += 1
        for be in room.bedienelemente:
            old_be = (old_bes.get((be.participant_number, be.taster_index))
                      if be.participant_number else None)
            if old_be is None or not (old_be.bauherr_annotation or old_be.datasheets):
                continue
            be.bauherr_annotation = be.bauherr_annotation or old_be.bauherr_annotation
            be.datasheets = be.datasheets or list(old_be.datasheets)
            adopted += 1
    return adopted


def kept_content(option: RebuildOption, project) -> str:
    """Was eine Option im bisherigen Projekt enthält: "" = nichts, sonst die
    Anzahl oder "vorhanden" -- für den Hinweis, was beim Neuaufbau ohne
    diese Option verloren geht."""
    if project is None:
        return ""
    if option.key == "bauherr_notes":
        count = _count_bauherr_notes(project)
        return str(count) if count else ""
    total, present = 0, False
    for attr in option.attributes:
        value = getattr(project, attr, None)
        if isinstance(value, (list, dict, tuple, set)):
            total += len(value)
        elif hasattr(value, "__dataclass_fields__"):
            try:
                present = present or value != type(value)()
            except TypeError:
                present = True
        elif value:
            present = True
    if total:
        return str(total)
    return "vorhanden" if present else ""


def lost_content(keep: set[str], project) -> list[str]:
    """Abgewählte Optionen, die im bisherigen Projekt Daten haben, z.B.
    ["Zeitprogramme (2)", "Inbetriebnahme (vorhanden)"]."""
    lost = []
    for option in REBUILD_OPTIONS:
        if option.key in keep:
            continue
        content = kept_content(option, project)
        if content:
            lost.append(f"{option.label} ({content})")
    return lost


def build_fresh_project(old: KnxProject, keep: set[str]) -> KnxProject:
    """Leeres Projekt am selben Speicherort, mit den gewählten Teilen des
    bisherigen Projekts (Objekte werden übernommen, nicht kopiert – das alte
    Projekt wird danach verworfen)."""
    fresh = KnxProject(name=old.name, project_number=old.project_number)
    for option in REBUILD_OPTIONS:
        if option.key in keep:
            for attr in option.attributes:
                setattr(fresh, attr, getattr(old, attr))
    fresh._file_path = old._file_path
    return fresh
