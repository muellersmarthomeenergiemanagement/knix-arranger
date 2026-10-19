"""ETS-Parametrierung aus dem Dynamic-Abschnitt (Stufe 1, FA-2304l): welche
Parameter eine KO-Variante verlangt, gelesen wie die ETS (choose/when über
Parameter, Parameterseiten, deutsche Texte)."""
from __future__ import annotations

import os

from knix_arranger.models.topology import CommunicationObject, Device
from knix_arranger.services.com_object_store import pack_com_object, unpack_com_object
from knix_arranger.services.ets_parameters import (
    Setting, settings_for, value_text, variant_settings,
)
from knix_arranger.services.knxprod_catalog_service import (
    KnxprodCatalogService, merge_conditions,
)
from tests.test_knxprod_catalog_service import _build_knxprod

_APP = "M-0001_A-0001-01"
# Taste 1: Funktion Dimmen (3) oder Jalousie (5) -> KO 1 heller/dunkler bzw.
# schritt/stopp; dieselbe Dimm-Variante unter zwei Szenen-Einstellungen
_BODY = f"""
  <ParameterTypes>
    <ParameterType Id="{_APP}_PT-Fn" Name="Fn"><TypeRestriction Base="Value">
      <Enumeration Id="{_APP}_PT-Fn_EN-3" Value="3" Text="Dimming"/>
      <Enumeration Id="{_APP}_PT-Fn_EN-5" Value="5" Text="Shutter"/>
    </TypeRestriction></ParameterType>
    <ParameterType Id="{_APP}_PT-Sc" Name="Sc"><TypeRestriction Base="Value">
      <Enumeration Id="{_APP}_PT-Sc_EN-0" Value="0" Text="local"/>
      <Enumeration Id="{_APP}_PT-Sc_EN-1" Value="1" Text="central"/>
    </TypeRestriction></ParameterType>
  </ParameterTypes>
  <Parameters>
    <Parameter Id="{_APP}_P-1" Name="Fn1" ParameterType="{_APP}_PT-Fn" Text="Function key:"/>
    <Parameter Id="{_APP}_P-2" Name="Sc" ParameterType="{_APP}_PT-Sc" Text="Scenes"/>
  </Parameters>
  <ParameterRefs>
    <ParameterRef Id="{_APP}_P-1_R-1" RefId="{_APP}_P-1"/>
    <ParameterRef Id="{_APP}_P-2_R-2" RefId="{_APP}_P-2"/>
  </ParameterRefs>
  <ComObjectTable>
    <ComObject Id="{_APP}_O-1" Number="1" Text="Key 1" FunctionText="Object 2"
               ObjectSize="1 Bit" CommunicationFlag="Enabled" WriteFlag="Enabled"/>
  </ComObjectTable>
  <ComObjectRefs>
    <ComObjectRef Id="{_APP}_O-1_R-11" RefId="{_APP}_O-1" FunctionText="brighter/darker, Dimming"
                  ObjectSize="4 Bit"/>
    <ComObjectRef Id="{_APP}_O-1_R-12" RefId="{_APP}_O-1" FunctionText="brighter/darker, Dimming"
                  ObjectSize="4 Bit"/>
    <ComObjectRef Id="{_APP}_O-1_R-13" RefId="{_APP}_O-1" FunctionText="step/stop, Shutter"/>
  </ComObjectRefs>
</Static>
<Dynamic>
  <Channel Id="{_APP}_CH-1" Text="Generic">
    <ParameterBlock Id="{_APP}_PB-1" Text="Configuration">
      <ParameterRefRef RefId="{_APP}_P-2_R-2"/>
    </ParameterBlock>
    <ParameterBlock Id="{_APP}_PB-2" Text="Key 1, left">
      <ParameterRefRef RefId="{_APP}_P-1_R-1"/>
    </ParameterBlock>
    <choose ParamRefId="{_APP}_P-2_R-2">
      <when test="0">
        <choose ParamRefId="{_APP}_P-1_R-1">
          <when test="3"><ComObjectRefRef RefId="{_APP}_O-1_R-11"/></when>
          <when test="5"><ComObjectRefRef RefId="{_APP}_O-1_R-13"/></when>
        </choose>
      </when>
      <when test="1">
        <choose ParamRefId="{_APP}_P-1_R-1">
          <when test="3"><ComObjectRefRef RefId="{_APP}_O-1_R-12"/></when>
        </choose>
      </when>
    </choose>
  </Channel>
</Dynamic>
<Static>
<Languages>
  <Language Identifier="de-DE"><TranslationUnit RefId="{_APP}">
    <TranslationElement RefId="{_APP}_PT-Fn_EN-3"><Translation AttributeName="Text" Text="Dimmen"/></TranslationElement>
    <TranslationElement RefId="{_APP}_PT-Fn_EN-5"><Translation AttributeName="Text" Text="Jalousie"/></TranslationElement>
    <TranslationElement RefId="{_APP}_P-1"><Translation AttributeName="Text" Text="Funktion Taste:"/></TranslationElement>
    <TranslationElement RefId="{_APP}_PB-2"><Translation AttributeName="Text" Text="Taste 1, links"/></TranslationElement>
  </TranslationUnit></Language>
</Languages>
"""


def _product():
    path = _build_knxprod(_BODY)
    try:
        return KnxprodCatalogService().import_file(path)[0]
    finally:
        os.remove(path)


def test_conditions_and_german_parameter_texts():
    product = _product()
    dim = next(c for c in product.com_objects if "Dimming" in c.function_text)
    shutter = next(c for c in product.com_objects if "Shutter" in c.function_text)
    # Dimm-Variante unter beiden Szenen-Einstellungen: die Szenen entscheiden nicht
    assert dim.conditions == [[[f"{_APP}_P-1", "3"]]]          # eine Alternative
    assert shutter.conditions == [[[f"{_APP}_P-2", "0"], [f"{_APP}_P-1", "5"]]]
    block, label, values, visible = product.parameters[f"{_APP}_P-1"]
    assert (block, label, values["3"], visible) == ("Taste 1, links", "Funktion Taste",
                                                    "Dimmen", True)


def test_only_deciding_parameters_are_instructions():
    product = _product()
    variants = [co.to_dict() for co in product.com_objects]
    dim = next(v for v in variants if "Dimming" in v["function_text"])
    assert variant_settings(dim, variants, product.parameters) == [
        Setting("Taste 1, links", "Funktion Taste", "Dimmen")]
    # einzige Variante einer Nummer: nichts einzustellen (Theben «Grundmodul»)
    assert variant_settings(dim, [dim], product.parameters) == []


def test_settings_for_device_with_conflict():
    product = _product()
    catalog_product = product.to_catalog_dict()

    class Catalog:
        def find_product(self, *_args):
            return catalog_product

        def parameters_of(self, prod):
            return prod["parameters"]

    def co(function, size):
        return CommunicationObject(object_number=1, name="Key 1", object_function=function,
                                   object_size=size)
    device = Device(manufacturer="Test", order_number="TP-1")
    result = settings_for(device, [co("brighter/darker, Dimming", "4 Bit")], Catalog())
    assert [s.text() for s in result.settings] == ["Taste 1, links › Funktion Taste: Dimmen"]
    both = settings_for(device, [co("brighter/darker, Dimming", "4 Bit"),
                                 co("step/stop, Shutter", "1 Bit")], Catalog())
    assert both.conflicts == {("Taste 1, links", "Funktion Taste"): ["Dimmen", "Jalousie"]}


def test_value_text_and_merge():
    values = {"0": "aus", "1": "ein", "3": "Dimmen"}
    assert value_text(values, "3") == "Dimmen"
    assert value_text(values, "0 1") == "aus oder ein"
    assert value_text(values, "!=0") == "nicht aus"
    # nur EIN Parameter verschieden: entscheidet nicht (Feller Szenenfunktion)
    assert merge_conditions([("a", "1"), ("b", "2")], [("a", "1"), ("b", "3")]) == [[["a", "1"]]]
    # verschiedene Zweige bleiben Alternativen (MDT «Schalten» unter
    # «Einzel-Tastenfunktion = Schalten» oder «= Werte senden»)
    assert merge_conditions([("f", "1"), ("u", "0")], [("f", "2"), ("w", "0"), ("d", "10")]) == [
        [["f", "1"], ["u", "0"]], [["f", "2"], ["w", "0"], ["d", "10"]]]


def test_store_row_keeps_conditions():
    co = {"number": 1, "name": "Key 1", "function_text": "x", "datapoint_type": "",
          "object_size": "1 Bit", "conditions": [["P-1", "3"]],
          "communication_flag": True, "read_flag": False, "write_flag": True,
          "transmit_flag": False, "update_flag": False}
    assert unpack_com_object(pack_com_object(co)) == co


def test_catalog_keeps_parameters_per_application():
    """Import in den eigenen Katalog: KOs mit Bedingungen in der SQLite-Datei,
    Parametertexte je Applikation (APPDATA ist je Test umgeleitet)."""
    from knix_arranger.services.product_search_service import ProductSearchService
    product = _product()
    service = ProductSearchService()
    service.add_products([product.to_catalog_dict()])
    fresh = ProductSearchService()                 # neu geladen, aus der Datei
    found = fresh.find_product(product.manufacturer, product.order_number)
    assert any(co.get("conditions") for co in found["com_objects"])
    assert fresh.parameters_of(found)[f"{_APP}_P-1"][1] == "Funktion Taste"


def test_variant_choice_follows_conditions_not_text():
    """Der Textzusatz «…, Dimming» (englisch) sagt der Textregel nichts; die
    Bedingung «Taste 1, links › Funktion Taste = Dimmen» schon."""
    from knix_arranger.services import ets_parameters, product_sync
    from knix_arranger.services.product_sync import communication_objects_of
    from knix_arranger.services.sensor_channels import SensorLink, family_variants
    catalog_product = _product().to_catalog_dict()

    class Catalog:
        def find_product(self, *_args):
            return catalog_product

        def parameters_of(self, prod):
            return prod["parameters"]

    device = Device(manufacturer="Test", order_number="TP-1",
                    communication_objects=communication_objects_of(
                        catalog_product["com_objects"]))
    link = SensorLink(key="a|LD|1|DIM", channel="Taste 1 lang", function="DIM",
                      ga_address="", ga_designation="", ga_function="DIM", dpt="DPST-3-7",
                      feedback=False)
    variants = [co for co in device.communication_objects if co.object_number == 1]
    assert len(family_variants(variants, link)) == len(variants)     # ohne Bedingungen
    ets_parameters.reset_family_cache()
    ets_parameters.attach_families(device, Catalog())
    chosen = family_variants(variants, link)
    assert [co.object_function for co in chosen if co.families] == ["brighter/darker, Dimming"]
    product_sync.reset_shared_catalog()
