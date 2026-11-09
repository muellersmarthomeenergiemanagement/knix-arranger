"""
Umbau-Variante einer Linie (FA-609c). Nachgebaut nach dem Chalet: Linie 1.1
ohne eigenen Koppler mit 63 Geräten und dem Z-Server (extern), Linie 1.2
hinter Koppler 1.2.0.
"""
from __future__ import annotations
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from knix_arranger.models.line_plan import TARGET_MAIN, TARGET_NEW, LinePlan
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, CommunicationObject, Device, Line, Topology
from knix_arranger.services.line_plan_service import evaluate, free_line_number


def _device(pa, gas=(), **kw) -> Device:
    return Device(physical_address=pa, device_type=kw.pop("device_type", "sensor"),
                  product=kw.pop("product", "Taster"),
                  communication_objects=[CommunicationObject(connected_gas=list(gas))], **kw)


def _project():
    # 1.1.1–1.1.30 «unten» (GA 1/0/x), 1.1.31–1.1.63 «oben» (GA 2/0/x),
    # 1/0/1 in beiden Teilen; Linie 1.2 nutzt 3/0/1 und 1/0/1
    line1 = [_device(f"1.1.{n}", [f"1/0/{n}", "1/0/1"] if n <= 30 else [f"2/0/{n}", "1/0/1"])
             for n in range(1, 64)]
    line1.append(Device(physical_address="1.1.-", device_type="power_supply",
                        product="SV 640mA"))
    zserver = Device(physical_address="1.1.200", product="Z-Server", device_type="other",
                     external=True, manually_added=True)
    line1.append(zserver)
    line2 = [_device("1.2.0", device_type="coupler", product="Linienkoppler"),
             _device("1.2.7", ["3/0/1", "1/0/1"], device_type="gateway", product="Revox")]
    project = KnxProject(name="Chalet")
    project.topology = Topology(is_imported=True, areas=[Area(area_number=1, lines=[
        Line(line_number=1, devices=line1), Line(line_number=2, devices=line2),
        Line(line_number=0, devices=[])])])
    return project, line1, zserver


def _split(project, line1, zserver, **kw) -> LinePlan:
    plan = LinePlan(source="1.1", new_line=3, **kw)
    for device in line1[30:63]:
        plan.targets[device.id] = TARGET_NEW
    plan.targets[zserver.id] = TARGET_MAIN
    return plan


def test_free_line_number_skips_used_lines():
    project, _l, _z = _project()
    assert free_line_number(project.topology.areas[0]) == 3


def test_split_into_new_line_with_main_line():
    project, line1, zserver = _project()
    result = evaluate(project, _split(project, line1, zserver, main_line=True))
    assert (result.before.count, result.before.capacity) == (64, 64)
    parts = {p.key: p for p in result.parts}
    assert (parts["source"].count, parts["new"].count, parts["main"].count) == (31, 34, 1)
    assert parts["source"].added == ["Linienkoppler 1.1.0"]
    assert parts["new"].added == ["Linienkoppler 1.3.0"] and parts["new"].new_supply
    assert all(p.status == "ok" for p in result.parts)
    assert "Linienkoppler 1.1.0 für Linie 1.1" in result.hardware
    # Teilnehmernummer bleibt, Z-Server auf die Hauptlinie
    moves = {r.old: r.new for r in result.readdress}
    assert moves["1.1.31"] == "1.3.31" and moves["1.1.200"] == "1.0.200"
    assert any("1.2.0" in h for h in result.hints)
    tables = {f.coupler: f for f in result.filters}
    assert tables["1.1.0"].new and tables["1.1.0"].ga_count == 30   # 1/0/1..30
    assert not tables["1.2.0"].changed
    assert result.crossing == 1                                      # 1/0/1
    (check,) = result.externals
    # Auch auf der Hauptlinie: GAs nur hinter einem Koppler trägt die ETS in
    # keine Filtertabelle ein (FA-643) -- nur 1/0/1 läuft über die Koppler
    assert check.where == "Hauptlinie 1.0" and not check.behind_coupler
    assert "1/0/1" not in check.blocked
    assert {"1/0/2", "2/0/31", "3/0/1"} <= set(check.blocked)
    assert check.blocked_now == ["3/0/1"]                            # heute: nur Revox


def test_visualisation_behind_new_coupler_misses_gas():
    """Bleibt der Z-Server hinter dem neuen Koppler 1.1.0, erreicht er nur
    die in Linie 1.1 verknüpften GAs -- ohne Dummy fehlen die anderen."""
    project, line1, zserver = _project()
    plan = _split(project, line1, zserver, main_line=True)
    del plan.targets[zserver.id]
    (check,) = evaluate(project, plan).externals
    assert check.where == "Linie 1.1" and check.behind_coupler
    assert "2/0/31" in check.blocked and "3/0/1" in check.blocked
    assert "1/0/2" not in check.blocked
    # heute ohne eigenen Koppler, aber 3/0/1 ist nur hinter 1.2.0 verknüpft
    assert check.blocked_now == ["3/0/1"]


def test_segment_keeps_addresses():
    project, line1, zserver = _project()
    plan = _split(project, line1, zserver, mode="segment")
    result = evaluate(project, plan)
    parts = {p.key: p for p in result.parts}
    assert parts["new"].added == ["Linienverstärker 1.1.64"]
    # ohne Koppler für 1.1 gibt es keine Hauptlinie: Z-Server bleibt
    assert "main" not in parts and result.readdress == []
    assert parts["source"].count == 31     # 30 Taster + Z-Server


def test_plan_round_trip():
    project, line1, zserver = _project()
    project.line_plans = [_split(project, line1, zserver, main_line=True)]
    loaded = KnxProject.from_dict(project.to_dict())
    (plan,) = loaded.line_plans
    assert plan.source == "1.1" and plan.main_line and plan.targets[zserver.id] == TARGET_MAIN


def test_dialog_and_report(tmp_path):
    from PySide6.QtWidgets import QApplication
    from knix_arranger.services.report_service import ReportService
    from knix_arranger.ui.dialogs.line_plan_dialog import LinePlanDialog
    QApplication.instance() or QApplication([])
    project, line1, zserver = _project()
    dlg = LinePlanDialog(project, "1.1")
    assert dlg._main_line.isChecked()                  # Linie 1.1 hat keinen Koppler
    # Zeile des Z-Servers auf die Hauptlinie
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(dlg._tree)
    while it.value():
        item = it.value()
        if item.text(1) == "1.1.200":
            combo = dlg._tree.itemWidget(item, 3)
            combo.setCurrentIndex(combo.findData(TARGET_MAIN))
        it += 1
    assert dlg._plan.targets == {zserver.id: TARGET_MAIN}
    assert dlg._parts.item(dlg._parts.rowCount() - 1, 0).text() == "Hauptlinie 1.0"
    dlg._store()
    assert [p.source for p in project.line_plans] == ["1.1"]
    path = tmp_path / "umbau.pdf"
    ReportService(project).generate_line_plan_report(str(path), project.line_plans[0])
    import fitz
    text = "".join(page.get_text() for page in fitz.open(str(path)))
    assert "Linienumbau Linie 1.1" in text and "1.0.200" in text
