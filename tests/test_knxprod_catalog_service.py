"""
Tests fuer KnxprodCatalogService (FA-2304) - KNXPROD-ComObject-Extraktion.

Regression: <ComObjectRef> (pro Applikation/Kanal konkretisiertes ComObject,
verweist per RefId auf die <ComObject>-Basisdefinition) muss gelesen und mit
der Basis gemergt werden. Viele Hersteller setzen DatapointType nur auf dem
Ref, nie auf der Basis - eine Implementierung, die nur <ComObject> liest,
liefert dann ComObjects ohne Datenpunkttyp (oder verliert sie ganz).
"""
import io
import zipfile

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knix_arranger.services.knxprod_catalog_service import KnxprodCatalogService


def _build_knxprod(app_xml_body: str) -> str:
    """Baut eine minimale, aber strukturell gueltige .knxprod-ZIP-Datei im
    Speicher und schreibt sie in eine temporaere Datei. `app_xml_body` ist
    der Inhalt des <ComObjectTable>/<ComObjectRefs>-Bereichs im Applikations-XML.
    """
    hardware_xml = """<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer RefId="M-0001">
      <Hardware>
        <Hardware Id="H1" Name="Testgeraet" ApplicationArea="Lighting">
          <Hardware2Programs>
            <Hardware2Program Id="H2P1">
              <ApplicationProgramRef RefId="APP1"/>
            </Hardware2Program>
          </Hardware2Programs>
          <Products>
            <Product Id="P1" Text="Testprodukt" OrderNumber="TP-1"
                     Hardware2ProgramRefId="H2P1"/>
          </Products>
        </Hardware>
      </Hardware>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

    catalog_xml = """<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer Name="TestHersteller">
      <Catalog>
        <CatalogItem ProductRefId="P1" Name="Testprodukt"/>
      </Catalog>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

    app_xml = f"""<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer>
      <ApplicationPrograms>
        <ApplicationProgram Id="APP1">
          <Static>
            {app_xml_body}
          </Static>
        </ApplicationProgram>
      </ApplicationPrograms>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("M-0001/Hardware.xml", hardware_xml)
        zf.writestr("M-0001/Catalog.xml", catalog_xml)
        zf.writestr("M-0001/M-0001_A-0001-01.xml", app_xml)

    import tempfile
    fd, path = tempfile.mkstemp(suffix=".knxprod")
    with os.fdopen(fd, "wb") as f:
        f.write(buf.getvalue())
    return path


class TestComObjectRefResolution:
    def test_datapoint_type_only_on_ref_is_resolved(self):
        """Basisobjekt ohne DatapointType, Ref traegt ihn - muss im Ergebnis
        landen (dies ist der Kernbug: vorher wurde nur <ComObject> gelesen,
        <ComObjectRef> komplett ignoriert)."""
        body = """
        <ComObjectTable>
          <ComObject Id="CO-1" Number="1" Text="Schalten Basis"
                     CommunicationFlag="Enabled" WriteFlag="Enabled"/>
        </ComObjectTable>
        <ComObjectRefs>
          <ComObjectRef Id="COR-1" RefId="CO-1" DatapointType="DPST-1-1"
                        Text="Kanal 1 Schalten" TransmitFlag="Enabled"/>
        </ComObjectRefs>
        """
        path = _build_knxprod(body)
        try:
            products = KnxprodCatalogService().import_file(path)
            assert len(products) == 1
            com_objects = products[0].com_objects
            assert len(com_objects) == 1
            co = com_objects[0]
            assert co.datapoint_type == "DPST-1-1"
            assert co.function_text == "Kanal 1 Schalten"  # Ref-Text ueberschreibt Basis-Text
            assert co.write_flag is True   # von der Basis geerbt
            assert co.transmit_flag is True  # vom Ref hinzugefuegt
        finally:
            os.remove(path)

    def test_base_without_ref_is_still_included(self):
        """Hersteller ohne ComObjectRefs (Basis traegt DPT direkt) - Objekt
        muss weiterhin uebernommen werden."""
        body = """
        <ComObjectTable>
          <ComObject Id="CO-1" Number="1" Text="Direkt" DatapointType="DPST-9-1"
                     CommunicationFlag="Enabled" TransmitFlag="Enabled"/>
        </ComObjectTable>
        """
        path = _build_knxprod(body)
        try:
            products = KnxprodCatalogService().import_file(path)
            com_objects = products[0].com_objects
            assert len(com_objects) == 1
            assert com_objects[0].datapoint_type == "DPST-9-1"
        finally:
            os.remove(path)

    def test_multiple_refs_to_same_base_produce_separate_com_objects(self):
        """Mehrere Kanaele koennen dieselbe Basisdefinition referenzieren,
        aber eigene Number/Text/DatapointType tragen (z.B. Kanal 1 vs. Kanal 2)."""
        body = """
        <ComObjectTable>
          <ComObject Id="CO-1" Text="Schalten"
                     CommunicationFlag="Enabled" WriteFlag="Enabled"/>
        </ComObjectTable>
        <ComObjectRefs>
          <ComObjectRef Id="COR-1" RefId="CO-1" Number="1" Text="Kanal 1"
                        DatapointType="DPST-1-1"/>
          <ComObjectRef Id="COR-2" RefId="CO-1" Number="2" Text="Kanal 2"
                        DatapointType="DPST-1-1"/>
        </ComObjectRefs>
        """
        path = _build_knxprod(body)
        try:
            products = KnxprodCatalogService().import_file(path)
            com_objects = products[0].com_objects
            assert len(com_objects) == 2
            numbers = sorted(co.number for co in com_objects)
            assert numbers == [1, 2]
            assert all(co.datapoint_type == "DPST-1-1" for co in com_objects)
        finally:
            os.remove(path)

    def test_identical_size_variants_are_merged(self):
        """Regression (Viessmann Vitogate): mehrere per Parameter umschaltbare
        Refs desselben Objekts, die sich nur in der Objektgroesse
        unterscheiden, ergeben EIN ComObject -- sonst erscheint jedes Objekt
        mehrfach und der GA-Bedarf wird vervielfacht."""
        body = """
        <ComObjectTable>
          <ComObject Id="CO-1" Number="1" Text="Object 0" FunctionText="1 bit"
                     CommunicationFlag="Enabled" WriteFlag="Enabled" TransmitFlag="Enabled"/>
        </ComObjectTable>
        <ComObjectRefs>
          <ComObjectRef Id="COR-1" RefId="CO-1" ObjectSize="1 Bit"/>
          <ComObjectRef Id="COR-2" RefId="CO-1" FunctionText="1 Byte" ObjectSize="1 Byte"/>
          <ComObjectRef Id="COR-3" RefId="CO-1" FunctionText="4 Byte" ObjectSize="4 Bytes"/>
        </ComObjectRefs>
        """
        path = _build_knxprod(body)
        try:
            prod = KnxprodCatalogService().import_file(path)[0]
            assert len(prod.com_objects) == 1
            assert prod.ga_max == 1
        finally:
            os.remove(path)

    def test_variants_with_different_datapoint_type_stay_separate(self):
        body = """
        <ComObjectTable>
          <ComObject Id="CO-1" Number="1" Text="Wert"
                     CommunicationFlag="Enabled" WriteFlag="Enabled"/>
        </ComObjectTable>
        <ComObjectRefs>
          <ComObjectRef Id="COR-1" RefId="CO-1" DatapointType="DPST-5-1"/>
          <ComObjectRef Id="COR-2" RefId="CO-1" DatapointType="DPST-9-1"/>
        </ComObjectRefs>
        """
        path = _build_knxprod(body)
        try:
            prod = KnxprodCatalogService().import_file(path)[0]
            assert sorted(co.datapoint_type for co in prod.com_objects) == ["DPST-5-1", "DPST-9-1"]
        finally:
            os.remove(path)


def _build_knxprod_no_application_area(catalog_section_names: list[str], product_name: str) -> str:
    """Wie `_build_knxprod`, aber ohne ApplicationArea auf <Hardware> (wie
    z.B. Theben-Exporte) und mit dem CatalogItem verschachtelt in
    <CatalogSection>-Elementen (`catalog_section_names`, von aussen nach
    innen), um den Katalogbaum-Fallback fuer die Kategorie-Erkennung zu testen.
    """
    hardware_xml = """<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer RefId="M-0001">
      <Hardware>
        <Hardware Id="H1" Name="Testgeraet">
          <Hardware2Programs>
            <Hardware2Program Id="H2P1">
              <ApplicationProgramRef RefId="APP1"/>
            </Hardware2Program>
          </Hardware2Programs>
          <Products>
            <Product Id="P1" Text="{name}" OrderNumber="TP-1"
                     Hardware2ProgramRefId="H2P1"/>
          </Products>
        </Hardware>
      </Hardware>
    </Manufacturer>
  </ManufacturerData>
</KNX>""".format(name=product_name)

    sections_open = "".join(f'<CatalogSection Name="{n}">' for n in catalog_section_names)
    sections_close = "</CatalogSection>" * len(catalog_section_names)
    catalog_xml = f"""<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer Name="TestHersteller">
      <Catalog>
        {sections_open}
        <CatalogItem ProductRefId="P1" Name="{product_name}"/>
        {sections_close}
      </Catalog>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

    app_xml = """<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer>
      <ApplicationPrograms>
        <ApplicationProgram Id="APP1">
          <Static>
            <ComObjectTable>
              <ComObject Id="CO-1" Number="1" Text="Wert"
                         CommunicationFlag="Enabled" TransmitFlag="Enabled"
                         DatapointType="DPST-9-1"/>
            </ComObjectTable>
          </Static>
        </ApplicationProgram>
      </ApplicationPrograms>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("M-0001/Hardware.xml", hardware_xml)
        zf.writestr("M-0001/Catalog.xml", catalog_xml)
        zf.writestr("M-0001/M-0001_A-0001-01.xml", app_xml)

    import tempfile
    fd, path = tempfile.mkstemp(suffix=".knxprod")
    with os.fdopen(fd, "wb") as f:
        f.write(buf.getvalue())
    return path


class TestCategoryFallbackViaCatalogSection:
    """Regression: Manche Hersteller (z.B. Theben) fuehren gar kein
    ApplicationArea auf <Hardware>. Ohne Fallback wird dann JEDES Produkt
    als 'actor' klassifiziert - auch klare Sensoren/Wetterstationen, die
    dadurch in der Produktsuche unter 'Wetterstation' unauffindbar bleiben,
    obwohl ihre ComObject-Daten korrekt geladen wurden."""

    def test_weather_station_without_application_area_classified_via_section_path(self):
        path = _build_knxprod_no_application_area(
            ["Physikalische Sensoren", "Weather stations"], "Meteodata 140",
        )
        try:
            products = KnxprodCatalogService().import_file(path)
            assert len(products) == 1
            prod = products[0]
            assert prod.category == "sensor"
            assert prod.device_type == "Wetterstation"
            assert prod.sensor_type == "Wetterstation"
            assert len(prod.com_objects) == 1  # ComObject-Daten trotzdem geladen
        finally:
            os.remove(path)

    def test_infrastructure_without_application_area_classified_via_section_path(self):
        path = _build_knxprod_no_application_area(
            ["Systemgeraete", "IP-Router"], "IP Router KNX",
        )
        try:
            products = KnxprodCatalogService().import_file(path)
            assert products[0].category == "infrastructure"
        finally:
            os.remove(path)

    def test_unclassifiable_section_without_application_area_is_other(self):
        """Katalogbaum und Name ohne erkennbare Stichworte -> "Sonstiges".
        Frueher "actor"/"Schaltaktor" -- so landeten Bedienelemente,
        Praesenzmelder usw. als Schaltaktoren im Katalog."""
        path = _build_knxprod_no_application_area(
            ["Diverses"], "Unbekanntes Geraet",
        )
        try:
            products = KnxprodCatalogService().import_file(path)
            assert products[0].device_type == "Sonstiges"
        finally:
            os.remove(path)


class TestManufacturerNameFallbackViaMasterFile:
    """Regression: Manche Hersteller (z.B. Theben) tragen ihren Namen nicht
    redundant im eigenen Catalog.xml ein (<Manufacturer RefId="M-0048"/>,
    kein Name-Attribut) - der Name muss dann aus der ZIP-weiten
    knx_master.xml (KNX-Standard-Herstellerregister) aufgeloest werden,
    sonst erscheint das Produkt unter der rohen Ordner-ID (z.B. "M-0048")
    und ist bei einer Herstellersuche unauffindbar."""

    @staticmethod
    def _build_knxprod_manufacturer_only_in_master(mfr_id: str, mfr_name: str) -> str:
        hardware_xml = f"""<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer RefId="{mfr_id}">
      <Hardware>
        <Hardware Id="H1" Name="Testgeraet" ApplicationArea="Sensor">
          <Hardware2Programs>
            <Hardware2Program Id="H2P1">
              <ApplicationProgramRef RefId="APP1"/>
            </Hardware2Program>
          </Hardware2Programs>
          <Products>
            <Product Id="P1" Text="Testprodukt" OrderNumber="TP-1"
                     Hardware2ProgramRefId="H2P1"/>
          </Products>
        </Hardware>
      </Hardware>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

        # Catalog.xml traegt bewusst KEINEN Name - nur die RefId (wie Theben)
        catalog_xml = f"""<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer RefId="{mfr_id}">
      <Catalog>
        <CatalogItem ProductRefId="P1" Name="Testprodukt"/>
      </Catalog>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

        app_xml = """<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer>
      <ApplicationPrograms>
        <ApplicationProgram Id="APP1">
          <Static>
            <ComObjectTable>
              <ComObject Id="CO-1" Number="1" Text="Wert"
                         CommunicationFlag="Enabled" TransmitFlag="Enabled"
                         DatapointType="DPST-9-1"/>
            </ComObjectTable>
          </Static>
        </ApplicationProgram>
      </ApplicationPrograms>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

        master_xml = f"""<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <MasterData>
    <Manufacturers>
      <Manufacturer Id="{mfr_id}" Name="{mfr_name}"/>
      <Manufacturer Id="M-9999" Name="Anderer Hersteller"/>
    </Manufacturers>
  </MasterData>
</KNX>"""

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(f"{mfr_id}/Hardware.xml", hardware_xml)
            zf.writestr(f"{mfr_id}/Catalog.xml", catalog_xml)
            zf.writestr(f"{mfr_id}/{mfr_id}_A-0001-01.xml", app_xml)
            zf.writestr("knx_master.xml", master_xml)

        import tempfile
        fd, path = tempfile.mkstemp(suffix=".knxprod")
        with os.fdopen(fd, "wb") as f:
            f.write(buf.getvalue())
        return path

    def test_manufacturer_name_resolved_from_master_file(self):
        """Hersteller, der (noch) nicht im mitgelieferten KNX-Register steht:
        Name kommt aus der knx_master.xml der Datei."""
        path = self._build_knxprod_manufacturer_only_in_master("M-FFF0", "Neuer Hersteller AG")
        try:
            products = KnxprodCatalogService().import_file(path)
            assert len(products) == 1
            assert products[0].manufacturer == "Neuer Hersteller AG"
            assert products[0].manufacturer_id == "M-FFF0"
        finally:
            os.remove(path)

    def test_known_manufacturer_gets_unified_name_and_id(self):
        path = self._build_knxprod_manufacturer_only_in_master("M-0048", "Theben AG")
        try:
            products = KnxprodCatalogService().import_file(path)
            assert products[0].manufacturer == "Theben"
            assert products[0].manufacturer_id == "M-0048"
            assert products[0].to_catalog_dict()["manufacturer_id"] == "M-0048"
        finally:
            os.remove(path)

    def test_ets_ids_kept_for_export(self):
        path = self._build_knxprod_manufacturer_only_in_master("M-0048", "Theben AG")
        try:
            prod = KnxprodCatalogService().import_file(path)[0]
            entry = prod.to_catalog_dict()
            assert entry["product_ref_id"] == "P1"
            assert entry["hw2prog_id"] == "H2P1"
            assert entry["application_program_id"] == "APP1"
        finally:
            os.remove(path)

    def test_manufacturer_falls_back_to_folder_id_without_master_entry(self):
        """Ohne Eintrag in knx_master.xml bleibt der bisherige Fallback
        (Ordner-ID) erhalten - kein Absturz, keine Fantasienamen."""
        path = self._build_knxprod_manufacturer_only_in_master("M-FFF0", "Neuer Hersteller AG")
        fixed = path + ".2"
        try:
            # Neues ZIP ohne den M-FFF0-Eintrag in knx_master.xml bauen
            with zipfile.ZipFile(path) as src, zipfile.ZipFile(fixed, "w") as dst:
                for item in src.infolist():
                    data = src.read(item.filename)
                    if item.filename == "knx_master.xml":
                        data = b"""<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <MasterData><Manufacturers/></MasterData>
</KNX>"""
                    dst.writestr(item, data)

            products = KnxprodCatalogService().import_file(fixed)
            assert products[0].manufacturer == "M-FFF0"
        finally:
            os.remove(path)
            if os.path.exists(fixed):
                os.remove(fixed)


def _build_knxprod_partial_catalog(product_name: str, application_area: str = "") -> str:
    """Nachbau einer aus einem .knxproj extrahierten Herstellerdatei: zwei
    Geraete mit je eigenem Applikationsprogramm, das Produkt P1 hat aber
    keinen CatalogItem in Catalog.xml und keine Hardware2ProgramRefId am
    <Product> -- die Zuordnung steht nur unter <Hardware2Programs>."""
    area = f' ApplicationArea="{application_area}"' if application_area else ""
    hardware_xml = f"""<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer RefId="M-0001">
      <Hardware>
        <Hardware Id="H1" Name="Geraet 1"{area}>
          <Products>
            <Product Id="P1" Text="{product_name}" OrderNumber="TP-1"/>
          </Products>
          <Hardware2Programs>
            <Hardware2Program Id="H2P1">
              <ApplicationProgramRef RefId="APP1"/>
            </Hardware2Program>
          </Hardware2Programs>
        </Hardware>
        <Hardware Id="H2" Name="Geraet 2">
          <Products>
            <Product Id="P2" Text="Anderes Geraet" OrderNumber="TP-2"/>
          </Products>
          <Hardware2Programs>
            <Hardware2Program Id="H2P2">
              <ApplicationProgramRef RefId="APP2"/>
            </Hardware2Program>
          </Hardware2Programs>
        </Hardware>
      </Hardware>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

    catalog_xml = """<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData>
    <Manufacturer Name="TestHersteller">
      <Catalog>
        <CatalogItem ProductRefId="P2" Name="Anderes Geraet" Hardware2ProgramRefId="H2P2"/>
      </Catalog>
    </Manufacturer>
  </ManufacturerData>
</KNX>"""

    def app_xml(app_id: str, count: int) -> str:
        objs = "".join(
            f'<ComObject Id="{app_id}-O{i}" Number="{i}" Text="Objekt {i}" '
            f'CommunicationFlag="Enabled" WriteFlag="Enabled" DatapointType="DPST-1-1"/>'
            for i in range(count)
        )
        return f"""<?xml version="1.0"?>
<KNX xmlns="http://knx.org/xml/project/20">
  <ManufacturerData><Manufacturer><ApplicationPrograms>
    <ApplicationProgram Id="{app_id}"><Static><ComObjectTable>{objs}</ComObjectTable></Static></ApplicationProgram>
  </ApplicationPrograms></Manufacturer></ManufacturerData>
</KNX>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("M-0001/Hardware.xml", hardware_xml)
        zf.writestr("M-0001/Catalog.xml", catalog_xml)
        zf.writestr("M-0001/M-0001_A-0001-01.xml", app_xml("APP1", 3))
        zf.writestr("M-0001/M-0001_A-0002-01.xml", app_xml("APP2", 5))

    import tempfile
    fd, path = tempfile.mkstemp(suffix=".knxprod")
    with os.fdopen(fd, "wb") as f:
        f.write(buf.getvalue())
    return path


class TestProductMissingFromCatalog:
    """Regression (Revox Gateway): In aus einem .knxproj extrahierten
    Herstellerdateien fehlt Catalog.xml-Eintrag und Hardware2ProgramRefId
    fuer manche Produkte. Ohne Fallback bekam das Produkt keine ComObjects
    und wurde als 'Schaltaktor' eingestuft -- je nach Importquelle waren
    dann andere Kanaele auswaehlbar."""

    def _import(self, name, area=""):
        path = _build_knxprod_partial_catalog(name, area)
        try:
            return {p.order_number: p for p in KnxprodCatalogService().import_file(path)}
        finally:
            os.remove(path)

    def test_com_objects_resolved_via_hardware2programs(self):
        products = self._import("Revox Gateway designed by Weinzierl")
        assert len(products["TP-1"].com_objects) == 3
        assert len(products["TP-2"].com_objects) == 5  # andere Produkte unveraendert

    def test_gateway_classified_as_infrastructure_by_name(self):
        prod = self._import("Revox Gateway designed by Weinzierl")["TP-1"]
        assert prod.category == "infrastructure"
        assert prod.device_type == "Multimedia-Gateway"

    def test_input_interface_classified_as_sensor_by_name(self):
        prod = self._import("Universalschnittstelle 8fach Komfort")["TP-1"]
        assert prod.category == "sensor"

    def test_application_area_still_wins_over_name(self):
        prod = self._import("KNX DALI Gateway", area="Lighting")["TP-1"]
        assert prod.category == "actor"
        assert prod.device_type == "DALI-Gateway"

    def test_unknown_name_is_other(self):
        prod = self._import("Geraet XY")["TP-1"]
        assert prod.device_type == "Sonstiges"
        assert len(prod.com_objects) == 3


class TestObjectFunctionAndTranslation:
    """ETS-Spalten: Text = «Name», FunctionText = «Objektfunktion» (bis 1.4.9
    las KNiX Text als Funktion -- 87 % der KOs ohne Funktion, Theben DM 4 T
    «Kanal C1 – Channel C1» für alle KOs)."""

    _BODY = """
        <ComObjectTable>
          <ComObject Id="M-0001_A-0001-01_O-0" Number="0" Name="Kanal C1" Text="Channel C1"
                     FunctionText="Switching ON/OFF" ObjectSize="1 Bit"
                     CommunicationFlag="Enabled" WriteFlag="Enabled"/>
          <ComObject Id="M-0001_A-0001-01_O-2" Number="2" Name="Kanal C1" Text="Channel C1"
                     FunctionText="Dimming value" ObjectSize="1 Byte"
                     CommunicationFlag="Enabled" WriteFlag="Enabled"/>
          <ComObject Id="M-0001_A-0001-01_O-9" Number="9" Name="Kanal C1" Text="Channel C1"
                     FunctionText="Status ON/OFF" ObjectSize="1 Bit"
                     CommunicationFlag="Enabled" TransmitFlag="Enabled" ReadFlag="Enabled"/>
        </ComObjectTable>
        <Languages>
          <Language Identifier="fr-FR">
            <TranslationUnit RefId="M-0001_A-0001-01">
              <TranslationElement RefId="M-0001_A-0001-01_O-0">
                <Translation AttributeName="FunctionText" Text="Commutation" />
              </TranslationElement>
            </TranslationUnit>
          </Language>
          <Language Identifier="de-DE">
            <TranslationUnit RefId="M-0001_A-0001-01">
              <TranslationElement RefId="M-0001_A-0001-01_O-0">
                <Translation AttributeName="Text" Text="Kanal C1" />
                <Translation AttributeName="FunctionText" Text="Schalten EIN/AUS" />
              </TranslationElement>
              <TranslationElement RefId="M-0001_A-0001-01_O-9">
                <Translation AttributeName="FunctionText" Text="Rückmeldung Ein/Aus" />
              </TranslationElement>
            </TranslationUnit>
          </Language>
        </Languages>
    """

    def _cos(self, body):
        path = _build_knxprod(body)
        try:
            return {co.number: co for co in KnxprodCatalogService().import_file(path)[0].com_objects}
        finally:
            os.remove(path)

    def test_name_function_size_and_german(self):
        cos = self._cos(self._BODY)
        assert (cos[0].name, cos[0].function_text) == ("Kanal C1", "Schalten EIN/AUS")
        assert cos[9].function_text == "Rückmeldung Ein/Aus"
        # ohne deutsche Übersetzung: Grundsprache
        assert (cos[2].name, cos[2].function_text) == ("Channel C1", "Dimming value")
        assert [cos[n].object_size for n in (0, 2)] == ["1 Bit", "1 Byte"]

    def test_dpt_from_unique_size_only(self):
        cos = self._cos(self._BODY)
        assert cos[0].datapoint_type == "DPT-1"      # 1 Bit ist immer DPT 1
        assert cos[2].datapoint_type == ""           # 1 Byte: 5, 17, 20 … offen

    def test_module_placeholder_name_uses_resolved_identifier(self):
        cos = self._cos("""
        <ComObjectTable>
          <ComObject Id="CO-1" Number="1" Name="RMG 4 I Kanal C1"
                     Text="{{ObjName}}{{ChannelNr}} {{0}}" FunctionText="Schaltobjekt"
                     CommunicationFlag="Enabled" WriteFlag="Enabled"/>
          <ComObject Id="CO-2" Number="2" Name="Obj_Switch_A" Text="{{0:Kanal A}}: "
                     FunctionText="Schalten" CommunicationFlag="Enabled" WriteFlag="Enabled"/>
        </ComObjectTable>""")
        assert cos[1].name == "RMG 4 I Kanal C1"
        assert cos[2].name == "{{0:Kanal A}}: "      # Standardtext «Kanal A» bleibt

    def test_size_only_function_text_falls_back_to_text(self):
        cos = self._cos("""
        <ComObjectTable>
          <ComObject Id="CO-1" Number="1" Text="Aussentemperatur" FunctionText="2 Byte"
                     ObjectSize="2 Bytes" CommunicationFlag="Enabled" TransmitFlag="Enabled"/>
        </ComObjectTable>""")
        assert cos[1].function_text == "Aussentemperatur"

    def test_ga_need_counts_each_number_once(self):
        path = _build_knxprod("""
        <ComObjectTable>
          <ComObject Id="CO-7" Number="7" Text="Kanal C1" FunctionText="Zwang = 1"
                     ObjectSize="1 Bit" CommunicationFlag="Enabled" WriteFlag="Enabled"/>
        </ComObjectTable>
        <ComObjectRefs>
          <ComObjectRef Id="COR-1" RefId="CO-7"/>
          <ComObjectRef Id="COR-2" RefId="CO-7" FunctionText="Dimmwert bei Zwang" ObjectSize="1 Byte"/>
        </ComObjectRefs>""")
        try:
            prod = KnxprodCatalogService().import_file(path)[0]
            assert sorted(co.function_text for co in prod.com_objects) == [
                "Dimmwert bei Zwang", "Zwang = 1"]           # Varianten bleiben
            assert (prod.ga_min, prod.ga_max) == (1, 1)
        finally:
            os.remove(path)
