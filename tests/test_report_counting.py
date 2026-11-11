"""
Berichte-Durchsicht 2026-11-10 (Chalet): eine Zählregel für Busteilnehmer in
allen Berichten, Präsenzmelder/Binäreingänge als Sensor, MG-Variante aus den
Projekteigenschaften, Kopfdaten mit Rückfall auf Projekt und Kundenprofil.
"""
from __future__ import annotations

import fitz

from knix_arranger.models.building import Apartment, Areal, Building, Floor, Room, Wing
from knix_arranger.models.client_profile import ClientProfile
from knix_arranger.models.company_profile import CompanyProfile
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import (
    Area, Device, Line, Topology, count_bus_devices, is_bus_device,
)
from knix_arranger.services.documentation_service import DocumentationService
from knix_arranger.services.knxproj_import_service import KnxprojImportService
from knix_arranger.services.plant_check import run_check
from knix_arranger.services.project_service import correct_sensor_types
from knix_arranger.services.report_service import ReportService


def _project(imported: bool = True) -> KnxProject:
    room = Room(name="Wohnen", number="01")
    project = KnxProject(name="Chalet")
    project.areal = Areal(buildings=[Building(wings=[Wing(floors=[
        Floor(name="EG", apartments=[Apartment(rooms=[room])])])])])
    devices_1 = [
        Device(physical_address="1.1.-", device_type="power_supply",
               product="SV/S30.640.3.1 Power Supply,640mA,MDRC"),
        Device(physical_address="1.1.1", device_type="actor",
               product="SA/S8.16.1 Switch Actuator,8-fold", room_id=room.id),
        Device(physical_address="1.1.12", device_type="actor",
               product="BE/S8.20.1 Binary Input,8-fold,Cont.Sc.,MDRC", room_id=room.id),
        Device(physical_address="1.1.29", device_type="actor",
               product="compact office EIB", room_id=room.id),
        Device(physical_address="1.1.200", device_type="other", product="Z-Server",
               external=True),
    ]
    devices_2 = [
        Device(physical_address="1.2.-", device_type="power_supply",
               product="SV/S30.640.3.1 Power Supply,640mA,MDRC"),
        Device(physical_address="1.2.0", device_type="coupler", product="LK/S4.1 Line Coupler"),
        Device(physical_address="1.2.4", device_type="actor", product="pirios 360 KNX",
               room_id=room.id),
    ]
    project.topology = Topology(is_imported=imported, areas=[
        Area(area_number=1, lines=[Line(line_number=1, devices=devices_1),
                                   Line(line_number=2, devices=devices_2),
                                   Line(line_number=0, devices=[])]),
        Area(area_number=0, lines=[Line(line_number=0, devices=[])]),
    ])
    return project


def _devices(project):
    return [d for a in project.topology.areas for ln in a.lines for d in ln.devices]


def _pdf_text(path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def test_bus_count_rule():
    devices = _devices(_project())
    count = count_bus_devices(devices)
    # Koppler zählt, Spannungsversorgungen nicht, Z-Server getrennt
    assert (count.ets, count.external, count.total) == (5, 1, 6)
    assert count.label() == "5 + 1 nicht im ETS-Projekt"
    assert not is_bus_device(devices[0])
    assert count_bus_devices(devices[1:4]).label() == "3"


def test_sensors_corrected_on_load():
    project = _project()
    assert sorted(correct_sensor_types(project)) == ["1.1.12", "1.1.29", "1.2.4"]
    types = {d.physical_address: d.device_type for d in _devices(project)}
    assert types["1.1.1"] == "actor" and types["1.1.29"] == "sensor"
    assert correct_sensor_types(project) == []
    assert correct_sensor_types(_project(imported=False)) == []


def test_import_classifies_presence_and_binary_input_as_sensor():
    infer = KnxprojImportService._infer_device_type
    writable = [{"write_flag": True}] * 4
    assert infer("compact office EIB", writable) == "sensor"
    assert infer("BE/S4.20.1 Binary Input,4-fold,Contact Sc.,MDRC", writable) == "sensor"
    assert infer("SA/S8.16.1 Switch Actuator,8-fold", writable) == "actor"


def test_plant_check_and_protocol_use_same_count():
    project = _project()
    item = next(i for i in run_check(project, (0, 0)) if i.title == "Busteilnehmer")
    assert item.value.startswith("5 (") and "1 Koppler" in item.value
    scope = DocumentationService(project)._plant_scope()
    assert scope[0][:2] == ["Busteilnehmer", "5 + 1 nicht im ETS-Projekt"]


def test_summary_counts(tmp_path):
    project = _project()
    path = tmp_path / "summary.pdf"
    ReportService(project).generate_project_summary(str(path))
    text = _pdf_text(path)
    assert "Bereiche: 1" in text and "Linien: 2" in text
    assert "Busteilnehmer: 5 + 1 nicht im ETS-Projekt" in text
    assert "Spannungsversorgungen: 2 (keine Busteilnehmer)" in text


def test_ga_report_uses_project_variant(tmp_path):
    project = _project()
    project.config.mg_variant = "B"
    assert project.group_addresses.variant == "A"      # Import-Standard
    path = tmp_path / "ga.pdf"
    ReportService(project).generate_ga_report(str(path))
    assert "Variante: B" in _pdf_text(path)


def test_report_info_falls_back_to_project_and_client():
    project = _project()
    project.project_number = "2026-1"
    project.client_profile = ClientProfile(name="Familie Muster", object_address="Dorf 1")
    info = project.report_info()
    assert (info.project_name, info.project_number) == ("Chalet", "2026-1")
    assert (info.client_name, info.project_address) == ("Familie Muster", "Dorf 1")
    project.project_info.client_name = "Bauherr AG"
    assert project.report_info().client_name == "Bauherr AG"


def test_stored_protocol_gets_integrator_and_footer_title(tmp_path):
    from knix_arranger.models.documentation import AcceptanceProtocol
    project = _project()
    company = CompanyProfile(company_name="Muster AG", user_name="Max Muster",
                             role="Integrator")
    path = tmp_path / "abnahme.pdf"
    DocumentationService(project, company_profile=company).export_acceptance_protocol(
        str(path), AcceptanceProtocol())
    text = _pdf_text(path)
    assert "Max Muster, Muster AG (Integrator)" in text
    assert "Abnahmeprotokoll  ·  Max Muster" in text


# ── Umfang: Validierung und ETS-Arbeitsliste (Befunde 14, 15) ────────────────

def _ga_structure(*addresses):
    from knix_arranger.models.group_address import (
        GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
    )
    structure = GroupAddressStructure()
    groups: dict = {}
    for addr, name in addresses:
        h, m, s = (int(x) for x in addr.split("/"))
        hg = groups.setdefault(h, MainGroup(number=h, name=f"HG {h}"))
        mg = next((g for g in hg.middle_groups if g.number == m), None)
        if mg is None:
            mg = MiddleGroup(number=m, name=f"MG {m}")
            hg.middle_groups.append(mg)
        mg.group_addresses.append(GroupAddress(
            main_group=h, middle_group=m, sub_group=s, designation=name,
            datapoint_type="DPST-1-1"))
    structure.main_groups = list(groups.values())
    return structure


def test_gaps_one_issue_per_middle_group():
    from knix_arranger.services.validation_engine import ValidationEngine
    structure = _ga_structure(("1/0/0", "a"), ("1/0/3", "b"), ("1/0/5", "c"), ("1/0/9", "d"))
    gaps = [i for i in ValidationEngine().validate(structure) if i.rule_id == "FA-605"]
    assert len(gaps) == 1
    assert gaps[0].details["gaps"] == [(1, 2), (4, 4), (6, 8)]
    assert "1–2, 4, 6–8 frei (6)" in gaps[0].message


def test_command_feedback_same_name_is_no_duplicate():
    project = _project()
    project.group_addresses = _ga_structure(
        ("1/0/0", "L.UG.01.1_ea"), ("1/7/0", "L.UG.01.1_ea"),     # Befehl/Rückmeldung
        ("0/2/105", "WP Sollwert"), ("0/2/109", "WP Sollwert"))   # echt doppelt
    from knix_arranger.services.validation_engine import ValidationEngine
    dup = [i for i in ValidationEngine(project.gewerk_catalog).validate(
        project.group_addresses, project)
        if i.rule_id == "FA-625" and "mehrfach" in i.message]
    assert [i.message for i in dup] == ["GA-Bezeichnung mehrfach: 0/2/105, 0/2/109"]


def test_worklist_done_summarised(tmp_path, monkeypatch):
    from knix_arranger.services import ets_worklist as wl
    done = [wl.WorkItem(f"k{n}", wl.PRIO_CHECK, "FA-604", f"GA 1/1/{n}", "DPT ergänzen.",
                        status=wl.STATUS_DONE, done_on="22.10.2026", sort=(n,))
            for n in range(100)]
    done.append(wl.WorkItem("x", wl.PRIO_MUST, "FA-614", "1.1.51 KO 6", "trennen.",
                            status=wl.STATUS_DONE, done_on="30.10.2026"))
    monkeypatch.setattr(wl, "build_worklist", lambda project: wl.Worklist(
        items=[wl.WorkItem("o", wl.PRIO_FUNC, "FA-637", "GA 4/4/1", "Funktion anlegen.")],
        done=done))
    path = tmp_path / "wl.pdf"
    wl.export_pdf(_project(), str(path))
    text = _pdf_text(path)
    assert "1  ETS-Funktionen anlegen" in text            # fortlaufend, nicht «4»
    assert "Zuletzt erledigt (30.10.2026)" in text
    assert "GA 1/1/5" not in text and "FA-604 (100)" in text
    assert "übrigen 100 erledigten Aufgaben" in text
