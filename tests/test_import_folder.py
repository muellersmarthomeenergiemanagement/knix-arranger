"""Ordner «Import» im Projektordner (FA-3402a)."""
import os

import pytest

from knix_arranger.models.project import KnxProject
from knix_arranger.services import import_folder
from knix_arranger.services.import_pipeline import GA_REPORT
from knix_arranger.services.project_service import ProjectService


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "Projekte"
    root.mkdir()
    monkeypatch.setattr("knix_arranger.utils.workspace.projects_folder", lambda: str(root))
    monkeypatch.setattr("knix_arranger.utils.workspace.workspace_root", lambda: str(tmp_path))
    return root


def _saved(workspace) -> KnxProject:
    project = KnxProject(name="Chalet")
    project._file_path = ProjectService().prepare_workspace_project_folder(str(workspace), "Chalet")
    return project


def _file(folder, name, text="x"):
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_neues_projekt_hat_import_ordner(workspace):
    project = _saved(workspace)
    assert os.path.isdir(os.path.join(project.folder_path, "Import"))
    assert import_folder.start_dir(project) == os.path.join(project.folder_path, "Import")


def test_eingelesene_datei_wird_kopiert(workspace, tmp_path):
    project = _saved(workspace)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    source = _file(downloads, "Chalet.knxproj", "v1")
    stored = import_folder.store(project, source)
    assert stored == os.path.join(project.folder_path, "Import", "Chalet.knxproj")
    assert open(stored, encoding="utf-8").read() == "v1"
    # gleiche Datei nochmals: keine zweite Kopie
    assert import_folder.store(project, source) == stored
    assert import_folder.store(project, stored) == stored
    assert os.listdir(os.path.dirname(stored)) == ["Chalet.knxproj"]
    # neuer Stand gleichen Namens: alter bleibt mit Datum erhalten
    _file(downloads, "Chalet.knxproj", "v2")
    import_folder.store(project, source)
    files = sorted(os.listdir(os.path.dirname(stored)))
    assert len(files) == 2 and "Chalet.knxproj" in files
    assert open(stored, encoding="utf-8").read() == "v2"


def test_ungespeichertes_projekt_holt_beim_speichern_nach(workspace, tmp_path):
    project = KnxProject(name="Neu")
    report = _file(tmp_path, "GA-Report.xlsx")
    assert import_folder.store(project, report) == report
    project.import_files[GA_REPORT] = report
    project._file_path = ProjectService().prepare_workspace_project_folder(str(workspace), "Neu")
    assert import_folder.collect_pending(project) == 1
    target = os.path.join(project.folder_path, "Import", "GA-Report.xlsx")
    assert os.path.isfile(target) and project.import_files[GA_REPORT] == target
    assert import_folder.collect_pending(project) == 0


def test_projekt_ohne_eigenen_ordner_bekommt_keinen(workspace, tmp_path):
    project = KnxProject(name="Alt")
    project._file_path = str(workspace / "Alt.knxarr")
    source = _file(tmp_path, "Alt.knxproj")
    assert import_folder.store(project, source) == source
    assert not os.path.exists(workspace / "Import")
