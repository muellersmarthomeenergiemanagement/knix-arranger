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
        "In KNiX korrigierte Angaben: Gewerk einer GA, Tastenbezeichnungen für den Bauherrn",
        True, ("ets_corrections",)),
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
