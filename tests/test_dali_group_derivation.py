"""
Tests fuer die DALI-Gruppenableitung aus NamingEngine-GAs ("LDA_M01_01 ...")
am Beispiel "Test Musik": ein einziges DALI-Element ergab zwei gleichnamige
Gruppen -- Schalt-GA mit Klartext-Kommentar "(Musikzimmer)" wurde nicht
erkannt, und die Rueckmeldung "RM WERT" kollidierte mit "WERT".
Dazu die Schaltflaeche "Gruppen aus GAs neu ableiten".
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox

from knix_arranger.models.dali_config import DaliGateway, DaliGroup
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Topology, Area, Line, Device
from knix_arranger.services.dali_service import DaliService
from knix_arranger.ui.views.dali_config_view import DaliConfigView


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


_MUSIK_GAS = [
    (10, "LDA_M01_01 E/A (Musikzimmer)"),
    (11, "LDA_M01_01 DIM"),
    (12, "LDA_M01_01 WERT"),
    (13, "LDA_M01_01 RM"),
    (14, "LDA_M01_01 RM WERT"),
    (15, "LDA_M01_01 SZENE"),
    (18, "LDA_M01_01 STOERUNG"),
]


def _project(gas=_MUSIK_GAS) -> tuple[KnxProject, Device]:
    project = KnxProject(name="Test Musik")
    mg = MiddleGroup(number=0, name="Licht")
    mg.group_addresses = [
        GroupAddress(main_group=1, middle_group=0, sub_group=sub, designation=d)
        for sub, d in gas
    ]
    hg = MainGroup(number=1, name="EG")
    hg.middle_groups = [mg]
    project.group_addresses = GroupAddressStructure()
    project.group_addresses.main_groups = [hg]

    device = Device(device_type="gateway", product="DALI-Gateway 16-fach",
                    physical_address="1.1.1")
    line = Line(name="Linie 1", line_number=1)
    line.devices = [device]
    area = Area(area_number=1, name="Bereich 1")
    area.lines = [line]
    project.topology = Topology()
    project.topology.areas = [area]
    return project, device


def _groups(gw):
    return [(g.ga_switch, g.ga_dim, g.ga_value) for g in gw.groups]


class TestDeriveGroupsNamingEngine:
    def test_one_element_gives_one_group_with_switch_dim_value(self):
        project, device = _project()
        gw = DaliGateway(gateway_device_id=device.id, name="GW")

        n = DaliService()._derive_groups_from_import(gw, device, project)

        assert n == 1
        assert _groups(gw) == [("1/0/10", "1/0/11", "1/0/12")]

    def test_rm_wert_is_fallback_when_no_command_value(self):
        project, device = _project([
            (10, "LDA_M01_01 E/A"), (14, "LDA_M01_01 RM WERT"),
        ])
        gw = DaliGateway(gateway_device_id=device.id, name="GW")
        DaliService()._derive_groups_from_import(gw, device, project)
        assert _groups(gw) == [("1/0/10", "", "1/0/14")]

    def test_command_value_replaces_earlier_rm_wert(self):
        # RM WERT hat die kleinere Adresse und wird zuerst verarbeitet
        project, device = _project([
            (10, "LDA_M01_01 E/A"), (11, "LDA_M01_01 RM WERT"), (12, "LDA_M01_01 WERT"),
        ])
        gw = DaliGateway(gateway_device_id=device.id, name="GW")
        DaliService()._derive_groups_from_import(gw, device, project)
        assert _groups(gw) == [("1/0/10", "", "1/0/12")]


class TestRederiveGroups:
    def test_service_replaces_existing_groups(self):
        project, device = _project()
        gw = DaliGateway(gateway_device_id=device.id, name="GW", groups=[
            DaliGroup(number=0, name="Musikzimmer", ga_dim="1/0/11", ga_value="1/0/12"),
            DaliGroup(number=1, name="Musikzimmer", ga_value="1/0/14"),
        ])
        assert DaliService().rederive_groups(project, gw) == 1
        assert _groups(gw) == [("1/0/10", "1/0/11", "1/0/12")]

    def test_service_reports_missing_gateway(self):
        project, _ = _project()
        gw = DaliGateway(gateway_device_id="weg", name="GW",
                         groups=[DaliGroup(number=0, name="Alt")])
        assert DaliService().rederive_groups(project, gw) == -1

    def test_button_asks_before_replacing(self):
        project, device = _project()
        view = DaliConfigView(project)
        view.set_project(project)
        gw = view._current_gw
        gw.groups = [DaliGroup(number=0, name="Alt")]

        with patch("knix_arranger.ui.views.dali_config_view.QMessageBox.question",
                   return_value=QMessageBox.No):
            view._rederive_groups()
        assert [g.name for g in gw.groups] == ["Alt"]

        with patch("knix_arranger.ui.views.dali_config_view.QMessageBox.question",
                   return_value=QMessageBox.Yes):
            view._rederive_groups()
        assert _groups(gw) == [("1/0/10", "1/0/11", "1/0/12")]
        assert view._groups_table.rowCount() == 1
