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


# ── Raum eines Geräts und getrennte Verknüpfungen ─────────────────────────

def _project_with_rooms():
    from knix_arranger.models.building import (
        Apartment, Areal, Bedienelement, Building, Floor, Room, Wing,
    )
    from knix_arranger.models.topology import Area, Device, Line
    project = _project()
    carnotzet = Room(number="01", name="Carnotzet")
    halle = Room(number="08", name="Einstellhalle")
    carnotzet.bedienelemente = [Bedienelement(element_type="Tastereinheit",
                                              participant_number="1.2.6")]
    floor = Floor(name="Erdgeschoss", short_code="EG")
    floor.apartments = [Apartment(name="", rooms=[carnotzet, halle])]
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[floor])])])
    taster = Device(physical_address="1.2.6", device_type="sensor",
                    product="Taster 3-fach", room_id=carnotzet.id)
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=2, devices=[taster])])]
    return project, taster, carnotzet, halle


def test_raum_korrigieren_verschiebt_bedienelement():
    from knix_arranger.services.ets_corrections import set_device_room
    project, taster, carnotzet, halle = _project_with_rooms()
    assert set_device_room(project, taster, halle)
    assert taster.room_id == halle.id
    assert carnotzet.bedienelemente == [] and len(halle.bedienelemente) == 1
    assert project.ets_corrections.room_by_device == {"1.2.6": {"room": "EG|08", "ets": "EG|01"}}
    assert [(d.field, d.ets_value, d.knix_value) for d in deviations(project)] == \
        [("Raum", "EG 01 Carnotzet", "EG 08 Einstellhalle")]
    # zurück in den ETS-Raum hebt die Korrektur auf
    assert set_device_room(project, taster, carnotzet)
    assert project.ets_corrections.room_by_device == {}


def test_raum_korrektur_ueberlebt_reimport():
    from knix_arranger.services.ets_corrections import set_device_room
    project, taster, carnotzet, halle = _project_with_rooms()
    set_device_room(project, taster, halle)
    loaded = KnxProject.from_dict(project.to_dict())
    rooms = {r.number: r for r in loaded.all_rooms}
    device = loaded.topology.areas[0].lines[0].devices[0]
    # wie frisch aus der ETS: neue Raum-IDs, Gerät wieder im Carnotzet
    for r in loaded.all_rooms:
        r.id = r.id + "-neu"
    device.room_id = rooms["01"].id
    rooms["08"].bedienelemente, rooms["01"].bedienelemente = [], rooms["08"].bedienelemente
    apply_ets_corrections(loaded)
    assert device.room_id == rooms["08"].id
    assert rooms["01"].bedienelemente == [] and len(rooms["08"].bedienelemente) == 1


def test_geplantes_projekt_raum_folgt_der_planung():
    """Geplante Geräte ergeben sich aus den Gewerken ihres Raums: kein
    Umhängen, sonst bleibt nach der Neuberechnung eine leere Kopie des
    Bedienelements im Zielraum (Projekt_23 1.1.106)."""
    from knix_arranger.services.ets_corrections import set_device_room
    project, taster, carnotzet, halle = _project_with_rooms()
    project.topology.is_imported = False
    assert not set_device_room(project, taster, halle)
    assert taster.room_id == carnotzet.id
    assert len(carnotzet.bedienelemente) == 1 and halle.bedienelemente == []


def test_geplantes_projekt_manuelles_geraet_ohne_raum_korrektur():
    from knix_arranger.services.ets_corrections import set_device_room
    project, taster, _carnotzet, halle = _project_with_rooms()
    project.topology.is_imported = False
    taster.manually_added = True
    assert set_device_room(project, taster, halle)
    assert taster.room_id == halle.id
    assert project.ets_corrections.room_by_device == {}


def test_getrennte_ga_wird_beim_reimport_wieder_getrennt_und_gemeldet():
    from tests.test_multi_ga_check import _project as multi_project
    from knix_arranger.services.ets_corrections import check_unlinks_after_import
    from knix_arranger.services.multi_ga_check import unlink_ga
    project = multi_project()
    assert unlink_ga(project, "1.1.51", 6, "12/1/62")
    assert project.ets_corrections.unlinked == ["1.1.51|6|12/1/62"]
    assert ("Verknüpfung", "12/1/62") in {(d.field, d.address) for d in deviations(project)}

    # Re-Import: die ETS liefert die Verknüpfung noch
    taster = project.topology.areas[0].lines[0].devices[0]
    taster.communication_objects[2].connected_gas.append("12/1/62")
    pending = check_unlinks_after_import(project)
    assert [p.text() for p in pending] == ["1.1.51 KO 6 Taste 2, links:  12/1/62 S1 Wohnen_ea"]
    apply_ets_corrections(project)
    assert taster.communication_objects[2].connected_gas == ["12/0/120"]

    # in der ETS nachgeführt: Korrektur entfällt
    assert check_unlinks_after_import(project) == []
    assert project.ets_corrections.unlinked == []


def test_geplantes_projekt_merkt_keine_trennung():
    from tests.test_multi_ga_check import _project as multi_project
    from knix_arranger.services.multi_ga_check import unlink_ga
    project = multi_project()
    project.topology.is_imported = False
    assert unlink_ga(project, "1.1.51", 6, "12/1/62")
    assert project.ets_corrections.unlinked == []


def test_import_ablauf_meldet_noch_verbundene_gas():
    from tests.test_multi_ga_check import _project as multi_project
    from knix_arranger.services.import_pipeline import ImportPipeline
    from knix_arranger.services.multi_ga_check import unlink_ga
    from knix_arranger.services.project_reconcile_service import ReimportDiff
    project = multi_project()
    unlink_ga(project, "1.1.51", 6, "12/1/62")
    taster = project.topology.areas[0].lines[0].devices[0]
    taster.communication_objects[2].connected_gas.append("12/1/62")   # frisch aus der ETS

    nur_gebaeude = ImportPipeline(project)          # Gebäude-Report: KO-Daten nicht neu
    nur_gebaeude.finalize("x.xlsx", ReimportDiff())
    assert nur_gebaeude.pending_unlinks == []
    assert project.ets_corrections.unlinked == ["1.1.51|6|12/1/62"]   # nicht verworfen

    taster.communication_objects[2].connected_gas.append("12/1/62")
    pipeline = ImportPipeline(project)
    pipeline.links_from_ets = True
    pipeline.finalize("x.knxproj", ReimportDiff())
    assert [p.ga_address for p in pipeline.pending_unlinks] == ["12/1/62"]
    assert "12/1/62" not in taster.communication_objects[2].connected_gas


def test_korrektur_entfaellt_wenn_ets_nachgefuehrt():
    project = _project()
    set_gewerk(project, ["2/2/115"], "G")
    tor = project.group_addresses.all_addresses()[0]
    tor.designation = "G.EG.01.03_ea   ( Tor Einstellhalle Berg )"   # Re-Import: in der ETS korrigiert
    tor.gewerk_code = "G"
    assert deviations(project) == []
    apply_ets_corrections(project)
    assert project.ets_corrections.gewerk_by_address == {}
    assert tor.gewerk_code == "G"


def test_raum_korrektur_entfaellt_wenn_ets_nachgefuehrt():
    from knix_arranger.services.ets_corrections import check_rooms_after_import, set_device_room
    project, taster, carnotzet, halle = _project_with_rooms()
    set_device_room(project, taster, halle)
    assert check_rooms_after_import(project) == 1      # frische Topologie: Gerät schon in der Halle
    assert project.ets_corrections.room_by_device == {}
    # ETS noch nicht nachgeführt: Korrektur bleibt
    project, taster, carnotzet, halle = _project_with_rooms()
    set_device_room(project, taster, halle)
    taster.room_id = carnotzet.id                       # wie frisch aus der ETS
    assert check_rooms_after_import(project) == 0
    assert "1.2.6" in project.ets_corrections.room_by_device
