"""GA-Kommentar (ETS) importieren und als Szenennamen verwenden (Chalet 0/4/1)."""
import pytest
from knix_arranger.models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.scene import Scene
from knix_arranger.services.scene_value_linking import (
    link_scene_names, scene_names_from_comment,
)
from knix_arranger.services.xlsx_import_service import XlsxImportService
from knix_arranger.utils.rtf import rtf_to_text

# Kommentar von 0/4/1 aus der knxproj (gekürzt)
ETS_RTF = (r"{\rtf1\ansi\ansicpg1252\uc1\htmautsp\deff2{\fonttbl{\f0\fcharset0 Times New Roman;}"
           r"{\f2\fcharset0 Segoe UI;}}\loch\hich\dbch\pard\plain\ltrpar\itap0{\lang1033\fs18\f2"
           r"\cf0 \cf0\ql{\f2 {\lang2055\ltrch #1: Anwesend}\li0\ri0\sa0\sb0\fi0\ql\par}" "\r\n"
           r"{\f2 {\lang2055\ltrch #2: Abwesend}\li0\ri0\sa0\sb0\fi0\ql\par}" "\r\n"
           r"{\f2 {\lang2055\ltrch #3: Ferien}\li0\ri0\sa0\sb0\fi0\ql\par}" "\r\n}\r\n}")


def _structure(*gas):
    return GroupAddressStructure(main_groups=[MainGroup(number=0, middle_groups=[
        MiddleGroup(number=4, group_addresses=list(gas))])])


def test_ets_kommentar_rtf_als_klartext():
    text = rtf_to_text(ETS_RTF).strip()
    assert scene_names_from_comment(text) == {1: "Anwesend", 2: "Abwesend", 3: "Ferien"}


def test_szenennamen_formate():
    assert scene_names_from_comment("#1: Anwesend\n2 = Abwesend\n#3 - Ferien\nNotiz") == {
        1: "Anwesend", 2: "Abwesend", 3: "Ferien"}
    assert scene_names_from_comment("#0: gibt es nicht\n#65: zu gross") == {}


def test_szenen_nach_kommentar_benannt_und_ergaenzt():
    ga = GroupAddress(main_group=0, middle_group=4, sub_group=1,
                      designation="Anwesendheit Chalet", comment="#1: Anwesend\n#2: Abwesend")
    project = KnxProject(name="Chalet")
    project.group_addresses = _structure(ga)
    channel = Scene(name="Anwesendheit Chalet", scene_number=0, scope="central",
                    is_detected=True, source_ga_addresses=["0/4/1"])
    own = Scene(name="Mein Name", scene_number=2, scope="central",
                is_detected=True, source_ga_addresses=["0/4/1"])
    auto = Scene(name="Anwesendheit Chalet – Szene 1", scene_number=1, scope="central",
                 is_detected=True, source_ga_addresses=["0/4/1"])
    project.scenes = [channel, auto, own]

    assert link_scene_names(project) == 1
    assert auto.name == "Anwesend"
    assert own.name == "Mein Name"                     # selbst vergebener Name bleibt
    assert link_scene_names(project) == 0              # idempotent


def test_szene_aus_kommentar_angelegt():
    ga = GroupAddress(main_group=0, middle_group=4, sub_group=1, comment="#3: Ferien")
    project = KnxProject()
    project.group_addresses = _structure(ga)
    project.scenes = [Scene(name="Kanal", is_detected=True, source_ga_addresses=["0/4/1"])]
    link_scene_names(project)
    assert [(s.scene_number, s.name) for s in project.scenes[1:]] == [(3, "Ferien")]


def test_reimport_behaelt_dpt_nummer_und_kommentar():
    old = _structure(GroupAddress(main_group=0, middle_group=4, sub_group=1,
                                  datapoint_type="DPST-18-1", comment="#1: Anwesend"))
    new_ga = GroupAddress(main_group=0, middle_group=4, sub_group=1,
                          datapoint_type="Szenensteuerung")
    other = GroupAddress(main_group=0, middle_group=4, sub_group=2, datapoint_type="Schalten")
    new = _structure(new_ga, other)
    assert XlsxImportService.keep_known_ga_details(old, new) == 1
    assert new_ga.datapoint_type == "DPST-18-1" and new_ga.comment == "#1: Anwesend"
    assert other.datapoint_type == "Schalten"           # ohne bisherigen Stand unverändert


def test_ga_report_liest_kommentarzeile(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=5, column=1, value="Gruppenadressen")
    header = {5: "Adresse", 10: "Name", 24: "Datentyp", 28: "Zentral"}
    for col, text in header.items():
        ws.cell(row=10, column=col, value=text)
    ws.cell(row=12, column=5, value="0")
    ws.cell(row=12, column=10, value="Zentral")
    ws.cell(row=13, column=5, value="0/4")
    ws.cell(row=13, column=10, value="Szenen")
    ws.cell(row=14, column=5, value="0/4/1")
    ws.cell(row=14, column=10, value="Anwesendheit   Chalet")
    ws.cell(row=14, column=24, value="Szenensteuerung")
    ws.cell(row=17, column=6, value="#1: Anwesend\n#2: Abwesend\n")   # Kommentarzeile
    ws.cell(row=18, column=5, value="Addr")                           # Geräte-Kopf
    ws.cell(row=18, column=8, value="Produkt")
    ws.cell(row=19, column=6, value="Ausgang A – nicht der GA-Kommentar")  # nach Geräte-Kopf
    ws.cell(row=20, column=5, value="0/4/2")
    ws.cell(row=20, column=10, value="Ohne Kommentar")
    path = tmp_path / "ga.xlsx"
    wb.save(path)

    structure = XlsxImportService().import_ga_report(str(path))
    gas = {g.address: g for g in structure.all_addresses()}
    assert gas["0/4/1"].comment == "#1: Anwesend\n#2: Abwesend"
    assert gas["0/4/2"].comment == ""


def test_szenenreport_erkennt_dpt_text(tmp_path):
    fitz = pytest.importorskip("fitz")
    from knix_arranger.services.report_service import ReportService
    ga = GroupAddress(main_group=0, middle_group=4, sub_group=1,
                      designation="Anwesendheit Chalet", datapoint_type="Szenensteuerung")
    project = KnxProject(name="Chalet")
    project.group_addresses = _structure(ga)
    project.scenes = [Scene(name="Anwesend", scene_number=1, is_detected=True,
                            detection_kind="dpt", source_ga_addresses=["0/4/1"])]
    path = str(tmp_path / "szenen.pdf")
    ReportService(project).generate_szenen_report(path)
    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    assert "1 Anwesend" in text
    assert "für Szenen wird 17.001" not in text
