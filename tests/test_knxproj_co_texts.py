"""
KO-Texte, Flags und Module beim .knxproj-Import: so, wie die ETS sie zeigt
(deutsche Übersetzung, Textparameter, Änderungen am einzelnen KO, Module mit
Argumenten aus dem Projekt oder über Zähler).
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import pytest

from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.knxproj_import_service import KnxprojImportService
from knix_arranger.services.ko_links import (
    COMMUNICATE, READ, TRANSMIT, UPDATE, WRITE, parse_flags,
)

_NS = "http://knx.org/xml/project/23"
AP = "M-0048_A-0001-11-ABCD"

APP_XML = f"""<KNX xmlns="{_NS}"><ManufacturerData><Manufacturer><ApplicationPrograms>
<ApplicationProgram Id="{AP}" Name="Test">
 <Static>
  <Parameters>
   <Parameter Id="{AP}_P-1" Name="Name1" Value="" />
  </Parameters>
  <ParameterRefs><ParameterRef Id="{AP}_P-1_R-1" RefId="{AP}_P-1" /></ParameterRefs>
  <ComObjectTable>
   <ComObject Id="{AP}_O-0" Name="Object 1" Text="Object 1" Number="0" FunctionText=""
     ObjectSize="1 Byte" Priority="Low" CommunicationFlag="Enabled" ReadFlag="Enabled"
     WriteFlag="Enabled" TransmitFlag="Enabled" UpdateFlag="Enabled" ReadOnInitFlag="Disabled" />
   <ComObject Id="{AP}_O-1" Name="Out" Text="Output {{{{0:A}}}}" Number="1" FunctionText="Switch"
     ObjectSize="1 Bit" CommunicationFlag="Enabled" WriteFlag="Enabled" />
  </ComObjectTable>
  <ComObjectRefs>
   <ComObjectRef Id="{AP}_O-0_R-1" RefId="{AP}_O-0" Text="Button 1, left" FunctionText="ON/OFF"
     ObjectSize="1 Bit" ReadFlag="Disabled" UpdateFlag="Disabled" />
   <ComObjectRef Id="{AP}_O-1_R-2" RefId="{AP}_O-1" TextParameterRefId="{AP}_P-1_R-1" />
  </ComObjectRefs>
  <Allocators><Allocator Id="{AP}_L-1" Name="Obj" Start="85" /></Allocators>
 </Static>
 <ModuleDefs>
  <ModuleDef Id="{AP}_MD-2" Name="Group">
   <Arguments>
    <Argument Id="{AP}_MD-2_A-2" Name="ObjNumberBase" Allocates="34" />
    <Argument Id="{AP}_MD-2_A-3" Name="GRP_NO" Allocates="1" />
   </Arguments>
   <Static>
    <Parameters><Parameter Id="{AP}_MD-2_P-2" Name="Desc" Value="" /></Parameters>
    <ParameterRefs><ParameterRef Id="{AP}_MD-2_P-2_R-2" RefId="{AP}_MD-2_P-2" /></ParameterRefs>
    <ComObjects>
     <ComObject Id="{AP}_MD-2_O-2-0" Name="Group 1, Switching" Text="Group 1, Switching" Number="0"
       FunctionText="On/Off" ObjectSize="1 Bit" CommunicationFlag="Enabled" WriteFlag="Enabled"
       BaseNumber="{AP}_MD-2_A-2" />
    </ComObjects>
    <ComObjectRefs>
     <ComObjectRef Id="{AP}_MD-2_O-2-0_R-10" RefId="{AP}_MD-2_O-2-0"
       Text="G{{{{GRP_NO}}}}, Switching, {{{{0}}}}" TextParameterRefId="{AP}_MD-2_P-2_R-2" />
    </ComObjectRefs>
   </Static>
  </ModuleDef>
 </ModuleDefs>
 <Dynamic>
  <Repeat Id="{AP}_X-1" Count="16">
   <Module Id="{AP}_MD-2_M-3" RefId="{AP}_MD-2">
    <NumericArg RefId="{AP}_MD-2_A-2" AllocatorRefId="{AP}_L-1" />
    <NumericArg RefId="{AP}_MD-2_A-3" AllocatorRefId="{AP}_L-2" />
   </Module>
  </Repeat>
 </Dynamic>
</ApplicationProgram>
</ApplicationPrograms>
<Languages><Language Identifier="de-DE">
 <TranslationUnit RefId="{AP}">
  <TranslationElement RefId="{AP}_O-0_R-1">
   <Translation AttributeName="Text" Text="Taste 1, links" />
   <Translation AttributeName="FunctionText" Text="EIN/AUS, Dimmen" />
  </TranslationElement>
  <TranslationElement RefId="{AP}_O-1_R-2">
   <Translation AttributeName="Text" Text="Ausgang {{{{0:A}}}}" />
   <Translation AttributeName="FunctionText" Text="Schalten" />
  </TranslationElement>
  <TranslationElement RefId="{AP}_MD-2_O-2-0_R-10">
   <Translation AttributeName="Text" Text="G{{{{GRP_NO}}}}, Schalten, {{{{0}}}}" />
   <Translation AttributeName="FunctionText" Text="An/Aus" />
  </TranslationElement>
 </TranslationUnit>
</Language></Languages>
</Manufacturer></ManufacturerData></KNX>"""


@pytest.fixture
def service():
    svc = KnxprojImportService()
    root = ET.fromstring(APP_XML)
    lookup: dict = {}
    svc._extract_app_co_refs(root, lookup)
    for app in root.iter(f"{{{_NS}}}ApplicationProgram"):
        svc._app_context[app.get("Id")] = svc._read_app_context(app)
    # Zähler für GRP_NO (Start 1), im Fixture-XML nicht als Element
    svc._app_context[AP]["allocators"][f"{AP}_L-2"] = 1
    svc.lookup = lookup
    return svc


def _device(xml: str) -> ET.Element:
    return ET.fromstring(f'<DeviceInstance xmlns="{_NS}">{xml}</DeviceInstance>')


def _resolve(svc, di: ET.Element, ref_id: str) -> dict:
    instance = next(e for e in di.iter(f"{{{_NS}}}ComObjectInstanceRef")
                    if e.get("RefId") == ref_id)
    return svc._resolve_co(AP, instance, svc.lookup, svc._device_parameters(di, AP),
                           svc._project_module_arguments(di))


def test_name_is_translated_text_not_internal_name(service):
    """Feller EDIZIOdue: ETS zeigt «Taste 1, links», nicht «Object 1»."""
    di = _device('<ComObjectInstanceRefs><ComObjectInstanceRef RefId="O-0_R-1" />'
                 '</ComObjectInstanceRefs>')
    attrs = _resolve(service, di, "O-0_R-1")
    assert service._co_name(attrs) == "Taste 1, links"
    assert attrs["FunctionText"] == "EIN/AUS, Dimmen"
    # ReadFlag der Ref gilt, auch ohne WriteFlag an der Ref
    assert parse_flags(service._co_flags(attrs)) == {COMMUNICATE, WRITE, TRANSMIT}


def test_instance_changes_override_application(service):
    di = _device('<ComObjectInstanceRefs><ComObjectInstanceRef RefId="O-0_R-1" '
                 'Text="Licht Küche" ReadFlag="Enabled" TransmitFlag="Disabled" />'
                 '</ComObjectInstanceRefs>')
    attrs = _resolve(service, di, "O-0_R-1")
    assert service._co_name(attrs) == "Licht Küche"
    assert parse_flags(service._co_flags(attrs)) == {COMMUNICATE, READ, WRITE}


def test_text_parameter_from_project_else_placeholder_default(service):
    di = _device('<ParameterInstanceRefs><ParameterInstanceRef '
                 f'RefId="{AP}_P-1_R-1" Value="Küche" /></ParameterInstanceRefs>'
                 '<ComObjectInstanceRefs><ComObjectInstanceRef RefId="O-1_R-2" />'
                 '</ComObjectInstanceRefs>')
    assert service._co_name(_resolve(service, di, "O-1_R-2")) == "Ausgang Küche"
    di = _device('<ComObjectInstanceRefs><ComObjectInstanceRef RefId="O-1_R-2" />'
                 '</ComObjectInstanceRefs>')
    assert service._co_name(_resolve(service, di, "O-1_R-2")) == "Ausgang A"


def test_module_by_allocator_with_instance_text_parameter(service):
    """Theben DALI: Nummer = Zähler-Start + (Instanz - 1) * Allocates + KO."""
    di = _device('<ParameterInstanceRefs><ParameterInstanceRef '
                 f'RefId="{AP}_MD-2_M-3_MI-2_P-2_R-2" Value="LDA.OG.05.02" />'
                 '</ParameterInstanceRefs><ComObjectInstanceRefs>'
                 '<ComObjectInstanceRef RefId="MD-2_M-3_MI-2_O-2-0_R-10" />'
                 '</ComObjectInstanceRefs>')
    attrs = _resolve(service, di, "MD-2_M-3_MI-2_O-2-0_R-10")
    assert attrs["Number"] == str(85 + 34)
    assert service._co_name(attrs) == "G2, Schalten, LDA.OG.05.02"


def test_module_arguments_stored_in_project_win(service):
    """Theben thePixa: die ETS legt die Argumente der Instanz im Projekt ab."""
    di = _device('<ModuleInstances><ModuleInstance Id="MD-2_M-3_MI-1" RefId="MD-2_M-3">'
                 '<Arguments><Argument RefId="MD-2_A-2" Value="10" />'
                 '<Argument RefId="MD-2_A-3" Value="7" /></Arguments>'
                 '</ModuleInstance></ModuleInstances><ComObjectInstanceRefs>'
                 '<ComObjectInstanceRef RefId="MD-2_M-3_MI-1_O-2-0_R-10" />'
                 '</ComObjectInstanceRefs>')
    attrs = _resolve(service, di, "MD-2_M-3_MI-1_O-2-0_R-10")
    assert attrs["Number"] == "10"
    assert service._co_name(attrs) == "G7, Schalten,"      # wie in der ETS


def test_inactive_variants_dropped_linked_kept():
    device = Device(physical_address="1.1.1")
    device.communication_objects = [
        CommunicationObject(object_number=0, name="Ausgang A", object_function="UND"),
        CommunicationObject(object_number=0, name="Ausgang A", object_function="Schalten",
                            connected_gas=["1/0/0"]),
        CommunicationObject(object_number=0, name="Ausgang A", object_function="ODER"),
        CommunicationObject(object_number=1, name="Ausgang B", object_function="UND"),
        CommunicationObject(object_number=1, name="Ausgang B", object_function="ODER"),
    ]
    metas = [{}, {}, {}, {}, {}]
    KnxprojImportService._drop_inactive_variants(device, metas)
    assert [(c.object_number, c.object_function) for c in device.communication_objects] == [
        (0, "Schalten"), (1, "UND")]
    assert len(metas) == 2


def test_old_knxproj_flag_format_keeps_read_flag():
    """Bis 1.4.23 «K S U E A I»: «UE» heisst Übertragen + Lesen, nicht Ü."""
    assert parse_flags("KSUEA-") == {COMMUNICATE, WRITE, TRANSMIT, READ, UPDATE}
    assert parse_flags("K--E--") == {COMMUNICATE, READ}
    assert parse_flags("KLSÜA-") == {COMMUNICATE, READ, WRITE, TRANSMIT, UPDATE}


# -- Abgleich mit dem ETS-Topologie-Report desselben Projekts ---------------

_ROOT = os.path.join(os.path.dirname(__file__), "..")
P19_PROJ = os.path.join(_ROOT, "P19_Salzmann", "P19_Software",
                        "260618_visp_efh salzmann pascal.knxproj")
P19_REPORT = os.path.join(_ROOT, "P19_Salzmann", "P19_Dokumente", "P19_Topologie.xlsx")
CHALET = os.path.join(_ROOT, "241114_Chalet 64.knxproj")


def _kos(topology) -> dict:
    return {(d.physical_address, c.object_number): c
            for a in topology.areas for l in a.lines for d in l.devices
            for c in d.communication_objects}


@pytest.mark.skipif(not (os.path.exists(P19_PROJ) and os.path.exists(P19_REPORT)),
                    reason="P19-Projektdateien fehlen")
def test_knxproj_matches_topology_report():
    pytest.importorskip("openpyxl")
    from knix_arranger.services.xlsx_import_service import XlsxImportService
    from_proj = _kos(KnxprojImportService().import_knxproj(P19_PROJ).topology)
    from_report = _kos(XlsxImportService().import_xlsx(P19_REPORT))
    # Auch nicht verknüpfte KOs (aus den Parametern) und je Nummer die aktive
    # Variante (MDT KO 59 «Betriebsart»)
    assert set(from_proj) == set(from_report)
    common = set(from_report)
    assert all(from_proj[k].name == from_report[k].name for k in common)
    assert all(from_proj[k].object_function == from_report[k].object_function for k in common)
    # DPT je KO: wo der Report eine Kennung ergibt, dieselbe
    assert all(from_proj[k].data_type == from_report[k].data_type for k in common
               if from_report[k].data_type.startswith("DP"))
    assert all(parse_flags(from_proj[k].flags) == parse_flags(from_report[k].flags)
               for k in common)
    assert all(sorted(from_proj[k].connected_gas) == sorted(from_report[k].connected_gas)
               for k in common)


@pytest.mark.skipif(not os.path.exists(CHALET), reason="Referenzprojekt fehlt")
def test_module_kos_resolved_in_reference_project():
    kos = _kos(KnxprojImportService().import_knxproj(CHALET).topology)
    assert kos[("1.1.16", 17)].name == "Z1 freies Schalten"
    assert kos[("1.1.16", 22)].name == "Z1 Helligkeitswert"
    assert not any(c.name.startswith(("MD-", "O-")) for c in kos.values())
