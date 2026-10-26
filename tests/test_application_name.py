"""Applikation beim knxproj-Import: deutscher Name mit Version statt ETS-Kennung."""
from __future__ import annotations
import zipfile
import xml.etree.ElementTree as ET

from knix_arranger.models.topology import Device
from knix_arranger.services.knxproj_import_service import (
    KnxprojImportService, _application_label,
)

NS = "http://knx.org/xml/project/23"
MFR = "M-0002"
APP = f"{MFR}_A-4701-11-5949"
H2P = f"{MFR}_H-SA_HP-4A22-11-F93B-O0007-4A22-21-3873-O0007"   # zwei Applikationen


def _app_xml(name="Switch Logic Status Time/5", version="17", german=True) -> str:
    translation = f"""
      <Languages><Language Identifier="de-DE"><TranslationUnit RefId="{APP}">
        <TranslationElement RefId="{APP}">
          <Translation AttributeName="Name" Text="Schalten Logik Status Zeit/5"/>
        </TranslationElement>
      </TranslationUnit></Language></Languages>""" if german else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><ManufacturerData><Manufacturer RefId="{MFR}">
  <ApplicationPrograms>
    <ApplicationProgram Id="{APP}" Name="{name}" ApplicationVersion="{version}"/>
  </ApplicationPrograms>{translation}
</Manufacturer></ManufacturerData></KNX>"""


def _label(**kw) -> str:
    root = ET.fromstring(_app_xml(**kw))
    app = next(root.iter(f"{{{NS}}}ApplicationProgram"))
    return _application_label(root, app)


def test_deutscher_name_mit_version():
    assert _label() == "Schalten Logik Status Zeit/5 (V1.1)"
    assert _label(german=False) == "Switch Logic Status Time/5 (V1.1)"
    assert _label(name="Wetterstation V1.2", version="18", german=False) == "Wetterstation V1.2"
    assert _label(version="", german=False) == "Switch Logic Status Time/5"


def test_import_traegt_applikation_ein(tmp_path):
    hardware = f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><ManufacturerData><Manufacturer RefId="{MFR}"><Hardware>
  <Hardware Id="{MFR}_H-SA" Name="SA/S8.16.1">
    <Products><Product Id="{MFR}_H-SA_P-SA" Text="SA/S8.16.1" OrderNumber="SA"/></Products>
    <Hardware2Programs><Hardware2Program Id="{H2P}">
      <ApplicationProgramRef RefId="{APP}"/>
    </Hardware2Program></Hardware2Programs>
  </Hardware>
</Hardware></Manufacturer></ManufacturerData></KNX>"""
    main = f"""<?xml version="1.0" encoding="utf-8"?>
<KNX xmlns="{NS}"><Project Id="P-TEST"><Installations><Installation Name="">
  <Topology><Area Id="P-TEST-0_A-1" Address="1"><Line Id="P-TEST-0_L-1" Address="1">
    <Segment Id="P-TEST-0_S-1"><DeviceInstance Id="P-TEST-0_DI-1" Address="1"
      ProductRefId="{MFR}_H-SA_P-SA" Hardware2ProgramRefId="{H2P}"/></Segment>
  </Line></Area></Topology>
</Installation></Installations></Project></KNX>"""
    path = tmp_path / "p.knxproj"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{MFR}/Hardware.xml", hardware)
        zf.writestr(f"{MFR}/{APP}.xml", _app_xml())
        zf.writestr("P-TEST/project.xml", f'<?xml version="1.0" encoding="utf-8"?>'
                    f'<KNX xmlns="{NS}"><Project Id="P-TEST"><ProjectInformation Name="A"/>'
                    f'</Project></KNX>')
        zf.writestr("P-TEST/0.xml", main)
    project = KnxprojImportService().import_knxproj(str(path))
    device = project.topology.areas[0].lines[0].devices[0]
    assert device.application_program == "Schalten Logik Status Zeit/5 (V1.1)"
    assert device.hw2prog_id == H2P


def test_alte_ets_kennung_wird_beim_laden_entfernt():
    old = Device.from_dict({"application_program": H2P, "hw2prog_id": H2P})
    assert old.application_program == "" and old.hw2prog_id == H2P
    named = Device.from_dict({"application_program": "Binär, 4f20M/1"})
    assert named.application_program == "Binär, 4f20M/1"
