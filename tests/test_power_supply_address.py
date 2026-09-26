"""Geraete ohne ETS-Adresse (Spannungsversorgungen) erhalten "B.L.-" statt "B.L.0"."""
from __future__ import annotations
import zipfile

from knix_arranger.models.topology import Topology
from knix_arranger.services.knxproj_import_service import KnxprojImportService
from knix_arranger.services.report_sorting import physical_address_key

NS = "http://knx.org/xml/project/23"
MFR = "M-0002"


def _hardware_xml() -> str:
    def hw(name, text, app):
        return f"""
      <Hardware Id="{MFR}_H-{name}" Name="{text}">
        <Products><Product Id="{MFR}_H-{name}_P-{name}" Text="{text}" OrderNumber="{name}"/></Products>
        <Hardware2Programs>
          <Hardware2Program Id="{MFR}_H-{name}_HP-{app}">
            <ApplicationProgramRef RefId="{MFR}_A-{app}"/>
          </Hardware2Program>
        </Hardware2Programs>
      </Hardware>"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><ManufacturerData><Manufacturer RefId="{MFR}"><Hardware>
{hw("SV", "SV/S30.640.3.1 Power Supply,640mA,MDRC", "0001-10-AAAA")}
{hw("LK", "LK/S4.1 Line-/Area Coupler, MDRC", "0002-10-BBBB")}
</Hardware></Manufacturer></ManufacturerData></KNX>"""


def _device(name, addr=None, app="0001-10-AAAA"):
    address = f'Address="{addr}" ' if addr is not None else ""
    return (f'<DeviceInstance Id="P-TEST-0_DI-{name}" {address}'
            f'ProductRefId="{MFR}_H-{name}_P-{name}" '
            f'Hardware2ProgramRefId="{MFR}_H-{name}_HP-{app}"/>')


def _knxproj(path) -> str:
    devices = _device("SV") + _device("LK", 0, "0002-10-BBBB")
    main = f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><Project Id="P-TEST"><Installations><Installation Name="">
  <Topology><Area Id="P-TEST-0_A-1" Address="1"><Line Id="P-TEST-0_L-2" Address="2">
    <Segment Id="P-TEST-0_S-1">{devices}</Segment>
  </Line></Area></Topology>
</Installation></Installations></Project></KNX>"""
    project_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><Project Id="P-TEST"><ProjectInformation Name="SV-Test"/></Project></KNX>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{MFR}/Hardware.xml", _hardware_xml())
        zf.writestr("P-TEST/project.xml", project_xml)
        zf.writestr("P-TEST/0.xml", main)
    return str(path)


def test_import_ohne_adresse(tmp_path):
    project = KnxprojImportService().import_knxproj(_knxproj(tmp_path / "p.knxproj"))
    devices = {d.product: d for a in project.topology.areas for l in a.lines for d in l.devices}
    sv = devices["SV/S30.640.3.1 Power Supply,640mA,MDRC"]
    lk = devices["LK/S4.1 Line-/Area Coupler, MDRC"]
    assert sv.physical_address == "1.2.-"
    assert sv.device_type == "power_supply"
    assert not sv.is_programmed
    assert lk.physical_address == "1.2.0"
    assert lk.device_type == "coupler"


def test_altprojekt_wird_beim_laden_korrigiert():
    data = {"areas": [{"area_number": 1, "lines": [{"line_number": 1, "devices": [
        {"physical_address": "1.1.0", "device_type": "coupler", "is_programmed": True,
         "product": "SV/S30.640.3.1 Power Supply,640mA,MDRC"},
        {"physical_address": "1.1.0", "device_type": "coupler",
         "product": "LK/S4.1 Line-/Area Coupler, MDRC"},
    ]}]}]}
    devices = Topology.from_dict(data).areas[0].lines[0].devices
    assert devices[0].physical_address == "1.1.-"
    assert devices[0].device_type == "power_supply"
    assert not devices[0].is_programmed
    assert devices[1].physical_address == "1.1.0"          # echter Koppler bleibt


def test_sortierung_ohne_adresse_zuerst_in_der_linie():
    addresses = ["1.1.2", "1.2.-", "1.1.-", "1.1.0", "1.2.1"]
    assert sorted(addresses, key=physical_address_key) == [
        "1.1.-", "1.1.0", "1.1.2", "1.2.-", "1.2.1",
    ]


def test_thepixa_ist_praesenzmelder():
    from knix_arranger.services.knxproj_import_service import KnxprojImportService as K
    assert K._infer_device_type("thePixa P360 KNX", []) == "sensor"
    assert K._infer_element_type("thePixa P360 KNX", []) == "Präsenzmelder"
    data = {"areas": [{"area_number": 1, "lines": [{"line_number": 1, "devices": [
        {"physical_address": "1.1.16", "device_type": "other", "product": "thePixa P360 KNX"},
    ]}]}]}
    assert Topology.from_dict(data).areas[0].lines[0].devices[0].device_type == "sensor"
