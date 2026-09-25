"""
Tests fuer GewerkSuggestionReviewDialog: Uebernahme von Vorschlaegen in
Mehrfach-Zuweisungen (ein Element je Aktor-Kanal).
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.services.gewerk_suggestion_service import suggest_gewerk_assignments
from knix_arranger.ui.dialogs.gewerk_suggestion_review_dialog import GewerkSuggestionReviewDialog

from tests.test_gewerk_suggestion_service import _project_with_two_blinds


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_accept_links_each_blind_to_its_element():
    project, room, placeholder = _project_with_two_blinds()
    suggestions, _ = suggest_gewerk_assignments(project)
    dlg = GewerkSuggestionReviewDialog(project, suggestions)
    dlg._on_accept()

    assert dlg.applied_count == 2
    assert room.gewerk_assignments == [placeholder]
    links = placeholder.all_element_links()
    assert set(links) == {1, 2}
    ga_by_id = {ga.id: ga for ga in project.group_addresses.all_addresses()}
    assert ga_by_id[links[1]["AUF/AB"]].designation == "J.EG.01.01_move"
    assert ga_by_id[links[2]["AUF/AB"]].designation == "J.EG.01.02_move"
    assert ga_by_id[links[2]["AUF/AB"]].element_number == 2
