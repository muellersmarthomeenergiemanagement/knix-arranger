"""
Tests fuer den Wizard-Ablauf: gemeinsame Aenderungspruefung (RecomputeGuard),
Direktspruenge ueber Schrittnummern, Hilfe pro Schritt und seiteneffektfreie
Exporte.
"""
from __future__ import annotations
import json
import os
import sys
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.models.building import GewerkAssignment
from knix_arranger.ui.wizard import step07_addresses
from knix_arranger.ui.wizard.recompute_guard import (
    RecomputeGuard, KEY_ADDRESSES, KEY_FUNCTIONS,
)
from knix_arranger.ui.wizard.wizard_controller import (
    WizardController, NUM_STEPS, STEP_INDEX_ADDRESSES, STEP_TITLES,
    _HELP_PATH, help_topic_key,
)


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestRecomputeGuard:
    def test_stale_until_marked(self, test_project):
        guard = RecomputeGuard()
        assert guard.is_stale(test_project, KEY_ADDRESSES)
        guard.mark_done(test_project, KEY_ADDRESSES)
        assert not guard.is_stale(test_project, KEY_ADDRESSES)

    def test_gewerk_change_makes_stale(self, test_project):
        guard = RecomputeGuard()
        guard.mark_done(test_project, KEY_FUNCTIONS)
        test_project.all_rooms[0].gewerk_assignments.append(
            GewerkAssignment(gewerk_code="L", count=1)
        )
        assert guard.is_stale(test_project, KEY_FUNCTIONS)

    def test_variant_change_makes_addresses_stale(self, test_project):
        guard = RecomputeGuard()
        guard.mark_done(test_project, KEY_ADDRESSES)
        test_project.config.mg_variant = "B" if test_project.config.mg_variant == "A" else "A"
        assert guard.is_stale(test_project, KEY_ADDRESSES)


class TestWizardGuardSharing:
    def test_all_steps_share_one_guard(self, test_project):
        wizard = WizardController(test_project)
        guarded = [s for s in wizard._steps if hasattr(s, "_guard")]
        assert len(guarded) >= 6
        assert all(s._guard is wizard._guard for s in guarded)

    def test_addresses_not_regenerated_without_changes(self, test_project):
        wizard = WizardController(test_project)
        wizard._go_to_step(STEP_INDEX_ADDRESSES)   # erste Generierung
        assert test_project.group_addresses.all_addresses()

        with patch.object(step07_addresses, "regenerate_addresses",
                          wraps=step07_addresses.regenerate_addresses) as regen:
            wizard._go_to_step(STEP_INDEX_ADDRESSES - 1)
            wizard._go_to_step(STEP_INDEX_ADDRESSES)
            assert regen.call_count == 0

            test_project.all_rooms[0].gewerk_assignments.append(
                GewerkAssignment(gewerk_code="L", count=1)
            )
            wizard._go_to_step(STEP_INDEX_ADDRESSES - 1)
            wizard._go_to_step(STEP_INDEX_ADDRESSES)
            assert regen.call_count == 1


    def test_second_full_pass_recomputes_nothing(self, test_project):
        """Neu vergebene IDs (Bedienelemente, Aktor-Zuordnungen) dürfen nicht
        als Änderung gelten – sonst rechnet jeder Durchlauf alles neu."""
        from knix_arranger.services.sensor_service import SensorService
        from knix_arranger.services.topology_engine import TopologyEngine
        from knix_arranger.ui.wizard import step05_gewerke

        wizard = WizardController(test_project)
        with patch("knix_arranger.ui.wizard.wizard_controller.QMessageBox"):
            for i in range(NUM_STEPS):
                wizard._go_to_step(i)
            with patch.object(step07_addresses, "regenerate_addresses") as ga10,                  patch.object(step05_gewerke, "regenerate_addresses") as ga5,                  patch.object(SensorService, "auto_assign_functions") as fn,                  patch.object(TopologyEngine, "populate_devices") as dev:
                for i in range(NUM_STEPS):
                    wizard._go_to_step(i)
        assert (ga10.call_count, ga5.call_count, fn.call_count, dev.call_count) == (0, 0, 0, 0)


class TestJumpToStep:
    def test_jump_stops_at_hard_blocked_step(self, test_project):
        """Ohne Topologie darf ein Direktsprung nicht an Schritt 7 vorbei."""
        test_project.topology.areas = []
        wizard = WizardController(test_project)
        with patch("knix_arranger.ui.wizard.wizard_controller.QMessageBox.warning") as warn:
            wizard._jump_to_step(STEP_INDEX_ADDRESSES)
        warn.assert_called_once()
        assert wizard._current_step == 6  # "7. Topologie"

    def test_jump_backwards_is_always_allowed(self, test_project):
        wizard = WizardController(test_project)
        wizard._go_to_step(4)
        wizard._jump_to_step(1)
        assert wizard._current_step == 1


class TestStepHelp:
    def test_every_step_has_matching_help_topic(self):
        # Schreibweise der Umlaute (ae/ä) ist hier nicht Gegenstand der Prüfung
        umlaut = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})
        topics = json.loads(_HELP_PATH.read_text(encoding="utf-8"))["help_topics"]
        for i in range(NUM_STEPS):
            topic = topics[help_topic_key(i)]
            number, _, name = STEP_TITLES[i].partition(". ")
            expected = f"Schritt {number}: {name}"
            assert topic["title"].translate(umlaut) == expected.translate(umlaut), topic["title"]
            assert f"Schritt {number} –" in topic["content_html"]


class TestExportHasNoSideEffects:
    def test_project_for_export_leaves_project_untouched(self, test_project):
        from knix_arranger.services.sensor_service import project_for_export

        before = json.dumps(test_project.to_dict(), sort_keys=True, default=repr)
        snapshot = project_for_export(test_project)
        after = json.dumps(test_project.to_dict(), sort_keys=True, default=repr)

        assert before == after
        assert snapshot is not test_project
