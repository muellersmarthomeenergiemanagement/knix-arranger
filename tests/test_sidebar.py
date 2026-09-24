"""Tests fuer die gruppierte Seitenleiste."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from knix_arranger.ui.widgets.sidebar import Sidebar, NAV_GROUPS


@pytest.fixture(scope="module", autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def sidebar():
    return Sidebar()


def _group(sidebar, title):
    return next(g for g in sidebar._groups if g.title == title)


def test_every_view_is_in_exactly_one_group():
    keys = [key for _, entries in NAV_GROUPS for key, _, _ in entries]
    assert len(keys) == len(set(keys))


def test_initially_only_planung_open(sidebar):
    assert sidebar.expanded_groups() == ["Planung"]


def test_several_groups_can_be_open(sidebar):
    received = []
    sidebar.groups_changed.connect(received.append)
    _group(sidebar, "Angebot")._header.click()
    _group(sidebar, "Adressen & Logik")._header.click()
    assert sidebar.expanded_groups() == ["Planung", "Adressen & Logik", "Angebot"]
    assert received[-1] == ["Planung", "Adressen & Logik", "Angebot"]


def test_header_click_closes_group(sidebar):
    _group(sidebar, "Planung")._header.click()
    assert sidebar.expanded_groups() == []


def test_restore_saved_groups(sidebar):
    sidebar.set_expanded_groups(["Projekt", "Angebot", "gibt es nicht"])
    assert sidebar.expanded_groups() == ["Projekt", "Angebot"]


def test_select_opens_group_without_closing_others(sidebar):
    received = []
    sidebar.groups_changed.connect(received.append)
    sidebar.select("material_list")
    assert sidebar._buttons["material_list"].isChecked()
    assert sidebar.expanded_groups() == ["Planung", "Topologie & Geräte"]
    assert received == [["Planung", "Topologie & Geräte"]]


def test_group_title_with_ampersand_is_shown(sidebar):
    # "&&" zeigt ein echtes "&" statt einer Tastenkürzel-Markierung
    assert _group(sidebar, "Topologie & Geräte")._header.text().strip() == "TOPOLOGIE && GERÄTE"
