"""Programmeinstellungen im Benutzerverzeichnis (NFA-134) und Protokollstufe (NFA-142)."""
import json
import logging

from knix_arranger.utils import app_settings
from knix_arranger.utils.logging_setup import set_log_level


def _use_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(app_settings.os, "name", "nt")


def test_settings_in_knix_arranger_folder(monkeypatch, tmp_path):
    _use_appdata(monkeypatch, tmp_path)
    app_settings.save_settings({"log_level": "DEBUG"})
    assert (tmp_path / "KNiX Arranger" / "app_settings.json").exists()
    assert app_settings.get_setting("log_level") == "DEBUG"


def test_old_folder_is_copied_and_kept(monkeypatch, tmp_path):
    """Kopieren statt verschieben: das installierte 1.1.31 liest nur den
    alten Ordner und fand sonst das Arbeitsverzeichnis nicht mehr."""
    _use_appdata(monkeypatch, tmp_path)
    old = tmp_path / "KNiXArranger" / "app_settings.json"
    old.parent.mkdir()
    old.write_text(json.dumps({"workspace_root_path": "C:/KNX"}), encoding="utf-8")

    assert app_settings.get_setting("workspace_root_path") == "C:/KNX"
    assert (tmp_path / "KNiX Arranger" / "app_settings.json").exists()
    assert json.loads(old.read_text(encoding="utf-8")) == {"workspace_root_path": "C:/KNX"}


def test_new_file_wins_over_old(monkeypatch, tmp_path):
    _use_appdata(monkeypatch, tmp_path)
    for folder, value in (("KNiXArranger", "alt"), ("KNiX Arranger", "neu")):
        path = tmp_path / folder / "app_settings.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"x": value}), encoding="utf-8")
    assert app_settings.get_setting("x") == "neu"


def test_broken_file_gives_defaults(monkeypatch, tmp_path):
    _use_appdata(monkeypatch, tmp_path)
    path = tmp_path / "KNiX Arranger" / "app_settings.json"
    path.parent.mkdir()
    path.write_text("{kaputt", encoding="utf-8")
    assert app_settings.get_setting("log_level", "INFO") == "INFO"


def test_set_log_level():
    logger = logging.getLogger("knix_arranger")
    before = logger.level
    try:
        set_log_level("DEBUG")
        assert logger.level == logging.DEBUG
        set_log_level("unbekannt")
        assert logger.level == logging.INFO
    finally:
        logger.setLevel(before)
