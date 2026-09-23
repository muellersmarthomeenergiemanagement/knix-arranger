"""Tests fuer den zentralen Event-Bus (ProjectBus)."""
import pytest

from knix_arranger.services.project_bus import ProjectBus


@pytest.fixture
def bus():
    return ProjectBus()


@pytest.mark.parametrize("emit, signal, context", [
    ("emit_building_changed", "building_changed", "building"),
    ("emit_functions_changed", "functions_changed", "functions"),
    ("emit_topology_changed", "topology_changed", "topology"),
    ("emit_addresses_changed", "addresses_changed", "addresses"),
    ("emit_material_changed", "material_changed", "material"),
    ("emit_project_loaded", "project_loaded", "project_loaded"),
])
def test_emit_sends_specific_signal_and_any_change(bus, emit, signal, context):
    specific, broadcast = [], []
    getattr(bus, signal).connect(lambda: specific.append(True))
    bus.any_change.connect(broadcast.append)

    getattr(bus, emit)()

    assert specific == [True]
    assert broadcast == [context]


def test_emit_does_not_trigger_other_signals(bus):
    fired = []
    bus.topology_changed.connect(lambda: fired.append("topology"))
    bus.emit_building_changed()
    assert fired == []


def test_begin_change_reports_description(bus):
    received = []
    bus.change_started.connect(received.append)
    bus.begin_change("Raum umbenannt")
    assert received == ["Raum umbenannt"]
