"""Passt ein zugeordnetes KO zur GA-Funktion? (ko_plausibility, FA-634)

Fälle aus Projekt_23: Hager TXM616D «RM WERT» auf der Zwangsführungs-
Rückmeldung (1.011), Revox-Gateway «… Status» auf Eingangs-KOs, Feller
EDIZIOdue Jalousie-Rückmeldung auf dem KO einer anderen Taste.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from knix_arranger.models.topology import CommunicationObject
from knix_arranger.services.actor_channels import device_circuits, suggest_co
from knix_arranger.services.ko_batch import REPLACED, apply_plan, plan_all
from knix_arranger.services.ko_plausibility import (
    actor_ko_problem, button_of, is_feedback_function, sensor_selection_problems,
)
from knix_arranger.services.validation_engine import ValidationEngine
from tests.test_actor_channels import _actor, project  # noqa: F401 (Fixture)


def _co(number, name, flags, dpt="", function=""):
    return CommunicationObject(object_number=number, name=name, object_function=function or name,
                               flags=flags, data_type=dpt)


@pytest.mark.parametrize("function, expected", [
    ("RM", True), ("RM WERT", True), ("STATUS POSITION HOEHE", True),
    ("Room 1: Mute Status", True), ("Room 1: Select User 1 Fav Status", True),
    ("E/A", False), ("Room 1: Mute On/Off", False), ("WERT", False),
])
def test_feedback_function(function, expected):
    assert is_feedback_function(function) == expected


def test_hager_rm_wert_not_on_priority_status():
    priority = _co(4, "Status indication priority_1", "KL-Ü--", "DPST-1-11")
    assert actor_ko_problem([priority], "RM WERT", "DPST-5-1").startswith("DPT passt nicht")
    assert suggest_co([priority], "RM WERT", dpt="DPST-5-1") is None
    assert actor_ko_problem([priority], "RM", "DPST-1-1") == ""


def test_revox_status_on_status_object():
    room = "{{0:Room 1}}"
    fav_off = _co(22, "R_1_USER_3_ROOM_FAV_OFF", "K-S---", "DPST-1-3",
                  f"{room}: Select User 3 Fav/Room Off")
    fav_status = _co(18, "R_1_USER_1_ROOM_FAV_STATUS", "K--Ü--", "DPST-1-3",
                     f"{room}: Select User 1 Fav Status")
    mute_status = _co(59, "R_1_MUTE_STATUS", "K--Ü--", "DPST-1-1", f"{room}: Mute Status")
    function = "Room 1: Select User 1 Fav Status"
    # Textbaustein «{{0:Room 1}}» mit echten Flags ist parametriert
    assert "Eingangs-KO" in actor_ko_problem([fav_off], function, "DPST-1-3")
    assert actor_ko_problem([fav_status], function, "DPST-1-3") == ""
    cos = [fav_off, fav_status, mute_status]
    assert suggest_co(cos, function, dpt="DPST-1-3") is fav_status
    assert suggest_co(cos, "Room 1: Mute Status", dpt="DPST-1-1") is mute_status


def _link(key, channel, function, feedback, role=""):
    return SimpleNamespace(key=key, channel=channel, ga_function=function,
                           function=function, feedback=feedback, role=role)


def _feller():
    variants = {}
    for n, name, flags in [
            (6, "Taste 2, links", "K-SÜ--"),
            (7, "Taste 2, links (langer Tastendruck)", "K-SÜ--"),
            (12, "Taste 3, links", "K-SÜ--"), (13, "Taste 3, links", "K--Ü--"),
            (14, "Taste 3, links, Signal LED", "K-S-A-"),
            (1, "Object 2", "KLSÜA-")]:
        variants.setdefault(n, []).append(_co(n, name, flags, "DPST-5-1"))
    links = [_link("r|J|1|STOPP", "Taste 5 kurz", "STOPP", False),
             _link("r|J|1|STATUS POSITION HOEHE", "Status 5", "STATUS POSITION HOEHE", True),
             _link("r|J|1|STATUS POSITION LAMELLEN", "Status 5", "STATUS POSITION LAMELLEN",
                   True)]
    return variants, links


def test_feller_feedback_on_same_button_only():
    variants, links = _feller()
    assert button_of(variants[7][0]) == "taste 2, links"
    assert button_of(variants[14][0]) == "taste 3, links"
    problems = sensor_selection_problems(
        links, {"r|J|1|STOPP": 12, "r|J|1|STATUS POSITION HOEHE": 7,
                "r|J|1|STATUS POSITION LAMELLEN": 14}, variants)
    assert problems == {"r|J|1|STATUS POSITION HOEHE": "KO einer anderen Taste"}
    # Nicht parametriert («Object 2» mit allen Flags): weder Flags noch Taste prüfbar
    assert sensor_selection_problems(
        links, {"r|J|1|STOPP": 12, "r|J|1|STATUS POSITION HOEHE": 1}, variants) == {}
    # Rückmeldung auf KO, das nicht empfängt
    assert "ohne S" in sensor_selection_problems(
        links, {"r|J|1|STATUS POSITION HOEHE": 13}, variants)["r|J|1|STATUS POSITION HOEHE"]


def test_named_product_gas_have_no_buttons():
    """ABB BE/S: GAs heissen wie die KOs («General», «Input A...X») -- keine
    Tastenprüfung."""
    variants = {0: [_co(0, "System", "KL-Ü--")], 1: [_co(1, "General", "K-S---")]}
    links = [_link("be|System", "Ausgang", "System", False),
             _link("be|General", "Ausgang", "General", True)]
    assert sensor_selection_problems(links, {"be|System": 0, "be|General": 1}, variants) == {}


def test_batch_replaces_unfitting_own_selection(project):  # noqa: F811
    actor = _actor(project)
    circuit = device_circuits(project, actor)[0]
    # RM auf dem Eingangs-KO «Schalten» (K S): unpassend, wird ersetzt
    actor.co_map = {circuit.key: {"E/A": 0, "RM": 0}}
    issues = [i for i in ValidationEngine().validate(project.group_addresses, project)
              if i.rule_id == "FA-634"]
    assert len(issues) == 1 and "Eingangs-KO" in issues[0].message
    batch = plan_all(project)
    assert actor not in batch.kept
    assert any(i.problem.startswith(REPLACED) and i.function == "RM" for i in batch.issues)
    apply_plan(project, batch)
    assert actor.co_map[circuit.key]["E/A"] == 0          # eigene, passende Wahl bleibt
    assert actor.co_map[circuit.key]["RM"] == 1           # «Status Schalten»
    assert not [i for i in ValidationEngine().validate(project.group_addresses, project)
                if i.rule_id == "FA-634"]
