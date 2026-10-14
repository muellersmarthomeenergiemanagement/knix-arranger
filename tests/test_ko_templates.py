"""KO-Zuordnung je Produkt merken (ko_templates): einmal zugeordnet, gilt
sie für alle gleichen Geräte -- in diesem und in künftigen Projekten."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.models.topology import CommunicationObject
from knix_arranger.services.actor_channels import device_circuits, device_com_objects
from knix_arranger.services.ko_templates import (
    apply_sensor_template, load_template, save_template, sensor_signature,
    sensor_template_entries,
)
from knix_arranger.services.sensor_channels import sensor_links
from tests.test_actor_channels import _actor, project  # noqa: F401 (Fixture)
from tests.test_sensor_channels import _setup


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_sensor_vorlage_fuer_gleiches_produkt():
    project_, melder = _setup()
    links = sensor_links(project_, melder)
    selection = {link.key: 11 for link in links}         # bewusst anders als Vorschlag
    save_template(melder, sensor_template_entries(links, selection))
    assert load_template(melder)[sensor_signature(links[0])] == 11
    known = {co.object_number for co in device_com_objects(melder)}
    assert apply_sensor_template(load_template(melder), links, known) == selection
    # KO, den das Gerät nicht hat, wird nicht übernommen
    save_template(melder, {sensor_signature(links[0]): 999})
    assert links[0].key not in apply_sensor_template(load_template(melder), links, known)


def test_ohne_bestellnummer_keine_vorlage():
    project_, melder = _setup()
    melder.order_number = ""
    save_template(melder, {"Kanal 1|E/A": 10})
    assert load_template(melder) == {}


def test_sensor_dialog_merkt_und_uebernimmt():
    _qapp()
    from knix_arranger.ui.dialogs.sensor_ko_dialog import SensorKoDialog
    project_, melder = _setup()
    dlg = SensorKoDialog(project_, [melder])
    combo = dlg._table.cellWidget(0, 3)
    combo.setCurrentIndex(combo.findData(13))
    dlg.apply()
    # Gleiches Produkt ohne eigene Auswahl: die gemerkte Zuordnung gilt
    melder.co_map = {}
    dlg = SensorKoDialog(project_, [melder])
    assert dlg._table.cellWidget(0, 3).currentData() == 13


def test_sensor_dialog_uebertraegt_auf_gleiche_geraete():
    _qapp()
    from knix_arranger.ui.dialogs.sensor_ko_dialog import SensorKoDialog
    project_, melder = _setup()
    zweiter = next(d for area in project_.topology.areas for line in area.lines
                   for d in line.devices if d.physical_address == "1.2.101")
    zweiter.manufacturer, zweiter.order_number = melder.manufacturer, melder.order_number
    zweiter.communication_objects = [CommunicationObject(
        object_number=co.object_number, name=co.name, object_function=co.object_function,
        data_type=co.data_type, flags=co.flags) for co in melder.communication_objects]
    dlg = SensorKoDialog(project_, [melder, zweiter])
    dlg._copy_to_others()
    dlg.apply()
    first = dlg._state[melder.id]
    second = dlg._state[zweiter.id]
    by_signature = {sensor_signature(link): first["selection"][link.key]
                    for link in first["links"]}
    for link in second["links"]:
        if sensor_signature(link) in by_signature:
            assert second["selection"][link.key] == by_signature[sensor_signature(link)]


def test_aktor_dialog_merkt_kanal_und_funktion(project):  # noqa: F811
    _qapp()
    from knix_arranger.ui.dialogs.actor_channel_dialog import ActorChannelDialog
    actor = _actor(project)
    dlg = ActorChannelDialog(project, [actor])
    dlg._circuit_table.selectRow(0)
    function = dlg._co_table.item(0, 0).text()
    ko = dlg._co_table.cellWidget(0, 2)
    ko.setCurrentIndex(ko.findData(2))                     # «Kanal A: Sperren»
    dlg.apply()
    circuit = device_circuits(project, actor)[0]
    channel = actor.channel_map[circuit.key]
    assert load_template(actor)[f"{channel}|{function}"] == 2
    # Ein neues gleiches Gerät (ohne Auswahl) erhält die gemerkte Zuordnung
    actor.co_map, actor.channel_map = {}, {}
    dlg = ActorChannelDialog(project, [actor])
    assert dlg._state[actor.id]["co"][circuit.key][function] == 2
