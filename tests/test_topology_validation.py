"""
Tests fuer die Topologie-Pruefungen der Validierung (FA-609, FA-611 bis FA-613).
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.address_generator import insert_ga
from knix_arranger.services.topology_validation import check_topology
from knix_arranger.services.validation_engine import ValidationEngine


def _project(*devices: Device, imported: bool = False) -> KnxProject:
    project = KnxProject(name="Test")
    project.topology.is_imported = imported
    line = Line(line_number=1, name="EG", devices=[
        Device(physical_address="1.1.0", device_type="coupler"),
        Device(physical_address="1.1.-", device_type="power_supply"),
        *devices,
    ])
    project.topology.areas.append(Area(area_number=1, lines=[line]))
    return project


def _actor(pa: str, *gas: str) -> Device:
    return Device(physical_address=pa, device_type="actor", product_name="Schaltaktor",
                  communication_objects=[CommunicationObject(object_number=1,
                                                             connected_gas=list(gas))])


def _rules(issues) -> list[tuple[str, str]]:
    return [(i.rule_id, i.level) for i in issues]


class TestTopologyChecks:
    def test_clean_line(self):
        assert check_topology(_project(_actor("1.1.1"))) == []

    def test_no_topology_no_issues(self):
        assert check_topology(KnxProject(name="Leer")) == []

    def test_line_load(self):
        warn = _project(*(_actor(f"1.1.{i}") for i in range(1, 86)))
        assert _rules(check_topology(warn)) == [("FA-609", "warning")]   # 86 inkl. Koppler
        err = _project(*(_actor(f"1.1.{i}") for i in range(1, 101)))
        assert _rules(check_topology(err)) == [("FA-609", "error")]

    def test_tp64_limit(self):
        project = _project(*(_actor(f"1.1.{i}") for i in range(1, 65)))
        project.topology.topology_mode = "TP-64"
        issues = check_topology(project)
        assert _rules(issues) == [("FA-609", "error")]
        assert "max. 64" in issues[0].message

    def test_physical_addresses(self):
        project = _project(_actor("1.2.5"), _actor("1.1.7"), _actor("1.1.7"),
                           _actor("1.1.0"), _actor("x.1"))
        messages = [i.message for i in check_topology(project) if i.rule_id == "FA-612"]
        assert "Schaltaktor 1.2.5 liegt in Linie 1.1 EG" in messages
        assert "1.1.7 doppelt vergeben: Schaltaktor und Schaltaktor" in messages
        assert "Schaltaktor 1.1.0: Teilnehmer 0 ist dem Koppler vorbehalten" in messages
        assert "1.1.0 doppelt vergeben: Gerät und Schaltaktor" in messages
        assert "Schaltaktor: ungültige physikalische Adresse «x.1»" in messages

    def test_area_coupler_in_first_line_is_fine(self):
        """Bereichskoppler B.0.0 steht im Modell in einer Linie seines
        Bereichs (area_coupler) -- kein FA-612 (Projekt_23: 1.0.0 in 1.1)."""
        project = _project(Device(physical_address="1.0.0", device_type="coupler"))
        assert not [i for i in check_topology(project) if i.rule_id == "FA-612"]
        # Fremder Bereich oder kein Koppler bleibt ein Fehler
        project = _project(Device(physical_address="2.0.0", device_type="coupler"),
                           _actor("1.0.5"))
        messages = [i.message for i in check_topology(project) if i.rule_id == "FA-612"]
        assert len(messages) == 2

    def test_power_supply_missing(self):
        project = _project(_actor("1.1.1"))
        line = project.topology.areas[0].lines[0]
        line.devices = [d for d in line.devices if d.device_type != "power_supply"]
        assert _rules(check_topology(project)) == [("FA-613", "warning")]
        project.topology.is_imported = True
        assert _rules(check_topology(project)) == [("FA-613", "info")]

    def test_co_link_to_missing_ga(self):
        project = _project(_actor("1.1.1", "2/0/0", "2/0/9"))
        insert_ga(project.group_addresses,
                  GroupAddress(main_group=2, middle_group=0, sub_group=0, designation="L"))
        issues = check_topology(project)
        assert _rules(issues) == [("FA-611", "warning")]
        assert "verknüpfte GA 2/0/9 fehlt" in issues[0].message

    def test_unlinked_ga_only_imported(self):
        project = _project(_actor("1.1.1", "2/0/0"))
        for sub in (0, 1):
            insert_ga(project.group_addresses,
                      GroupAddress(main_group=2, middle_group=0, sub_group=sub,
                                   designation=f"GA {sub}"))
        assert check_topology(project) == []
        project.topology.is_imported = True
        issues = check_topology(project)
        assert _rules(issues) == [("FA-611", "info")]
        assert issues[0].address == "2/0/1"


class TestEngine:
    def test_engine_includes_topology(self):
        project = _project(_actor("1.2.5"))
        issues = ValidationEngine().validate(project.group_addresses, project=project)
        assert any(i.rule_id == "FA-612" for i in issues)
