"""
Tests fuer RecalcService (Kaskaden-Neuberechnung).
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.recalc_service import RecalcService
from knix_arranger.services.topology_engine import TopologyEngine
from knix_arranger.services.address_generator import AddressGenerator
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene


def _mg(structure, hg_number: int, mg_number: int):
    hg = next(h for h in structure.main_groups if h.number == hg_number)
    return next(m for m in hg.middle_groups if m.number == mg_number)


class TestRecalcServicePreservesScenes:
    """Regression: recalc_actors_and_addresses() darf bereits generierte
    Szenen-GAs (HG 0 / MG 4) nicht verwerfen, nur weil es beim Neu-Generieren
    der GAs die Projekt-Szenen nicht an den AddressGenerator weiterreicht."""

    def test_recalc_keeps_scene_gas(self, eg_room_with_gewerke, gewerk_catalog):
        project = KnxProject(name="Test")
        project.areal = eg_room_with_gewerke
        project._gewerk_catalog = gewerk_catalog
        project.scenes = [Scene(name="Kino", scene_number=1)]

        engine = TopologyEngine()
        project.topology = engine.calculate_topology(eg_room_with_gewerke)

        gen = AddressGenerator(gewerk_catalog, variant=project.config.mg_variant)
        project.group_addresses = gen.generate(
            eg_room_with_gewerke, scenes=project.scenes,
        )

        # Vorbedingung: Die (gemeinsame) Szenenaufruf-GA ist tatsaechlich
        # vorhanden (KNX-Konvention DPT 17/18: Szenen mit gleichem
        # Geltungsbereich teilen sich eine GA statt je einer eigenen, siehe
        # scene_addressing.py -- daher steht "Kino" nicht in der Bezeichnung).
        mg4_before = _mg(project.group_addresses, 0, 4)
        assert any("Szenenaufruf" in ga.designation for ga in mg4_before.group_addresses)

        result = RecalcService().recalc_actors_and_addresses(project)
        assert result["ok"]

        mg4_after = _mg(project.group_addresses, 0, 4)
        assert any("Szenenaufruf" in ga.designation for ga in mg4_after.group_addresses)
