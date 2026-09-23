"""Tests fuer die Liste der zuletzt verwendeten Produkte."""
import pytest

from knix_arranger.services import recent_products as rp


@pytest.fixture(autouse=True)
def recent_file(monkeypatch, tmp_path):
    path = tmp_path / "recent" / "recent_products.json"
    monkeypatch.setattr(rp, "_RECENT_FILE", str(path))
    return path


def _prod(nr, mfr="MDT"):
    return {"manufacturer": mfr, "order_number": nr, "product_name": f"Produkt {nr}"}


def test_empty_without_file():
    assert rp.load_recent() == []


def test_newest_first():
    rp.add_recent(_prod("A"))
    rp.add_recent(_prod("B"))
    assert [p["order_number"] for p in rp.load_recent()] == ["B", "A"]


def test_duplicate_moves_to_front():
    for nr in ("A", "B", "C"):
        rp.add_recent(_prod(nr))
    rp.add_recent(_prod("A"))
    assert [p["order_number"] for p in rp.load_recent()] == ["A", "C", "B"]


def test_same_number_other_manufacturer_is_separate():
    rp.add_recent(_prod("A", "MDT"))
    rp.add_recent(_prod("A", "ABB"))
    assert len(rp.load_recent()) == 2


def test_limited_to_max_recent():
    for i in range(rp.MAX_RECENT + 3):
        rp.add_recent(_prod(str(i)))
    recent = rp.load_recent()
    assert len(recent) == rp.MAX_RECENT
    assert recent[0]["order_number"] == str(rp.MAX_RECENT + 2)


def test_corrupt_or_wrong_type_gives_empty_list(recent_file):
    recent_file.parent.mkdir(parents=True)
    recent_file.write_text("{kaputt", encoding="utf-8")
    assert rp.load_recent() == []
    recent_file.write_text('{"kein": "array"}', encoding="utf-8")
    assert rp.load_recent() == []
