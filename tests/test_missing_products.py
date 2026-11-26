"""
Fehlende Herstellerdateien (FA-3108f): Liste je Hersteller und Applikation,
Nachführen mit Erhalt der Verknüpfungen und neuer Bedeutung, Herauslösen aus
einem ETS-Projekt, Arbeitsliste und Schrittleiste.
"""
from __future__ import annotations

import os

from knix_arranger.models.project import KnxProject
from knix_arranger.services import device_scan as ds
from knix_arranger.services import ga_meaning
from knix_arranger.services import missing_products as mp
from tests.test_device_scan import _Catalog


def _reconstructed() -> KnxProject:
    """Vom Bus aufgenommen, ohne Katalog: ABB-Aktor 1.1.5 und Elsner 1.2.3,
    GAs gelesen und Bedeutung ergänzt (nur «KO n», darum SF)."""
    project = KnxProject()
    findings = [
        ds.ScanFinding("1.1.5", True, 0x07B0, "M-0002", program="4701-11",
                       order_info="SA/S8.16.5"),
        ds.ScanFinding("1.1.6", True, 0x07B0, "M-0002", program="4701-11",
                       order_info="SA/S8.16.5"),
        ds.ScanFinding("1.2.3", True, 0x07B0, "M-00C9", program="0101-10",
                       order_info="70135"),
    ]
    ds.adopt_findings(project, findings, None)
    ds.adopt_links(project, [ds.LinkTables("1.1.5", ["1/0/1"], {0: ["1/0/1"]}),
                             ds.LinkTables("1.1.6", ["1/0/2"], {0: ["1/0/2"]}),
                             ds.LinkTables("1.2.3", ["3/0/1"], {4: ["3/0/1"]})])
    ga_meaning.apply(project, ga_meaning.propose(project))
    return project


def _ga(project, address):
    return next(g for g in project.group_addresses.all_addresses() if g.address == address)


def test_missing_lists_manufacturer_order_and_application():
    project = _reconstructed()
    entries = mp.missing(project)
    assert [(e.manufacturer_id, e.program, e.addresses) for e in entries] == [
        ("M-0002", "4701-11", ["1.1.5", "1.1.6"]), ("M-00C9", "0101-10", ["1.2.3"])]
    abb = entries[0]
    assert abb.manufacturer == "ABB" and abb.order_numbers == ["SA/S8.16.5"]
    assert abb.application_text == "4701 Version 1.1"
    assert mp.device_count(project) == 3


def test_complete_keeps_links_and_refreshes_meaning():
    project = _reconstructed()
    assert "_1.1.5_" in _ga(project, "1/0/1").designation      # nach Geräteadresse benannt
    # von Hand benannt: bleibt
    _ga(project, "1/0/2").designation = "Licht Küche"
    result = mp.complete(project, _Catalog())
    assert result.completed == ["1.1.5", "1.1.6"] and result.still_missing == ["1.2.3"]
    device = next(d for d in ds.project_devices(project) if d.physical_address == "1.1.5")
    assert device.product == "Schaltaktor 8-fach" and device.hw2prog_id
    linked = [(co.name, co.connected_gas) for co in device.communication_objects
              if co.connected_gas]
    assert linked == [("Ausgang A", ["1/0/1"])]
    assert "Ausgang A" in _ga(project, "1/0/1").designation
    assert _ga(project, "1/0/2").designation == "Licht Küche"
    assert result.renamed >= 1
    assert "2 Geräte" in result.text() and "1.2.3" in result.text()
    assert [e.manufacturer_id for e in mp.missing(project)] == ["M-00C9"]


def test_from_knxproj_never_replaces_library_file(tmp_path, monkeypatch):
    from knix_arranger.services import knxproj_import_service, product_folder
    library = tmp_path / "Produkte KNX"
    library.mkdir()
    (library / "ABB (M-0002).knxprod").write_bytes(b"voll")
    monkeypatch.setattr(product_folder, "products_folder", lambda: str(library))

    def extract(self, path, dest):
        out = os.path.join(dest, "ABB (M-0002).knxprod")
        open(out, "wb").write(b"nur dieses Projekt")
        other = os.path.join(dest, "Elsner (M-00C9).knxprod")
        open(other, "wb").write(b"elsner")
        return [out, other]
    monkeypatch.setattr(knxproj_import_service.KnxprojImportService,
                        "extract_product_libraries", extract)
    read = []
    monkeypatch.setattr(mp, "read_files",
                        lambda paths, catalog=None: read.append(
                            sorted(os.path.basename(p) for p in paths)) or mp.ReadResult(2))
    result = mp.from_knxproj(str(tmp_path / "Chalet.knxproj"), catalog=object())
    assert result.products == 2
    assert read == [["ABB (M-0002) aus Chalet.knxprod", "Elsner (M-00C9).knxprod"]]
    assert (library / "ABB (M-0002).knxprod").read_bytes() == b"voll"


def test_worklist_and_steps_show_missing_files():
    from knix_arranger.services import ets_worklist
    from knix_arranger.services import reconstruction_steps as rs
    project = _reconstructed()
    items = [i for i in ets_worklist.current_items(project) if i.rule_id == "FA-3108f"]
    assert [i.where for i in items] == ["Gerät 1.1.5", "Gerät 1.1.6", "Gerät 1.2.3"]
    assert "4701 Version 1.1" in items[0].task and "SA/S8.16.5" in items[0].task
    adopt = next(s for s in rs.steps(project) if s.key == rs.ADOPT)
    assert adopt.state == rs.PARTIAL and "3 ohne Herstellerdatei" in adopt.detail
    mp.complete(project, _Catalog())
    adopt = next(s for s in rs.steps(project) if s.key == rs.ADOPT)
    assert "1 ohne Herstellerdatei" in adopt.detail


def test_dialog_lists_and_completes(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.missing_products_dialog import MissingProductsDialog
    project = _reconstructed()
    monkeypatch.setattr(mp, "read_pending", lambda catalog=None: mp.ReadResult())
    dialog = MissingProductsDialog(project, catalog=_Catalog())
    assert dialog._table.rowCount() == 2
    assert dialog._table.item(0, 0).text() == "ABB (M-0002)"
    assert dialog._table.item(0, 2).text() == "4701 Version 1.1"
    assert dialog._table.item(0, 3).text() == "1.1.5, 1.1.6"
    dialog._complete()
    assert dialog.completed == ["1.1.5", "1.1.6"]
    assert dialog._table.rowCount() == 1
    assert "2 Geräte" in dialog._status.text()


def test_view_shows_button_only_with_missing_files():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.views.device_scan_view import DeviceScanView
    view = DeviceScanView()
    view.set_project(KnxProject())
    assert view._products_btn.isHidden()
    view.set_project(_reconstructed())
    assert not view._products_btn.isHidden()
    assert view._products_btn.text() == "Herstellerdateien (3)…"
