"""
Gruppenbedienungen in importierten Projekten erkennen und als Funktion
übernehmen (FA-531).
"""
from __future__ import annotations

from knix_arranger.models.building import (
    Apartment, Building, Floor, GewerkAssignment, Room, Wing,
)
from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import (
    Area, CommunicationObject, Device, Line, Topology,
)
from knix_arranger.services.ets_function_plan import (
    check_plan, function_gas, member_links, restore_function_ids, sync_function_gas,
)
from knix_arranger.services.group_function_detection import adopt, suggest_group_functions


def _project(extra_gas=(), pir=False):
    """Küche OG 05 mit zwei Leuchten an einem Schaltaktor; 3/4/89 schaltet
    beide (Raum-Zentral), 3/7/x sind Rückmeldungen."""
    project = KnxProject(name="Import")
    lights = GewerkAssignment(gewerk_code="L", count=2)
    room = Room(number="05", name="Küche", gewerk_assignments=[lights])
    floor = Floor(name="Obergeschoss", short_code="OG", main_group_number=3,
                  apartments=[Apartment(name="OG", rooms=[room])])
    project.areal.buildings.append(Building(wings=[Wing(floors=[floor])]))

    def ga(mg, sub, name, dpt="Schalten", assignment=lights):
        return GroupAddress(main_group=3, middle_group=mg, sub_group=sub, designation=name,
                            datapoint_type=dpt, assignment_id=assignment.id if assignment else "")
    group_name = "L.OG.05.01_ea von pir" if pir else "Raum5_Licht Zentral"
    gas = [ga(0, 70, "L.OG.05.01_ea  ( Decke )"), ga(0, 75, "L.OG.05.02_ea  ( Insel )"),
           ga(4, 89, group_name, assignment=None),
           ga(7, 70, "L.OG.05.01_ea  ( Decke )"), ga(7, 75, "L.OG.05.02_ea  ( Insel )"),
           *extra_gas]
    mgs: dict[int, MiddleGroup] = {}
    for g in gas:
        mgs.setdefault(g.middle_group, MiddleGroup(number=g.middle_group)).group_addresses.append(g)
    project.group_addresses = GroupAddressStructure(main_groups=[MainGroup(
        number=3, name="OG", middle_groups=list(mgs.values()))])

    def co(n, name, flags, connected):
        return CommunicationObject(object_number=n, name=name, flags=flags,
                                   connected_gas=connected)
    actor = Device(device_type="actor", product="Schaltaktor 2-fach", physical_address="1.1.1",
                   communication_objects=[
                       co(0, "Kanal A Schalten", "K-S---", ["3/0/70", "3/4/89"]),
                       co(1, "Kanal A Status", "KL-Ü--", ["3/7/70"]),
                       co(2, "Kanal B Schalten", "K-S---", ["3/0/75", "3/4/89"]),
                       co(3, "Kanal B Status", "KL-Ü--", ["3/7/75"])])
    project.topology = Topology(is_imported=True, areas=[Area(area_number=1, lines=[
        Line(line_number=1, name="Linie 1", devices=[actor])])])
    return project, room, lights


def test_group_ga_on_two_channels_is_suggested():
    project, room, lights = _project()
    [suggestion] = suggest_group_functions(project)
    assert suggestion.name == "Licht Zentral"
    assert suggestion.function_type == "FT-1"
    assert suggestion.room is room
    assert [(a.id, n) for _r, a, n in suggestion.members] == [(lights.id, 1), (lights.id, 2)]
    assert {p: g.address for p, g in suggestion.gas.items()} == {"E/A": "3/4/89"}


def test_motion_detector_and_planned_projects_are_skipped():
    project, _room, _lights = _project(pir=True)
    assert suggest_group_functions(project) == []
    project, _room, _lights = _project()
    project.topology.is_imported = False
    assert suggest_group_functions(project) == []


def test_adopted_function_keeps_ets_ga_and_survives_reimport():
    project, _room, _lights = _project()
    count = len(project.group_addresses.all_addresses())
    function = adopt(project, suggest_group_functions(project)[0], "Licht Küche")
    assert sync_function_gas(project) == []
    gas = [g for g in function_gas(project.group_addresses) if g.function_id == function.id]
    assert [(g.address, g.designation, g.ets_known) for g in gas] == [
        ("3/4/89", "Raum5_Licht Zentral", True)]
    assert len(project.group_addresses.all_addresses()) == count   # keine neuen GAs
    links = {m.element_number: own.address for m, _f, own in member_links(project, function)}
    assert links == {1: "3/0/70", 2: "3/0/75"}
    assert not [i for i in check_plan(project) if "Küche" in i.message]
    assert suggest_group_functions(project) == []                  # schon übernommen

    # Re-Import: frische GAs ohne Funktion -> über Adresse + Bezeichnung zurück
    restored = KnxProject.from_dict(project.to_dict())
    for g in restored.group_addresses.all_addresses():
        g.function_id, g.ets_known = "", False
    assert restore_function_ids(restored) == 1
    assert [g.address for g in function_gas(restored.group_addresses)] == ["3/4/89"]


def test_deleting_adopted_function_keeps_its_ga():
    project, _room, _lights = _project()
    function = adopt(project, suggest_group_functions(project)[0])
    sync_function_gas(project)
    project.functions.remove(function)
    sync_function_gas(project)
    ga = next(g for g in project.group_addresses.all_addresses() if g.address == "3/4/89")
    assert (ga.function_id, ga.ets_known) == ("", False)


def test_room_wide_numbering_is_mapped_to_elements():
    """Richtlinie 10.3: Nummer je Raum über alle Gewerke fortgeführt (Chalet:
    Küche LD 01, L 02–03). KNiX zählt je Gewerk -- 02/03 werden L 1/2."""
    from knix_arranger.services.ets_function_plan import (
        element_labels_by_address, room_wide_renumbering,
    )
    extra = [GroupAddress(main_group=3, middle_group=0, sub_group=60,
                          designation="LD.OG.05.01_ea  ( Spots )")]
    project, room, lights = _project(extra_gas=extra)
    for ga in project.group_addresses.all_addresses():
        ga.designation = ga.designation.replace("L.OG.05.01", "L.OG.05.02").replace(
            "L.OG.05.02_ea  ( Insel )", "L.OG.05.03_ea  ( Insel )") \
            if ga.designation.startswith("L.") else ga.designation
    assert room_wide_renumbering(project) == {lights.id: {2: 1, 3: 2}}
    labels = element_labels_by_address(project)
    assert labels["3/0/70"].startswith("L_OG_05_01") and labels["3/0/75"].startswith("L_OG_05_02")
    [suggestion] = suggest_group_functions(project)
    assert suggestion.missing_channels == 0
    assert [n for _r, _a, n in suggestion.members] == [1, 2]


def test_adopted_function_ga_once_per_channel_in_belegungsplan():
    """Die übernommene Funktions-GA hängt in der ETS schon am KO: der
    Belegungsplan (Topologie, Aktorenbericht) zeigt sie je Kanal einmal,
    nicht zusätzlich über das Mitglied (Chalet 1.1.6, 3/4/89 doppelt)."""
    from knix_arranger.services.belegungsplan_service import BelegungsplanService
    project, _room, _lights = _project()
    adopt(project, suggest_group_functions(project)[0], "Licht Küche")
    rows = [(r.channel_number, r.function_name) for r in
            BelegungsplanService().generate(project).actor_rows if r.ga_address == "3/4/89"]
    assert sorted(rows) == sorted(set(rows))
    assert len(rows) == 2       # Kanal A und Kanal B


def test_jalousie_group_recognizes_slat_position_by_name():
    """Chalet Studio: «J.Studio Position» und «J.Studio Lamellenstellung»
    haben beide 5.001 -- die zweite ist die Lamellenposition, nicht verloren."""
    from knix_arranger.services.group_function_detection import _point
    height = GroupAddress(designation="J.Studio Position", datapoint_type="DPST-5-1")
    slat = GroupAddress(designation="J.Studio Lamellenstellung", datapoint_type="DPST-5-1")
    assert _point(height, "FT-7") == "POSITION HOEHE"
    assert _point(slat, "FT-7") == "POSITION LAMELLEN"


def test_adopted_jalousie_plans_no_further_points():
    """FA-531: keine eigenen GAs (Chalet: 2/1/248 Lamellen, 2/1/249 Sperren
    neben den bestehenden) -- auch nicht nach Speichern und Laden."""
    from knix_arranger.models.ets_function import KnixFunction
    from knix_arranger.services.ets_function_plan import planned_points
    from knix_arranger.services.group_function_detection import GroupSuggestion
    project, room, lights = _project()
    gas = {"AUF/AB": GroupAddress(main_group=2, middle_group=1, sub_group=250,
                                  designation="J.Studio Bewegen")}
    function = adopt(project, GroupSuggestion(
        name="Balkon", function_type="FT-7", room=room,
        members=[(room, lights, 1), (room, lights, 2)], gas=gas))
    assert planned_points(function) == []
    assert planned_points(KnixFunction.from_dict(function.to_dict())) == []
    # Im Dialog alle Punkte wieder gewählt: bleibt nach dem Laden so
    function.omitted = []
    again = KnixFunction.from_dict(function.to_dict())
    assert again.omitted == [] and len(planned_points(again)) == 4


def test_adopted_jalousie_keeps_shading_ga_as_own_point():
    """Chalet 2/1/254 «J.Studio Beschattung» (1.023, Elemente «_beschattung»
    1.022): eigener Punkt mit der GA aus der ETS, keine neue GA, und über
    die Element-GAs auf den Aktorkanälen erkannt."""
    from knix_arranger.models.ets_function import KnixFunction
    from knix_arranger.services.ets_function_plan import function_points, planned_points
    from knix_arranger.services.group_function_detection import GroupSuggestion, _point
    shading = GroupAddress(main_group=3, middle_group=1, sub_group=254,
                           designation="J.Studio Beschattung", datapoint_type="DPST-1-23")
    assert _point(shading, "FT-7") == "BESCHATTUNG"
    assert _point(shading, "FT-1") == ""
    project, room, lights = _project()
    function = adopt(project, GroupSuggestion(
        name="Balkon", function_type="FT-7", room=room,
        members=[(room, lights, 1), (room, lights, 2)], gas={"BESCHATTUNG": shading}))
    assert [(c.function, c.dpt) for c in function.custom_points] == [
        ("BESCHATTUNG", "DPST-1-23")]
    assert [p.function for p in function_points(function)] == ["BESCHATTUNG"]
    assert planned_points(function) == []
    assert planned_points(KnixFunction.from_dict(function.to_dict())) == []
    assert (shading.function_id, shading.function_name) == (function.id, "BESCHATTUNG")


def test_imported_shading_suffix_is_element_function():
    from knix_arranger.services.ets_function_plan import _element_function
    ga = GroupAddress(designation="J.EG.06.3_beschattung", datapoint_type="DPST-1-22")
    assert _element_function(ga) == "BESCHATTUNG"


def _griesser_co(n, name, function, dpt, connected, flags="K-S---"):
    return CommunicationObject(object_number=n, name=name, object_function=function,
                               flags=flags, data_type=dpt, connected_gas=connected)


def test_co_function_reads_manufacturer_text():
    """FA-531a: die Bedeutung kommt vom KO (Griesser JAX-9, Chalet 1.1.11)."""
    from knix_arranger.services.actor_channels import co_function
    from knix_arranger.services.ets_function_plan import _KO_CANDIDATES
    cases = [
        ("Bedienung Storen (M1), Endlage", "Auf / Ab", "DPST-1-8", "AUF/AB"),
        ("Bedienung Storen (M1), Wippen", "Schritt / Stopp", "DPST-1-7", "STOPP"),
        ("Bedienung Storen (M1), Höhe", "Höhe 0…255", "DPST-5-1", "POSITION HOEHE"),
        ("Bedienung Storen (M1), Winkel", "Winkel 0…255", "DPST-5-1", "POSITION LAMELLEN"),
        ("Bedienung Storen (M1), Beschattung", "Auf / Beschattung", "DPST-1-22",
         "BESCHATTUNG"),
        # «Ein / Aus» und «Alarm» gleich stark: unklar, aber nie E/A
        ("Sicherheit 1 (M1), Alarm", "Ein / Aus", "DPST-1-5", ""),
    ]
    for name, function, dpt, expected in cases:
        assert co_function(_griesser_co(0, name, function, dpt, []),
                           _KO_CANDIDATES) == expected, name
    feedback = _griesser_co(10, "Sonnenschutz (M1), Rückmeldung Winkel", "Winkel 0…255",
                            "DPST-5-1", [], flags="KL-Ü--")
    assert co_function(feedback, _KO_CANDIDATES) == ""


def test_ko_wins_over_fantasy_name_and_suffix():
    """Der Integrator nennt die Winkel-GA «Stellung» bzw. «_hoehe»: das KO
    des Aktors entscheidet, Endung und DPT nur ohne KO."""
    from knix_arranger.services.ets_function_plan import _element_function, ko_functions
    from knix_arranger.services.group_function_detection import _point
    project, _room, _lights = _project()
    project.topology.areas[0].lines[0].devices.append(Device(
        device_type="actor", physical_address="1.1.11", communication_objects=[
            _griesser_co(6, "Bedienung Storen (M1), Winkel", "Winkel 0…255", "DPST-5-1",
                         ["2/1/13", "2/1/253"]),
            _griesser_co(28, "Bedienung Storen (M2), Winkel", "Winkel 0…255", "DPST-5-1",
                         ["2/1/253"])]))
    by_ko = ko_functions(project)
    assert by_ko["2/1/253"] == by_ko["2/1/13"] == "POSITION LAMELLEN"
    assert by_ko["3/0/70"] == "E/A"
    fantasy = GroupAddress(main_group=2, middle_group=1, sub_group=253,
                           designation="J.Studio Stellung", datapoint_type="DPST-5-1")
    assert _point(fantasy, "FT-7") == "POSITION HOEHE"            # ohne KO: DPT
    assert _point(fantasy, "FT-7", by_ko) == "POSITION LAMELLEN"
    wrong_suffix = GroupAddress(main_group=2, middle_group=1, sub_group=13,
                                designation="J.EG.06.3_hoehe")
    assert _element_function(wrong_suffix) == "POSITION HOEHE"
    assert _element_function(wrong_suffix, by_ko) == "POSITION LAMELLEN"
