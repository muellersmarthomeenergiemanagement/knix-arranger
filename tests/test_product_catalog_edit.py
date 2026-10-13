"""
Katalogpflege: Produkte ausblenden und Stammdaten bearbeiten, z.B. das
ältere "KNX Revox Gateway" ausblenden, wenn das Multiuser 3.0 verbaut ist
(Projekt_23 Chalet Franziska).
"""
from __future__ import annotations
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from knix_arranger.services.product_search_service import (
    ProductSearchService, _user_catalog_path,
)

_OLD = {"category": "infrastructure", "device_type": "Sonstiges",
        "manufacturer": "Weinzierl", "order_number": "KNX Revox Gateway",
        "product_name": "Revox Gateway designed by Weinzierl",
        "com_objects": [{"number": 1, "name": "SYSTEM_OFF"}]}
_NEW = {**_OLD, "order_number": "Revox Multiuser 3.0 KNX Gateway",
        "product_name": "Revox Multiuser 3.0 KNX Gateway by Weinzierl"}


def _orders(svc, **kw):
    return [r.order_number for r in svc.search_all("Revox", **kw)]


def test_hide_persists_and_reimport_shows_again():
    svc = ProductSearchService()
    svc.add_products([dict(_OLD), dict(_NEW)])
    svc.set_hidden("Weinzierl", "KNX Revox Gateway", True)
    assert _orders(svc) == ["Revox Multiuser 3.0 KNX Gateway"]
    hidden = [r for r in svc.search_all("Revox", include_hidden=True) if r.hidden]
    assert [r.order_number for r in hidden] == ["KNX Revox Gateway"]
    # Zuweisungen bestehender Projekte finden das Produkt weiterhin
    assert svc.find_product("Weinzierl", "KNX Revox Gateway")

    reloaded = ProductSearchService()
    assert _orders(reloaded) == ["Revox Multiuser 3.0 KNX Gateway"]
    assert "hidden" in json.load(open(_user_catalog_path(), encoding="utf-8"))

    reloaded.add_product(dict(_OLD))      # erneuter KNXPROD-Import
    assert sorted(_orders(ProductSearchService())) == [
        "KNX Revox Gateway", "Revox Multiuser 3.0 KNX Gateway"]


def test_hide_base_catalog_product():
    svc = ProductSearchService()
    base = svc.search_actors("Schaltaktor")[0]
    svc.set_hidden(base.manufacturer, base.order_number, True, base.product_name)
    again = ProductSearchService()
    assert (base.manufacturer, base.order_number) not in {
        (r.manufacturer, r.order_number) for r in again.search_actors("Schaltaktor")}
    again.set_hidden(base.manufacturer, base.order_number, False, base.product_name)
    assert (base.manufacturer, base.order_number) in {
        (r.manufacturer, r.order_number)
        for r in ProductSearchService().search_actors("Schaltaktor")}


def test_edit_keeps_com_objects_and_renames():
    svc = ProductSearchService()
    svc.add_product(dict(_NEW))
    product = svc.edit_product("Weinzierl", "Revox Multiuser 3.0 KNX Gateway",
                               {"product_name": "Revox Gateway MU 3.0",
                                "price_hint": "CHF 900", "com_objects": []})
    assert product["product_name"] == "Revox Gateway MU 3.0"
    assert product["com_objects"] == _NEW["com_objects"]     # nicht bearbeitbar
    assert product["price_hint"] == "CHF 900"

    svc.edit_product("Weinzierl", "Revox Multiuser 3.0 KNX Gateway",
                     {"order_number": "MU-3.0"})
    reloaded = ProductSearchService()
    assert _orders(reloaded) == ["MU-3.0"]
    assert reloaded.find_product("Weinzierl", "MU-3.0")["com_objects"]


def test_edit_base_product_and_duplicate_key():
    svc = ProductSearchService()
    a, b = svc.search_actors("Schaltaktor")[:2]
    svc.edit_product(a.manufacturer, a.order_number, {"price_hint": "CHF 1"}, a.product_name)
    assert ProductSearchService().find_product(
        a.manufacturer, a.order_number, a.product_name)["price_hint"] == "CHF 1"
    with pytest.raises(ValueError):
        svc.edit_product(a.manufacturer, a.order_number,
                         {"manufacturer": b.manufacturer, "order_number": b.order_number},
                         a.product_name)


def test_dialog_context_menu_hides_and_shows_hidden(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMenu
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs import product_select_dialog
    ProductSearchService().add_products([dict(_OLD), dict(_NEW)])
    dlg = product_select_dialog.ProductSelectDialog()
    dlg._search_edit.setText("KNX Revox Gateway")
    assert dlg._table.rowCount() == 1

    def choose(text):
        class Menu(QMenu):
            def exec(self, *_a):
                return next(a for a in self.actions() if a.text() == text)
        monkeypatch.setattr(product_select_dialog, "QMenu", Menu)

    choose("Ausblenden")
    dlg._show_table_context_menu(dlg._table.visualItemRect(dlg._table.item(0, 0)).center())
    assert dlg._table.rowCount() == 0
    dlg._show_hidden_action.setChecked(True)
    assert dlg._table.rowCount() == 1
    assert "(ausgeblendet)" in dlg._table.item(0, 4).text()
    choose("Wieder einblenden")
    dlg._show_table_context_menu(dlg._table.visualItemRect(dlg._table.item(0, 0)).center())
    dlg._show_hidden_action.setChecked(False)
    assert dlg._table.rowCount() == 1


# ── Eigener Katalog: KOs in der Datenbank (Format 3) ──

_CO = {"number": 3, "name": "R_1_VOLUME", "function_text": "Volume",
       "datapoint_type": "DPT-5", "communication_flag": True, "read_flag": False,
       "write_flag": True, "transmit_flag": False, "update_flag": True}


def _write_user_catalog(data):
    with open(_user_catalog_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)


def _raw_user_catalog():
    return json.load(open(_user_catalog_path(), encoding="utf-8"))


def _assert_upgraded():
    raw = _raw_user_catalog()
    assert raw["format"] == 3
    assert "com_objects" not in raw["products"][0]
    assert raw["products"][0]["co_count"] == 1
    assert ProductSearchService().find_product(
        "Weinzierl", _NEW["order_number"])["com_objects"] == [_CO]


def test_format_1_is_moved_to_database():
    _write_user_catalog({"products": [{**_NEW, "com_objects": [_CO]}]})
    svc = ProductSearchService()
    assert svc.find_product("Weinzierl", _NEW["order_number"])["com_objects"] == [_CO]
    _assert_upgraded()


def test_format_2_is_moved_to_database():
    _write_user_catalog({"format": 2, "products": [
        {**_NEW, "com_objects": [[3, "R_1_VOLUME", "Volume", "DPT-5", 0b10101]]}]})
    ProductSearchService()
    _assert_upgraded()


def test_round_trip_is_lossless():
    extra = {"number": 1, "name": "X", "function_text": "", "datapoint_type": "",
             "communication_flag": True, "object_size": "1 Bit"}
    no_flag = {"number": 2, "name": "Y", "function_text": "", "datapoint_type": ""}
    given = {**_NEW, "com_objects": [extra, no_flag, _CO]}
    ProductSearchService().add_product(given)
    assert given["com_objects"] == [extra, no_flag, _CO]    # Eingabe unverändert
    cos = ProductSearchService().find_product("Weinzierl", _NEW["order_number"])["com_objects"]
    assert cos == [extra, no_flag, _CO]
    assert not os.path.exists(_user_catalog_path() + ".tmp")


def test_search_loads_com_objects_only_on_access():
    ProductSearchService().add_product({**_NEW, "com_objects": [_CO]})
    svc = ProductSearchService()
    assert all("com_objects" not in p for p in svc._user_products)   # nur co_count
    calls = []
    store_get = svc._store.get
    svc._store.get = lambda key: calls.append(key) or store_get(key)
    result = svc.search_all("Revox")
    assert len(result) == 1 and not calls
    assert result[0].com_objects == [_CO]
    assert result[0].com_objects == [_CO] and len(calls) == 1          # einmal geladen


def test_edit_with_new_order_number_moves_com_objects():
    svc = ProductSearchService()
    svc.add_product({**_NEW, "com_objects": [_CO]})
    svc.edit_product("Weinzierl", _NEW["order_number"], {"order_number": "MU-3.0"})
    reloaded = ProductSearchService()
    assert reloaded.find_product("Weinzierl", "MU-3.0")["com_objects"] == [_CO]
    from knix_arranger.utils.manufacturers import product_key
    assert reloaded._store.get(product_key("Weinzierl", _NEW["order_number"])) == []


def test_missing_database_gives_empty_com_objects():
    ProductSearchService().add_product({**_NEW, "com_objects": [_CO]})
    os.remove(os.path.join(os.path.dirname(_user_catalog_path()),
                           "product_com_objects.sqlite"))
    assert ProductSearchService().find_product(
        "Weinzierl", _NEW["order_number"])["com_objects"] == []


def test_dialog_uses_session_catalog():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.services.product_sync import shared_catalog
    from knix_arranger.ui.dialogs.product_select_dialog import ProductSelectDialog
    svc = ProductSearchService()
    svc.add_product(dict(_NEW))                 # gespeichert -> Sitzungskatalog
    assert shared_catalog() is svc
    assert ProductSelectDialog()._search_service is svc


def test_recent_product_comes_with_com_objects(monkeypatch, tmp_path):
    """"Zuletzt verwendet" speichert nur Stammdaten -- gewählt wurde das
    Revox deshalb ohne KOs (Projekt_23, 13.10.2026)."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.services import recent_products
    from knix_arranger.ui.dialogs.product_select_dialog import ProductSelectDialog
    monkeypatch.setattr(recent_products, "_RECENT_FILE", str(tmp_path / "recent.json"))
    ProductSearchService().add_product({**_NEW, "com_objects": [_CO]})
    recent_products.add_recent({k: _NEW[k] for k in ("manufacturer", "order_number",
                                                     "product_name", "category")})
    dlg = ProductSelectDialog()
    assert dlg._recent_table.rowCount() == 1
    dlg._recent_table.selectRow(0)
    assert dlg._selected.order_number == _NEW["order_number"]
    assert dlg._selected.com_objects == [_CO]
