"""Soll-Flags aus der Rolle (flag_rules, FA-635): pro GA eine Quelle mit L Ü,
Empfänger mit S (und I, wo der Zustand nach Busneustart gebraucht wird)."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from knix_arranger.services.actor_channels import device_circuits
from knix_arranger.services.flag_rules import (
    actor_flags, expected_by_link, expected_links, flags_label, receiver_read_flags,
    sensor_flags,
)
from knix_arranger.services.validation_engine import ValidationEngine
from tests.test_actor_channels import _actor, project  # noqa: F401 (Fixture)


@pytest.mark.parametrize("function, expected", [
    ("E/A", "K S"), ("DIM", "K S"), ("AUF/AB", "K S"), ("SZENE", "K S"),
    ("RM", "K L Ü"), ("RM WERT", "K L Ü"), ("STATUS POSITION HOEHE", "K L Ü"),
    ("STOERUNG", "K L Ü"), ("IST", "K S I"),
    ("Room 1: Mute Status", "K L Ü"), ("Room 1: Mute On/Off", "K S"),
])
def test_actor_flags(function, expected):
    assert flags_label(actor_flags(function)) == expected


def _link(ga_function, feedback=False, role=""):
    return SimpleNamespace(ga_function=ga_function, feedback=feedback, role=role)


@pytest.mark.parametrize("link, expected", [
    (_link("E/A"), "K S Ü"),                          # Taste sendet, kennt den Zustand
    (_link("RM", feedback=True), "K S I"),            # LED/Status empfangen
    (_link("SZENE"), "K Ü"),                          # Szene abrufen
    (_link("IST", role="raumtemperatur"), "K L Ü"),   # Taster liefert Raumtemperatur
    (_link("E/A", role="aktorstatus"), "K S I"),
    (_link("RM"), "K L Ü"),                           # eigener Zustand (Melder)
])
def test_sensor_flags(link, expected):
    assert flags_label(sensor_flags(link)) == expected


def _issues(project, rule):
    return [i for i in ValidationEngine().validate(project.group_addresses, project)
            if i.rule_id == rule]


def test_read_flag_on_receiver(project):  # noqa: F811
    """Hager TXM616D «ON/OFF_1» an E/A mit L-Flag: Hinweis FA-635."""
    actor = _actor(project)
    circuit = device_circuits(project, actor)[0]
    actor.co_map = {circuit.key: {"E/A": 0, "RM": 1}}
    assert receiver_read_flags(project) == []
    actor.communication_objects[0].flags = "KLS---"
    found = receiver_read_flags(project)
    assert [(d.physical_address, co.object_number) for d, co, _g, _f in found] == [
        (actor.physical_address, 0)]
    issues = _issues(project, "FA-635")
    assert len(issues) == 1 and issues[0].level == "info" and "E/A" in issues[0].message
    # Die Quelle (Status, K L Ü) behält ihr L-Flag ohne Hinweis
    assert all(co.object_number != 1 for _d, co, _g, _f in found)


def test_devices_without_product_use_expected_flags(project):  # noqa: F811
    expected = expected_by_link(project)
    assert expected
    links = expected_links(project, expected)
    assert links and all(not link.device.communication_objects for link in links)
    assert all("ohne Produkt" in link.label for link in links)


def test_topology_shows_expected_flags(project):  # noqa: F811
    from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator
    from knix_arranger.ui.views.topology_view import TopologyView
    QApplication.instance() or QApplication([])
    _actor(project).communication_objects = []        # Platzhalter ohne Produkt
    view = TopologyView()
    view.set_project(project)
    view._tree.expandAll()
    texts = []
    it = QTreeWidgetItemIterator(view._tree)
    while it.value():
        texts.append(it.value().text(4))
        it += 1
    assert any("Soll-Flags K S" in t for t in texts)
    assert any("Soll-Flags K L Ü" in t for t in texts)
