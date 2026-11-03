"""
Busanalyse (FA-640), Anlagen-Check (FA-641) und Arbeitsweg Bestand.
Telegramme aus dem Chalet-Mitschnitt (Busmonitor über ise KNX Remote Access).
"""
from __future__ import annotations
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from knix_arranger.models.group_address import (
    GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup,
)
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.bus_monitor import BusLogError, analyze, decode, parse_log, summarize

# Z-Server 1.1.200 -> 0/5/13 Write 0, Quittung, Revox 1.2.7 -> 12/1/1 Write 1 mit
# drei Wiederholungen (Steuerfeld 9C), Salva 1.1.25 -> 1/2/1 2 Byte
_LOG = """<?xml version="1.0" encoding="utf-8"?>
<CommunicationLog xmlns="http://knx.org/xml/telegrams/01">
  <RecordStart Timestamp="2026-11-03T20:14:31.0864569Z" ConnectionName="SDA - ise KNX Remote Access" Mode="Busmonitor" />
  <Telegram Timestamp="2026-11-03T20:14:50.0125676Z" Service="L_Busmon.ind" RawData="2B0903010506044BB27923BC11C8050DE10080F3" />
  <Telegram Timestamp="2026-11-03T20:14:50.2377704Z" Service="L_Busmon.ind" RawData="2B0903010206044BB90EFBCC" />
  <Telegram Timestamp="2026-11-03T20:16:35.4550424Z" Service="L_Busmon.ind" RawData="2B09030105060455222D1FBC12076101D1008166" />
  <Telegram Timestamp="2026-11-03T20:16:35.4754814Z" Service="L_Busmon.ind" RawData="2B0903010606045522928B9C12076101D1008146" />
  <Telegram Timestamp="2026-11-03T20:16:35.4960561Z" Service="L_Busmon.ind" RawData="2B0903010706045522F7F69C12076101D1008146" />
  <Telegram Timestamp="2026-11-03T20:16:35.507237Z" Service="L_Busmon.ind" RawData="2B09030100060455235D629C12076101D1008146" />
  <Telegram Timestamp="2026-11-03T20:17:00.4952759Z" Service="L_Busmon.ind" RawData="2B0903010106045DB67A1EBC1119010AE300800C97B8" />
  <RecordStop Timestamp="2026-11-03T20:17:20.1999403Z" />
</CommunicationLog>
"""


def _log(tmp_path) -> str:
    path = tmp_path / "Telegramme.xml"
    path.write_text(_LOG, encoding="utf-8")
    return str(path)


def _project():
    project = KnxProject(name="Chalet")
    zserver = Device(physical_address="1.1.200", product="Z-Server", device_type="other",
                     external=True)
    blind = Device(physical_address="1.1.4", device_type="actor", product="Jalousieaktor 8-fach",
                   communication_objects=[CommunicationObject(
                       name="Kanal A Windalarm", flags="KS----", connected_gas=["0/5/13"])])
    revox = Device(physical_address="1.2.7", device_type="gateway", product="Revox",
                   communication_objects=[CommunicationObject(
                       name="Raum", flags="K--Ü--", connected_gas=["12/1/1"])])
    project.topology = Topology(is_imported=True, areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=[zserver, blind]), Line(line_number=2, devices=[revox])])])
    gas = [GroupAddress(main_group=0, middle_group=5, sub_group=13,
                        designation="M.Windsicherheit_ea", datapoint_type="DPST-1-1"),
           GroupAddress(main_group=12, middle_group=1, sub_group=1,
                        designation="MM.UG.02.01_wert Raum", datapoint_type="DPST-1-1")]
    project.group_addresses = GroupAddressStructure(main_groups=[
        MainGroup(number=g.main_group, middle_groups=[MiddleGroup(
            number=g.middle_group, group_addresses=[g])]) for g in gas])
    return project


def test_decode_busmonitor_frame():
    t = decode("2B0903010506044BB27923BC11C8050DE10080F3", None)
    assert (t.src, t.dst, t.service, t.payload, t.repeat) == ("1.1.200", "0/5/13", "Write",
                                                             "0", False)
    assert decode("2B0903010206044BB90EFBCC", None) == "ack"
    repeated = decode("2B0903010606045522928B9C12076101D1008146", None)
    assert repeated.repeat and repeated.dst == "12/1/1"


def test_decode_group_monitor_frame():
    # L_Data.ind: Steuerfeld 1/2, Quelle 1.1.25, Ziel 1/2/1, 2 Byte 0C97
    t = decode("2900BCE011190A010300800C97", None)
    assert (t.src, t.dst, t.service, t.payload, t.repeat) == ("1.1.25", "1/2/1", "Write",
                                                             "0C97", False)


def test_summary_counts_repeats_and_peak(tmp_path):
    summary = summarize(parse_log(_log(tmp_path)))
    assert (summary["telegrams"], summary["repeats"], summary["acks"]) == (3, 3, 1)
    assert summary["peak_per_second"] == 4
    pairs = {(p[0], p[1]): p for p in summary["pairs"]}
    assert pairs[("1.2.7", "12/1/1")][3:5] == [1, 3]


def test_not_a_log(tmp_path):
    path = tmp_path / "x.xml"
    path.write_text("<Project/>", encoding="utf-8")
    with pytest.raises(BusLogError):
        parse_log(str(path))


def test_analysis_against_project(tmp_path):
    project = _project()
    a = analyze(project, summarize(parse_log(_log(tmp_path))))
    assert [s.address for s in a.unknown] == ["1.1.25"]            # Salva fehlt im Projekt
    assert a.external_gas == {"1.1.200": ["0/5/13"]}
    assert [p.dst for p in a.unlinked] == ["0/5/13"]               # Z-Server nicht verknüpft
    assert a.repeated[0].dst == "12/1/1" and a.repeated[0].receivers == []
    titles = [f.title for f in a.findings]
    assert "1 Absender nicht im Projekt" in titles
    assert any(t.startswith("3 Wiederholungen") for t in titles)


def test_line_plan_uses_observed_sends(tmp_path):
    from knix_arranger.models.line_plan import LinePlan
    from knix_arranger.services.line_plan_service import evaluate
    project = _project()
    project.bus_recordings.append(summarize(parse_log(_log(tmp_path))))
    (check,) = evaluate(project, LinePlan(source="1.1", main_line=True)).externals
    assert check.observed == ["0/5/13"] and check.confirmed == []   # 0/5/13 in Linie 1.1


def test_plant_check_and_round_trip(tmp_path):
    from knix_arranger.services.plant_check import run_check
    project = _project()
    project.bus_recordings.append(summarize(parse_log(_log(tmp_path))))
    loaded = KnxProject.from_dict(project.to_dict())
    assert loaded.bus_recordings[0]["file"] == "Telegramme.xml"
    items = {(i.area, i.title): i for i in run_check(loaded, (0, 0))}
    assert items[("Topologie", "Geräte ausserhalb des ETS-Projekts")].value == "1.1.200 Z-Server"
    assert items[("Busanalyse", "Mitschnitt 2026-11-03")].rating == "beachten"
    assert items[("Validierung", "Fehler und Warnungen")].rating == "ok"


def test_bestand_steps():
    from knix_arranger.services.workflow_status import bestand_steps
    steps = bestand_steps(_project(), 0, 2)
    assert [s.nav_key for s in steps] == ["import_csv", "validation", "bus_analysis",
                                          "plant_check", "renovation", "reports"]
    assert steps[0].detail == "2 Geräte, 2 GAs"


def test_views_and_sidebar(tmp_path):
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.views.bus_analysis_view import BusAnalysisView
    from knix_arranger.ui.views.plant_check_view import PlantCheckView
    from knix_arranger.ui.views.renovation_view import RenovationView
    from knix_arranger.ui.widgets.sidebar import Sidebar
    QApplication.instance() or QApplication([])
    project = _project()
    project.bus_recordings.append(summarize(parse_log(_log(tmp_path))))
    bus = BusAnalysisView()
    bus.set_project(project)
    assert bus._senders.rowCount() == 3 and bus._findings.topLevelItemCount() >= 2
    check = PlantCheckView()
    check.set_problem_counts((0, 0))
    check.set_project(project)
    assert check._table.rowCount() > 5
    renovation = RenovationView()
    renovation.set_project(project)
    assert renovation._lines.rowCount() == 2 and renovation._external.rowCount() == 1
    sidebar = Sidebar()
    sidebar.set_imported(True)
    order = [sidebar._nav_layout.itemAt(i).widget().title
             for i in range(len(sidebar._groups))]
    assert order[:2] == ["Projekt", "Bestand & Umbau"]
    sidebar.set_imported(False)
    order = [sidebar._nav_layout.itemAt(i).widget().title
             for i in range(len(sidebar._groups))]
    assert order.index("Bestand & Umbau") == order.index("Adressen & Logik") + 1


def test_reports(tmp_path):
    import fitz
    from knix_arranger.services.report_service import ReportService
    project = _project()
    summary = summarize(parse_log(_log(tmp_path)))
    project.bus_recordings.append(summary)
    service = ReportService(project)
    service.generate_bus_analysis_report(str(tmp_path / "bus.pdf"), summary)
    service.generate_plant_check_report(str(tmp_path / "check.pdf"), (0, 0))
    text = "".join(p.get_text() for p in fitz.open(str(tmp_path / "bus.pdf")))
    assert "Busanalyse" in text and "1.1.25" in text and "nicht im Projekt" in text
    text = "".join(p.get_text() for p in fitz.open(str(tmp_path / "check.pdf")))
    assert "Anlagen-Check" in text and "Z-Server" in text
