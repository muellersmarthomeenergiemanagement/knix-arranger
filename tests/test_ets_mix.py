"""Theben MIX (READER_VERSION 5): eine Applikation für mehrere Grundmodule.
Derselbe Parameter zweimal in einer Kette («Art des Grundmoduls > 0», darin
«= 1»), dieselben KOs unter mehreren Werten («1 oder 2» statt ohne
Bedingung) und unsichtbare Parameter mit festem Wert (Access="None")."""
from __future__ import annotations

import os

from knix_arranger.services.knxprod_catalog_service import (
    KnxprodCatalogService, condition_alternatives, reduce_alternatives,
)
from tests.test_knxprod_catalog_service import _build_knxprod

_APP = "M-0001_A-0001-01"
_BODY = f"""
  <ParameterTypes>
    <ParameterType Id="{_APP}_PT-Gm" Name="Gm"><TypeRestriction Base="Value">
      <Enumeration Id="{_APP}_PT-Gm_EN-0" Value="0" Text="Gerät auswählen.."/>
      <Enumeration Id="{_APP}_PT-Gm_EN-1" Value="1" Text="RMG 8 S.."/>
      <Enumeration Id="{_APP}_PT-Gm_EN-2" Value="2" Text="RMG 8 T.."/>
      <Enumeration Id="{_APP}_PT-Gm_EN-6" Value="6" Text="HMG 6 T.."/>
    </TypeRestriction></ParameterType>
  </ParameterTypes>
  <Parameters>
    <Parameter Id="{_APP}_P-57" Name="Gm" ParameterType="{_APP}_PT-Gm"
               Text="Art des Grundmoduls" Value="0"/>
    <Parameter Id="{_APP}_P-9" Name="Hidden" ParameterType="{_APP}_PT-Gm" Text="-"
               Value="1" Access="None"/>
  </Parameters>
  <ParameterRefs>
    <ParameterRef Id="{_APP}_P-57_R-1" RefId="{_APP}_P-57"/>
    <ParameterRef Id="{_APP}_P-9_R-9" RefId="{_APP}_P-9"/>
  </ParameterRefs>
  <ComObjectTable>
    <ComObject Id="{_APP}_O-0" Number="0" Text="Modul" FunctionText="x"
               ObjectSize="1 Bit" CommunicationFlag="Enabled" WriteFlag="Enabled"/>
  </ComObjectTable>
  <ComObjectRefs>
    <ComObjectRef Id="{_APP}_O-0_R-1" RefId="{_APP}_O-0" FunctionText="Manuell"/>
    <ComObjectRef Id="{_APP}_O-0_R-2" RefId="{_APP}_O-0" FunctionText="Sperren"/>
    <ComObjectRef Id="{_APP}_O-0_R-3" RefId="{_APP}_O-0" FunctionText="Fest aktiv"/>
    <ComObjectRef Id="{_APP}_O-0_R-4" RefId="{_APP}_O-0" FunctionText="Nie aktiv"/>
  </ComObjectRefs>
</Static>
<Dynamic>
  <Channel Id="{_APP}_CH-1" Text="Generic">
    <ParameterBlock Id="{_APP}_PB-1" Text="Allgemein">
      <ParameterRefRef RefId="{_APP}_P-57_R-1"/>
    </ParameterBlock>
    <choose ParamRefId="{_APP}_P-57_R-1">
      <when test="&gt;0">
        <choose ParamRefId="{_APP}_P-57_R-1">
          <when test="1">
            <ComObjectRefRef RefId="{_APP}_O-0_R-1"/>
            <ComObjectRefRef RefId="{_APP}_O-0_R-2"/>
          </when>
          <when test="2"><ComObjectRefRef RefId="{_APP}_O-0_R-2"/></when>
        </choose>
      </when>
    </choose>
    <choose ParamRefId="{_APP}_P-9_R-9">
      <when test="1"><ComObjectRefRef RefId="{_APP}_O-0_R-3"/></when>
      <when test="2"><ComObjectRefRef RefId="{_APP}_O-0_R-4"/></when>
    </choose>
  </Channel>
</Dynamic>
<Static>
"""


def _variants():
    path = _build_knxprod(_BODY)
    try:
        product = KnxprodCatalogService().import_file(path)[0]
    finally:
        os.remove(path)
    return {co.function_text: condition_alternatives(co.conditions)
            for co in product.com_objects}


def test_mix_module_conditions():
    variants = _variants()
    gm = f"{_APP}_P-57"
    # «> 0», darin «= 1»: es gilt der genauere Wert
    assert variants["Manuell"] == [[[gm, "1"]]]
    # unter «= 1» und «= 2»: beide Werte, nicht «ohne Bedingung»
    assert variants["Sperren"] == [[[gm, "1 2"]]]
    # unsichtbarer Parameter mit festem Wert 1: ohne Bedingung bzw. nie aktiv
    assert variants["Fest aktiv"] == [[]]
    assert "Nie aktiv" not in variants


def test_all_values_drop_the_parameter():
    """Kommen alle Werte vor, entscheidet der Parameter nicht (Feller:
    Szenenfunktion lokal/dezentral)."""
    chains = [[("sz", "0"), ("fn", "3")], [("sz", "1"), ("fn", "3")]]
    assert reduce_alternatives(chains, domain=lambda p: {"0", "1"}) == [[["fn", "3"]]]
    assert reduce_alternatives(chains, domain=lambda p: {"0", "1", "2"}) == [
        [["fn", "3"], ["sz", "0 1"]]]
