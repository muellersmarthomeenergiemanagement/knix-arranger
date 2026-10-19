"""Stufe 2: Module (ModuleDef) der Herstellerdatei -- MDT Glastaster II Smart
mit «ModuleDefOneButton» je Funktion F1, F2 …: KO-Nummer = Basis-Argument +
relative Nummer, Texte mit Argumenten, Parameter je Instanz. Dazu die
Zuordnung bei Tastern, deren Befehle nur senden, und Rückmeldungen im Zweig
ihres Befehls."""
from __future__ import annotations

import os

from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.ets_parameters import (
    settings_for, variant_settings, views_compatible,
)
from knix_arranger.services.knxprod_catalog_service import (
    KnxprodCatalogService, product_fixed_values, reduce_alternatives, when_matches,
)
from knix_arranger.services.sensor_channels import SensorLink, suggested_sensor_co_map
from tests.test_knxprod_catalog_service import _build_knxprod

_APP = "M-0001_A-0001-01"
_MD = f"{_APP}_MD-1"
# Ein Baustein «Taste» mit Funktion Schalten (0) oder Jalousie (1); KO 0/1
# relativ, Basis über das Argument ObjNumberBase; zwei Instanzen F1, F2
_BODY = f"""
  <ParameterTypes>
    <ParameterType Id="{_APP}_PT-Fn" Name="Fn"><TypeRestriction Base="Value">
      <Enumeration Id="{_APP}_PT-Fn_EN-0" Value="0" Text="Schalten"/>
      <Enumeration Id="{_APP}_PT-Fn_EN-1" Value="1" Text="Jalousie"/>
    </TypeRestriction></ParameterType>
  </ParameterTypes>
  <ModuleDefs>
    <ModuleDef Id="{_MD}" Name="OneButton">
      <Arguments>
        <Argument Id="{_MD}_A-1" Name="ObjNumberBase"/>
        <Argument Id="{_MD}_A-2" Name="ChNo"/>
      </Arguments>
      <Static>
        <Parameters>
          <Parameter Id="{_MD}_P-1" Name="Fn" ParameterType="{_APP}_PT-Fn" Text="Funktion" Value="0"/>
          <Parameter Id="{_MD}_P-2" Name="Txt" ParameterType="{_APP}_PT-Fn" Text="Text" Value=""/>
        </Parameters>
        <ParameterRefs>
          <ParameterRef Id="{_MD}_P-1_R-1" RefId="{_MD}_P-1"/>
          <ParameterRef Id="{_MD}_P-2_R-2" RefId="{_MD}_P-2"/>
        </ParameterRefs>
        <ComObjects>
          <ComObject Id="{_MD}_O-2-0" Number="0" Text="Taste" FunctionText="x" ObjectSize="1 Bit"
                     CommunicationFlag="Enabled" TransmitFlag="Enabled" BaseNumber="{_MD}_A-1"/>
          <ComObject Id="{_MD}_O-2-1" Number="1" Text="Taste" FunctionText="x" ObjectSize="1 Bit"
                     CommunicationFlag="Enabled" TransmitFlag="Enabled" WriteFlag="Enabled"
                     BaseNumber="{_MD}_A-1"/>
        </ComObjects>
        <ComObjectRefs>
          <ComObjectRef Id="{_MD}_O-2-0_R-1" RefId="{_MD}_O-2-0" Text="F{{{{ChNo}}}}: {{{{0}}}}"
                        FunctionText="Schalten" TextParameterRefId="{_MD}_P-2_R-2"/>
          <ComObjectRef Id="{_MD}_O-2-1_R-2" RefId="{_MD}_O-2-1" Text="F{{{{ChNo}}}}: {{{{0}}}}"
                        FunctionText="Status für Anzeige" TextParameterRefId="{_MD}_P-2_R-2"/>
          <ComObjectRef Id="{_MD}_O-2-0_R-3" RefId="{_MD}_O-2-0" Text="F{{{{ChNo}}}}: {{{{0}}}}"
                        FunctionText="Jalousie Auf/Ab" TextParameterRefId="{_MD}_P-2_R-2"/>
        </ComObjectRefs>
      </Static>
      <Dynamic>
        <ParameterBlock Id="{_MD}_PB-1" Text="F{{{{ChNo}}}}: {{{{0}}}}">
          <ParameterRefRef RefId="{_MD}_P-1_R-1"/>
          <choose ParamRefId="{_MD}_P-1_R-1">
            <when test="0">
              <ComObjectRefRef RefId="{_MD}_O-2-0_R-1"/>
              <ComObjectRefRef RefId="{_MD}_O-2-1_R-2"/>
            </when>
            <when test="1"><ComObjectRefRef RefId="{_MD}_O-2-0_R-3"/></when>
          </choose>
        </ParameterBlock>
      </Dynamic>
    </ModuleDef>
  </ModuleDefs>
</Static>
<Dynamic>
  <Channel Id="{_APP}_CH-1" Text="Tasten">
    <Module Id="{_MD}_M-1" RefId="{_MD}">
      <NumericArg RefId="{_MD}_A-1" Value="0"/><NumericArg RefId="{_MD}_A-2" Value="1"/>
    </Module>
    <Module Id="{_MD}_M-2" RefId="{_MD}">
      <NumericArg RefId="{_MD}_A-1" Value="7"/><NumericArg RefId="{_MD}_A-2" Value="2"/>
    </Module>
  </Channel>
</Dynamic>
<Static>
"""


def _product():
    path = _build_knxprod(_BODY)
    try:
        return KnxprodCatalogService().import_file(path)[0]
    finally:
        os.remove(path)


def test_module_instances_get_numbers_names_and_own_parameters():
    product = _product()
    numbers = sorted({(co.number, co.name, co.function_text) for co in product.com_objects})
    assert numbers == [(0, "F1", "Jalousie Auf/Ab"), (0, "F1", "Schalten"),
                       (1, "F1", "Status für Anzeige"), (7, "F2", "Jalousie Auf/Ab"),
                       (7, "F2", "Schalten"), (8, "F2", "Status für Anzeige")]
    blocks = sorted(info[0] for info in product.parameters.values())
    assert blocks == ["F1", "F2"]          # ein Parameter je Instanz
    f2 = next(co for co in product.com_objects if co.number == 7 and co.function_text == "Schalten")
    cos = [co.to_dict() for co in product.com_objects]
    settings = variant_settings(f2.to_dict(), [c for c in cos if c["number"] == 7],
                                product.parameters)
    assert [s.text() for s in settings] == ["F2 › Funktion: Schalten"]


def test_alternatives_compare_what_the_ets_shows():
    """Feller: «Funktion Taste» je Szenen-Zweig ein eigener Parameter, gleich
    benannt -- die Zweige unterscheiden sich nur in der Szenenfunktion."""
    views = {"sz_lokal": ("Konfig", "Szenen"), "fn_a": ("Taste 1", "Funktion"),
             "fn_b": ("Taste 1", "Funktion")}
    chains = [[("sz_lokal", "0"), ("fn_a", "3")], [("sz_lokal", "1"), ("fn_b", "3")]]
    assert reduce_alternatives(chains, lambda p, t: (views[p], t)) == [[["fn_a", "3"]]]
    # ohne Sicht (Kennungen): zwei getrennte Alternativen
    assert len(reduce_alternatives(chains)) == 2


def test_product_fixes_shared_application_parameter():
    params = {"P-1": ["Allgemein", "Art des Grundmoduls",
                      {"0": "Gerät auswählen..", "3": "HMG 6 T..", "4": "RMG 8 S.."}, True]}
    assert product_fixed_values(params, "HMG 6 T", "4930240") == {"P-1": "3"}
    assert product_fixed_values(params, "DM 4 T", "4940275") == {}
    assert when_matches("1 3 5", "3") and when_matches(">2", "3") and not when_matches("!=3", "3")


def _link(channel, code, function, dpt, feedback):
    return SensorLink(key=f"a|{code}|1|{function}", channel=channel, function=function,
                      ga_address="", ga_designation="", ga_function=function, dpt=dpt,
                      feedback=feedback)


def test_send_only_commands_and_feedback_in_same_branch():
    """MDT: Befehle senden nur (K Ü) -- kein Rückmelde-KO. Die Rückmeldung
    kommt aus demselben Zweig wie der Befehl."""
    def co(number, function, flags, view):
        c = CommunicationObject(object_number=number, name="F1", object_function=function,
                                object_size="1 Bit", flags=flags)
        c.families, c.condition_views = frozenset({"schalten"}), [view]
        return c
    schalten = {("F1", "Unterfunktion"): "Schalten"}
    zustand = {("F1", "Unterfunktion"): "Zustand senden"}
    cos = [co(0, "Schalten", "K--Ü--", schalten),
           co(3, "Status für Anzeige", "K-SÜ--", zustand),
           co(1, "Status für Anzeige", "K-SÜ--", schalten)]
    device = Device(device_type="sensor", communication_objects=cos)
    links = [_link("Taste 1 kurz", "L", "E/A", "DPST-1-1", False),
             _link("Status 1", "L", "RM", "DPST-1-1", True)]
    result = suggested_sensor_co_map(device, links, cos)
    assert (result["a|L|1|E/A"], result["a|L|1|RM"]) == (0, 1)
    assert not views_compatible(cos[0], cos[1]) and views_compatible(cos[0], cos[2])


def test_double_click_only_if_nothing_else():
    def co(number, name, function):
        return CommunicationObject(object_number=number, name=name, object_function=function,
                                   object_size="1 Bit", flags="K--Ü--")
    cos = [co(10, "Taste 2, Doppelklick", "AUF/AB, fahren Beschattung"),
           co(6, "Taste 2", "AUF/AB, Jalousie")]
    device = Device(device_type="sensor", communication_objects=cos)
    links = [_link("Taste 2 lang", "J", "AUF/AB", "DPST-1-8", False)]
    assert suggested_sensor_co_map(device, links, cos) == {"a|J|1|AUF/AB": 6}
