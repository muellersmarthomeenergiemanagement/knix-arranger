"""
Parameter eines Geräts aus der .knxproj wie unter «Geräteparameter» im
ETS-Report (ets_parameter_view): sichtbare Seiten und Werte, aktive KOs,
daraus Tastenbelegung, Szenenwerte und Szenenauslöser.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import pytest

from knix_arranger.services import ets_parameter_view as view
from knix_arranger.services.ets_parameter_view import ApplicationParameters, ParameterPage

_NS = "http://knx.org/xml/project/23"
AP = "M-001E_A-0001-10-ABCD"


def _app(dynamic: str, static: str = "", module_defs: str = "") -> ApplicationParameters:
    xml = f"""<ApplicationProgram xmlns="{_NS}" Id="{AP}">
      <Static>
        <ParameterTypes>
          <ParameterType Id="{AP}_PT-Count">
            <TypeRestriction Base="Value" SizeInBit="2">
              <Enumeration Id="{AP}_PT-Count_EN-0" Text="1" Value="0" />
              <Enumeration Id="{AP}_PT-Count_EN-1" Text="2" Value="1" />
            </TypeRestriction>
          </ParameterType>
          <ParameterType Id="{AP}_PT-Num"><TypeNumber SizeInBit="8" minInclusive="0" maxInclusive="255" /></ParameterType>
        </ParameterTypes>
        <Parameters>
          <Parameter Id="{AP}_P-1" Name="Anzahl" ParameterType="{AP}_PT-Count" Text="Anzahl Tasten:" Value="0" />
          <Parameter Id="{AP}_P-2" Name="Phil" ParameterType="{AP}_PT-Count" Text="Bedienung:" Value="0" />
          <Parameter Id="{AP}_P-3" Name="Hidden" ParameterType="{AP}_PT-Num" Text="intern" Value="0" Access="None" />
          <Parameter Id="{AP}_P-4" Name="Hell" ParameterType="{AP}_PT-Num" Text="Helligkeit" Value="100" SuffixText="%" />
          <Parameter Id="{AP}_P-9" Name="Seite" ParameterType="{AP}_PT-Num" Text="Konfiguration Tasten" Value="0" />
          <Parameter Id="{AP}_P-10" Name="Seite2" ParameterType="{AP}_PT-Num" Text="Taste 1" Value="0" />
          <Parameter Id="{AP}_P-11" Name="Seite3" ParameterType="{AP}_PT-Num" Text="Allgemein" Value="0" />
          {static}
        </Parameters>
        <ParameterRefs>
          <ParameterRef Id="{AP}_P-1_R-1" RefId="{AP}_P-1" DisplayOrder="10" />
          <ParameterRef Id="{AP}_P-2_R-2" RefId="{AP}_P-2" DisplayOrder="20" />
          <ParameterRef Id="{AP}_P-2_R-3" RefId="{AP}_P-2" DisplayOrder="20" />
          <ParameterRef Id="{AP}_P-3_R-4" RefId="{AP}_P-3" />
          <ParameterRef Id="{AP}_P-4_R-5" RefId="{AP}_P-4" DisplayOrder="5" />
          <ParameterRef Id="{AP}_P-9_R-9" RefId="{AP}_P-9" DisplayOrder="500" />
          <ParameterRef Id="{AP}_P-10_R-10" RefId="{AP}_P-10" DisplayOrder="1000" />
          <ParameterRef Id="{AP}_P-11_R-11" RefId="{AP}_P-11" DisplayOrder="100" />
        </ParameterRefs>
      </Static>
      <ModuleDefs>{module_defs}</ModuleDefs>
      <Dynamic>{dynamic}</Dynamic>
    </ApplicationProgram>"""
    program = ET.fromstring(xml)
    texts = {f"{AP}_PT-Count_EN-1": {"Text": "zwei"}}
    return ApplicationParameters(program, texts)


BUTTONS = f"""
<ChannelIndependentBlock>
 <ParameterBlock Id="{AP}_PB-1" Name="Konfig" ParamRefId="{AP}_P-9_R-9">
  <ParameterRefRef RefId="{AP}_P-1_R-1" />
  <ParameterRefRef RefId="{AP}_P-3_R-4" />
  <choose ParamRefId="{AP}_P-1_R-1">
   <when test="0"><ParameterRefRef RefId="{AP}_P-2_R-2" /></when>
   <when test="1"><ParameterRefRef RefId="{AP}_P-2_R-3" />
     <ComObjectRefRef RefId="{AP}_O-1_R-1" /></when>
  </choose>
  <ParameterRefRef RefId="{AP}_P-4_R-5" />
 </ParameterBlock>
 <ParameterBlock Id="{AP}_PB-2" Name="Taste" ParamRefId="{AP}_P-10_R-10">
  <ParameterSeparator Id="{AP}_PS-1" Text="Taste links" />
  <ParameterRefRef RefId="{AP}_P-4_R-5" />
 </ParameterBlock>
 <ParameterBlock Id="{AP}_PB-3" Name="Leerseite" />
 <ParameterBlock Id="{AP}_PB-4" Name="Allg" ParamRefId="{AP}_P-11_R-11" />
</ChannelIndependentBlock>"""


def _titles(params) -> list[str]:
    return [p.title for p in params.pages]


def test_pages_ordered_like_ets_and_untitled_pages_dropped():
    params = _app(BUTTONS).evaluate({})
    # DisplayOrder des Titelparameters: Allgemein (100) vor Konfiguration (500)
    assert _titles(params) == ["Allgemein", "Konfiguration Tasten", "Taste 1"]


def test_branch_by_value_per_parameter_ref():
    app = _app(BUTTONS)
    params = app.evaluate({})
    konfig = params.pages[1]
    # Einträge nach DisplayOrder: Helligkeit (5) zuerst; unsichtbarer Parameter fehlt
    assert konfig.entries == [("Helligkeit", "100 %"), ("Anzahl Tasten:", "1"),
                              ("Bedienung:", "1")]
    assert (("", f"{AP}_O-1_R-1") in params.active_cos) is False
    # Wert an der Ref R-3 gilt nur für R-3 (die ETS führt Werte je Ref)
    params = app.evaluate({f"{AP}_P-1_R-1": "1", f"{AP}_P-2_R-2": "1"})
    assert params.pages[1].entries[1:] == [("Anzahl Tasten:", "zwei"), ("Bedienung:", "1")]
    assert ("", f"{AP}_O-1_R-1") in params.active_cos


def test_assign_sets_parameter_for_later_choose():
    dynamic = f"""<ChannelIndependentBlock>
      <choose ParamRefId="{AP}_P-1_R-1"><when test="0">
        <Assign TargetParamRefRef="{AP}_P-3_R-4" Value="7" /></when></choose>
      <choose ParamRefId="{AP}_P-3_R-4"><when test="7">
        <ComObjectRefRef RefId="{AP}_O-2_R-2" /></when></choose>
    </ChannelIndependentBlock>"""
    assert ("", f"{AP}_O-2_R-2") in _app(dynamic).evaluate({}).active_cos


def test_channel_joined_like_report_and_module_instance_values():
    module_defs = f"""<ModuleDef Id="{AP}_MD-1" Name="Kanal">
      <Arguments><Argument Id="{AP}_MD-1_A-1" Name="Nr" /></Arguments>
      <Static><Parameters>
        <Parameter Id="{AP}_MD-1_P-1" Name="Szene" ParameterType="{AP}_PT-Num"
          Text="Ausgangszustand für&#10;Szene {{{{Nr}}}}" Value="0" /></Parameters>
        <ParameterRefs><ParameterRef Id="{AP}_MD-1_P-1_R-1" RefId="{AP}_MD-1_P-1" /></ParameterRefs>
      </Static>
      <Dynamic><ParameterBlock Id="{AP}_MD-1_PB-1" Name="b" Text="Funktionsfreigabe">
        <ParameterRefRef RefId="{AP}_MD-1_P-1_R-1" /></ParameterBlock></Dynamic>
    </ModuleDef>"""
    dynamic = f"""<Channel Id="{AP}_CH-1" Name="c" Text="Ausgang 1" Number="1">
      <Module Id="{AP}_MD-1_M-1" RefId="{AP}_MD-1"><NumericArg RefId="{AP}_MD-1_A-1" Value="2" /></Module>
    </Channel>"""
    app = _app(dynamic, module_defs=module_defs)
    params = app.evaluate({f"{AP}_MD-1_M-1_MI-1_P-1_R-1": "5"},
                          lambda md, use, index: {f"{AP}_MD-1_A-1": "2"})
    page = params.pages[0]
    assert page.title == "Ausgang 1 > Funktionsfreigabe"
    assert page.entries == [("Ausgangszustand für\nSzene 2", "5")]


def test_button_configuration_and_triggers_from_pages():
    pages = [
        ParameterPage("Sperren Tasten", [("Taste 1:", "Ja")]),
        ParameterPage("Konfiguration Tasten", [("Anzahl Tasten:", "2"), ("Trenner", None)]),
        ParameterPage("   Taste 1, links", [("Funktion Taste:", "Wert"),
                                            ("      1Byte Wert (0..255):", "0"),
                                            ("Langer Tastendruck Taste links:", "aktiv"),
                                            ("1Byte Wert (0..255):", "2")]),
        ParameterPage("Helligkeit LED", [("LED:", "100 %")]),
    ]
    assert view.button_configuration(pages) == (
        "Anzahl Tasten: 2\n\nTaste 1, links:\n  Funktion Taste: Wert\n"
        "  1Byte Wert (0..255): 0\n  Langer Tastendruck Taste links: aktiv\n"
        "  1Byte Wert (0..255): 2")
    triggers = [(t.button, t.scene_number) for t in view.scene_triggers(pages)]
    assert triggers == [("Taste 1, links", 1), ("Taste 1, links (langer Tastendruck)", 3)]


def test_scene_values_abb_and_hager():
    pages = [
        # ABB: Zeilenumbruch im Text fällt wie im Report weg
        ParameterPage("A: Szene", [("Ausgang zuordnen zu\r\n(Szene 1...64)", "Szene 2"),
                                   ("Standardwert", "AUS"),
                                   ("Ausgang zugeodnet zu\r\n(Szene 1...64)", "keiner Szene"),
                                   ("Standardwert", "EIN")]),
        ParameterPage("Ausgang 3 > Ausgang 3: Funktionsfreigabe",
                      [("Szene 2", "1"), ("Ausgangszustand für Szene 2", "Aus")]),
    ]
    values = [(v.channel, v.scene_number, v.value) for v in view.scene_values(pages)]
    assert values == [("A", 2, "AUS"), ("Ausgang 3", 2, "Aus")]


# -- Abgleich mit den Reports von Chalet Franziska --------------------------
# Die .knxproj hat ein Passwort; es steht nicht im Repository. Lokal:
# KNIX_TEST_FRANZISKA_PASSWORD setzen.

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_DIR = os.path.join(_ROOT, "Chalet Franziska 2005", "Importdateien")
FRANZISKA = os.path.join(_DIR, "261021 Chalet_Franziska_2005.knxproj")
FRANZISKA_REPORT = os.path.join(_DIR, "Topologie.xlsx")
_PASSWORD = os.environ.get("KNIX_TEST_FRANZISKA_PASSWORD", "")


@pytest.mark.skipif(not (_PASSWORD and os.path.exists(FRANZISKA)
                         and os.path.exists(FRANZISKA_REPORT)),
                    reason="Chalet-Franziska-Dateien oder Passwort fehlen")
def test_franziska_matches_topology_report():
    pytest.importorskip("openpyxl")
    from knix_arranger.services.knxproj_import_service import KnxprojImportService
    from knix_arranger.services.ko_links import parse_flags
    from knix_arranger.services.xlsx_import_service import XlsxImportService
    project = KnxprojImportService().import_knxproj(FRANZISKA, password=_PASSWORD)
    devices = {d.physical_address: d for a in project.topology.areas
               for l in a.lines for d in l.devices}
    report = XlsxImportService()

    def norm(text):
        return " ".join((text or "").replace("\xa0", " ").split())

    kos = {(d.physical_address, c.object_number): c for d in devices.values()
           for c in d.communication_objects}
    report_kos = {(d.physical_address, c.object_number): c
                  for a in report.import_xlsx(FRANZISKA_REPORT).areas
                  for l in a.lines for d in l.devices for c in d.communication_objects}
    assert set(report_kos) <= set(kos)
    for key, expected in report_kos.items():
        co = kos[key]
        assert norm(co.name) == norm(expected.name), key
        assert norm(co.object_function) == norm(expected.object_function), key
        assert parse_flags(co.flags) == parse_flags(expected.flags), key
        assert sorted(co.connected_gas) == sorted(expected.connected_gas), key

    buttons = report.extract_button_configuration(FRANZISKA_REPORT)
    assert buttons and all(devices[a].button_configuration == text
                           for a, text in buttons.items())
    for address, entries in report.extract_scene_values(FRANZISKA_REPORT).items():
        assert sorted((e.channel, e.scene_number, e.value) for e in devices[address].scene_values) \
            == sorted((e.channel, e.scene_number, e.value) for e in entries)
    for address, entries in report.extract_scene_triggers(FRANZISKA_REPORT).items():
        assert sorted((e.button, e.scene_number) for e in devices[address].scene_triggers) \
            == sorted((e.button, e.scene_number) for e in entries)
