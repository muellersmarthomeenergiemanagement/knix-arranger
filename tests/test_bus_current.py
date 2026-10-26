"""Busstrom je Linie gegen die Spannungsversorgung (FA-613b)."""
from __future__ import annotations
import zipfile

import pytest

from knix_arranger.models.project import KnxProject
from knix_arranger.models.topology import Area, Device, Line
from knix_arranger.services.bus_current import (
    DEFAULT_DEVICE_MA, line_current, parse_bus_current, supply_capacity,
)

NS = "http://knx.org/xml/project/23"
MFR = "M-0002"


def _sv(product="SV/S30.640.3.1 Power Supply,640mA,MDRC", **kw):
    return Device(physical_address="1.1.-", device_type="power_supply", product=product, **kw)


def _actor(pa, current=0.0, **kw):
    return Device(physical_address=pa, device_type="actor", product="Aktor",
                  bus_current=current, **kw)


def test_buscurrent_lesen():
    assert parse_bus_current("10") == 10
    assert parse_bus_current("5.0000000e+000") == 5
    assert parse_bus_current("0") == 0          # ABB: 0 = keine Angabe
    assert parse_bus_current(None) == 0
    assert parse_bus_current("x") == 0


def test_groesse_der_spannungsversorgung():
    assert supply_capacity(_sv()) == (640, True)
    assert supply_capacity(_sv("TXA116 Alimentation 2x 320 mA")) == (320, True)
    assert supply_capacity(_sv("PS KNX", bus_current=1280)) == (1280, True)
    # Herstellerdaten mit 1 bzw. ohne Angabe: 640 mA angenommen
    assert supply_capacity(_sv("KNX-Netzteil", bus_current=1)) == (640, False)


def test_summe_je_linie():
    line = Line(line_number=1, devices=[
        _sv(),
        _actor("1.1.1", 12),
        _actor("1.1.2", 2.5),
        _actor("1.1.3"),                                   # ohne Angabe: Richtwert
        Device(physical_address="1.1.-", product="DR/S4.1 Drossel,REG"),  # ohne Busadresse
    ])
    lc = line_current(line)
    assert lc.consumer_count == 3
    assert lc.data_ma == 14.5
    assert lc.estimated_ma == DEFAULT_DEVICE_MA and lc.estimated_count == 1
    assert lc.supply_ma == 640
    assert lc.summary() == "24 / 640 mA (4 %)"
    assert lc.estimate_note() == "davon 10 mA geschätzt (1 Gerät ohne Herstellerangabe)"


def test_ohne_spannungsversorgung():
    lc = line_current(Line(devices=[_actor("1.1.1", 20)]))
    assert lc.load is None and not lc.overloaded
    assert lc.summary() == "20 mA, keine Spannungsversorgung"


def test_strom_aus_dem_katalog():
    class Catalog:
        def bus_current_of(self, manufacturer, order_number, product_name=""):
            return 25.0 if order_number == "3901-4.KNX" else 0.0
    device = _actor("1.1.1", manufacturer="Feller", order_number="3901-4.KNX")
    lc = line_current(Line(devices=[device]), Catalog())
    assert lc.data_ma == 25 and not lc.estimated_count


def test_geraet_speichert_strom():
    device = _actor("1.1.1", 12)
    assert Device.from_dict(device.to_dict()).bus_current == 12

    class Prod:
        manufacturer = "ABB"; manufacturer_id = "M-0002"; order_number = "X"
        product_name = "Y"; product_ref_id = ""; hw2prog_id = ""
        secure_supported = False; bus_current = 7.5
    device.apply_product(Prod())
    assert device.bus_current == 7.5
    device.apply_product(None)
    assert device.bus_current == 0


def _project(devices) -> KnxProject:
    project = KnxProject(name="Strom")
    project.topology.areas = [Area(area_number=1, lines=[Line(line_number=1, devices=devices)])]
    return project


def _issues(project):
    from knix_arranger.services.topology_validation import check_topology
    return [i for i in check_topology(project) if i.rule_id == "FA-613b"]


def test_validierung_reserve_und_ueberlast():
    small = "SV/S30.160.1.1 Power Supply,160mA,MDRC"
    ok = _project([_sv(small)] + [_actor(f"1.1.{n}", 10) for n in range(1, 11)])
    assert _issues(ok) == []                                        # 100 / 160 mA

    tight = _project([_sv(small)] + [_actor(f"1.1.{n}", 10) for n in range(1, 15)])
    issues = _issues(tight)                                         # 140 / 160 mA
    assert [i.level for i in issues] == ["warning"]
    assert "140 / 160 mA (88 %)" in issues[0].message

    over = _project([_sv(small)] + [_actor(f"1.1.{n}") for n in range(1, 18)])
    issues = _issues(over)                                          # 170 / 160 mA
    assert [i.level for i in issues] == ["error"]
    assert "17 Geräte ohne Herstellerangabe" in issues[0].message


# ── Herstellerdaten ──────────────────────────────────────────────────────────

def _hardware_xml() -> str:
    def hw(name, text, attrs):
        return f"""
      <Hardware Id="{MFR}_H-{name}" Name="{text}" {attrs}>
        <Products><Product Id="{MFR}_H-{name}_P-{name}" Text="{text}" OrderNumber="{name}"/></Products>
      </Hardware>"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><ManufacturerData><Manufacturer RefId="{MFR}"><Hardware>
{hw("TXA111", "TXA111 Alimentation 320 mA", 'IsPowerSupply="true"')}
{hw("SA", "SA/S8.16.1 Schaltaktor", 'BusCurrent="5.0000000e+000"')}
{hw("TA", "Tastsensor", 'BusCurrent="0"')}
</Hardware></Manufacturer></ManufacturerData></KNX>"""


def _knxproj(path) -> str:
    def device(name, addr=None):
        address = f'Address="{addr}" ' if addr is not None else ""
        return (f'<DeviceInstance Id="P-TEST-0_DI-{name}" {address}'
                f'ProductRefId="{MFR}_H-{name}_P-{name}"/>')
    devices = device("TXA111") + device("SA", 1) + device("TA", 2)
    main = f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><Project Id="P-TEST"><Installations><Installation Name="">
  <Topology><Area Id="P-TEST-0_A-1" Address="1"><Line Id="P-TEST-0_L-1" Address="1">
    <Segment Id="P-TEST-0_S-1">{devices}</Segment>
  </Line></Area></Topology>
</Installation></Installations></Project></KNX>"""
    project_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><Project Id="P-TEST"><ProjectInformation Name="Strom"/></Project></KNX>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{MFR}/Hardware.xml", _hardware_xml())
        zf.writestr("P-TEST/project.xml", project_xml)
        zf.writestr("P-TEST/0.xml", main)
    return str(path)


def test_knxproj_import_liest_busstrom(tmp_path):
    from knix_arranger.services.knxproj_import_service import KnxprojImportService
    project = KnxprojImportService().import_knxproj(_knxproj(tmp_path / "p.knxproj"))
    line = project.topology.areas[0].lines[0]
    devices = {d.order_number: d for d in line.devices}
    assert devices["SA"].bus_current == 5
    assert devices["TA"].bus_current == 0
    # Hager: kein Schlüsselwort im Namen, aber IsPowerSupply
    assert devices["TXA111"].device_type == "power_supply"
    lc = line_current(line)
    assert (lc.data_ma, lc.estimated_count, lc.supply_ma) == (5, 1, 320)


def test_knxprod_liest_busstrom(tmp_path):
    from knix_arranger.services.knxprod_catalog_service import KnxprodCatalogService
    path = tmp_path / "test.knxprod"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{MFR}/Hardware.xml", _hardware_xml())
    entries = KnxprodCatalogService()._parse_hardware_xml(
        zipfile.ZipFile(path), MFR, [f"{MFR}/Hardware.xml"])
    by_order = {e["order_number"]: e for e in entries}
    assert by_order["SA"]["bus_current"] == 5
    assert by_order["SA"]["channels"] == 0      # Strom ist keine Kanalzahl
    assert by_order["TA"]["bus_current"] == 0


def test_bericht_zeigt_busstrom(tmp_path):
    fitz = pytest.importorskip("fitz")
    from knix_arranger.services.report_service import ReportService
    project = _project([_sv(), _actor("1.1.1", 12), _actor("1.1.2")])
    path = str(tmp_path / "topo.pdf")
    ReportService(project).generate_topology_report(path)
    doc = fitz.open(path)
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    assert "22 / 640 mA (3 %)" in text           # Kennzahlen
    assert "22 / 640 mA" in text                 # Schema
    assert "10 mA geschätzt" in text
