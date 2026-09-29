"""
Gemeinsamer Ablauf nach jedem ETS-Import (.knxproj, Topologie-, GA- und
Gebäude-Report).

Früher hatte jeder der vier Import-Wege in main_window.py seine eigene
Schrittfolge. Die Folgen unterschieden sich in Reihenfolge und Vollständigkeit
-- z.B. übernahm der .knxproj-Import die Tastenbelegung nicht aus den KOs, und
nach "Projekt neu aus ETS aufbauen" standen in der Chalet-Bibliothek geratene
Belegungen (1.1.40) bzw. gar keine (1.1.52). Jetzt liefert jeder Import-Weg
nur seine Primärdaten (Topologie, GA-Struktur, Gebäudestruktur); alles Weitere
läuft hier in fester Reihenfolge:

1. link_topology()  nur Excel-Wege: Einbauorte, Verteiler-Räume, Raum-Linien-
                    Verknüpfung, KO-Anreicherung aus dem GA-Report
2. derive()         Bedienelemente, Tastenbelegung aus den KOs, Gewerke,
                    GA-Metadaten -- VOR dem Abgleich, damit dieser die
                    frischen ETS-Daten sieht
3. reconcile()      Re-Import-Abgleich mit dem bisherigen Stand
4. finalize()       Gewerk-IDs, Szenen, DALI, Tastenbelegung, Änderungs-
                    protokoll -- NACH dem Abgleich, da sie Raum- und Geräte-IDs
                    verwenden

Scheitert ein Schritt, läuft der Import weiter; der Schritt steht in
`problems` und wird dem Benutzer am Ende angezeigt statt nur geloggt.
"""
from __future__ import annotations

import logging
import os
import re

from ..models.project import KnxProject
from .dali_service import DaliService
from .gewerk_service import GewerkService
from .knxproj_import_service import KnxprojImportService
from .project_reconcile_service import ReimportDiff, reconcile_reimport
from .sensor_service import refresh_bedienelemente
from .xlsx_import_service import XlsxImportService

logger = logging.getLogger("knix_arranger.import")

TOPOLOGY_XLSX = "topology_xlsx"
GA_REPORT = "ga_report"
BUILDING_REPORT = "building_report"

_GEWERK_PREFIX_RE = re.compile(r"^([A-Z]{1,4})[._]", re.IGNORECASE)
_FLOOR_ROOM_RE = re.compile(r"^([A-Z]{1,4})\.([A-Z0-9]{2,5})\.(\d{1,2})\.", re.IGNORECASE)
_ROOM_NAME_RE = re.compile(r"\(\s*(.+?)\s*\)")


def enrich_ga_metadata(project: KnxProject) -> int:
    """Befüllt leere gewerk_code und room_number importierter GAs aus der
    Bezeichnung 'GEWERK.STOCKWERK.RAUM.ELEM_FUNKTION  ( Raumname )'.

    - gewerk_code: erstes Segment vor "." oder "_" (4- und 3-Segment-
      Konvention, analog xlsx_import_service._parse_xlsx_designation)
    - room_number: Raumname aus den Klammern, sonst STOCKWERK.RAUM

    Überschreibt nur leere Felder. Gibt die Anzahl angereicherter GAs zurück.
    """
    enriched = 0
    for ga in project.group_addresses.all_addresses():
        desig = ga.designation or ""
        if not desig:
            continue
        changed = False
        if not ga.gewerk_code:
            m = _GEWERK_PREFIX_RE.match(desig)
            if m:
                ga.gewerk_code = m.group(1).upper()
                changed = True
        if not ga.room_number:
            mn = _ROOM_NAME_RE.search(desig)
            if mn:
                ga.room_number = mn.group(1).strip()
                changed = True
            else:
                mf = _FLOOR_ROOM_RE.match(desig)
                if mf:
                    ga.room_number = f"{mf.group(2)}.{mf.group(3)}"
                    changed = True
        if changed:
            enriched += 1
    return enriched


def auto_configure_dali(project: KnxProject) -> int:
    """DALI-Gateways nach einem Import konfigurieren (überschreibt keine
    bestehenden Gruppen/EVGs)."""
    if not project.topology.areas:
        return 0
    return DaliService().auto_configure_from_import(project)


class ImportPipeline:
    """Schritte nach dem Einlesen der Primärdaten, siehe Modulkommentar."""

    def __init__(self, project: KnxProject, importer: XlsxImportService | None = None):
        self.project = project
        self.importer = importer or XlsxImportService()
        self.problems: list[str] = []
        self.channel_conflicts: list[str] = []
        self.gewerke_assigned = 0
        self.scenes_detected = 0

    # ── Hilfen ────────────────────────────────────────────────────────────

    def step(self, label: str, func, *args, default=None, **kwargs):
        """Führt einen Schritt aus; ein Fehler bricht den Import nicht ab,
        sondern wird für die Anzeige gesammelt."""
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logger.warning("Import-Schritt '%s' fehlgeschlagen: %s", label, exc, exc_info=True)
            self.problems.append(f"{label}: {exc}")
            return default

    def source(self, key: str) -> str:
        """Pfad eines früher importierten Reports, falls die Datei noch da ist."""
        path = self.project.import_files.get(key, "")
        return path if path and os.path.isfile(path) else ""

    def set_source(self, key: str, path: str) -> None:
        self.project.import_files[key] = path

    # ── 1. Topologie mit Gebäude und GAs verbinden (Excel-Wege) ─────────

    def link_topology(self, ga_structure=None) -> None:
        """Einbauorte, Tasten-/Szenenangaben, Verteiler-Räume und Raum-Linien-
        Verknüpfung aus allen bekannten Reports; KO-Verbindungen aus dem
        GA-Report. Ohne Topologie gibt es nichts zu verbinden."""
        project, importer = self.project, self.importer
        if not project.topology.areas:
            return
        ga_structure = ga_structure or project.group_addresses
        topology_xlsx = self.source(TOPOLOGY_XLSX)
        ga_report = self.source(GA_REPORT)
        building_report = self.source(BUILDING_REPORT)

        # Einbauorte: Gebäude-Report hat Vorrang vor der Gebäude-Spalte des
        # GA-Reports (tatsächliche ETS-Raumzuordnung statt Freitext)
        device_locations: dict = {}
        if ga_report:
            device_locations.update(self.step(
                "Einbauorte aus GA-Report", importer.extract_device_locations,
                ga_report, default={}))
        if building_report:
            device_locations.update(self.step(
                "Einbauorte aus Gebäude-Report",
                importer.extract_device_locations_from_building_report,
                building_report, default={}))
        device_notes = None
        if topology_xlsx:
            device_notes = self.step(
                "Installations-Hinweise", importer.extract_device_notes, topology_xlsx)

        # Tastenbelegung (Text), Szenen-Schaltwerte und -Auslöser; der
        # Gebäude-Report hat Vorrang vor dem Topologie-Report
        report_paths = [p for p in (topology_xlsx, building_report) if p]
        for label, extract, attr in (
            ("Tastenbelegung", importer.extract_button_configuration, "button_configuration"),
            ("Szenen-Schaltwerte", importer.extract_scene_values, "scene_values"),
            ("Szenen-Auslöser", importer.extract_scene_triggers, "scene_triggers"),
        ):
            values: dict = {}
            for path in report_paths:
                values.update(self.step(label, extract, path, default={}))
            self._apply_to_devices(attr, values)

        # Verteiler-Räume VOR der Raum-Linien-Verknüpfung, damit Geräte im
        # Verteiler dorthin statt in einen Funktionsraum kommen; manuelle
        # Zuordnungen aus Schritt 3b danach wieder anwenden
        self.step("Verteiler-Räume", importer.create_verteiler_rooms,
                  project.topology, project.areal)
        self.step("Verteiler-Zuordnung", importer.apply_verteiler_room_overrides,
                  project.topology, project.areal, project.verteiler_room_overrides)
        self.step("Raum-Linien-Verknüpfung", importer.link_rooms_to_lines,
                  project.topology, ga_structure, project.areal,
                  device_locations=device_locations or None, device_notes=device_notes)
        if ga_report:
            self.step("KO-Verbindungen aus GA-Report", importer.enrich_device_ko_connections,
                      project.topology, ga_report)

    def _apply_to_devices(self, attr: str, values: dict) -> None:
        if not values:
            return
        for area in self.project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    value = values.get(device.physical_address)
                    if value and getattr(device, attr) != value:
                        setattr(device, attr, value)

    # ── 2. Ableiten (vor dem Abgleich) ────────────────────────────────────

    def derive(self) -> None:
        project = self.project
        if project.topology.areas:
            self.step("Bedienelemente", KnxprojImportService._create_bedienelemente_from_topology,
                      project.topology, project.areal)
            # Tastenbelegung direkt aus den KO-GA-Verknüpfungen (FA-521c)
            self.step("Tastenbelegung aus den Objekten",
                      self.importer.backfill_function_assignments,
                      project.topology, project.areal, project.group_addresses)
        if project.group_addresses.all_addresses() and project.areal.all_rooms:
            gewerke = GewerkService(project.gewerk_catalog)
            # Nur Räume ohne bestehende Zuweisungen (FA-519b)
            self.gewerke_assigned = self.step(
                "Gewerke aus Gruppenadressen", gewerke.derive_gewerk_assignments,
                project.group_addresses, project.areal, overwrite=False, default=0)
            if project.topology.areas:
                self.channel_conflicts = self.step(
                    "Kanal-Gewerk-Prüfung", gewerke.detect_channel_gewerk_conflicts,
                    project.topology, project.group_addresses, default=[])
        self.step("GA-Metadaten", enrich_ga_metadata, project)

    # ── 3. Abgleich ───────────────────────────────────────────────────────

    def reconcile(self, old_project: KnxProject) -> ReimportDiff:
        """Übernimmt IDs und KNiX-Planungsdaten aus dem bisherigen Stand.
        Nicht über step(): ohne Abgleich wären Materialliste, Secure-Archiv
        und DALI verwaist -- dann lieber den ganzen Import abbrechen."""
        return reconcile_reimport(old_project, self.project)

    # ── 4. Abschluss (nach dem Abgleich) ──────────────────────────────────

    def finalize(self, filepath: str, diff: ReimportDiff) -> None:
        project = self.project
        # GAs mit ihrer Gewerk-Zuweisung verknüpfen (FA-521e) -- braucht die
        # endgültigen Raum-Daten nach dem Abgleich
        self.step("Gewerk-Verknüpfung der GAs",
                  GewerkService(project.gewerk_catalog).relink_assignment_ids,
                  project.group_addresses, project.areal)
        self.step("Szenen-Erkennung", self._detect_scenes)
        self.step("DALI-Konfiguration", auto_configure_dali, project)
        # Tastenbelegung aller Bedienelemente aus ihren Funktionen -- einmal
        # hier statt bei jedem Anzeigen (siehe refresh_bedienelemente)
        self.step("Tastenbelegung aktualisieren", refresh_bedienelemente, project)
        is_reimport = diff.devices_matched > 0 or diff.rooms_matched > 0
        project.add_changelog_entry(
            "Re-Import" if is_reimport else "Import",
            f"{os.path.basename(filepath)}: {diff.summary_line()}",
        )

    def _detect_scenes(self) -> None:
        from .scene_detection_service import detect_scenes
        from .scene_value_linking import link_scene_names
        added = detect_scenes(self.project)
        self.project.scenes.extend(added)
        self.scenes_detected = len(added)
        # Szenennamen aus dem GA-Kommentar ("#1: Anwesend")
        link_scene_names(self.project)

    # ── Alles zusammen (Excel-Wege) ───────────────────────────────────────

    def run(self, old_project: KnxProject, filepath: str, ga_structure=None) -> ReimportDiff:
        self.link_topology(ga_structure)
        self.derive()
        diff = self.reconcile(old_project)
        self.finalize(filepath, diff)
        return diff
