"""Aktor mit Kanaldefizit auf mehrere Geräte aufteilen (Materialliste).

Projekt_23 1.1.10: «Heizungsaktor 12-fach» = ABB VAA/S6.230.2.1 mit 6
Kanälen -- mehr Stück in der Materialliste ergaben kein zweites Gerät, die
Heizkreise 7–12 lagen auf Kanälen, die es nicht gibt.
"""
from __future__ import annotations

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections import Counter
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.belegungsplan_service import BelegungsplanService
from knix_arranger.services.product_search_service import ProductSuggestion
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.ui.views import material_list_view as module
from knix_arranger.ui.views.material_list_view import MaterialListView

_VAA = ProductSuggestion(manufacturer="ABB", order_number="VAA/S6.230.2.1",
                         product_name="Heizungsaktor 6-fach 230V REG", channels=6,
                         category="actor", actor_type="Heizungsaktor")


@pytest.fixture
def view():
    QApplication.instance() or QApplication([])
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="Heizung")
    rooms = [Room(number=f"W0{n}", name=f"Raum {n}",
                  gewerk_assignments=[GewerkAssignment(gewerk_code="H", count=4)])
             for n in range(1, 4)]
    rooms[0].gewerk_assignments.append(GewerkAssignment(gewerk_code="J", count=2))
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2,
                  apartments=[Apartment(name="Wohnung", rooms=rooms)])
    project.areal = Areal(buildings=[Building(name="Haus", wings=[Wing(floors=[floor])])])
    engine = TopologyEngine(project.config.topology_mode)
    project.topology = engine.calculate_topology(project.areal)
    engine.populate_devices(project.topology, project.all_rooms, project.gewerk_catalog)
    regenerate_addresses(project)
    view = MaterialListView()
    view.set_project(project)
    yield view
    logging.disable(logging.NOTSET)


def _heating(view):
    return next(e for e in view._material_list.entries
                if e.device_type.startswith("Heizungsaktor") and e.required_channels == 12)


def _devices(view):
    return {d.physical_address: d for area in view._project.topology.areas
            for line in area.lines for d in line.devices}


class Dialog:
    """Produktdialog, der den Heizungsaktor wählt."""
    def __init__(self, *args, **kwargs):
        self._search_edit = type("E", (), {"setText": lambda *_: None})()
        self.selected_product = _VAA

    def setWindowTitle(self, *_):
        pass

    def has_type_preselection(self):
        return True

    def exec(self):
        return True


def test_produkt_mit_defizit_teilt_auf(view):
    """Ohne Rückfrage: die nötige Anzahl Geräte wird eingefügt."""
    entry = _heating(view)
    jalousie = next(e for e in view._material_list.entries if e.device_type.startswith("Jalousie"))
    jalousie_device = _devices(view)[jalousie.physical_addresses[0]]

    with patch.object(module, "ProductSelectDialog", Dialog), \
            patch("knix_arranger.services.product_sync.shared_catalog", return_value=None), \
            patch.object(QMessageBox, "information") as info, \
            patch.object(view, "_offer_channel_assignment"):
        view._assign_product_to_entry(entry)
    assert "2 Geräte eingefügt" in info.call_args[0][2]

    heating = [e for e in view._material_list.entries if e.device_type == "Heizungsaktor 6-fach"]
    assert len(heating) == 2 and entry not in view._material_list.entries
    devices = _devices(view)
    for e in heating:
        device = devices[e.physical_addresses[0]]
        assert (device.order_number, device.product, e.required_channels) == (
            "VAA/S6.230.2.1", "Heizungsaktor 6-fach", 6)
    # Die 12 Heizkreise verteilen sich auf je 6 Kanäle
    rows = [r for r in BelegungsplanService().generate(view._project).actor_rows
            if r.function_name == "STELLGROESSE" and r.room_id]
    per_device = Counter(r.physical_address for r in rows)
    assert sorted(per_device.values()) == [6, 6]
    # Die Adresse des nachfolgenden Aktors ist in der Materialliste nachgeführt
    assert jalousie.physical_addresses == [jalousie_device.physical_address]


def test_typ_batch_teilt_aktoren_auf(view):
    """Zuweisung an alle Platzhalter eines Typs: Aktoren mit zu wenig Kanälen
    werden ebenfalls aufgeteilt."""
    from PySide6.QtWidgets import QInputDialog
    entry = _heating(view)
    with patch.object(module, "ProductSelectDialog", Dialog), \
            patch("knix_arranger.services.product_sync.shared_catalog", return_value=None), \
            patch.object(QInputDialog, "getItem",
                         side_effect=lambda _p, _t, _l, items, *_a: (
                             next(i for i in items if i.startswith(entry.device_type)), True)), \
            patch.object(QMessageBox, "warning") as warning, \
            patch.object(QMessageBox, "information") as info, \
            patch.object(view, "_offer_device_product"), \
            patch.object(view, "_auto_assign_kos"):
        view._batch_assign_by_type()
    assert not warning.called                      # keine Rückfrage für Aktoren
    assert "auf mehrere Geräte" in info.call_args[0][2]
    heating = [e for e in view._material_list.entries if e.device_type == "Heizungsaktor 6-fach"]
    assert len(heating) == 2
    assert {_devices(view)[e.physical_addresses[0]].order_number for e in heating} == {
        "VAA/S6.230.2.1"}


def test_aufteilen_uebernimmt_produkt(view):
    entry = _heating(view)
    device = _devices(view)[entry.physical_addresses[0]]
    device.apply_product(_VAA)
    new = view._split_actor(entry, 2)
    devices = _devices(view)
    assert [devices[e.physical_addresses[0]].order_number for e in new] == ["VAA/S6.230.2.1"] * 2


def test_variante_mit_kos_wird_angeboten(view):
    """Katalog kennt das Gerät doppelt: ohne KOs und aus der KNXPROD."""
    variant = ProductSuggestion(manufacturer="ABB", order_number="2CDG 110 116 R0011",
                                product_name="VAA/S6.230.2.1 Valve Drive Actuator, 6f",
                                channels=6, category="actor", co_count=82)

    class Catalog:
        def variant_with_com_objects(self, prod):
            return variant if prod.order_number == "VAA/S6.230.2.1" else None
    with patch("knix_arranger.services.product_sync.shared_catalog", return_value=Catalog()), \
            patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        assert view._prefer_variant_with_kos(_VAA) is variant
    with patch("knix_arranger.services.product_sync.shared_catalog", return_value=Catalog()), \
            patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        assert view._prefer_variant_with_kos(_VAA) is _VAA


def _catalog():
    """Katalog mit dem ABB-Heizungsaktor doppelt (Basis ohne KOs, KNXPROD mit
    82 KOs), einem fremden Nachbau und einem Platzhalter."""
    from knix_arranger.services.product_search_service import ProductSearchService
    service = ProductSearchService.__new__(ProductSearchService)
    service._catalog = [
        {"manufacturer": "ABB", "order_number": "VAA/S6.230.2.1",
         "product_name": "Heizungsaktor 6-fach 230V REG", "category": "actor", "channels": 6},
        {"manufacturer": "ABB", "order_number": "2CDG 110 116 R0011",
         "product_name": "VAA/S6.230.2.1 Valve Drive Actuator, 6f", "category": "actor",
         "channels": 6, "co_count": 82},
        {"manufacturer": "Hager", "order_number": "X", "product_name": "VAA/S6.230.2.1 Nachbau",
         "category": "actor", "co_count": 5},
        {"manufacturer": "Feller", "order_number": "Dummy", "product_name": "Dummy Secure",
         "category": "actor"},
        {"manufacturer": "Feller", "order_number": "Dummy", "product_name": "Dummy",
         "category": "actor", "co_count": 3},
    ]
    service._hidden = set()
    service._online_keys = set()
    service._user_products = []
    service._indexes = {}
    service._pending_com_objects = {}
    service.com_objects_of = lambda product: []
    return service


def test_katalog_findet_doppelte():
    service = _catalog()
    duplicates = service.duplicate_variants()
    assert [other["order_number"] for other in duplicates.values()] == [
        "2CDG 110 116 R0011"]                              # Platzhalter nicht
    assert service.duplicate_of("ABB", "VAA/S6.230.2.1")["co_count"] == 82
    variant = service.variant_with_com_objects(_VAA)
    assert (variant.order_number, variant.co_count) == ("2CDG 110 116 R0011", 82)
    assert service.variant_with_com_objects(variant) is None   # hat schon KOs
    # Die Produktsuche bietet den Eintrag ohne KOs nicht mehr an
    orders = [p.order_number for p in service.search_all(query="VAA/S6")]
    assert "VAA/S6.230.2.1" not in orders and "2CDG 110 116 R0011" in orders
    assert "VAA/S6.230.2.1" in [p.order_number for p in
                                service.search_all(query="VAA/S6", include_hidden=True)]


def test_materialliste_ersetzt_doppelte(view):
    entry = _heating(view)
    entry.manufacturer, entry.order_number = "ABB", "VAA/S6.230.2.1"
    entry.product_name = _VAA.product_name
    device = _devices(view)[entry.physical_addresses[0]]
    device.apply_product(_VAA)
    with patch("knix_arranger.services.product_sync.shared_catalog", return_value=_catalog()):
        pairs = view.duplicate_replacements()
        assert [(e, v.order_number) for e, v in pairs] == [(entry, "2CDG 110 116 R0011")]
        view.apply_replacements(pairs)
        assert view.duplicate_replacements() == []
    assert (entry.order_number, device.order_number) == ("2CDG 110 116 R0011",) * 2


def test_validierung_warnt_bei_doppeltem_produkt(view):
    from knix_arranger.models.group_address import GroupAddressStructure
    from knix_arranger.services.validation_engine import ValidationEngine
    device = _devices(view)[_heating(view).physical_addresses[0]]
    device.apply_product(_VAA)
    with patch("knix_arranger.services.product_sync.shared_catalog", return_value=_catalog()):
        issues = [i for i in ValidationEngine().validate(GroupAddressStructure(), view._project)
                  if i.rule_id == "FA-622"]
    assert len(issues) == 1 and issues[0].level == "warning"
    assert "2CDG 110 116 R0011" in issues[0].message
