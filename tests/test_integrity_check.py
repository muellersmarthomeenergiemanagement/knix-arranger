"""
Verweise bleiben über Bearbeitungen und Neuberechnungen gültig
(services/integrity_check, Datenstruktur-Prüfung 2026-10-16).
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.building import (
    Apartment, Areal, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.button_move import add_bedienelement, remove_bedienelement
from knix_arranger.services.integrity_check import check_integrity
from knix_arranger.services.knx_secure_service import KnxSecureService
from knix_arranger.services.recalc_service import RecalcService
from knix_arranger.services.sensor_service import refresh_bedienelemente
from knix_arranger.services.topology_engine import TopologyEngine


def _project(gewerk_catalog):
    waschen = Room(number="CUG01", name="Waschen")
    waschen.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=2)]
    technik = Room(number="CUG02", name="Technik")
    technik.gewerk_assignments = [GewerkAssignment(gewerk_code="L", count=1),
                                  GewerkAssignment(gewerk_code="H", count=1),
                                  GewerkAssignment(gewerk_code="A", count=2)]
    lift = Room(number="CUG03", name="Liftschacht")
    lift.gewerk_assignments = [GewerkAssignment(gewerk_code="A", count=1)]
    floor = Floor(name="Untergeschoss", short_code="UG", main_group_number=4)
    floor.apartments = [Apartment(name="Wohnung", rooms=[waschen, technik, lift])]
    project = KnxProject(name="Test")
    project.areal = Areal(buildings=[Building(name="Haus", wings=[Wing(floors=[floor])])])
    project._gewerk_catalog = gewerk_catalog
    project.topology = TopologyEngine().calculate_topology(project.areal)
    _recalc(project)
    return project, waschen, technik


def _recalc(project):
    RecalcService().recalc_actors_and_addresses(project)
    refresh_bedienelemente(project)


def test_references_survive_edits_and_recalculation(gewerk_catalog):
    """Projekt_23-Ablauf: Taster entfernen, Melder einfügen, neu berechnen --
    Secure-Archiv, Bedienelemente und Zuordnungen zeigen weiter auf
    vorhandene Geräte und GAs."""
    project, waschen, technik = _project(gewerk_catalog)
    secure = KnxSecureService()
    secure.update_device_compatibility(project.knx_secure, project)
    assert check_integrity(project) == []

    taster = next(be for be in technik.bedienelemente if be.element_type == "Tastereinheit")
    remove_bedienelement(technik, taster)
    add_bedienelement(waschen, "Bewegungsmelder", 1)
    add_bedienelement(technik, "Wassermelder", 1)
    _recalc(project)
    secure.update_device_compatibility(project.knx_secure, project)

    assert check_integrity(project) == []


def test_fdsk_stays_with_its_device(gewerk_catalog):
    """Ein eingetragener FDSK hängt nach einer Änderung am selben Gerät."""
    project, waschen, _technik = _project(gewerk_catalog)
    secure = KnxSecureService()
    secure.update_device_compatibility(project.knx_secure, project)
    sensor = next(d for a in project.topology.areas for l in a.lines for d in l.devices
                  if d.device_type == "sensor" and d.room_id != waschen.id)
    project.knx_secure.device_infos[sensor.id].fdsk = "00112233445566778899AABBCCDDEEFF"
    room_id, product = sensor.room_id, sensor.product

    add_bedienelement(waschen, "Präsenzmelder", 1)   # Adressen rücken nach
    _recalc(project)
    secure.update_device_compatibility(project.knx_secure, project)

    with_fdsk = [d for a in project.topology.areas for l in a.lines for d in l.devices
                 if project.knx_secure.device_infos.get(d.id)
                 and project.knx_secure.device_infos[d.id].fdsk]
    assert [(d.room_id, d.product) for d in with_fdsk] == [(room_id, product)]


# ── Bereinigung beim Öffnen (FA-624) und Validierung (FA-623, FA-625) ─────

def test_cleanup_relinks_or_releases_without_losing_entries(gewerk_catalog):
    """Tote Verweise aus früheren Versionen: Checklistenpunkt wieder mit
    seinem Bedienelement verbinden, Materialliste und Gewerk-Verknüpfung
    lösen -- Einträge und Prüfergebnisse bleiben."""
    from knix_arranger.models.documentation import ChecklistItem, CommissioningChecklist
    from knix_arranger.models.material_list import MaterialEntry
    from knix_arranger.services.reference_cleanup import clean_references
    project, waschen, _technik = _project(gewerk_catalog)
    taster = waschen.bedienelemente[0]
    project.checklists = [CommissioningChecklist(room_id=waschen.id, room_name="Waschen", items=[
        ChecklistItem(be_id="alt", be_type=taster.element_type,
                      be_number=taster.participant_number, result="ok"),
        ChecklistItem(be_id="weg", be_type="Rauchmelder", be_number="9.9.9", result="ok"),
    ])]
    project.material_list.entries = [MaterialEntry(device_id="weg", product_name="Aktor")]
    waschen.gewerk_assignments[0].linked_ga_ids = {"E/A": "gibt-es-nicht"}

    messages = clean_references(project)

    items = project.checklists[0].items
    assert [(i.be_id, i.result) for i in items] == [(taster.id, "ok"), ("", "ok")]
    assert project.material_list.entries[0].device_id == ""
    assert waschen.gewerk_assignments[0].linked_ga_ids == {}
    assert messages and clean_references(project) == []
    assert check_integrity(project) == []


def test_cleanup_indexes_sensors_of_older_files(gewerk_catalog):
    """Dateien vor 2026-10-16: Sensoren ohne Index werden ihrem Bedienelement
    zugeordnet, wie es die Neuberechnung tut."""
    from knix_arranger.services.reference_cleanup import clean_references
    project, _waschen, technik = _project(gewerk_catalog)
    sensors = [d for a in project.topology.areas for l in a.lines for d in l.devices
               if d.device_type == "sensor"]
    expected = {d.id: d.taster_index for d in sensors}
    thermostat = next(be for be in technik.bedienelemente if be.element_type == "Raumthermostat")
    address = thermostat.participant_number
    for d in sensors:
        d.taster_index = 0
    thermostat.participant_number = ""

    clean_references(project)

    assert {d.id: d.taster_index for d in sensors} == expected
    assert thermostat.participant_number == address


def test_validation_reports_references_and_structure(gewerk_catalog):
    """FA-623 meldet, was die Bereinigung nicht lösen kann; FA-625 Gewerk
    doppelt im Raum. Beide gehören nicht auf die ETS-Arbeitsliste."""
    from knix_arranger.models.dali_config import DaliGateway
    from knix_arranger.services.ets_worklist import current_items
    from knix_arranger.services.validation_engine import ValidationEngine
    project, waschen, _technik = _project(gewerk_catalog)
    project.dali_configs["weg"] = DaliGateway(gateway_device_id="weg", gateway_address="1.1.2")
    waschen.gewerk_assignments.append(GewerkAssignment(gewerk_code="L", count=1))

    issues = ValidationEngine(gewerk_catalog).validate(project.group_addresses, project)

    found = {(i.rule_id, i.level, i.message.split(":")[0]) for i in issues
             if i.rule_id in ("FA-623", "FA-625")}
    assert ("FA-623", "warning", "DALI") in found
    assert ("FA-625", "warning", "Raum CUG01 Waschen") in found
    assert not any(item.rule in ("FA-623", "FA-625") for item in current_items(project))


# ── Checklisten nicht mehr vorhandener Räume (FA-623/624) ─────────────────

def _orphan(room_name, items):
    from knix_arranger.models.documentation import CommissioningChecklist
    return CommissioningChecklist(room_id="alter-raum", room_name=room_name, items=items)


def test_cleanup_moves_checklist_results_by_address(gewerk_catalog):
    """Neuaufbau mit Option «Inbetriebnahme»: Ergebnisse mit Adresse wandern
    in die Checkliste des heutigen Raums, verwaiste ohne Ergebnis fallen weg,
    der Rest bleibt für die Validierung."""
    from knix_arranger.models.documentation import ChecklistItem
    from knix_arranger.services.reference_cleanup import clean_references
    project, waschen, _technik = _project(gewerk_catalog)
    taster = next(be for be in waschen.bedienelemente if be.element_type == "Tastereinheit")
    project.checklists = [
        _orphan("01 Waschküche", [
            ChecklistItem(be_type="Tastereinheit", be_number=taster.participant_number,
                          check_type="Montage", result="OK", checked_by="MM"),
            ChecklistItem(be_type="Tastereinheit", be_number=taster.participant_number,
                          check_type="Applikation")]),
        _orphan("02 Leer", [ChecklistItem(be_type="Tastereinheit", check_type="Montage")]),
        _orphan("03 Ohne Adresse", [ChecklistItem(be_type="Tastereinheit",
                                                  check_type="Montage", result="OK")]),
        _orphan("04 Dali", [])]
    project.checklists[3].room_id = "__dali__"

    clean_references(project)

    names = [cl.room_name for cl in project.checklists]
    assert names == ["03 Ohne Adresse", "04 Dali", "CUG01 Waschen"]
    moved = next(i for i in project.checklists[2].items
                 if i.be_number == taster.participant_number and i.check_type == "Montage")
    assert (moved.result, moved.checked_by, moved.be_id) == ("OK", "MM", taster.id)
    assert [i.kind for i in check_integrity(project)] == ["Checkliste: Raum fehlt"]


def test_validation_offers_to_move_or_remove_checklist(gewerk_catalog):
    """Rechtsklick auf «Checkliste: Raum fehlt»: Raum wählen, Vorschlag nach
    Namen übernehmen oder entfernen."""
    from knix_arranger.models.documentation import ChecklistItem
    from knix_arranger.services import checklist_repair as cr
    from knix_arranger.services import validation_targets as vt
    from knix_arranger.services.validation_engine import ValidationEngine
    project, waschen, _technik = _project(gewerk_catalog)
    orphan = _orphan("07 Waschen", [ChecklistItem(be_type="Tastereinheit",
                                                  check_type="Montage", result="OK")])
    project.checklists = [orphan]

    issue = next(i for i in ValidationEngine(gewerk_catalog).validate(
        project.group_addresses, project) if i.rule_id == "FA-623")
    targets = vt.targets_for({"rule_id": issue.rule_id, "address": issue.address,
                              "message": issue.message, "details": issue.details}, project)
    assert [t.focus[0] for t in targets] == ["choose", "move", "remove"]
    assert targets[1].focus[1] == waschen.id

    assert cr.move_checklist(project, orphan.id, waschen.id) == 1
    assert [cl.room_id for cl in project.checklists] == [waschen.id]
    assert check_integrity(project) == []
