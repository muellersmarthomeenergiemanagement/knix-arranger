"""
Produktdialog: Typenbaum (Gruppe › Typ mit Anzahl), Spalten Kanäle/KOs,
Infobereich mit der Kanalbenennung des Herstellers, KNXPROD per Einfügen
(Strg+V) oder Ziehen.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QMimeData, Qt, QUrl
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication

from knix_arranger.services.product_search_service import ProductSearchService


def _co(i, text):
    return {"number": i, "name": text, "function_text": text, "datapoint_type": "DPT-1",
            "communication_flag": True, "read_flag": False, "write_flag": True,
            "transmit_flag": False, "update_flag": False}


_PRODUCTS = [
    {"manufacturer": "ABB", "order_number": "TEST SA/S4.16", "product_name": "Switch Act, 4-f",
     "category": "actor", "device_type": "Schaltaktor", "channels": 4,
     "com_objects": [_co(i, f"Kanal {c}: Schalten") for i, c in enumerate("ABCD", 1)]},
    {"manufacturer": "ABB", "order_number": "TEST UD/S2", "product_name": "Dimm Act 2-f",
     "category": "actor", "device_type": "Dimmaktor", "channels": 2},
    {"manufacturer": "Weinzierl", "order_number": "TEST Revox MU 3.0",
     "product_name": "Revox Multiuser 3.0", "category": "infrastructure",
     "device_type": "Multimedia-Gateway"},
]


@pytest.fixture
def dialog_factory(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    from knix_arranger.services import recent_products
    monkeypatch.setattr(recent_products, "_RECENT_FILE", str(tmp_path / "recent.json"))
    ProductSearchService().add_products(_PRODUCTS)
    from knix_arranger.ui.dialogs import product_select_dialog

    def make(**kwargs):
        dlg = product_select_dialog.ProductSelectDialog(**kwargs)
        dlg._search_edit.setText("TEST")   # ohne den mitgelieferten Basiskatalog
        return dlg
    return make


def _tree_texts(dlg):
    texts = []
    for i in range(dlg._type_tree.topLevelItemCount()):
        item = dlg._type_tree.topLevelItem(i)
        texts.append(item.text(0))
        texts += ["  " + item.child(j).text(0) for j in range(item.childCount())]
    return texts


def _orders(dlg):
    from knix_arranger.ui.dialogs.product_select_dialog import _COL_ORDER
    return sorted(dlg._table.item(r, _COL_ORDER).text() for r in range(dlg._table.rowCount()))


def test_tree_groups_and_filter(dialog_factory):
    dlg = dialog_factory()
    texts = _tree_texts(dlg)
    assert texts[0].startswith("Alle Produkte (")
    assert "  Schaltaktor (1)" in texts and "  Multimedia-Gateway (1)" in texts
    gateway = next(i for i in range(dlg._type_tree.topLevelItemCount())
                   if dlg._type_tree.topLevelItem(i).text(0).startswith("Gateways"))
    dlg._type_tree.setCurrentItem(dlg._type_tree.topLevelItem(gateway))
    assert _orders(dlg) == ["TEST Revox MU 3.0"]
    # Suche zählt im Baum mit, die Auswahl bleibt
    dlg._search_edit.setText("TEST UD")
    assert dlg._table.rowCount() == 0
    assert dlg.has_type_preselection()


def test_preselection_from_material_list_and_gateway_gewerk(dialog_factory):
    dlg = dialog_factory(initial_device_type="Schaltaktor 8-fach")
    assert dlg._type_filter == ("type", "Schaltaktor")
    assert _orders(dlg) == ["TEST SA/S4.16"]
    dlg = dialog_factory(initial_device_type="KNX-Schnittstelle")     # Gewerk MM
    assert dlg._type_filter == ("group", "Gateways & Schnittstellen")
    assert _orders(dlg) == ["TEST Revox MU 3.0"]
    dlg = dialog_factory(initial_category_filter="actor")
    assert _orders(dlg) == ["TEST SA/S4.16"]      # Aktor ohne KOs ausgeblendet
    dlg._show_without_kos_action.setChecked(True)
    assert _orders(dlg) == ["TEST SA/S4.16", "TEST UD/S2"]
    assert not dialog_factory()._type_filter[0]


def test_columns_and_details_with_manufacturer_channel_names(dialog_factory):
    from knix_arranger.ui.dialogs.product_select_dialog import _COL_CH, _COL_KO, _COL_ORDER
    dlg = dialog_factory()
    row = next(r for r in range(dlg._table.rowCount())
               if dlg._table.item(r, _COL_ORDER).text() == "TEST SA/S4.16")
    assert dlg._table.item(row, _COL_CH).text() == "4"
    assert dlg._table.item(row, _COL_KO).text() == "4"
    dlg._table.selectRow(row)
    text = dlg._details.text()
    assert "4 KOs" in text and "4 Kanäle im Gerät: Kanal A – Kanal D" in text
    # ohne KOs (nur mit «Auch Geräte ohne KOs zeigen»)
    dlg._show_without_kos_action.setChecked(True)
    row = next(r for r in range(dlg._table.rowCount())
               if dlg._table.item(r, _COL_ORDER).text() == "TEST UD/S2")
    assert dlg._table.item(row, _COL_KO).text() == "–"
    dlg._table.selectRow(row)
    assert "ohne KOs" in dlg._details.text()


def test_number_columns_sort_numerically(dialog_factory):
    from knix_arranger.ui.dialogs.product_select_dialog import _NumberItem
    assert _NumberItem(2) < _NumberItem(10)
    assert _NumberItem(0).text() == "–"


def _mime_with(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def test_knxprod_paths_from_files_and_folders(tmp_path):
    from knix_arranger.ui.dialogs.product_select_dialog import _knxprod_paths
    sub = tmp_path / "ABB"
    sub.mkdir()
    (sub / "a.knxprod").write_bytes(b"")
    (tmp_path / "b.KNXPROD").write_bytes(b"")
    (tmp_path / "notiz.txt").write_text("x")
    paths = _knxprod_paths(_mime_with([tmp_path]))
    assert [os.path.basename(p) for p in paths] == ["a.knxprod", "b.KNXPROD"]
    assert _knxprod_paths(_mime_with([tmp_path / "notiz.txt"])) == []
    assert _knxprod_paths(None) == []


def test_paste_imports_copied_knxprod_files(dialog_factory, monkeypatch, tmp_path):
    knxprod = tmp_path / "Revox.knxprod"
    knxprod.write_bytes(b"")
    dlg = dialog_factory()
    imported = []
    monkeypatch.setattr(dlg, "_import_paths", lambda paths, base="": imported.append(paths))
    QApplication.clipboard().setMimeData(_mime_with([knxprod]))
    dlg.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_V, Qt.ControlModifier))
    assert len(imported) == 1 and os.path.basename(imported[0][0]) == "Revox.knxprod"
    # Im Suchfeld: Dateien werden importiert, Text bleibt normaler Text
    imported.clear()
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_V, Qt.ControlModifier)
    assert event.matches(QKeySequence.Paste)
    assert dlg.eventFilter(dlg._search_edit, event) is True and len(imported) == 1
    QApplication.clipboard().setText("Revox")
    imported.clear()
    assert dlg.eventFilter(dlg._search_edit, event) is False and not imported


def test_drop_imports_knxprod(dialog_factory, monkeypatch, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QDropEvent
    knxprod = tmp_path / "Revox.knxprod"
    knxprod.write_bytes(b"")
    dlg = dialog_factory()
    imported = []
    monkeypatch.setattr(dlg, "_import_paths", lambda paths, base="": imported.append(paths))
    mime = _mime_with([knxprod])
    event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    dlg.dropEvent(event)
    assert len(imported) == 1 and imported[0][0].endswith("Revox.knxprod")


def test_assignment_without_quantity(dialog_factory):
    """Produkt für bestehende Zeilen: Menge und Linie gelten nicht (die
    Anzahl folgt aus der Topologie) und werden nicht angezeigt."""
    dlg = dialog_factory(for_assignment=True)
    assert not dlg._qty_spin.parentWidget().isVisibleTo(dlg)
    assert dlg._line_combo is None
    add = dialog_factory()
    assert add._qty_spin.parentWidget().isVisibleTo(add)
