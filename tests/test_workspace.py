"""Ordnerstruktur: Projekte und Bibliothek (utils/workspace).

Neue Installationen: Arbeitsverzeichnis/Projekte und /Bibliothek (Produkte
KNX, Datenblätter, Vorlagen). Ältere: Projekte direkt im Arbeitsverzeichnis,
Bibliothek wird bewusst eingerichtet (Projekt_23: Dropbox/…/Projekte ->
Dropbox/…/Bibliothek), nichts wird automatisch verschoben.
"""
from __future__ import annotations

import json
import os

import pytest

from knix_arranger.services import product_folder
from knix_arranger.utils import workspace as ws
from knix_arranger.utils.app_settings import load_settings, save_settings


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Früherer Ordner ~/.knix_arranger im Testverzeichnis."""
    path = tmp_path / "home" / ".knix_arranger"
    path.mkdir(parents=True)
    monkeypatch.setattr(ws, "_home_dir", lambda: str(path))
    from knix_arranger.services import ko_templates
    monkeypatch.setattr(ko_templates, "_TEMPLATE_FILE", None)
    return path


def test_neue_installation(tmp_path, home):
    (home / "ko_templates.json").write_text(json.dumps({"ABB|X": {"1|E/A": 3}}))
    root = tmp_path / "KNX-Projekte"
    ws.setup_workspace(str(root))
    assert ws.projects_folder() == str(root / "Projekte")
    assert ws.library_folder() == str(root / "Bibliothek")
    for name in ("Produkte KNX", "Datenblätter", "Vorlagen"):
        assert (root / "Bibliothek" / name).is_dir()
    assert product_folder.products_folder() == str(root / "Bibliothek" / "Produkte KNX")
    assert ws.datasheets_folder() == str(root / "Bibliothek" / "Datenblätter")
    # Vorlagen aus ~/.knix_arranger in der Bibliothek, KO-Vorlagen werden dort gelesen
    assert (root / "Bibliothek" / "Vorlagen" / "ko_templates.json").exists()
    from knix_arranger.services import ko_templates
    from knix_arranger.models.topology import Device
    device = Device(manufacturer="ABB", order_number="X")
    assert ko_templates._template_file() == str(root / "Bibliothek" / "Vorlagen" /
                                                "ko_templates.json")
    assert isinstance(ko_templates.load_template(device), dict)


def test_aeltere_installation_bleibt(tmp_path):
    save_settings({"workspace_root_path": str(tmp_path / "Projekte")})
    assert ws.projects_folder() == str(tmp_path / "Projekte")
    assert ws.library_folder() == ""
    assert ws.templates_folder() == ws.appdata_dir()
    assert ws.datasheets_folder() == ""
    assert product_folder.products_folder() == str(tmp_path / "Projekte" / "Produkte KNX")
    assert ws.suggested_library() == str(tmp_path / "Bibliothek")


def test_bibliothek_einrichten_verschiebt_herstellerdateien(tmp_path):
    projects = tmp_path / "Projekte"
    old = projects / "Produkte KNX"
    (old / "MDT").mkdir(parents=True)
    (old / "ABB.knxprod").write_bytes(b"abb")
    (old / "MDT" / "Taster.knxprod").write_bytes(b"mdt")
    save_settings({"workspace_root_path": str(projects)})
    os.makedirs(ws.appdata_dir(), exist_ok=True)
    with open(os.path.join(ws.appdata_dir(), "custom_ga_library.json"), "w") as f:
        f.write("[]")
    library = tmp_path / "Bibliothek"
    result = ws.setup_library(str(library))
    assert result == {"products": 2, "templates": 1}
    assert (library / "Produkte KNX" / "MDT" / "Taster.knxprod").read_bytes() == b"mdt"
    assert not (old / "ABB.knxprod").exists()
    assert (library / "Vorlagen" / "custom_ga_library.json").exists()
    assert os.path.exists(os.path.join(ws.appdata_dir(), "custom_ga_library.json"))  # Sicherung
    assert load_settings()["library_folder"] == str(library)
    assert product_folder.products_folder() == str(library / "Produkte KNX")
    assert ws.projects_folder() == str(projects)          # Projekte unverändert


def test_vorhandene_datei_wird_nicht_ueberschrieben(tmp_path):
    projects = tmp_path / "Projekte"
    (projects / "Produkte KNX").mkdir(parents=True)
    (projects / "Produkte KNX" / "ABB.knxprod").write_bytes(b"alt")
    save_settings({"workspace_root_path": str(projects)})
    library = tmp_path / "Bibliothek"
    (library / "Produkte KNX").mkdir(parents=True)
    (library / "Produkte KNX" / "ABB.knxprod").write_bytes(b"neu")
    assert ws.setup_library(str(library))["products"] == 0
    assert (library / "Produkte KNX" / "ABB.knxprod").read_bytes() == b"neu"


def test_home_dir_aufloesen(home):
    (home / "recent_products.json").write_text("[1]")
    (home / "ko_templates.json").write_text("{}")
    ws.migrate_home_dir()
    assert os.path.exists(os.path.join(ws.appdata_dir(), "recent_products.json"))
    assert os.path.exists(ws.template_path("ko_templates.json"))
    from knix_arranger.services import recent_products
    assert recent_products.load_recent() == [1]


def test_neues_projekt_ohne_datenblaetter_mit_bibliothek(tmp_path):
    from knix_arranger.services.project_service import ProjectService
    ws.setup_workspace(str(tmp_path))
    path = ProjectService().prepare_workspace_project_folder(ws.projects_folder(), "Chalet")
    project_dir = os.path.dirname(path)
    assert os.path.dirname(project_dir) == ws.projects_folder()
    assert os.path.isdir(os.path.join(project_dir, "Berichte"))
    assert not os.path.exists(os.path.join(project_dir, "Datenblätter"))
