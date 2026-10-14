"""Produktordner: Sammlung der .knxprod-Dateien, neue Dateien melden und
einlesen; Busgeräte nur mit KOs in der Produktauswahl."""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.services import product_folder as pf
from knix_arranger.services.product_search_service import ProductSuggestion


def _file(folder, name, content=b"x"):
    path = os.path.normpath(os.path.join(folder, name))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


def test_ordner_aus_arbeitsverzeichnis_und_einstellung(tmp_path):
    from knix_arranger.utils.app_settings import load_settings, save_settings
    save_settings({"workspace_root_path": str(tmp_path)})
    assert pf.products_folder() == os.path.join(str(tmp_path), "Produkte KNX")
    pf.set_products_folder(str(tmp_path / "Eigene"))
    assert pf.products_folder() == str(tmp_path / "Eigene")
    assert load_settings()["workspace_root_path"] == str(tmp_path)   # bleibt


def test_neue_und_geaenderte_dateien(tmp_path):
    folder = str(tmp_path / "Produkte KNX")
    abb = _file(folder, "ABB.knxprod")
    mdt = _file(folder, "MDT/Taster.knxprod")
    _file(folder, "liesmich.txt")
    assert pf.pending_files(folder) == [abb, mdt]
    pf.mark_imported([abb, mdt], {abb: 281, mdt: 4}, folder)
    assert pf.pending_files(folder) == []
    index = next(iter(pf.load_index().values()))
    assert index["MDT/Taster.knxprod"]["products"] == 4
    # Neue Fassung (andere Grösse) wird wieder gemeldet
    time.sleep(0.01)
    _file(folder, "ABB.knxprod", b"neuer")
    assert pf.pending_files(folder) == [abb]


def test_import_legt_datei_in_den_ordner(tmp_path):
    folder = str(tmp_path / "Produkte KNX")
    outside = _file(str(tmp_path / "Downloads"), "Theben.knxprod")
    inside = _file(folder, "ABB.knxprod")
    copies = pf.add_to_folder([outside, inside], folder)
    assert copies == [os.path.join(folder, "Theben.knxprod"), inside]
    assert os.path.exists(copies[0])
    # Ein Nachbarordner mit gleichem Anfang gilt nicht als Produktordner
    neighbour = _file(str(tmp_path / "Produkte KNX2"), "X.knxprod")
    pf.mark_imported([neighbour], {}, folder)
    assert "X.knxprod" not in str(pf.load_index())


def test_busgeraete_und_fehlende_hersteller():
    actor = ProductSuggestion(manufacturer="ABB", category="actor")
    sensor = ProductSuggestion(manufacturer="MDT", category="sensor")
    dali = ProductSuggestion(manufacturer="MDT", category="infrastructure",
                             device_type="DALI-Gateway")
    psu = ProductSuggestion(manufacturer="ABB", category="infrastructure",
                            device_type="Netzteil")
    with_kos = ProductSuggestion(manufacturer="Hager", category="actor", co_count=12)
    assert [pf.is_bus_device(p) for p in (actor, sensor, dali, psu)] == [True, True, True, False]
    assert pf.missing_manufacturers([actor, sensor, dali, psu, with_kos]) == {"MDT": 2, "ABB": 1}


def test_produktauswahl_blendet_busgeraete_ohne_kos_aus():
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.product_select_dialog import ProductSelectDialog
    products = [
        ProductSuggestion(manufacturer="ABB", order_number="VAA", product_name="ohne KOs",
                          category="actor", actor_type="Heizungsaktor"),
        ProductSuggestion(manufacturer="ABB", order_number="2CDG", product_name="mit KOs",
                          category="actor", actor_type="Heizungsaktor", co_count=82),
        ProductSuggestion(manufacturer="ABB", order_number="SV/S", product_name="Netzteil",
                          category="infrastructure", device_type="Netzteil"),
    ]
    dialog = ProductSelectDialog()
    with patch.object(dialog._search_service, "search_all", return_value=products):
        dialog._refresh_results()
        shown = [dialog._table.item(r, 2).text() for r in range(dialog._table.rowCount())]
        assert sorted(shown) == ["2CDG", "SV/S"]
        assert "KNXPROD fehlt für: ABB (1)" in dialog._missing_label.text()
        dialog._show_without_kos_action.setChecked(True)
        assert dialog._table.rowCount() == 3
