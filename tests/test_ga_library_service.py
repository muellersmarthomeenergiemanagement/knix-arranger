"""Tests fuer die projektuebergreifende GA-Vorlagen-Bibliothek."""
import json

import pytest

from knix_arranger.models.group_address import GroupAddress
from knix_arranger.services import ga_library_service as lib


@pytest.fixture(autouse=True)
def no_legacy(monkeypatch, tmp_path):
    """Alter Ablageort im Programmordner: auf ein leeres Testverzeichnis umbiegen."""
    monkeypatch.setattr(lib, "_LEGACY_PATH", tmp_path / "legacy" / "custom_ga_library.json")


def _ga(**kw):
    defaults = dict(main_group=1, middle_group=2, sub_group=3, designation="Licht Küche",
                    datapoint_type="DPST-1-1", gewerk_code="LD", function_name="E/A",
                    description="Deckenlicht", central="")
    defaults.update(kw)
    return GroupAddress(**defaults)


def test_empty_library():
    assert lib.load_library() == []


def test_add_and_load_entry():
    lib.add_entry("Küche Licht", _ga())
    assert lib.load_library() == [{
        "name": "Küche Licht", "main_group": 1, "middle_group": 2, "sub_group": 3,
        "designation": "Licht Küche", "datapoint_type": "DPST-1-1", "gewerk_code": "LD",
        "function_name": "E/A", "description": "Deckenlicht", "central": "",
    }]


def test_stored_in_appdata(tmp_path):
    lib.add_entry("A", _ga())
    # conftest leitet APPDATA auf tmp_path um
    assert (tmp_path / "KNiX Arranger" / "custom_ga_library.json").exists()


def test_remove_entry():
    lib.add_entry("A", _ga())
    lib.add_entry("B", _ga(sub_group=4))
    lib.remove_entry(0)
    assert [e["name"] for e in lib.load_library()] == ["B"]


def test_remove_invalid_index_is_ignored():
    lib.add_entry("A", _ga())
    lib.remove_entry(5)
    lib.remove_entry(-1)
    assert len(lib.load_library()) == 1


def test_corrupt_file_gives_empty_list(tmp_path):
    path = tmp_path / "KNiX Arranger" / "custom_ga_library.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{kaputt", encoding="utf-8")
    assert lib.load_library() == []


def test_legacy_library_is_taken_over(tmp_path):
    legacy = tmp_path / "legacy" / "custom_ga_library.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps([{"name": "Alt"}]), encoding="utf-8")
    assert [e["name"] for e in lib.load_library()] == ["Alt"]

    # Beim nächsten Speichern landet alles am neuen Ort
    lib.add_entry("Neu", _ga())
    assert [e["name"] for e in lib.load_library()] == ["Alt", "Neu"]
    assert (tmp_path / "KNiX Arranger" / "custom_ga_library.json").exists()
