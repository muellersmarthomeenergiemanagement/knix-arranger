"""
Ordner "Import" im Projektordner (FA-3402a).

Alle Dateien, die in das Projekt eingelesen werden (ETS-Projekt, ETS-Reports,
GA-Export, Busmonitor-Mitschnitte, ausgefüllte Checklisten), liegen als Kopie
in <Projekt>/Import. So bleibt nachvollziehbar, woraus das Projekt entstanden
ist, und spätere Importe (ImportPipeline.source) finden die Reports wieder,
auch wenn das Original aus Downloads oder E-Mail gelöscht wird.

Noch nie gespeicherte Projekte haben keinen Ordner: die Dateien werden beim
ersten Speichern nachgeholt (collect_pending).
"""
from __future__ import annotations

import filecmp
import logging
import os
import shutil
from datetime import datetime

logger = logging.getLogger("knix_arranger.import_folder")

IMPORT_FOLDER = "Import"
LEGACY_FOLDER = "Importdateien"      # von Hand angelegt (Chalet)


def _own_folder(project_dir: str) -> bool:
    """Liegt das Projekt in einem eigenen Ordner? Ältere Projekte direkt im
    Arbeitsverzeichnis bekommen keinen gemeinsamen Import-Ordner."""
    from ..utils.workspace import projects_folder, workspace_root
    norm = os.path.normcase(os.path.abspath(project_dir))
    shared = {os.path.normcase(os.path.abspath(p))
              for p in (projects_folder(), workspace_root()) if p}
    return norm not in shared


def import_dir(project, create: bool = True) -> str:
    """<Projektordner>/Import ("" bei ungespeichertem Projekt oder ohne
    eigenen Projektordner)."""
    folder = project.folder_path if project is not None else None
    if not folder or not _own_folder(folder):
        return ""
    path = os.path.join(folder, IMPORT_FOLDER)
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            logger.warning("Import-Ordner nicht angelegt: %s", exc)
            return ""
    return path


def start_dir(project) -> str:
    """Startordner der Dateiauswahl beim Einlesen."""
    path = import_dir(project)
    if path:
        return path
    folder = project.folder_path if project is not None else None
    if folder:
        legacy = os.path.join(folder, LEGACY_FOLDER)
        return legacy if os.path.isdir(legacy) else folder
    return ""


def _inside(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(path)),
                                   os.path.normcase(os.path.abspath(folder))]) \
            == os.path.normcase(os.path.abspath(folder))
    except ValueError:          # anderes Laufwerk
        return False


def _set_aside(target: str) -> None:
    """Gleichnamige ältere Datei mit ihrem Datum umbenennen statt überschreiben
    (z.B. Chalet.knxproj -> Chalet_20261105_1405.knxproj)."""
    stem, ext = os.path.splitext(target)
    stamp = datetime.fromtimestamp(os.path.getmtime(target)).strftime("%Y%m%d_%H%M")
    aside = f"{stem}_{stamp}{ext}"
    n = 2
    while os.path.exists(aside):
        aside = f"{stem}_{stamp}_{n}{ext}"
        n += 1
    os.replace(target, aside)


def store(project, path: str) -> str:
    """Legt eine eingelesene Datei als Kopie im Import-Ordner ab und gibt den
    Pfad der Kopie zurück. Bei ungespeichertem Projekt wird die Datei für
    das erste Speichern vorgemerkt und der Originalpfad zurückgegeben."""
    if not path or not os.path.isfile(path) or project is None:
        return path
    folder = import_dir(project)
    if not folder:
        if not project.folder_path:
            pending = project.__dict__.setdefault("_pending_imports", [])
            if path not in pending:
                pending.append(path)
        return path
    if _inside(path, folder):
        return path
    target = os.path.join(folder, os.path.basename(path))
    try:
        if os.path.exists(target):
            if filecmp.cmp(path, target, shallow=False):
                return target
            _set_aside(target)
        shutil.copy2(path, target)
    except OSError as exc:
        logger.warning("Importdatei nicht kopiert: %s: %s", path, exc)
        return path
    return target


def collect_pending(project) -> int:
    """Nach dem ersten Speichern: vorgemerkte Importdateien in den Import-
    Ordner kopieren und die gemerkten Report-Pfade darauf umstellen."""
    if not import_dir(project):
        return 0
    pending = list(project.__dict__.pop("_pending_imports", []) or [])
    pending += [p for p in project.import_files.values() if p and p not in pending]
    copied = 0
    moved: dict[str, str] = {}
    for path in pending:
        new = store(project, path)
        if new != path:
            moved[path] = new
            copied += 1
    for key, path in list(project.import_files.items()):
        if path in moved:
            project.import_files[key] = moved[path]
    return copied
