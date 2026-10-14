"""KOs aller Geräte auf einmal zuordnen (ko_batch, FA-3009).

Projekt_23: drei Schaltaktoren mit Produkt (1.2.13, 1.3.13, 2.1.1) und vier
Melder 6131/40 -- ein Lauf ordnet alle zu; DIM/WERT/RM WERT der Lichtkreise
haben am Schaltaktor keinen KO und lassen sich weglassen.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.services.actor_channels import device_circuits
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.ko_batch import NO_KO, UNNEEDED, apply_plan, plan_all
from knix_arranger.services.ko_templates import actor_signature, save_template
from knix_arranger.services.sensor_channels import SENSOR_CO_KEY
from tests.test_actor_channels import _actor, project  # noqa: F401 (Fixture)
from tests.test_sensor_channels import _setup


def test_plan_schreibt_erst_beim_uebernehmen(project):  # noqa: F811
    actor = _actor(project)
    batch = plan_all(project)
    assert [p.device for p in batch.plans] == [actor]
    assert actor.co_map == {}                      # nur gerechnet
    apply_plan(project, batch)
    circuit = device_circuits(project, actor)[0]
    selection = actor.co_map[circuit.key]
    assert selection["E/A"] >= 0 and selection["RM"] >= 0
    assert actor.channel_map[circuit.key] == circuit.channel


def test_nicht_benoetigt_und_weglassen(project):  # noqa: F811
    batch = plan_all(project)
    unneeded = {i.function for i in batch.issues if i.problem == UNNEEDED}
    assert {"DIM", "WERT"} <= unneeded
    assert not [i for i in batch.issues if i.problem == NO_KO]
    before = len([g for g in project.group_addresses.all_addresses() if not g.is_placeholder])
    omitted = apply_plan(project, batch, omit=True)
    assert omitted == batch.unneeded_count
    regenerate_addresses(project)
    after = len([g for g in project.group_addresses.all_addresses() if not g.is_placeholder])
    assert after == before - omitted


def test_eigene_auswahl_bleibt(project):  # noqa: F811
    actor = _actor(project)
    circuit = device_circuits(project, actor)[0]
    actor.co_map = {circuit.key: {"E/A": 2}}
    batch = plan_all(project)
    assert batch.kept == [actor] and not batch.plans
    apply_plan(project, batch)
    assert actor.co_map == {circuit.key: {"E/A": 2}}


def test_gemerkte_zuordnung_vor_vorschlag(project):  # noqa: F811
    actor = _actor(project)
    circuit = device_circuits(project, actor)[0]
    save_template(actor, {actor_signature(circuit.channel, "E/A"): 2})
    batch = plan_all(project)
    apply_plan(project, batch)
    assert actor.co_map[circuit.key]["E/A"] == 2


def test_sensoren_mit_rollen():
    project_, melder = _setup()
    batch = plan_all(project_)
    apply_plan(project_, batch)
    selection = melder.co_map[SENSOR_CO_KEY]
    assert 10 in selection.values()                # P1: Bewegung (Master)
    assert any(key.endswith("#extern") and number == 13
               for key, number in selection.items())


def test_dialog():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.ko_batch_dialog import KoBatchDialog
    project_, _melder = _setup()
    dlg = KoBatchDialog(project_, plan_all(project_))
    assert dlg.omit is False
