"""
Kanäle und KOs eines Aktors zuordnen (Materialliste › «Kanäle und KOs
zuordnen…», services/actor_channels): Stromkreis -> Kanal im Gerät in der
Benennung des Herstellers, je GA der KO -- oder bewusst keiner.
"""
from __future__ import annotations

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.actor_channels import (
    channel_names, circuit_key, device_channels, device_circuits, suggest_co,
)
from knix_arranger.services.address_generator import regenerate_addresses
from knix_arranger.services.belegungsplan_service import BelegungsplanService
from knix_arranger.services.co_linking_service import CoLinkingService
from knix_arranger.services.topology_engine import TopologyEngine


def _kos(channels="ABCD"):
    cos, n = [], 0
    for ch in channels:
        for function, flags in (("Schalten", "K-S---"), ("Status Schalten", "KL-Ü--"),
                                ("Sperren", "K-S---")):
            cos.append(CommunicationObject(object_number=n, name=f"Kanal {ch}",
                                           object_function=function, flags=flags,
                                           data_type="DPST-1-1"))
            n += 1
    return cos


@pytest.fixture
def project():
    logging.disable(logging.CRITICAL)
    project = KnxProject(name="Kanäle")
    rooms = [Room(number="W01", name="Wohnen",
                  gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=2)]),
             Room(number="W02", name="Küche",
                  gewerk_assignments=[GewerkAssignment(gewerk_code="L", count=1)])]
    floor = Floor(name="Erdgeschoss", short_code="EG", main_group_number=2,
                  apartments=[Apartment(name="Wohnung", rooms=rooms)])
    project.areal = Areal(buildings=[Building(name="Haus", wings=[Wing(floors=[floor])])])
    engine = TopologyEngine(project.config.topology_mode)
    project.topology = engine.calculate_topology(project.areal)
    engine.populate_devices(project.topology, project.all_rooms, project.gewerk_catalog)
    regenerate_addresses(project)
    actor = _actor(project)
    actor.manufacturer, actor.order_number = "ABB", "SA/S4.16"
    actor.communication_objects = _kos()
    yield project
    logging.disable(logging.NOTSET)


def _actor(project) -> Device:
    return next(d for a in project.topology.areas for ln in a.lines for d in ln.devices
                if d.device_type == "actor" and d.product.startswith("Schaltaktor"))


def _rows(project):
    actor = _actor(project)
    return [r for r in BelegungsplanService().generate(project).actor_rows
            if r.physical_address == actor.physical_address and r.room_id]


def test_channels_with_manufacturer_names(project):
    actor = _actor(project)
    channels = device_channels(actor)
    assert [ch.label for ch in channels] == ["Kanal A", "Kanal B", "Kanal C", "Kanal D"]
    assert len(channels[0].com_objects) == 3
    assert channel_names(actor)[3] == "Kanal C"
    # ohne KOs: Kanal 1…n nach Kanalzahl
    plain = Device(product="Schaltaktor 4-fach")
    assert [ch.label for ch in device_channels(plain)] == ["Kanal 1", "Kanal 2",
                                                          "Kanal 3", "Kanal 4"]
    assert channel_names(plain) == {}


def test_circuits_and_default_numbering_gets_names(project):
    circuits = device_circuits(project, _actor(project))
    assert [(c.room_number, c.element_number, c.channel) for c in circuits] == [
        ("W01", 1, 1), ("W01", 2, 2), ("W02", 1, 3)]
    assert all(c.functions for c in circuits)
    # ohne Zuordnung: Reihenfolge wie bisher, aber mit Kanalnamen
    assert {r.channel_label for r in _rows(project)} == {"Kanal A", "Kanal B", "Kanal C"}


def test_channel_map_moves_circuits_and_fills_free_channels(project):
    actor = _actor(project)
    kitchen = next(c for c in device_circuits(project, actor) if c.room_number == "W02")
    actor.channel_map = {kitchen.key: 4}
    labels = {(r.room_number, r.element_number): r.channel_label for r in _rows(project)}
    assert labels == {("W01", 1): "Kanal A", ("W01", 2): "Kanal B", ("W02", 1): "Kanal D"}
    actor.channel_map = {kitchen.key: 1}       # Küche auf A, Wohnen rückt nach
    labels = {(r.room_number, r.element_number): r.channel_label for r in _rows(project)}
    assert labels == {("W02", 1): "Kanal A", ("W01", 1): "Kanal B", ("W01", 2): "Kanal C"}


def test_suggest_co_by_function():
    cos = _kos("A")
    assert suggest_co(cos, "E/A").object_function == "Schalten"
    assert suggest_co(cos, "RM").object_function == "Status Schalten"
    assert suggest_co(cos, "SZENE") is None
    english = [CommunicationObject(object_number=1, name="Output A", object_function="Switching"),
               CommunicationObject(object_number=2, name="Output A",
                                   object_function="Status switching")]
    assert suggest_co(english, "E/A").object_number == 1
    assert suggest_co(english, "RM").object_number == 2


def test_co_map_links_chosen_ko_or_none(project):
    actor = _actor(project)
    circuits = device_circuits(project, actor)
    first = circuits[0]
    functions = [f for f, _ga in first.functions]
    assert "E/A" in functions
    # E/A -> Kanal D Schalten (Nr. 9), alle anderen Funktionen nicht verknüpfen
    actor.co_map = {first.key: {f: (9 if f == "E/A" else -1) for f in functions}}
    proposals = [p for p in CoLinkingService().generate_proposals(project)
                 if p.physical_address == actor.physical_address and p.room_name == "Wohnen"]
    first_gas = {ga for _f, ga in first.functions}
    chosen = [p for p in proposals if p.ga_address in first_gas]
    assert [(p.function_name, p.co_name, p.confidence) for p in chosen] == [
        ("E/A", "Kanal D", "sicher")]


def test_maps_survive_recalculation_and_saving(project):
    actor = _actor(project)
    key = circuit_key("x", "L", 1)
    actor.channel_map = {key: 2}
    actor.co_map = {key: {"E/A": 3}}
    actor.communication_objects[0].connected_gas = ["2/1/0"]
    restored = Device.from_dict(actor.to_dict())
    assert (restored.channel_map, restored.co_map) == ({key: 2}, {key: {"E/A": 3}})
    # wie die App (Schritte 4/8, Neuberechnung): manuelle Zuweisungen erhalten
    TopologyEngine(project.config.topology_mode).populate_devices(
        project.topology, project.all_rooms, project.gewerk_catalog, preserve_manual=True)
    again = _actor(project)
    assert again is not actor
    assert (again.channel_map, again.co_map) == ({key: 2}, {key: {"E/A": 3}})
    assert len(again.communication_objects) == 12
    assert again.communication_objects[0].connected_gas == []   # Adressen ggf. veraltet


def test_dialog_changes_channel_and_ko(project):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.actor_channel_dialog import ActorChannelDialog
    actor = _actor(project)
    dlg = ActorChannelDialog(project, [actor])
    assert dlg._circuit_table.rowCount() == 3
    assert "Frei: Kanal D" in dlg._channel_info.text()
    # Küche (Zeile 3) auf Kanal A: doppelt vergeben, KOs neu vorgeschlagen
    combo = dlg._circuit_table.cellWidget(2, 1)
    combo.setCurrentIndex(combo.findData(1))
    assert "Mehrfach vergeben: Kanal A" in dlg._channel_info.text()
    dlg._circuit_table.selectRow(2)
    ko_combo = dlg._co_table.cellWidget(0, 2)
    function = dlg._co_table.item(0, 0).text()
    expected = suggest_co(device_channels(actor)[0].com_objects, function)
    assert ko_combo.currentData() == (expected.object_number if expected else -1)
    ko_combo.setCurrentIndex(0)                            # «nicht verknüpfen»
    dlg.apply()
    kitchen = next(c for c in device_circuits(project, actor) if c.room_number == "W02")
    assert actor.co_map[kitchen.key][function] == -1
    combo.setCurrentIndex(combo.findData(4))               # doch Kanal D
    dlg.apply()
    assert actor.channel_map[kitchen.key] == 4
    assert actor.co_map[kitchen.key]["E/A"] == 9           # Kanal D neu vorgeschlagen


# ── Nur so viele GAs wie nötig: nicht benötigte Funktionen weglassen ──

def _l_gas(project):
    return [g for g in project.group_addresses.all_addresses()
            if g.gewerk_code == "L" and not g.is_placeholder]


def test_unneeded_functions_only_without_ko(project):
    from knix_arranger.services.actor_channels import suggested_co_map, unneeded_functions
    actor = _actor(project)
    circuit = device_circuits(project, actor)[0]
    channel = device_channels(actor)[0]
    selection = suggested_co_map(channel, circuit)
    assert sorted(unneeded_functions(channel, circuit, selection)) == ["DIM", "RM WERT", "WERT"]
    # E/A bewusst nicht verknüpft, KO aber vorhanden: GA bleibt
    selection["E/A"] = -1
    assert "E/A" not in unneeded_functions(channel, circuit, selection)
    # ohne KOs nichts bekannt
    assert unneeded_functions(None, circuit, {}) == []


def test_dialog_omits_unneeded_functions_as_reserve(project):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.actor_channel_dialog import ActorChannelDialog
    before = _l_gas(project)
    addresses = {g.address for g in before if g.function_name == "E/A"}
    dlg = ActorChannelDialog(project, [_actor(project)])
    assert "9 GAs entfallen" in dlg._omit_check.text()
    dlg._omit_check.setChecked(True)
    assert dlg.apply() == 9
    regenerate_addresses(project)
    after = _l_gas(project)
    assert len(before) - len(after) == 9
    assert sorted({g.function_name for g in after}) == ["E/A", "RM"]
    # Plätze bleiben Reserve: E/A behält ihre Adressen
    assert {g.address for g in after if g.function_name == "E/A"} == addresses
    # Kanalzuordnung und Belegungsplan funktionieren weiter
    assert {r.channel_label for r in _rows(project)} == {"Kanal A", "Kanal B", "Kanal C"}


def test_omit_hidden_when_addresses_fixed(project):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.actor_channel_dialog import ActorChannelDialog
    project.ets_transferred = "2026-10-13"
    dlg = ActorChannelDialog(project, [_actor(project)])
    dlg._omit_check.setChecked(True)
    assert dlg.apply() == 0


def test_csv_export_leaves_reserves_as_gaps(project, tmp_path):
    from knix_arranger.services.actor_channels import omit_functions
    from knix_arranger.services.csv_export_service import CsvExportService
    circuit = device_circuits(project, _actor(project))[0]
    assert omit_functions(project, circuit.key, ["DIM"]) == 1
    regenerate_addresses(project)
    path = tmp_path / "ga.csv"
    CsvExportService().export_csv(project.group_addresses, str(path))
    text = path.read_text(encoding="cp1252")    # ETS-Format
    reserves = [g for g in project.group_addresses.all_addresses() if g.is_placeholder]
    real = [g for g in project.group_addresses.all_addresses() if not g.is_placeholder]
    assert reserves and real
    assert all(f'"{g.address}"' not in text for g in reserves)
    assert all(f'"{g.address}"' in text for g in real)


# ── Griesser JAX-9: "GO0002" + "(M1)" im Text, Platzhalter-Doppel ──

_JAX_FUNCTIONS = ["Operation of Blinds (M{m}), End position", "Operation of Blinds (M{m}), Tilt",
                  "Operation of Blinds (M{m}), Shading", "Operation of Blinds (M{m}), Height",
                  "Operation of Blinds (M{m}), Angle", "Operation of Blinds (M{m}), Position",
                  "Sun Protection (M{m}), Activate position feedback",
                  "Sun Protection (M{m}), Height feedback",
                  "Sun Protection (M{m}), Angle feedback",
                  "Automatic lock-out (M{m}), activate"]


def _jax_kos(motors=3):
    cos = [CommunicationObject(object_number=1, name="GO0001",
                               object_function="Griesser object, Central Command")]
    n = 2
    for m in range(1, motors + 1):
        for text in _JAX_FUNCTIONS:
            # erste Variante nur Platzhalter, zweite mit echtem Text
            cos.append(CommunicationObject(object_number=n, name=f"GO{n:04d}",
                                           object_function="{{0:GO}}"))
            cos.append(CommunicationObject(object_number=n, name=f"GO{n:04d}",
                                           object_function=text.format(m=m)))
            n += 1
    cos += [CommunicationObject(object_number=n + i, name=f"GO{n + i:04d}",
                                object_function="{{0:GO}}") for i in range(80)]
    return cos


def test_unique_com_objects_prefers_real_text():
    from knix_arranger.services.knxprod_catalog_service import unique_com_objects
    cos = [{"number": 2, "function_text": "{{0:GO}}"},
           {"number": 2, "function_text": "Operation of Blinds (M1), End position"},
           {"number": 3, "function_text": "Leckage Alarm"},
           {"number": 3, "function_text": "Leckage Alarm 2"}]
    assert [c["function_text"] for c in unique_com_objects(cos)] == [
        "Operation of Blinds (M1), End position", "Leckage Alarm"]


def test_griesser_motors_and_ko_suggestions():
    from knix_arranger.services.actor_channels import Circuit, suggested_co_map, unneeded_functions
    device = Device(product="Jalousieaktor 2-fach", communication_objects=_jax_kos())
    channels = device_channels(device)
    assert [ch.label for ch in channels] == ["Motor 1", "Motor 2", "Motor 3"]
    assert len(channels[0].com_objects) == len(_JAX_FUNCTIONS)
    circuit = Circuit(key="r|J|1", room_number="W01", room_name="Wohnen", gewerk_code="J",
                      element_number=1, channel=1, functions=[
                          (f, "") for f in ("AUF/AB", "STOPP", "POSITION HOEHE",
                                            "POSITION LAMELLEN", "BESCHATTUNG", "SPERREN",
                                            "STATUS POSITION HOEHE", "STATUS POSITION LAMELLEN")])
    selection = suggested_co_map(channels[0], circuit)
    by_number = {co.object_number: co.object_function for co in channels[0].com_objects}
    chosen = {f: by_number[n].split(", ", 1)[1] for f, n in selection.items()}
    assert chosen == {
        "AUF/AB": "End position", "STOPP": "Tilt", "POSITION HOEHE": "Height",
        "POSITION LAMELLEN": "Angle", "BESCHATTUNG": "Shading", "SPERREN": "activate",
        "STATUS POSITION HOEHE": "Height feedback",
        "STATUS POSITION LAMELLEN": "Angle feedback"}
    assert unneeded_functions(channels[0], circuit, selection) == []
    # Sicherung: Hauptfunktion ohne KO -> nichts weglassen
    selection.pop("AUF/AB")
    selection["STOPP"] = -1
    assert unneeded_functions(channels[0], circuit, selection) == []


def test_room_sheet_shows_channel_names():
    from knix_arranger.services.room_sheet import _channel_text
    assert _channel_text(["Motor 3", "Motor 1"]) == "Motor 1, Motor 3"
    assert _channel_text(["1", "2", "Kanal C"]) == "K1–2, Kanal C"


# ── Weitere Hersteller: Kanal-Schreibweisen, Programmnamen, Datenpunkttyp ──

def _device(rows):
    return Device(product="Aktor", communication_objects=[
        CommunicationObject(object_number=n, name=name, object_function=text, data_type=dpt,
                            flags=flags)
        for n, name, text, dpt, flags in rows])


@pytest.mark.parametrize("texts, labels", [
    ([("Obj_UpDown", "Output A - Direct: {{0}}"), ("Obj_UpDown", "Output B - Direct: {{0}}")],
     ["Output A", "Output B"]),                     # Wort des Herstellers
    ([("Ch A Val A Status Actuating Value", "Channel - Valve A"),
      ("Ch B Val A Status Actuating Value", "Channel - Valve A")], ["Kanal A", "Kanal B"]),
    ([("Sortie 1", "Sortie 1"), ("Sortie 2", "Sortie 2")], ["Sortie 1", "Sortie 2"]),
    ([("RMG 4 I  Kanal C1", "RMG 4 I channel C1"), ("RMG 4 I  Kanal C2", "x")],
     ["Kanal C1", "Kanal C2"]),
    ([("A, Schalten", "A, Schalten"), ("B, Schalten", "B, Schalten")], ["Kanal A", "Kanal B"]),
])
def test_channel_spellings_of_manufacturers(texts, labels):
    device = _device([(i, name, text, "", "") for i, (name, text) in enumerate(texts)])
    assert [ch.label for ch in device_channels(device)] == labels


def test_output_a_x_is_central_not_channel_a():
    device = _device([(1, "Ausgang A-X", "Output A-X", "", ""),
                      (2, "Ausgang A", "Output A", "", ""), (3, "Ausgang B", "Output B", "", "")])
    channels = device_channels(device)
    assert [len(ch.com_objects) for ch in channels] == [1, 1]


def test_program_names_are_split_for_matching():
    from knix_arranger.services.actor_channels import suggest_co
    cos = _device([(95, "Obj_TravelUpDown", "Channel A - Shutter: {{0}}", "DPST-1-8", ""),
                   (97, "Obj_StopTravel", "Channel A - Shutter: {{0}}", "DPST-1-7", ""),
                   (98, "Obj_HeightPosition", "Channel A - Shutter: {{0}}", "DPST-5-1", "")]
                  ).communication_objects
    assert suggest_co(cos, "AUF/AB").object_number == 95
    assert suggest_co(cos, "STOPP").object_number == 97
    assert suggest_co(cos, "POSITION HOEHE").object_number == 98


def test_dpt_fallback_without_function_text():
    """Hager: alle KOs eines Kanals heissen "Output 1" -- nur der DPT hilft."""
    from knix_arranger.services.actor_channels import Circuit, suggested_co_map
    device = _device([(1, "Output 1", "Output 1", "DPST-1-8", "K-S---"),
                      (2, "Output 1", "Output 1", "DPST-1-7", "K-S---"),
                      (3, "Output 1", "Output 1", "DPST-5-1", "K-S---"),
                      (4, "Output 1", "Output 1", "DPST-5-1", "K-S---"),
                      (5, "Output 1", "Output 1", "DPST-5-1", "KL-Ü--"),
                      (6, "Output 2", "Output 2", "DPST-1-8", "K-S---")])
    channel = device_channels(device)[0]
    circuit = Circuit(key="x", room_number="", room_name="", gewerk_code="J",
                      element_number=1, channel=1,
                      functions=[(f, "") for f in ("AUF/AB", "STOPP", "POSITION HOEHE",
                                                   "POSITION LAMELLEN", "STATUS POSITION HOEHE")],
                      dpts={"AUF/AB": "DPST-1-8", "STOPP": "DPST-1-7",
                            "POSITION HOEHE": "DPST-5-1", "POSITION LAMELLEN": "DPST-5-1",
                            "STATUS POSITION HOEHE": "DPST-5-1"})
    assert suggested_co_map(channel, circuit) == {
        "AUF/AB": 1, "STOPP": 2, "POSITION HOEHE": 3, "POSITION LAMELLEN": 4,
        "STATUS POSITION HOEHE": 5}


def test_dialog_offers_all_device_kos_when_channel_unknown(project):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from knix_arranger.ui.dialogs.actor_channel_dialog import ActorChannelDialog
    actor = _actor(project)
    # KOs ohne erkennbare Kanäle (z.B. Busch-Jaeger Room Controller)
    actor.communication_objects = [
        CommunicationObject(object_number=n, name=f"M1_Objekt_{n:02d}_1Bit",
                            object_function="") for n in range(1, 13)]
    dlg = ActorChannelDialog(project, [actor])
    dlg._circuit_table.selectRow(0)
    assert "alle 12 KOs des Geräts" in dlg._co_hint.text()
    combo = dlg._co_table.cellWidget(0, 2)
    assert combo.isEnabled() and combo.count() == 13
    combo.setCurrentIndex(combo.findData(7))
    dlg.apply()
    first = device_circuits(project, actor)[0]
    function = dlg._co_table.item(0, 0).text()
    assert actor.co_map[first.key][function] == 7
