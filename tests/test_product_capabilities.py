"""
Fähigkeiten realer Produkte (FA-1411), Abgleich mit der Planung (FA-629,
FA-630) und Raumtemperatur über einen Taster (FA-1411b).
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import CommunicationObject
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.product_capabilities import (
    TEMPERATURE, capabilities, keys_from_name, plan_conflicts, temperature_source_of,
    use_taster_temperature,
)
from knix_arranger.services.sensor_channels import (
    sensor_links, sensor_plan, suggested_sensor_co_map,
)
from knix_arranger.services.sensor_service import SensorService
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.services.validation_engine import ValidationEngine


def _co(number, name, flags="K--Ü--", dpt=""):
    return CommunicationObject(object_number=number, name=name, object_function=name,
                               flags=flags, data_type=dpt)


def _edizio_colore() -> list:
    """Wie im Katalog: Tasten-KOs ohne Namen, KO 70 «Raumtemperatur»."""
    cos = [_co(n, f"Object {n + 1}", "K-SÜ--") for n in range(26)]
    cos.append(_co(70, "Raumtemperatur", "K--Ü--", "DPST-9-1"))
    cos.append(_co(71, "Fremdsteuerung Raumtemperatur", "K-S---", "DPST-9-1"))
    return cos


def test_capabilities_from_kos_and_name():
    rocker = [_co(0, "Taste 1", "K-SÜ--"), _co(3, "Taste 1, rechts", "K-SÜ--"),
              _co(18, "Taste 4", "K-SÜ--"), _co(21, "Taste 4, rechts", "K-SÜ--")]
    caps = capabilities(rocker)
    assert (caps.keys, caps.rocker) == (8, True)

    caps = capabilities(_edizio_colore(), "EDIZIOdue colore Taster 1-8fach RGB Temp")
    assert caps.keys == 8                                 # aus dem Namen
    assert caps.sensors[TEMPERATURE].object_number == 70  # nicht «Fremdsteuerung»
    assert "8 Tasten" in caps.summary and "Temperatur (KO 70)" in caps.summary

    rtr = [_co(53, "Room temperature, basic set value", "K-S---"),
           _co(55, "Room temperature, actual value", "KL-Ü--")]
    assert capabilities(rtr).sensors[TEMPERATURE].object_number == 55
    lgs = [_co(6, "RTC: Ist-Temperatur", "KL-Ü--", "DPT-9 DPST-9-1"),
           _co(9, "RTC: Störung Ist-Temperatur", "KL-Ü--", "DPST-1-1")]
    assert capabilities(lgs).sensors[TEMPERATURE].object_number == 6
    assert keys_from_name("Präsenzmelder 4-fach") == 0     # kein Taster


def _project(gewerk_catalog):
    room = Room(number="CDG02", name="Schlafzimmer")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=9),
                               GewerkAssignment(gewerk_code="H", count=1)]
    project = KnxProject(name="Fähigkeiten")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[Floor(
        name="DG", short_code="DG", main_group_number=1,
        apartments=[Apartment(name="Wohnung", rooms=[room])])])])])
    project._gewerk_catalog = gewerk_catalog
    engine = TopologyEngine(project.config.topology_mode)
    project.topology = engine.calculate_topology(project.areal)
    regenerate_addresses(project)
    _recompute(project)
    return project, room


def _recompute(project):
    SensorService().auto_assign_functions(project.all_rooms, project.group_addresses,
                                          topology=project.topology)
    engine = TopologyEngine(project.config.topology_mode)
    engine.populate_devices(project.topology, project.all_rooms, project.gewerk_catalog)
    SensorService().auto_assign_functions(project.all_rooms, project.group_addresses,
                                          topology=project.topology)


def _devices(project, product):
    return [d for a in project.topology.areas for l in a.lines for d in l.devices
            if d.device_type == "sensor" and d.product == product]


def _taster(project):
    device = _devices(project, "Tastereinheit")[0]
    device.communication_objects = _edizio_colore()
    device.product_name = "EDIZIOdue colore Taster 1-8fach RGB Temp"
    return device


def _issues(project, rule):
    return [i for i in ValidationEngine().validate(project.group_addresses, project)
            if i.rule_id == rule]


def test_plan_conflicts_and_takeover(gewerk_catalog):
    project, room = _project(gewerk_catalog)
    taster = _taster(project)
    thermostat = _devices(project, "Raumthermostat")[0]

    keys = _issues(project, "FA-629")
    assert keys and "9 Tasten geplant" in keys[0].message and "hat 8" in keys[0].message
    temp = _issues(project, "FA-630")
    assert temp and thermostat.physical_address in temp[0].message

    offer = next(o for o in plan_conflicts(project)[1] if o.device is taster)
    assert [be.participant_number for be in offer.thermostats] == [thermostat.physical_address]
    assert use_taster_temperature(project, offer, remove_thermostats=True) == 1
    heating = next(a for a in room.gewerk_assignments if a.gewerk_code == "H")
    assert heating.temperature_sources == {1: offer.bedienelement.taster_index}

    # Neuberechnung: Thermostat bleibt weg, Quelle bleibt, keine Meldung FA-630
    _recompute(project)
    taster = _taster(project)
    assert not _devices(project, "Raumthermostat")
    assert temperature_source_of(room, heating, 1) is not None
    assert _issues(project, "FA-630") == []

    # Der Taster sendet die IST-GA über KO 70
    links = sensor_links(project, taster, sensor_plan(project))
    temp_link = next(l for l in links if l.role == "raumtemperatur")
    ist = next(g for g in project.group_addresses.all_addresses()
               if g.gewerk_code == "H" and g.function_name == "IST")
    assert temp_link.ga_address == ist.address and not temp_link.feedback
    from knix_arranger.services.actor_channels import device_com_objects
    assert suggested_sensor_co_map(taster, links, device_com_objects(taster))[temp_link.key] == 70

    # Speichern/Laden
    loaded = KnxProject.from_dict(project.to_dict())
    h = next(a for r in loaded.all_rooms for a in r.gewerk_assignments if a.gewerk_code == "H")
    assert h.temperature_sources == heating.temperature_sources


def test_keep_thermostat(gewerk_catalog):
    project, room = _project(gewerk_catalog)
    taster = _taster(project)
    offer = next(o for o in plan_conflicts(project)[1] if o.device is taster)
    assert use_taster_temperature(project, offer, remove_thermostats=False) == 0
    _recompute(project)
    assert _devices(project, "Raumthermostat")


def test_jump_target_for_keys(gewerk_catalog):
    from knix_arranger.services import validation_targets as vt
    project, room = _project(gewerk_catalog)
    _taster(project)
    issue = _issues(project, "FA-629")[0]
    targets = vt.targets_for({"rule_id": issue.rule_id, "address": issue.address,
                              "message": issue.message, "details": issue.details}, project)
    assert targets[0].kind == vt.KEYS and targets[0].key == issue.address
    assert targets[1].kind == vt.BAUHERR and targets[1].key == room.id
    assert any(t.kind == vt.DEVICE for t in targets)


def test_split_surplus_to_second_taster(gewerk_catalog):
    from knix_arranger.services.product_capabilities import (
        copy_device_product, planned_keys, split_surplus,
    )
    project, room = _project(gewerk_catalog)
    taster = _taster(project)
    shortage = plan_conflicts(project)[0][0]
    assert (shortage.planned, shortage.available) == (9, 8)
    new_be = split_surplus(project, shortage)
    assert planned_keys(shortage.bedienelement) == 8 and planned_keys(new_be) == 1
    assert new_be.element_type == "Tastereinheit" and not new_be.is_auto

    _recompute(project)
    from knix_arranger.services.sensor_service import link_bedienelemente_to_devices
    link_bedienelemente_to_devices(project.topology, project.all_rooms)
    tasters = _devices(project, "Tastereinheit")
    assert len(tasters) == 2
    second = next(d for d in tasters if d.physical_address == new_be.participant_number)
    taster = next(d for d in tasters if d is not second)
    taster.communication_objects = _edizio_colore()
    taster.product_name = "EDIZIOdue colore Taster 1-8fach RGB Temp"
    copy_device_product(taster, second)
    assert second.product_name == taster.product_name
    assert [co.object_number for co in second.communication_objects][-1] == 71
    assert plan_conflicts(project)[0] == []


class _Product:
    def __init__(self, manufacturer, name, cos, order="X"):
        self.manufacturer, self.product_name, self.order_number = manufacturer, name, order
        self.sensor_type, self.channels = "Tastereinheit", 0
        self.manufacturer_id = self.product_ref_id = self.hw2prog_id = ""
        self.secure_supported = False
        self.com_objects = [{"number": c.object_number, "name": c.name,
                             "function_text": c.object_function, "datapoint_type": c.data_type,
                             "transmit_flag": True} for c in cos]
        self.co_count = len(cos)


class _Catalog:
    def __init__(self, products):
        self._products = products

    def search_sensors(self, _sensor_type):
        return self._products


def test_products_with_enough_keys(gewerk_catalog):
    from knix_arranger.services.product_capabilities import (
        apply_catalog_product, products_with_keys,
    )
    project, room = _project(gewerk_catalog)
    taster = _taster(project)
    taster.manufacturer = "Feller"
    ten = [_co(n, f"Taste {k}" + (", rechts" if n % 2 else "")) for n, k in
           enumerate(i for i in range(1, 6) for _ in range(2))]
    catalog = _Catalog([
        _Product("ABB", "triton 5/10fach Taster", ten, "A"),
        _Product("Feller", "Taster 1-12fach", [], "F12"),
        _Product("Feller", "Taster 1-6fach", [], "F6"),
        _Product("Feller", "Taster 1-10fach Temp",
                 [_co(70, "Raumtemperatur", "K--Ü--", "DPST-9-1")], "F10T"),
    ])
    options = products_with_keys(catalog, taster, 9)
    names = [o.product.order_number for o in options]
    assert names == ["F10T", "F12", "A"]            # Hersteller, Fühler, dann Tastenzahl
    shortage = plan_conflicts(project)[0][0]
    apply_catalog_product(taster, options[0].product, shortage.bedienelement)
    assert taster.order_number == "F10T" and taster.co_map == {}
    assert plan_conflicts(project)[0] == []


def test_key_shortage_dialog_choice(gewerk_catalog):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.key_shortage_dialog import (
        PRODUCT, SPLIT, KeyShortageDialog,
    )
    project, room = _project(gewerk_catalog)
    _taster(project)
    shortage = plan_conflicts(project)[0][0]
    dialog = KeyShortageDialog(shortage, _Catalog([_Product("X", "Taster 1-10fach", [])]))
    dialog._accept()
    assert dialog.choice == SPLIT
    dialog = KeyShortageDialog(shortage, _Catalog([_Product("X", "Taster 1-10fach", [])]))
    dialog._product.setChecked(True)
    assert dialog._list.count() == 1
    dialog._accept()
    assert dialog.choice == PRODUCT and dialog.selected_product.product_name == "Taster 1-10fach"


def test_channels_follow_product(gewerk_catalog):
    from knix_arranger.services.button_move import bedienelement_of_device
    from knix_arranger.services.product_capabilities import fit_taster_channels
    from knix_arranger.services.sensor_service import link_bedienelemente_to_devices
    project, room = _project(gewerk_catalog)
    link_bedienelemente_to_devices(project.topology, project.all_rooms)
    taster = _taster(project)
    _room, be = bedienelement_of_device(project, taster)
    assert be.channels == 9
    assert not fit_taster_channels(project, be)           # 9 belegt > 8 Tasten
    be.funktionen.pop()                                   # T9 entfernt
    be.is_auto = False
    assert fit_taster_channels(project, be) and be.channels == 8
    be.funktionen.pop()                                   # T8 entfernt: Taste bleibt
    assert not fit_taster_channels(project, be) and be.channels == 8


def test_channel_detection_cached_per_ko_list():
    from knix_arranger.models.topology import Device
    from knix_arranger.services import actor_channels
    cos = [_co(n, f"Kanal {ch}", "K-S---") for n, ch in enumerate("ABCD")]
    a = Device(device_type="actor", product="Schaltaktor 4-fach", communication_objects=cos)
    first = [(c.number, c.label, [co.object_number for co in c.com_objects])
             for c in actor_channels.device_channels(a)]
    b = Device(device_type="actor", product="Schaltaktor 4-fach",
               communication_objects=[_co(n, f"Kanal {ch}", "K-S---") for n, ch in enumerate("ABCD")])
    second = actor_channels.device_channels(b)
    assert [(c.number, c.label, [co.object_number for co in c.com_objects]) for c in second] == first
    assert all(co in b.communication_objects for c in second for co in c.com_objects)


def test_topology_shows_temperature_channel(gewerk_catalog):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator
    QApplication.instance() or QApplication([])
    from knix_arranger.services.sensor_service import link_bedienelemente_to_devices
    from knix_arranger.ui.views.topology_view import TopologyView
    project, room = _project(gewerk_catalog)
    link_bedienelemente_to_devices(project.topology, project.all_rooms)
    taster = _taster(project)
    offer = next(o for o in plan_conflicts(project)[1] if o.device is taster)
    use_taster_temperature(project, offer, remove_thermostats=False)
    view = TopologyView()
    view.set_project(project)
    view._tree.expandAll()
    it = QTreeWidgetItemIterator(view._tree)
    found = []
    while it.value():
        item = it.value()
        if item.text(0) == "Raumtemperatur" and item.parent().text(1) == taster.physical_address:
            found.append(item.child(0))
        it += 1
    ist = next(g for g in project.group_addresses.all_addresses()
               if g.gewerk_code == "H" and g.function_name == "IST")
    assert found and found[0].text(1) == ist.address and "KO 70" in found[0].text(0)


def test_switched_heating_on_a_key(gewerk_catalog):
    """Spiegelheizung (H Element 2, nur Ein/Aus): Taste schaltet E/A mit RM,
    keine Raumtemperatur angeboten."""
    from knix_arranger.models.building import SensorFunktion
    from knix_arranger.services.ga_edit import set_element_profile
    from knix_arranger.services.sensor_service import link_bedienelemente_to_devices
    room = Room(number="CDG04", name="Badzimmer")
    room.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1),
                               GewerkAssignment(gewerk_code="H", count=2)]
    project = KnxProject(name="Spiegel")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[Floor(
        name="DG", short_code="DG", main_group_number=1,
        apartments=[Apartment(name="Wohnung", rooms=[room])])])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine(project.config.topology_mode).calculate_topology(project.areal)
    regenerate_addresses(project)
    _recompute(project)
    link_bedienelemente_to_devices(project.topology, project.all_rooms)
    heating = next(a for a in room.gewerk_assignments if a.gewerk_code == "H")
    mirror = next(g for g in project.group_addresses.all_addresses()
                  if g.assignment_id == heating.id and g.element_number == 2)
    set_element_profile(project, mirror, "schalten_rm")
    te = next(b for b in room.bedienelemente if b.element_type == "Tastereinheit")
    te.funktionen.append(SensorFunktion(gewerk_code="H", element_number=2))
    te.is_auto = False
    _recompute(project)
    te = next(b for b in room.bedienelemente if b.element_type == "Tastereinheit")
    fas = [(fa.role, fa.function_ga.split(" ")[1]) for fa in te.function_assignments
           if fa.function_ga.startswith("H_")]
    assert fas == [("befehl", "E/A"), ("rueckmeldung", "RM")]
    taster = _taster(project)
    elements = [(o.assignment.gewerk_code, o.element_number) for o in plan_conflicts(project)[1]
                if o.device is taster]
    assert elements == [("H", 1)]                 # nicht die Spiegelheizung


def test_material_list_type_filter(gewerk_catalog):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.views.material_list_view import MaterialListView, _COL_TYPE
    project, room = _project(gewerk_catalog)
    view = MaterialListView()
    view.set_project(project)
    combo = view._type_filter_combo
    types = [combo.itemData(i) for i in range(1, combo.count())]
    assert "Tastereinheit" in types and "Raumthermostat" in types
    combo.setCurrentIndex(combo.findData("Tastereinheit"))
    shown = {view._table.item(r, _COL_TYPE).text() for r in range(view._table.rowCount())}
    assert shown == {"Tastereinheit"}
    combo.setCurrentIndex(0)
    assert view._table.rowCount() > 1
