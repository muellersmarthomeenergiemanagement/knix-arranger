"""Korrekturschicht für importierte ETS-Projekte (FA-616)."""
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.services.ets_corrections import (
    apply_ets_corrections, deviations, effective_gewerk, gewerk_display, set_gewerk,
)
from knix_arranger.services.rebuild_service import REBUILD_OPTIONS
from knix_arranger.services.validation_engine import ValidationEngine


def _project(imported=True) -> KnxProject:
    project = KnxProject(name="Chalet")
    project.topology.is_imported = imported
    mg = MiddleGroup(number=2, name="Allgemein")
    mg.group_addresses = [
        GroupAddress(main_group=2, middle_group=2, sub_group=115, gewerk_code="T",
                     designation="T.EG.01.03_ea   ( Tor Einstellhalle Berg )"),
        GroupAddress(main_group=2, middle_group=2, sub_group=1, gewerk_code="L",
                     designation="L.EG.01.01_ea ( Decke )"),
    ]
    project.group_addresses = GroupAddressStructure(
        main_groups=[MainGroup(number=2, name="EG", middle_groups=[mg])])
    return project


def test_gewerk_korrigieren_und_aufheben():
    project = _project()
    tor = project.group_addresses.all_addresses()[0]
    assert set_gewerk(project, ["2/2/115"], "G") == 1
    assert tor.gewerk_code == "G"
    assert effective_gewerk(project, tor) == "G"
    assert gewerk_display(tor) == "G (statt T)"
    set_gewerk(project, ["2/2/115"], "")
    assert tor.gewerk_code == "T"
    assert project.ets_corrections.gewerk_by_address == {}


def test_korrektur_ueberlebt_speichern_und_reimport():
    project = _project()
    set_gewerk(project, ["2/2/115"], "G")
    loaded = KnxProject.from_dict(project.to_dict())
    tor = loaded.group_addresses.all_addresses()[0]
    tor.gewerk_code = "T"                 # wie frisch aus der ETS
    assert apply_ets_corrections(loaded) == 1
    assert tor.gewerk_code == "G"
    assert any(o.key == "ets_corrections" and o.default for o in REBUILD_OPTIONS)


def test_abweichungen_in_der_validierung():
    project = _project()
    set_gewerk(project, ["2/2/115"], "G")
    assert [(d.address, d.ets_value, d.knix_value) for d in deviations(project)] == \
        [("2/2/115", "T", "G")]
    issues = [i for i in ValidationEngine().validate(project.group_addresses, project=project)
              if i.rule_id == "FA-616"]
    assert [(i.address, i.level) for i in issues] == [("2/2/115", "info")]


def test_richtlinien_nach_projektart():
    """Importiert: Richtlinien nur als Hinweis; mit KNiX geplant: Fehler."""
    for imported, level in ((True, "info"), (False, "error")):
        project = _project(imported)
        project.group_addresses.all_addresses()[1].designation = "Licht Decke"   # FA-610
        issues = ValidationEngine().validate(project.group_addresses, project=project)
        levels = {i.level for i in issues if i.rule_id in ValidationEngine.GUIDELINE_RULES}
        assert levels == {level}
