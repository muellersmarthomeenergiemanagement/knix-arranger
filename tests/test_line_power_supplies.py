"""Spannungsversorgungen (T-06): jede TP-Linie braucht eine eigene SV --
Bereichslinie 0.0, Hauptlinie je Bereich, jede Linie (Projekt_23: zwei SVs
"Bereichslinie" auf 1.0.-/2.0.-, die SV der Bereichslinie 0.0 fehlte)."""
from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line, Topology
from knix_arranger.services.topology_diagram import build_topology_diagram
from knix_arranger.services.topology_engine import (
    BACKBONE_SV_PRODUCT, MAIN_LINE_SV_PRODUCT, apply_line_power_supplies,
)
from knix_arranger.services.topology_validation import _check_power_supplies


def _topology(*lines_per_area, backbone="TP"):
    areas = [Area(area_number=i + 1, coupler_address=f"{i + 1}.0.0",
                  lines=[Line(line_number=n + 1, coupler_address=f"{i + 1}.{n + 1}.0")
                         for n in range(count)])
             for i, count in enumerate(lines_per_area)]
    return Topology(areas=areas, backbone_type=backbone)


def _supplies(t):
    result = {"0.0": t.backbone_power_supply}
    result.update({f"{a.area_number}.0": a.backbone_power_supply for a in t.areas})
    return {k: (v.physical_address, v.product) if v else None for k, v in result.items()}


def test_two_areas_tp_backbone():
    t = _topology(4, 1)
    apply_line_power_supplies(t)
    assert _supplies(t) == {
        "0.0": ("0.0.-", BACKBONE_SV_PRODUCT),
        "1.0": ("1.0.-", MAIN_LINE_SV_PRODUCT),
        "2.0": ("2.0.-", MAIN_LINE_SV_PRODUCT),
    }


def test_one_area_several_lines_has_main_line_supply():
    t = _topology(3)
    apply_line_power_supplies(t)
    assert _supplies(t) == {"0.0": None, "1.0": ("1.0.-", MAIN_LINE_SV_PRODUCT)}


def test_one_line_only_no_extra_supplies():
    t = _topology(1)
    apply_line_power_supplies(t)
    assert _supplies(t) == {"0.0": None, "1.0": None}


def test_ip_backbone_and_ip_main_line_need_no_tp_supply():
    t = _topology(2, 2, backbone="IP")
    t.areas[1].backbone_type = "IP"
    apply_line_power_supplies(t)
    assert _supplies(t) == {"0.0": None, "1.0": ("1.0.-", MAIN_LINE_SV_PRODUCT), "2.0": None}


def test_old_area_supply_renamed_product_kept():
    t = _topology(2, 1)
    t.areas[0].backbone_power_supply = Device(
        device_type="power_supply", product=BACKBONE_SV_PRODUCT,
        manufacturer="MDT", order_number="STC-0640.01")
    apply_line_power_supplies(t)
    sv = t.areas[0].backbone_power_supply
    assert (sv.product, sv.manufacturer, sv.order_number) == (
        MAIN_LINE_SV_PRODUCT, "MDT", "STC-0640.01")


def test_save_load_and_validation():
    t = _topology(2, 1)
    restored = Topology.from_dict(t.to_dict())
    issues = [i.message for i in _check_power_supplies(restored)]
    assert "Bereichslinie 0.0: keine Spannungsversorgung" in issues
    assert "Hauptlinie 1.0: keine Spannungsversorgung" in issues

    apply_line_power_supplies(restored)
    restored = Topology.from_dict(restored.to_dict())
    assert restored.backbone_power_supply.physical_address == "0.0.-"
    assert not [i for i in _check_power_supplies(restored)
                if "Hauptlinie" in i.message or "Bereichslinie" in i.message]


def test_diagram_shows_backbone_and_main_line_supply():
    project = KnxProject(name="Chalet")
    project.topology = _topology(2, 1)
    apply_line_power_supplies(project.topology)
    diagram = build_topology_diagram(project)
    assert diagram["backbone"] == "Bereichslinie (TP)"
    # SV der Bereichslinie an der Bereichslinie, SV der Hauptlinie im Bereich
    assert diagram["backbone_power"]["lines"] == ["0.0.-"]
    power = [n for n in diagram["areas"][0]["nodes"] if n["kind"] == "power"]
    assert [(n["title"], n["lines"]) for n in power] == [("SV Hauptlinie", ["1.0.-"])]
    assert diagram["areas"][0]["main_line"] == "Hauptlinie 1.0"
