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


# ── Kompaktes Format des eigenen Katalogs (Format 2) ──

def _write_user_catalog(data):
    with open(_user_catalog_path(), "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_old_format_is_read_and_upgraded_once():
    co = {"number": 3, "name": "R_1_VOLUME", "function_text": "Volume",
          "datapoint_type": "DPT-5", "communication_flag": True, "read_flag": False,
          "write_flag": True, "transmit_flag": False, "update_flag": True}
    _write_user_catalog({"products": [{**_NEW, "com_objects": [co]}]})
    svc = ProductSearchService()
    assert svc.find_product("Weinzierl", _NEW["order_number"])["com_objects"] == [co]
    raw = json.load(open(_user_catalog_path(), encoding="utf-8"))
    assert raw["format"] == 2
    assert raw["products"][0]["com_objects"] == [[3, "R_1_VOLUME", "Volume", "DPT-5", 0b10101]]
    # erneut geladen: gleiche KOs, keine weitere Umstellung nötig
    assert ProductSearchService().find_product(
        "Weinzierl", _NEW["order_number"])["com_objects"] == [co]


def test_packed_round_trip_keeps_extra_fields_and_default_flag():
    extra = {"number": 1, "name": "X", "function_text": "", "datapoint_type": "",
             "communication_flag": True, "object_size": "1 Bit"}
    no_flag = {"number": 2, "name": "Y", "function_text": "", "datapoint_type": ""}
    svc = ProductSearchService()
    svc.add_product({**_NEW, "com_objects": [extra, no_flag]})
    raw = json.load(open(_user_catalog_path(), encoding="utf-8"))
    rows = raw["products"][0]["com_objects"]
    assert rows[0] == extra                    # Zusatzfeld: bleibt Dict
    assert rows[1] == [2, "Y", "", "", 1]      # fehlendes Flag = kommunizierend
    cos = ProductSearchService().find_product("Weinzierl", _NEW["order_number"])["com_objects"]
    assert cos[0] == extra
    assert cos[1]["communication_flag"] is True and cos[1]["write_flag"] is False
    assert not os.path.exists(_user_catalog_path() + ".tmp")


def test_dialog_uses_session_catalog():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.services.product_sync import shared_catalog
    from knix_arranger.ui.dialogs.product_select_dialog import ProductSelectDialog
    svc = ProductSearchService()
    svc.add_product(dict(_NEW))                 # gespeichert -> Sitzungskatalog
    assert shared_catalog() is svc
    assert ProductSelectDialog()._search_service is svc
