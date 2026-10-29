"""Gewerke in der Ansicht "ETS-Funktionen" (FA-530c): Gewerk der GA, bei
ETS-eigenen GAs abgeleitet über die Aktor-KOs, Korrektur und Anzeige."""
import os

from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.topology import Area, Line, Device, CommunicationObject
from knix_arranger.services.function_gewerke import EtsGewerke, gewerk_cell, gewerk_label

from tests.test_ets_functions import _import


def _with_actor(project):
    """Aktorkanal mit Element-GA "LD.DG.04.01_ea" und ETS-GA "Schalten" 12/1/6."""
    element = GroupAddress(main_group=3, middle_group=0, sub_group=1,
                           designation="LD.DG.04.01_ea", gewerk_code="LD")
    project.group_addresses.main_groups[0].middle_groups[0].group_addresses.append(element)
    device = Device(physical_address="1.1.5", device_type="actor")
    device.communication_objects = [CommunicationObject(
        object_number=1, name="Kanal A", object_function="Schalten",
        connected_gas=["3/0/1", "12/1/6"])]
    line = Line(line_number=1)
    line.devices.append(device)
    area = Area(area_number=1)
    area.lines.append(line)
    project.topology.areas.append(area)
    return project


def test_label_and_cell():
    project = _import()
    assert gewerk_label(project, "J") == "J Jalousie"
    assert gewerk_label(project, "XY") == "XY"
    assert gewerk_cell(project, []).text == "–"
    several = gewerk_cell(project, ["L", "LD", "L"])
    assert several.text == "L, LD"
    assert several.tooltip == f"{gewerk_label(project, 'L')}, {gewerk_label(project, 'LD')}"


def test_ga_own_gewerk_and_correction():
    project = _import()
    gewerke = EtsGewerke(project)
    # J.DG.04.02-04_move -> J aus dem ETS-Namen
    assert gewerke.cell("0/1/105").text == "J Jalousie"
    project.ets_corrections.gewerk_by_address["0/1/105"] = "G"
    assert gewerke.cell("0/1/105").text == (
        f"{gewerk_label(project, 'G')} (statt J Jalousie)")


def test_ets_generated_ga_derived_from_actor_channel():
    project = _with_actor(_import())
    gewerke = EtsGewerke(project)
    cell = gewerke.cell("12/1/6")
    assert cell.text == gewerk_label(project, "LD") and cell.derived
    assert "abgeleitet" in cell.tooltip
    # Statusrückmeldung 12/1/7 auf keinem KO
    assert gewerke.cell("12/1/7").text == "–"
    assert gewerke.function_cell(["12/1/6", "12/1/7"]).derived
    # eigenes Gewerk einer GA geht vor dem abgeleiteten
    mixed = gewerke.function_cell(["12/1/6", "0/1/105"])
    assert mixed.text == "J Jalousie" and not mixed.derived


def test_view_shows_gewerk_column():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.views.ets_functions_view import EtsFunctionsView
    _app = QApplication.instance() or QApplication([])
    view = EtsFunctionsView()
    view.set_project(_with_actor(_import()))
    assert view._tree.headerItem().text(1) == "Gewerk"
    room = view._tree.topLevelItem(0)
    functions = {room.child(i).text(0): room.child(i) for i in range(room.childCount())}
    lese = functions["Leselampen (Licht schalten)"]
    assert lese.text(1) == gewerk_label(view._project, "LD")
    assert lese.font(1).italic()
    assert lese.child(0).text(2) and lese.child(0).text(1) == gewerk_label(view._project, "LD")
    blinds = functions["Jalousien Schlafzimmer (Sonnenschutz)"]
    assert blinds.text(1) == "J Jalousie" and not blinds.font(1).italic()
