"""
Projekt speichern/laden (.knxarr = SQLite) (NFA-044)
"""
from __future__ import annotations
import os
import re
import shutil
import logging
from datetime import datetime
from ..models.project import KnxProject
from ..models.company_profile import CompanyProfile

logger = logging.getLogger("knix_arranger.project_service")

# Benutzerdaten-Verzeichnis (NFA-134)
APPDATA_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "KNiX Arranger"
)

# Reservierte Geräte-Namen, die unter Windows als Ordnername ungültig sind
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Gateway am Produktnamen: "Gateway", "IP-Interface" … oder zusammengesetzt
# auf "-gate" ("Vitogate"), wie knxproj_import_service._infer_device_type
_GATEWAY_NAME_RE = re.compile(
    r"gateway|ip interface|usb interface|knxnet|remote access|\b\w+gate\b")


def correct_gateway_types(project) -> list[str]:
    """Vor 1.4.38 als Sensor eingelesene Gateways (Chalet: «Vitogate 200,
    type KNX», die Schnittstelle zur Wärmepumpe) zum Gateway machen und
    das dafür angelegte Bedienelement im Raum («Wassermelder») entfernen. Nur
    importierte Projekte; Geräte mit Tasten bleiben Sensoren. Gibt die
    Adressen der korrigierten Geräte zurück."""
    if not project.topology.is_imported:
        return []
    fixed = []
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                name = re.sub(r"[-_/\s]+", " ", (device.product or device.product_name or "")
                              .lower())
                if (device.device_type != "sensor" or not _GATEWAY_NAME_RE.search(name)
                        or any((co.name or "").lower().startswith("taste")
                               for co in device.communication_objects)):
                    continue
                device.device_type = "gateway"
                fixed.append(device.physical_address)
    if fixed:
        for room in project.all_rooms:
            # ein Gateway ist kein Bedienelement im Raum
            room.bedienelemente = [be for be in room.bedienelemente
                                   if be.participant_number not in fixed]
    return fixed


class ProjectService:
    """Service für Projekt-Verwaltung."""

    def __init__(self):
        os.makedirs(APPDATA_DIR, exist_ok=True)
        self._profile_path = os.path.join(APPDATA_DIR, "company_profile.json")

    def create_new_project(self, name: str = "Neues Projekt",
                           template_id: str = "") -> KnxProject:
        """Erstellt ein neues Projekt."""
        from .building_service import BuildingService

        project = KnxProject(name=name)
        project.project_info.project_name = name
        project.project_info.date = datetime.now().strftime("%Y-%m-%d")

        if template_id:
            areal = BuildingService.load_template(template_id)
            if areal:
                project.areal = areal
        else:
            project.areal = BuildingService.create_default_areal(name)

        return project

    def save_project(self, project: KnxProject, filepath: str):
        """Speichert ein Projekt als .knxarr-Datei."""
        project.save(filepath)
        logger.info(f"Projekt gespeichert: {filepath}")

    def load_project(self, filepath: str) -> KnxProject:
        """Lädt ein Projekt aus einer .knxarr-Datei."""
        project = KnxProject.load(filepath)
        fixed = correct_gateway_types(project)
        if fixed:
            logger.info(f"Als Gateway eingeordnet: {', '.join(fixed)}")
        logger.info(f"Projekt geladen: {filepath}")
        return project

    def sanitize_project_folder_name(self, name: str) -> str:
        """Entfernt Zeichen, die in Windows-Ordnernamen ungültig sind."""
        invalid = '<>:"/\\|?*'
        cleaned = "".join(c for c in name if c not in invalid).strip().rstrip(".")
        if not cleaned or cleaned.upper() in _RESERVED_WINDOWS_NAMES:
            return "Projekt"
        return cleaned

    def project_folder_path(self, workspace_root: str, project_name: str) -> str:
        """Liefert den künftigen .knxarr-Pfad für einen Projektnamen, ohne ihn anzulegen."""
        folder_name = self.sanitize_project_folder_name(project_name)
        return os.path.join(workspace_root, folder_name, f"{folder_name}.knxarr")

    def suggest_save_path(self, current_path: str, project_name: str,
                          workspace_root: str = "") -> str:
        """Vorschlagspfad für "Speichern unter".

        - Projektordner existiert: bisherige Projektdatei.
        - Projektordner umbenannt/verschoben: nächster noch vorhandener
          übergeordneter Ordner (meist das Arbeitsverzeichnis) mit dem
          bisherigen Dateinamen.
        - Noch nie gespeichert: Arbeitsverzeichnis, sonst nur der Dateiname.
        """
        if current_path:
            filename = os.path.basename(current_path)
            folder = os.path.dirname(current_path)
            while folder and not os.path.isdir(folder):
                parent = os.path.dirname(folder)
                if parent == folder:
                    folder = ""
                    break
                folder = parent
            return os.path.join(folder, filename) if folder else filename
        filename = f"{self.sanitize_project_folder_name(project_name)}.knxarr"
        if workspace_root and os.path.isdir(workspace_root):
            return os.path.join(workspace_root, filename)
        return filename

    def prepare_workspace_project_folder(self, workspace_root: str, project_name: str) -> str:
        """Erstellt {workspace}/{Name}/ mit Unterordnern Revisionen/, Berichte/ und Import/.

        Gibt den künftigen .knxarr-Pfad zurück. Löst FileExistsError aus,
        wenn im Workspace bereits ein Projekt mit diesem Namen existiert
        (erkennbar an einer vorhandenen .knxarr-Datei). Ein verwaister,
        leerer Ordner aus einem zuvor abgebrochenen Versuch wird wiederverwendet.
        """
        knxarr_path = self.project_folder_path(workspace_root, project_name)
        project_dir = os.path.dirname(knxarr_path)
        if os.path.exists(knxarr_path):
            raise FileExistsError(project_dir)
        os.makedirs(os.path.join(project_dir, "Revisionen"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "Berichte"), exist_ok=True)
        # Eingelesene Dateien (ETS-Projekt, Reports, Mitschnitte), FA-3402a
        os.makedirs(os.path.join(project_dir, "Import"), exist_ok=True)
        # Mit Bibliothek liegen die Datenblätter dort (utils/workspace)
        from ..utils.workspace import datasheets_folder
        if not datasheets_folder():
            os.makedirs(os.path.join(project_dir, "Datenblätter"), exist_ok=True)
        return knxarr_path

    BACKUP_FOLDER = "Sicherungen"
    BACKUPS_KEPT = 10

    def create_backup(self, filepath: str, reason: str = "") -> str:
        """Sichert die gespeicherte Projektdatei vor Import oder Neuaufbau
        (NFA-042) in den Unterordner "Sicherungen" des Projekts, z.B.
        "Chalet_20260928_1405_vor_Import.knxarr". Die ältesten Sicherungen
        über BACKUPS_KEPT hinaus werden gelöscht."""
        if not filepath or not os.path.exists(filepath):
            return ""
        folder = os.path.join(os.path.dirname(filepath), self.BACKUP_FOLDER)
        os.makedirs(folder, exist_ok=True)
        stem = os.path.splitext(os.path.basename(filepath))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{reason}" if reason else ""
        backup_path = os.path.join(folder, f"{stem}_{timestamp}{suffix}.knxarr")
        shutil.copy2(filepath, backup_path)
        logger.info(f"Sicherung erstellt: {backup_path}")
        self._prune_backups(folder, stem)
        return backup_path

    def _prune_backups(self, folder: str, stem: str) -> None:
        # Nach Zeitstempel im Namen sortieren – copy2 übernimmt das
        # Änderungsdatum der Projektdatei, das Dateidatum taugt dafür nicht
        backups = sorted(
            f for f in os.listdir(folder)
            if f.startswith(f"{stem}_") and f.endswith(".knxarr")
            and f[len(stem) + 1:len(stem) + 16].replace("_", "").isdigit()
        )
        for name in backups[:-self.BACKUPS_KEPT]:
            try:
                os.remove(os.path.join(folder, name))
            except OSError as exc:
                logger.warning(f"Alte Sicherung nicht gelöscht: {name}: {exc}")

    def save_company_profile(self, profile: CompanyProfile):
        """Speichert das Firmenprofil global (FA-852)."""
        import json
        with open(self._profile_path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)

    def load_company_profile(self) -> CompanyProfile:
        """Lädt das globale Firmenprofil."""
        import json
        if os.path.exists(self._profile_path):
            with open(self._profile_path, "r", encoding="utf-8") as f:
                return CompanyProfile.from_dict(json.load(f))
        return CompanyProfile()

    def get_recent_projects(self) -> list[str]:
        """Gibt die letzten geöffneten Projekte zurück."""
        recent_file = os.path.join(APPDATA_DIR, "recent_projects.json")
        import json
        if os.path.exists(recent_file):
            with open(recent_file, "r", encoding="utf-8") as f:
                return json.load(f).get("projects", [])
        return []

    def add_to_recent(self, filepath: str):
        """Fügt ein Projekt zur Recent-Liste hinzu."""
        import json
        recent = self.get_recent_projects()
        if filepath in recent:
            recent.remove(filepath)
        recent.insert(0, filepath)
        recent = recent[:10]  # Max. 10

        recent_file = os.path.join(APPDATA_DIR, "recent_projects.json")
        with open(recent_file, "w", encoding="utf-8") as f:
            json.dump({"projects": recent}, f, indent=2)

    # ------------------------------------------------------------------
    # ETS6-Projektpasswoerter fuer KNXPROJ-Import (FA-525c)
    # ------------------------------------------------------------------

    @staticmethod
    def _knxproj_pw_fernet(project_id: str):
        """Schluessel aus der Projekt-ID abgeleitet (Obfuskierung, kein Geheimnis-Schutz)."""
        import base64
        import hashlib
        from cryptography.fernet import Fernet

        raw = hashlib.pbkdf2_hmac(
            "sha256", project_id.encode("utf-8"), b"knxarr-knxproj-pw-v1", 100_000
        )
        return Fernet(base64.urlsafe_b64encode(raw))

    def save_knxproj_password(self, project_id: str, password: str):
        """Speichert ein ETS6-Projektpasswort lokal (verschluesselt mit der Projekt-ID)."""
        import json
        passwords = self._load_knxproj_passwords()
        passwords[project_id] = self._knxproj_pw_fernet(project_id).encrypt(
            password.encode("utf-8")
        ).decode("ascii")
        path = os.path.join(APPDATA_DIR, "knxproj_passwords.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(passwords, f, indent=2)

    def get_knxproj_password(self, project_id: str) -> str | None:
        """Liest ein zuvor gespeichertes ETS6-Projektpasswort, falls vorhanden."""
        from cryptography.fernet import InvalidToken

        enc = self._load_knxproj_passwords().get(project_id)
        if not enc:
            return None
        try:
            return self._knxproj_pw_fernet(project_id).decrypt(enc.encode("ascii")).decode("utf-8")
        except InvalidToken:
            return None

    def _load_knxproj_passwords(self) -> dict:
        import json
        path = os.path.join(APPDATA_DIR, "knxproj_passwords.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
