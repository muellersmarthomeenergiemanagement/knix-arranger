"""Gemeinsamer Import-Ablauf (ImportPipeline) für alle ETS-Import-Wege."""
from knix_arranger.models.building import (
    Apartment, Areal, Bedienelement, Building, Floor, Room, Wing,
)
from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.address_generator import insert_ga
from knix_arranger.services.import_pipeline import (
    GA_REPORT, ImportPipeline, enrich_ga_metadata,
)


def _project(button_ga="3/4/20"):
    room = Room(number="02", name="Bibliothek")
    areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="OG", short_code="OG", apartments=[Apartment(rooms=[room])])])])])
    taster = Device(
        physical_address="1.1.40", device_type="sensor", room_id=room.id,
        product="EDIZIOdue colore 1-8fach Taster RGB Temp",
        communication_objects=[CommunicationObject(
            object_number=0, name="Taste 1, links", connected_gas=[button_ga])],
    )
    project = KnxProject(name="Test")
    project.topology = Topology(areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[taster])])])
    project.areal = areal
    insert_ga(project.group_addresses, GroupAddress(
        main_group=3, middle_group=4, sub_group=20,
        designation="Raum2_Szene High  ( Bibliothek )"))
    return project, room


def test_derive_assigns_buttons_from_objects():
    project, room = _project()
    pipeline = ImportPipeline(project)

    pipeline.derive()

    [be] = room.bedienelemente
    assert be.participant_number == "1.1.40"
    assert not be.is_auto
    assert be.function_assignments[0].function_ga.startswith("3/4/20")
    assert pipeline.problems == []


def test_run_keeps_fresh_assignment_against_guessed_old_state():
    """Ablauf wie nach "Projekt neu aus ETS aufbauen": der alte Stand hat
    eine geratene Belegung, der Abgleich darf sie nicht zurückholen."""
    old, old_room = _project()
    old_room.bedienelemente = [Bedienelement(
        element_type="Tastereinheit", participant_number="1.1.40", is_auto=True)]
    project, room = _project()
    room.id = old_room.id
    project.topology.areas[0].lines[0].devices[0].room_id = room.id

    diff = ImportPipeline(project).run(old, "Gruppenadressen.xlsx")

    [be] = room.bedienelemente
    assert be.function_assignments[0].function_ga.startswith("3/4/20")
    assert diff.rooms_matched == 1
    assert project.changelog[-1].message.startswith("Gruppenadressen.xlsx")


def test_failed_step_is_reported_and_import_continues():
    project, room = _project()
    pipeline = ImportPipeline(project)

    def broken(*_args, **_kwargs):
        raise ValueError("kaputt")

    pipeline.importer.backfill_function_assignments = broken
    pipeline.derive()

    assert pipeline.problems == ["Tastenbelegung aus den Objekten: kaputt"]
    assert room.bedienelemente  # Bedienelemente-Schritt lief trotzdem


def test_sources_belong_to_project_and_must_exist(tmp_path):
    project, _ = _project()
    report = tmp_path / "Gruppenadressen.xlsx"
    pipeline = ImportPipeline(project)
    pipeline.set_source(GA_REPORT, str(report))

    assert pipeline.source(GA_REPORT) == ""      # Datei fehlt
    report.write_bytes(b"x")
    assert pipeline.source(GA_REPORT) == str(report)
    assert KnxProject.from_dict(project.to_dict()).import_files == {GA_REPORT: str(report)}


def test_enrich_ga_metadata_fills_only_empty_fields():
    project, _ = _project()
    insert_ga(project.group_addresses, GroupAddress(
        main_group=1, middle_group=0, sub_group=5, designation="LDA.OG.02.01_ea",
        gewerk_code="L"))

    enrich_ga_metadata(project)

    by_addr = {ga.address: ga for ga in project.group_addresses.all_addresses()}
    assert by_addr["1/0/5"].gewerk_code == "L"
    assert by_addr["1/0/5"].room_number == "OG.02"
    assert by_addr["3/4/20"].room_number == "Bibliothek"
