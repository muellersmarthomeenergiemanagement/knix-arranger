"""Re-Import der .knxproj behält Tastenparameter und Szenenwerte aus den
ETS-Reports (die .knxproj liefert sie nicht)."""
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, SceneValueEntry
from knix_arranger.services.project_reconcile_service import reconcile_reimport
from knix_arranger.services.rebuild_service import adopt_report_params

PARAMS = "Taste 1: Bedienphilosophie: Zweiflächen\nFunktion: Dimmen"


def _project(with_params: bool) -> KnxProject:
    project = KnxProject(name="Chalet")
    taster = Device(physical_address="1.1.51", device_type="sensor")
    aktor = Device(physical_address="1.1.15", device_type="actor")
    if with_params:
        taster.button_configuration = PARAMS
        aktor.scene_values = [SceneValueEntry(channel="A", scene_number=1, value="100 %")]
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1,
                                                               devices=[taster, aktor])])]
    return project


def _devices(project):
    return {d.physical_address: d for d in project.topology.areas[0].lines[0].devices}


def test_reimport_behaelt_parameter_aus_dem_report():
    old, fresh = _project(True), _project(False)      # fresh: wie aus der .knxproj
    diff = reconcile_reimport(old, fresh)
    devices = _devices(fresh)
    assert devices["1.1.51"].button_configuration == PARAMS
    assert devices["1.1.15"].scene_values[0].value == "100 %"
    assert diff.report_params_kept == 2


def test_frische_parameter_haben_vorrang():
    old, fresh = _project(True), _project(False)
    _devices(fresh)["1.1.51"].button_configuration = "neu aus dem Report"
    reconcile_reimport(old, fresh)
    assert _devices(fresh)["1.1.51"].button_configuration == "neu aus dem Report"


def test_neuaufbau_uebernimmt_parameter():
    old, fresh = _project(True), _project(False)
    assert adopt_report_params(old, fresh) == 2
    assert _devices(fresh)["1.1.51"].button_configuration == PARAMS
