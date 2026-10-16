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
