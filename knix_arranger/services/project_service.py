"""
Projekt speichern/laden (.knxarr = SQLite) (NFA-044)
"""
from __future__ import annotations
import os
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
        logger.info(f"Projekt geladen: {filepath}")
        return project

    def sanitize_project_folder_name(self, name: str) -> str:
        """Entfernt Zeichen, die in Windows-Ordnernamen ungültig sind."""
        invalid = '<>:"/\\|?*'
        cleaned = "".join(c for c in name if c not in invalid).strip().rstrip(".")
        return cleaned or "Projekt"

    def prepare_workspace_project_folder(self, workspace_root: str, project_name: str) -> str:
        """Erstellt {workspace}/{Name}/ mit Unterordnern Revisionen/ und Berichte/.

        Gibt den künftigen .knxarr-Pfad zurück. Löst FileExistsError aus,
        wenn im Workspace bereits ein gleichnamiger Projektordner existiert.
        """
        folder_name = self.sanitize_project_folder_name(project_name)
        project_dir = os.path.join(workspace_root, folder_name)
        if os.path.exists(project_dir):
            raise FileExistsError(project_dir)
        os.makedirs(os.path.join(project_dir, "Revisionen"))
        os.makedirs(os.path.join(project_dir, "Berichte"))
        return os.path.join(project_dir, f"{folder_name}.knxarr")

    def create_backup(self, filepath: str) -> str:
        """Erstellt ein Backup vor Reorganisation (NFA-042)."""
        if not os.path.exists(filepath):
            return ""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = filepath.replace(".knxarr", f"_backup_{timestamp}.knxarr")
        shutil.copy2(filepath, backup_path)
        logger.info(f"Backup erstellt: {backup_path}")
        return backup_path

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
