"""
Datenpunkttyp je Kommunikationsobjekt: Übersetzung der ETS-Namen, DPT aus
.knxproj und Report, Laden älterer Projekte, Prüfung des Untertyps (FA-638)
und Vorzug des Untertyps bei KO-Vorschlägen.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from knix_arranger.models.group_address import GroupAddress
from knix_arranger.models.topology import CommunicationObject, Device, normalize_dpt
from knix_arranger.services.actor_channels import suggest_co
from knix_arranger.services.knxproj_import_service import KnxprojImportService
from knix_arranger.services.ko_plausibility import subtype_problem
from knix_arranger.services.ko_size import ko_dpt_text, ko_label
from knix_arranger.services.xlsx_import_service import XlsxImportService
from knix_arranger.utils.ets_dpt_names import dpt_text, ets_dpt_id


def test_report_names_with_main_type_and_repeats():
    assert ets_dpt_id("1-Bit, Freigeben") == "DPST-1-3"
    assert ets_dpt_id("Schalten, Schalten") == "DPST-1-1"
    assert ets_dpt_id("3-Bit gesteuert, Dimmer Schritt") == "DPST-3-7"
    assert ets_dpt_id("8-Bit vorzeichenlos, Zählimpulse (0..255)") == "DPST-5-10"
    assert ets_dpt_id("Bit-kombinierte Info Ein/Aus") == "DPST-27-1"


def test_ambiguous_name_decided_by_size():
    assert ets_dpt_id("Temperatur (°C)") == "DPST-9-1"
    assert ets_dpt_id("Temperatur (°C)", 16) == "DPST-9-1"
    assert ets_dpt_id("Temperatur (°C)", 32) == "DPST-14-68"


def test_several_ids_take_the_specific_one():
    assert ets_dpt_id("DPT-9 DPST-9-1") == "DPST-9-1"
    assert ets_dpt_id("DPST-1-1 DPST-1-1") == "DPST-1-1"
    assert dpt_text("DPST-1-8") == "1.008 Auf/Ab"
    assert dpt_text("DPT-1") == "1.x 1-Bit"


def test_report_ko_column():
    assert XlsxImportService._ko_datapoint("Auf/Ab") == {"data_type": "DPST-1-8", "object_size": ""}
    assert XlsxImportService._ko_datapoint("1 bit") == {"data_type": "DPT-1", "object_size": "1 bit"}
    assert XlsxImportService._ko_datapoint("2 bytes") == {"data_type": "2 bytes",
                                                         "object_size": "2 bytes"}


def test_old_projects_translated_on_load():
    co = CommunicationObject.from_dict({"object_number": 1, "data_type": "Schalten"})
    assert co.data_type == "DPST-1-1"
    assert normalize_dpt("1 Bit") == "DPT-1"
    assert normalize_dpt("2 Bytes", "2 Bytes") == "2 Bytes"


def test_knxproj_dpt_from_variant_and_instance():
    svc = KnxprojImportService()
    attrs = {"Number": "3", "Text": "Kanal A", "ObjectSize": "1 Bit",
             "DatapointType": "DPT-1 DPST-1-1"}
    assert svc._make_co(attrs, []).data_type == "DPST-1-1"
    assert svc._make_co({"Number": "4", "ObjectSize": "1 Bit"}, []).data_type == "DPT-1"
    assert svc._make_co({"Number": "5", "ObjectSize": "2 Bytes"}, []).data_type == "2 Bytes"
    assert "DatapointType" in svc._INSTANCE_OVERRIDES


def test_display_with_dpt_or_size():
    co = CommunicationObject(object_number=9, name="Kanal C1", object_function="Status",
                             flags="KL-Ü--", data_type="DPST-1-11", object_size="1 Bit")
    assert ko_dpt_text(co) == "1.011 Status"
    assert ko_label(co) == "9: Kanal C1 – Status (1.011 Status, sendet)"
    co.data_type = "2 Bytes"
    co.object_size = "2 Bytes"
    assert ko_dpt_text(co) == "2 Byte"


def test_subtype_checked_only_where_it_changes_the_value():
    # 5.001 Prozent an 5.010 Zählimpulse (P19, Feller «Befehl An_Abwesend=1»)
    assert subtype_problem(["DPST-5-1"], "DPST-5-10") == \
        "KO 5.001 Prozent (0..100%), GA 5.010 Zählimpulse (0..255)"
    # DPT 1: Herstellereigenheiten wie Beschattung 1.022 an 1.023 bleiben still
    assert subtype_problem(["DPST-1-22"], "DPST-1-23") == ""
    # passende Variante derselben Nummer, fehlender Untertyp, anderer Haupttyp
    assert subtype_problem(["DPST-5-1", "DPST-5-10"], "DPST-5-10") == ""
    assert subtype_problem(["DPT-5"], "DPST-5-10") == ""
    assert subtype_problem(["DPST-1-1"], "DPST-5-10") == ""


def test_validation_reports_value_subtype(monkeypatch):
    from knix_arranger.models.project import KnxProject
    from knix_arranger.models.topology import Area, Line
    from knix_arranger.services.validation_engine import ValidationEngine
    project = KnxProject(name="t")
    device = Device(physical_address="1.1.13", device_type="sensor")
    device.communication_objects = [CommunicationObject(
        object_number=12, name="Taste 3, links", object_function="senden, Wert",
        flags="K-SÜ--", data_type="DPST-5-1", object_size="1 Byte", connected_gas=["0/4/1"])]
    line = Line(line_number=1)
    line.devices.append(device)
    area = Area(area_number=1)
    area.lines.append(line)
    project.topology.areas.append(area)
    ga = GroupAddress(main_group=0, middle_group=4, sub_group=1, designation="Befehl An_Abwesend=1",
                      datapoint_type="DPST-5-10")
    monkeypatch.setattr(project.group_addresses, "all_addresses", lambda: [ga])
    issues = ValidationEngine._check_dpt_subtypes(project)
    assert [(i.rule_id, i.address) for i in issues] == [("FA-638", "0/4/1")]
    assert "5.001 Prozent" in issues[0].message


def test_suggestion_prefers_same_subtype():
    cos = [CommunicationObject(object_number=1, name="Kanal A", object_function="Status Schalten",
                               flags="KL-Ü--", data_type="DPST-1-1"),
           CommunicationObject(object_number=2, name="Kanal A", object_function="Status Schalten",
                               flags="KL-Ü--", data_type="DPST-1-11")]
    assert suggest_co(cos, "RM", dpt="DPST-1-11").object_number == 2
    assert suggest_co(cos, "RM", dpt="DPST-1-1").object_number == 1
