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


# ── Quittungen (ACK, NAK, BUSY) ──────────────────────────────────────────

def test_decode_nak_busy():
    assert decode("2B0903010206044BB90EFB0C", None) == "nak"
    assert decode("2B0903010206044BB90EFBC0", None) == "busy"
    assert decode("2B0903010206044BB90EFB00", None) == "nak_busy"
    assert decode("2B0903010206044BB90EFB55", None) is None


def test_ack_belongs_to_preceding_frame(tmp_path):
    rec = parse_log(_log(tmp_path))
    assert [t.ack for t in rec.telegrams] == ["ack", "", "", "", "", ""]
    summary = summarize(rec)
    assert summary["ack_known"] and summary["unacked"] == 5
    pairs = {(p[0], p[1]): p for p in summary["pairs"]}
    assert pairs[("1.1.200", "0/5/13")][6] == [1, 0, 0, 0]
    assert pairs[("1.2.7", "12/1/1")][6] == [0, 0, 0, 4]


def test_ack_findings(tmp_path):
    # Revox 1.2.7 -> 12/1/1 mit Empfänger, 1.1.25 -> 0/1/10 erhält NAK, dann BUSY
    log = _LOG.replace(
        '<RecordStop', '<Telegram Timestamp="2026-11-03T20:17:00.5Z" Service="L_Busmon.ind" '
        'RawData="2B0903010206044BB90EFB0C" />\n  <Telegram Timestamp="2026-11-03T20:17:00.6Z" '
        'Service="L_Busmon.ind" RawData="2B0903010106045DB67A1E9C1119010AE300800C97B8" />\n'
        '  <Telegram Timestamp="2026-11-03T20:17:00.7Z" Service="L_Busmon.ind" '
        'RawData="2B0903010206044BB90EFBC0" />\n  <RecordStop')
    path = tmp_path / "Quittungen.xml"
    path.write_text(log, encoding="utf-8")
    summary = summarize(parse_log(str(path)))
    assert (summary["acks"], summary["naks"], summary["busys"]) == (1, 1, 1)
    project = _project()
    project.topology.areas[0].lines[0].devices.append(Device(
        physical_address="1.1.30", device_type="sensor", product="Display",
        communication_objects=[CommunicationObject(name="Raum", connected_gas=["12/1/1"])]))
    a = analyze(project, summary)
    pair = {p.dst: p for p in a.pairs}
    assert pair["12/1/1"].unacked and pair["12/1/1"].ack_text == "keine"
    assert pair["0/1/10"].ack_text == "0 von 2, NAK 1, BUSY 1"
    assert pair["0/5/13"].ack_text == "alle"
    titles = [f.title for f in a.findings]
    assert "1 Mal NAK (Telegramm gestört empfangen)" in titles
    assert "1 Mal BUSY (Empfänger ausgelastet)" in titles
    assert "1 Ziel(e) mit Empfänger in der ETS, aber ohne Quittung" in titles


def test_ack_missed_by_interface_and_old_recordings(tmp_path):
    summary = summarize(parse_log(_log(tmp_path)))
    titles = [f.title for f in analyze(_project(), summary).findings]
    assert not any("ohne Quittung" in t and "Empfänger" in t for t in titles)
    # Gruppenmonitor oder Mitschnitt ohne einzige Quittung: keine Auswertung
    summary["acks"] = 0
    assert all(p.acks is None for p in analyze(_project(), summary).pairs)
    # gespeicherte Mitschnitte älterer Versionen (Paare mit sechs Feldern)
    old = {k: v for k, v in summarize(parse_log(_log(tmp_path))).items()
           if k not in ("naks", "busys", "ack_known", "unacked")}
    old["pairs"] = [p[:6] for p in old["pairs"]]
    a = analyze(_project(), old)
    assert all(p.ack_text == "–" for p in a.pairs) and a.unacked == []


# ── Filter (Ansicht Busanalyse) ──────────────────────────────────────────

def test_text_matches_addresses_and_text():
    from knix_arranger.services.bus_monitor import text_matches
    cells = ["1.2.7", "1/5/1", "MM.UG.02.01_wert Raum (Waschen)", "Write"]
    assert text_matches("", cells)
    assert text_matches("1.2.7 1/5/1", cells)
    assert text_matches("1.2.7 → 1/5/1", cells)           # Zeile aus einem Befund
    assert text_matches("1/5 waschen", cells)               # Anfang der GA, Text ohne Gross/klein
    assert text_matches("1.2", cells)                       # Linie
    assert not text_matches("1/5/10", cells)
    assert not text_matches("1/5/1", ["1/5/10"])            # keine Teiladresse
    assert not text_matches("1.2.70", cells)
    assert not text_matches("Wohnen", cells)


def test_pair_flags(tmp_path):
    from knix_arranger.services.bus_monitor import pair_flags, pair_matches
    a = analyze(_project(), summarize(parse_log(_log(tmp_path))))
    flags = {p.dst: pair_flags(a)[id(p)] for p in a.pairs}
    assert flags["12/1/1"] >= {"repeated", "unacked"}
    assert "unknown" in flags["0/1/10"] and "missing" in flags["0/1/10"]
    assert flags["0/5/13"] == {"unlinked"}
    assert pair_matches(set(), "all") and not pair_matches(set(), "notable")
    assert pair_matches({"unacked"}, "notable") and not pair_matches({"unacked"}, "disturbed")


def test_view_filter_and_jumps(tmp_path):
    from PySide6.QtWidgets import QApplication
    from knix_arranger.ui.views.bus_analysis_view import BusAnalysisView
    QApplication.instance() or QApplication([])
    project = _project()
    project.bus_recordings.append(summarize(parse_log(_log(tmp_path))))
    view = BusAnalysisView()
    view.set_project(project)

    def shown(table):
        return sorted(table.item(r, 1 if table is view._pairs else 0).text()
                      for r in range(table.rowCount()) if not table.isRowHidden(r))

    assert shown(view._pairs) == ["0/1/10", "0/5/13", "12/1/1"]
    assert view._line.count() == 3                          # alle, Linie 1.1, Linie 1.2
    view._category.setCurrentIndex(view._category.findData("unacked"))
    assert shown(view._pairs) == ["12/1/1"] and shown(view._senders) == ["1.2.7"]
    view._category.setCurrentIndex(view._category.findData("unknown"))
    assert shown(view._senders) == ["1.1.25"]
    view._reset_filter()
    view._line.setCurrentIndex(view._line.findData("1.1"))
    assert shown(view._pairs) == ["0/1/10", "0/5/13"]
    assert shown(view._senders) == ["1.1.200", "1.1.25"]
    view._reset_filter()
    view._search.setText("Windsicherheit")
    assert shown(view._pairs) == ["0/5/13"] and shown(view._senders) == ["1.1.200"]
    assert view._count.text() == "1 von 3 Telegrammen"
    # Befunde: nur passende Einzelzeilen; Doppelklick springt zu den Telegrammen
    view._reset_filter()
    repeat = next(view._findings.topLevelItem(i) for i in range(view._findings.topLevelItemCount())
                  if "Wiederholungen" in view._findings.topLevelItem(i).text(0))
    view._finding_jump(repeat.child(1))
    assert view._search.text() == "1.2.7 12/1/1" and shown(view._pairs) == ["12/1/1"]
    assert view._tabs.currentWidget() is view._pairs
    row = next(r for r in range(view._senders.rowCount())
               if view._senders.item(r, 0).text() == "1.1.25")
    view._sender_jump(view._senders.item(row, 0))
    assert view._search.text() == "1.1.25" and shown(view._pairs) == ["0/1/10"]


# ── Weitere Auswertungen (FA-640c–h) ─────────────────────────────────────

def _raw(src: str, dst: str, service: str = "Write", data: bytes | None = b"\x01",
         hops: int = 6, repeat: bool = False) -> str:
    """Busmonitor-Rahmen (L_Busmon.ind) bauen; data=None: Read, Länge 1 Byte
    mit Wert < 0x40: Wert im APCI-Byte (bis 6 Bit)."""
    a, l, d = (int(x) for x in src.split("."))
    h, m, s = (int(x) for x in dst.split("/"))
    apci = {"Read": 0x00, "Response": 0x40, "Write": 0x80}[service]
    if data is None:
        tpdu = bytes([0x00, apci])
    elif len(data) == 1 and data[0] < 0x40 and not data.startswith(b"\xff"):
        tpdu = bytes([0x00, apci | data[0]])
    else:
        tpdu = bytes([0x00, apci]) + data
    ctrl = 0xBC if not repeat else 0x9C
    npci = 0x80 | (hops << 4) | (len(tpdu) - 1)
    body = bytes([ctrl, a << 4 | l, d, h << 3 | m, s, npci]) + tpdu + b"\x00"
    return "2B00" + body.hex().upper()


def _write_log(tmp_path, frames: list[tuple[str, str]], name: str = "Test.xml") -> str:
    """frames: (Zeit "HH:MM:SS", RawData)."""
    rows = "\n".join(f'  <Telegram Timestamp="2026-11-04T{t}.0Z" Service="L_Busmon.ind" '
                     f'RawData="{raw}" />' for t, raw in frames)
    path = tmp_path / name
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<CommunicationLog xmlns="http://knx.org/xml/telegrams/01">\n'
        '  <RecordStart Timestamp="2026-11-04T10:00:00.0Z" ConnectionName="USB" Mode="Busmonitor" />\n'
        f"{rows}\n  <RecordStop Timestamp=\"2026-11-04T10:10:00.0Z\" />\n</CommunicationLog>\n",
        encoding="utf-8")
    return str(path)


_ACK_RAW = "2B00CC"


def _checks_project():
    project = _project()
    line1 = project.topology.areas[0].lines[0]
    line1.devices += [
        Device(physical_address="1.1.30", device_type="actor", product="Schaltaktor",
               communication_objects=[CommunicationObject(
                   name="Status", flags="K-LÜ--", connected_gas=["0/5/14"])]),
        Device(physical_address="1.1.31", device_type="actor", product="Schaltaktor 2",
               communication_objects=[CommunicationObject(
                   name="Status", flags="K-LÜ--", connected_gas=["0/5/14"])]),
    ]
    from knix_arranger.models.group_address import GroupAddress
    mg = project.group_addresses.main_groups[0].middle_groups[0]
    mg.group_addresses.append(GroupAddress(main_group=0, middle_group=5, sub_group=14,
                                           designation="L.EG.01.01_rm Status",
                                           datapoint_type="DPST-1-11"))
    mg.group_addresses.append(GroupAddress(main_group=0, middle_group=5, sub_group=15,
                                           designation="H.EG.01.01_ist Temp",
                                           datapoint_type="DPST-9-1"))
    return project


def test_dpt_values():
    from knix_arranger.services.dpt_values import decode_value, dpt_parts, expected_size
    assert dpt_parts("DPST-9-1") == (9, 1) and dpt_parts("DPT-5") == (5, 0)
    assert dpt_parts("9.001 Temperatur") == (9, 1) and dpt_parts("") == (0, 0)
    assert expected_size("DPST-1-1") == 0 and expected_size("DPST-9-1") == 2
    assert expected_size("DPT-14") == 4 and expected_size("") is None
    assert decode_value("DPST-1-1", "1", 0) == "Ein"
    assert decode_value("DPST-1-8", "1", 0) == "Ab"
    assert decode_value("DPST-3-7", "9", 0) == "heller 100 %"
    assert decode_value("DPST-5-1", "FF", 1) == "100 %"
    assert decode_value("DPST-9-1", "0C97", 2) == "23.5 °C"
    assert decode_value("DPST-9-1", "8A24", 2) == "-30 °C"
    assert decode_value("DPST-14-56", "447A0000", 4) == "1000 W"
    assert decode_value("DPST-16-0", "48616C6C6F0000", 7) == "48616C6C6F0000"   # Länge passt nicht
    assert decode_value("DPST-16-0", "48616C6C6F" + "00" * 9, 14) == "«Hallo»"
    assert decode_value("DPST-17-1", "02", 1) == "Szene 3"
    assert decode_value("DPST-18-1", "82", 1) == "Szene 3 speichern"
    assert decode_value("DPST-10-1", "6E1E00", 3) == "14:30:00"
    assert decode_value("DPST-9-1", "01", 1) == "01"                        # falsche Länge
    assert decode_value("DPST-9-1", "0C97", None) == "23.5 °C"             # ältere Mitschnitte


def test_size_read_multi_checks(tmp_path):
    path = _write_log(tmp_path, [
        # 1.1.200 schreibt 2 Byte auf die 1-Bit-GA 0/5/13
        ("10:00:01", _raw("1.1.200", "0/5/13", data=b"\x0c\x97")), ("10:00:01", _ACK_RAW),
        # Lesen auf 0/5/15 ohne Antwort, auf 0/5/14 antworten zwei Aktoren
        ("10:00:02", _raw("1.1.200", "0/5/15", "Read", None)), ("10:00:02", _ACK_RAW),
        ("10:00:03", _raw("1.1.200", "0/5/14", "Read", None)), ("10:00:03", _ACK_RAW),
        ("10:00:03", _raw("1.1.30", "0/5/14", "Response", b"\x01")), ("10:00:03", _ACK_RAW),
        ("10:00:03", _raw("1.1.31", "0/5/14", "Response", b"\x00")), ("10:00:03", _ACK_RAW),
        # beide Aktoren schreiben auch die Rückmelde-GA
        ("10:00:04", _raw("1.1.30", "0/5/14", data=b"\x01")), ("10:00:04", _ACK_RAW),
        ("10:00:05", _raw("1.1.31", "0/5/14", data=b"\x00")), ("10:00:05", _ACK_RAW),
    ])
    rec = parse_log(path)
    assert [t.size for t in rec.telegrams[:2]] == [2, -1] and rec.telegrams[0].hops == 6
    a = analyze(_checks_project(), summarize(rec))
    (size,) = a.size_issues
    assert size.pair.dst == "0/5/13" and (size.expected, size.found) == (0, [2])
    assert [i.ga for i in a.unanswered] == ["0/5/15"] and a.unanswered[0].read_flags == []
    (multi_resp,) = a.multi_response
    assert multi_resp.responders == ["1.1.30", "1.1.31"]
    assert multi_resp.read_flags == ["1.1.30", "1.1.31"]
    (multi,) = a.multi_senders
    assert multi.ga == "0/5/14" and multi.critical and multi.reason == "Rückmeldung"
    titles = [f.title for f in a.findings]
    assert titles[0] == "1 Mal passt die Datenlänge nicht zum DPT der GA"     # Fehler zuerst
    assert "1 Leseanfrage(n) ohne Antwort" in titles
    assert "1 GA(s) mit mehreren Antwortenden" in titles
    assert "1 Rückmeldung(en) oder Messwert(e) mit mehreren Sendern" in titles
    assert titles[-1].startswith("Mitschnitt über")
    values = {(p.src, p.dst, p.service): p.value for p in a.pairs}
    assert values[("1.1.30", "0/5/14", "Write")] == "aktiv"
    assert values[("1.1.200", "0/5/13", "Write")] == "0C97"                   # Länge falsch


def test_measuring_line_forwarding_hops(tmp_path):
    path = _write_log(tmp_path, [
        ("10:00:01", _raw("1.1.200", "0/5/13", data=b"\x01")),               # Linie 1.1, Zähler 6
        ("10:00:02", _raw("1.2.7", "12/1/1", data=b"\x01", hops=5)),          # über Koppler
        ("10:00:03", _raw("1.2.7", "0/5/13", data=b"\x00", hops=5)),          # 1.1.4 empfängt
        ("10:00:04", _raw("1.2.8", "12/1/2", data=b"\x01", hops=7)),
    ])
    a = analyze(_project(), summarize(parse_log(path)))
    assert a.measuring_line == "1.1"
    assert [p.dst for p in a.forwarded] == ["12/1/1"]
    assert [p.dst for p in a.hop_issues] == ["12/1/2"]
    titles = [f.title for f in a.findings]
    assert "1 GA(s) ohne Empfänger auf Linie 1.1 weitergeleitet" in titles
    assert "1 Mal Routing-Zähler 7 oder 0" in titles


def test_bus_load_per_minute(tmp_path):
    from knix_arranger.services.bus_checks import load_buckets, load_series
    frames = [(f"10:01:{i % 60:02d}", _raw("1.1.200", "0/5/13", data=b"\x01"))
              for i in range(300)]
    summary = summarize(parse_log(_write_log(tmp_path, frames)))
    ((minute, count, bits),) = summary["minutes"]
    # 9 Byte Rahmen: 50 + 9 * 13 = 167 Bit je Rahmen
    assert (minute, count, bits) == ("2026-11-04T10:01", 300, 300 * 167)
    (point,) = load_series(summary)
    assert round(point.percent, 1) == round(300 * 167 / 9600 / 60 * 100, 1) == 8.7
    many = [type(point)(f"m{i}", 1, float(i)) for i in range(500)]
    buckets = load_buckets(many, 100)
    assert len(buckets) == 100 and buckets[0].percent == 4.0 and buckets[0].frames == 5
    # Busbelegung über dem Richtwert ergibt einen Befund
    summary["minutes"] = [["2026-11-04T10:01", 2000, int(0.55 * 9600 * 60)]]
    a = analyze(_project(), summary)
    load = next(f for f in a.findings if f.title.startswith("Busbelegung"))
    assert load.level == "warning" and load.title == "Busbelegung bis 55 % in einer Minute"


def test_compare_recordings(tmp_path):
    from knix_arranger.services.bus_checks import compare
    before = summarize(parse_log(_log(tmp_path)))
    after = summarize(parse_log(_write_log(tmp_path, [
        (f"10:{i // 60:02d}:{i % 60:02d}", _raw("1.1.200", "0/5/13", data=b"\x01"))
        for i in range(0, 600, 5)] + [("10:05:00", _raw("1.1.40", "0/5/13", data=b"\x00"))])))
    c = compare(_project(), after, before)
    metrics = dict((m[0], m[1:]) for m in c.metrics)
    assert metrics["Absender"] == ("3", "2")
    assert c.new_senders == ["1.1.40"] and c.gone_senders == ["1.1.25", "1.2.7"]
    assert c.gone_targets == ["0/1/10", "12/1/1"]
    assert any(t.startswith("3 Wiederholungen") for t in c.resolved_findings)
    assert any(k == "1.1.200 → 0/5/13" for k, _b, _a in c.changed)


def test_view_load_compare_and_report(tmp_path):
    import fitz
    from PySide6.QtWidgets import QApplication
    from knix_arranger.services.report_service import ReportService
    from knix_arranger.ui.views.bus_analysis_view import BusAnalysisView
    QApplication.instance() or QApplication([])
    project = _project()
    first = summarize(parse_log(_log(tmp_path)))
    second = summarize(parse_log(_write_log(tmp_path, [
        ("10:00:01", _raw("1.1.200", "0/5/13", data=b"\x01")), ("10:00:01", _ACK_RAW)])))
    project.bus_recordings += [first, second]
    view = BusAnalysisView()
    view.set_project(project)
    assert view._load_chart._points and "Mittel" in view._load_info.text()
    assert view._compare_with.count() == 2                  # kein Vergleich + erster Mitschnitt
    view._compare_with.setCurrentIndex(1)
    assert view._metrics.rowCount() >= 8
    tops = [view._differences.topLevelItem(i).text(0)
            for i in range(view._differences.topLevelItemCount())]
    assert "Absender nicht mehr gesehen (2)" in tops
    pdf_path = tmp_path / "vergleich.pdf"
    ReportService(project).generate_bus_analysis_report(str(pdf_path), second, first)
    text = "".join(p.get_text() for p in fitz.open(str(pdf_path)))
    assert "Buslast" in text and "Vergleich mit früherem Mitschnitt" in text
    assert "Messpunkt" in text
