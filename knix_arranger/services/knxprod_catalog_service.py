"""
KNXPROD-Katalog-Import (FA-2304)

Liest Produktdaten aus herstellerseitigen .knxprod-Dateien ein.
.knxprod ist ein ZIP-Archiv mit standardisierter XML-Struktur (KNX-Spec):

  Aufbau:
    myproduct.knxprod (ZIP)
    └── M-XXXX/               (Hersteller-Ordner, 4-stelliger Hex-Code)
        ├── Catalog.xml       (Produktkatalog mit Namen/Bezeichnungen)
        ├── Hardware.xml      (Hardware-Eigenschaften, Kanäle, Adressen)
        └── M-XXXX_A-YYYY-ZZ/ (Applikationsprogramm-Ordner)
            └── M-XXXX_A-YYYY-ZZ.xml  (ComObjects, DPTs, Flags)

Produktinfos die gelesen werden:
  - Hersteller (Name aus Ordnerpfad / Catalog.xml)
  - Produktname und Bestellnummer (OrderNumber)
  - Kanalanzahl (NumberOfChannels)
  - Kategorie (aus ApplicationArea-Attribut, wird auf interne Kategorien gemappt)
  - Kommunikationsobjekte (ComObjects mit DPT und Flags) aus Applikationsprogramm
"""
from __future__ import annotations
import logging
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..utils.manufacturers import canonical_manufacturer

logger = logging.getLogger("knix_arranger.knxprod_catalog")

# Mapping von KNX-ApplicationArea auf interne Kategorien (ProductSearchService)
_AREA_TO_CATEGORY: dict[str, str] = {
    "HVAC": "actor",
    "Lighting": "actor",
    "Shutter": "actor",
    "Heating": "actor",
    "Security": "sensor",
    "Sensor": "sensor",
    "Metering": "sensor",
    "SystemDevice": "infrastructure",
    "Remote": "sensor",
}


@dataclass
class ComObjectInfo:
    """Kommunikationsobjekt eines KNX-Geräts, aus Applikationsprogramm gelesen."""
    number: int = 0
    name: str = ""
    function_text: str = ""       # Text/FunctionText-Attribut (Funktion des Objekts)
    datapoint_type: str = ""      # z.B. "DPT-1", "DPT-5.001"
    communication_flag: bool = True
    read_flag: bool = False
    write_flag: bool = False
    transmit_flag: bool = False
    update_flag: bool = False

    @property
    def needs_ga(self) -> bool:
        """True wenn dieses ComObject wahrscheinlich eine Gruppenadresse benötigt."""
        return (
            self.communication_flag
            and (self.write_flag or self.transmit_flag
                 or self.read_flag or self.update_flag)
        )

    @property
    def flags_display(self) -> str:
        """Kompakter Flags-String, z.B. 'K-WS--' (ETS-Notation)."""
        return "".join([
            "K" if self.communication_flag else "-",
            "L" if self.read_flag else "-",
            "Ü" if self.write_flag else "-",
            "S" if self.transmit_flag else "-",
            "U" if self.update_flag else "-",
        ])

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "function_text": self.function_text,
            "datapoint_type": self.datapoint_type,
            "communication_flag": self.communication_flag,
            "read_flag": self.read_flag,
            "write_flag": self.write_flag,
            "transmit_flag": self.transmit_flag,
            "update_flag": self.update_flag,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ComObjectInfo:
        return cls(
            number=data.get("number", 0),
            name=data.get("name", ""),
            function_text=data.get("function_text", ""),
            datapoint_type=data.get("datapoint_type", ""),
            communication_flag=data.get("communication_flag", True),
            read_flag=data.get("read_flag", False),
            write_flag=data.get("write_flag", False),
            transmit_flag=data.get("transmit_flag", False),
            update_flag=data.get("update_flag", False),
        )


@dataclass
class KnxprodProduct:
    """Aus einer KNXPROD-Datei extrahiertes Produkt."""
    manufacturer: str
    order_number: str
    product_name: str
    channels: int
    category: str        # "actor" | "sensor" | "infrastructure"
    device_type: str     # abgeleitet aus Name/Kategorie
    manufacturer_id: str = ""   # KNX-Hersteller-ID "M-XXXX" (Ordnername im Archiv)
    actor_type: str = ""
    sensor_type: str = ""
    com_objects: list[ComObjectInfo] = field(default_factory=list)
    secure_supported: bool = False   # KNX Secure Unterstuetzung (FA-2705)

    @property
    def ga_min(self) -> int:
        """Minimaler GA-Bedarf: ComObjects mit Schreib- oder Sendeobjekt."""
        return sum(
            1 for co in self.com_objects
            if co.communication_flag and (co.write_flag or co.transmit_flag)
        )

    @property
    def ga_max(self) -> int:
        """Maximaler GA-Bedarf: alle aktiven ComObjects."""
        return sum(1 for co in self.com_objects if co.needs_ga)

    def to_catalog_dict(self) -> dict:
        """Kompatibles Format für product_catalog.json / ProductSearchService."""
        return {
            "category": self.category,
            "device_type": self.device_type,
            "actor_type": self.actor_type,
            "sensor_type": self.sensor_type,
            "manufacturer": self.manufacturer,
            "manufacturer_id": self.manufacturer_id,
            "order_number": self.order_number,
            "product_name": self.product_name,
            "channels": self.channels,
            "url": "",
            "price_hint": "",
            "com_objects": [co.to_dict() for co in self.com_objects],
            "ga_min": self.ga_min,
            "ga_max": self.ga_max,
            "secure_supported": self.secure_supported,
        }


class KnxprodCatalogService:
    """Liest Produktdaten aus .knxprod-Dateien (FA-2304)."""

    def import_file(self, filepath: str) -> list[KnxprodProduct]:
        """
        Importiert Produkte aus einer KNXPROD-Datei.

        Returns:
            Liste der gefundenen Produkte (kann leer sein).

        Raises:
            ValueError: Wenn die Datei kein gültiges ZIP/KNXPROD-Format hat.
        """
        try:
            with zipfile.ZipFile(filepath, "r") as zf:
                return self._parse_zip(zf)
        except zipfile.BadZipFile as e:
            raise ValueError(f"Keine gültige KNXPROD-Datei: {e}") from e

    def _parse_zip(self, zf: zipfile.ZipFile) -> list[KnxprodProduct]:
        """Durchsucht das ZIP nach Manufacturer-Ordnern und liest Catalog/Hardware/Apps."""
        products: list[KnxprodProduct] = []
        namelist = zf.namelist()

        # Hersteller-Ordner finden (M-XXXX/)
        mfr_folders = {
            name.split("/")[0]
            for name in namelist
            if name.startswith("M-") and "/" in name
        }

        for folder in sorted(mfr_folders):
            mfr_name, mfr_id = canonical_manufacturer(
                self._resolve_manufacturer_name(zf, folder, namelist), folder,
            )

            # Hardware.xml, Catalog.xml lesen
            hardware_entries = self._parse_hardware_xml(zf, folder, namelist)
            catalog_names, catalog_hw2prog, catalog_sections = self._parse_catalog_xml(
                zf, folder, namelist,
            )

            # Applikationsprogramm-XMLs und Hardware2Program-Mapping lesen
            hw2prog_map = self._parse_hw2prog_map(zf, folder, namelist)
            app_comobjects = self._parse_app_programs(zf, folder, namelist)

            for hw in hardware_entries:
                # Produktname aus Catalog.xml ergänzen
                full_name = catalog_names.get(hw["id"], hw.get("name", ""))
                section_path = catalog_sections.get(hw["id"], "")
                order_number = hw.get("order_number", "")
                channels = hw.get("channels", 0)
                # Fehlt ApplicationArea in Hardware.xml (z.B. Theben), wird die
                # Kategorie ersatzweise aus dem ETS-Katalogbaum abgeleitet.
                # Fehlt auch der Katalogbaum (Produkt nicht in Catalog.xml),
                # hilft der Produktname (z.B. "... Gateway" -> Infrastruktur).
                category = (
                    hw.get("category")
                    or self._infer_category_from_section(section_path)
                    or self._infer_category_from_name(full_name)
                    or "actor"
                )
                device_type = self._infer_device_type(full_name, category, section_path)

                # ComObjects über Hardware2Program → ApplikationsprogrammID auflösen.
                # Hardware2ProgramRefId steht je nach Hersteller entweder am Product-
                # Element (Hardware.xml) oder am CatalogItem (Catalog.xml, per ProductRefId).
                hw2prog_id = (
                    hw.get("hw2prog_id")
                    or catalog_hw2prog.get(hw["id"], "")
                    or hw.get("hw2prog_fallback", "")
                )
                app_id = hw2prog_map.get(hw2prog_id, "")
                com_objects = app_comobjects.get(app_id, [])

                # Fallback nur wenn eindeutig: genau ein Applikationsprogramm in der Datei.
                # Bei mehreren Programmen würde ein blindes Zusammenführen ComObjects
                # fremder Produkte zuordnen (z.B. Sammel-Produktdatenbanken).
                if not com_objects and len(app_comobjects) == 1:
                    com_objects = next(iter(app_comobjects.values()))

                prod = KnxprodProduct(
                    manufacturer=mfr_name,
                    manufacturer_id=mfr_id,
                    order_number=order_number,
                    product_name=full_name or order_number,
                    channels=channels,
                    category=category,
                    device_type=device_type,
                    actor_type=device_type if category == "actor" else "",
                    sensor_type=device_type if category == "sensor" else "",
                    com_objects=com_objects,
                    secure_supported=hw.get("secure_supported", False),
                )
                products.append(prod)

        if not products:
            logger.warning("Keine Produkte in KNXPROD gefunden.")

        logger.info(f"KNXPROD-Import: {len(products)} Produkte gefunden.")
        return products

    def _resolve_manufacturer_name(
        self, zf: zipfile.ZipFile, folder: str, namelist: list[str]
    ) -> str:
        """Versucht den Herstellernamen zu lesen: zuerst aus dem eigenen
        Catalog.xml, sonst aus der ZIP-weiten knx_master.xml (dem
        KNX-Standard-Herstellerregister, Element <Manufacturer Id="M-XXXX"
        Name="..."/>). Manche Hersteller (z.B. Theben) tragen ihren eigenen
        Namen nicht redundant in Catalog.xml ein – dort steht dann nur die
        ID (<Manufacturer RefId="M-0048"/>)."""
        catalog_path = f"{folder}/Catalog.xml"
        if catalog_path in namelist:
            try:
                xml_bytes = zf.read(catalog_path)
                root = self._parse_xml(xml_bytes)
                for mfr in root.iter():
                    if mfr.tag.endswith("Manufacturer"):
                        name = mfr.get("Name") or mfr.get("name", "")
                        if name:
                            return name
            except Exception as e:
                logger.debug(f"Herstellername aus {catalog_path} nicht lesbar: {e}")

        if "knx_master.xml" in namelist:
            try:
                xml_bytes = zf.read("knx_master.xml")
                root = self._parse_xml(xml_bytes)
                for mfr in root.iter():
                    if mfr.tag.endswith("Manufacturer") and mfr.get("Id") == folder:
                        name = mfr.get("Name", "")
                        if name:
                            return name
            except Exception as e:
                logger.debug(f"Herstellername aus knx_master.xml nicht lesbar: {e}")

        return folder  # Fallback: Ordnername

    def _parse_hardware_xml(
        self, zf: zipfile.ZipFile, folder: str, namelist: list[str]
    ) -> list[dict]:
        """Liest Hardware-Einträge aus Hardware.xml (inkl. Hardware2ProgramRefId)."""
        hw_path = f"{folder}/Hardware.xml"
        if hw_path not in namelist:
            return []

        try:
            xml_bytes = zf.read(hw_path)
            root = self._parse_xml(xml_bytes)
        except Exception as e:
            logger.warning(f"Hardware.xml in {folder} nicht lesbar: {e}")
            return []

        entries = []
        for hw in root.iter():
            if not hw.tag.endswith("Hardware"):
                continue
            hw_id = hw.get("Id", "")
            hw_name = hw.get("Name", "")

            # Hardware2Program-Einträge dieser Hardware: Ersatz für die
            # Produkt->Applikation-Zuordnung, wenn Catalog.xml für das Produkt
            # keinen CatalogItem führt (z.B. aus einem .knxproj extrahierte
            # Herstellerdateien, die nur einen Teil des Katalogs enthalten).
            own_h2p = [
                h2p.get("Id", "")
                for group in hw if group.tag.endswith("Hardware2Programs")
                for h2p in group if h2p.tag.endswith("Hardware2Program") and h2p.get("Id")
            ]

            for prod in hw:
                if not prod.tag.endswith("Products"):
                    continue
                for product in prod:
                    order_number = product.get("OrderNumber", "")
                    if not order_number:
                        continue

                    channels = int(
                        product.get("ChannelCount")
                        or product.get("NumberOfChannels")
                        or hw.get("BusCurrentNeeded", 0)
                        or 0
                    )

                    # Manche Hersteller (z.B. Theben) führen ApplicationArea gar
                    # nicht in Hardware.xml – dann bleibt category leer und wird
                    # in _parse_zip() über den ETS-Katalogbaum (CatalogSection)
                    # nachtraeglich bestimmt, statt blind auf "actor" zu fallen.
                    app_area = hw.get("ApplicationArea", "")
                    category = _AREA_TO_CATEGORY.get(app_area, "")

                    # KNX Secure-Unterstützung (FA-2705)
                    secure_supported = (
                        hw.get("SupportsTPSecure", "false").lower() == "true"
                        or hw.get("SupportsIPSecure", "false").lower() == "true"
                        or product.get("SupportsTPSecure", "false").lower() == "true"
                        or product.get("SupportsIPSecure", "false").lower() == "true"
                    )

                    entries.append({
                        "id": product.get("Id", hw_id),
                        "name": product.get("Text", hw_name),
                        "order_number": order_number,
                        "channels": channels,
                        "category": category,
                        "hw2prog_id": product.get("Hardware2ProgramRefId", ""),
                        # nur eindeutig verwendbar: genau ein Programm für diese Hardware
                        "hw2prog_fallback": own_h2p[0] if len(own_h2p) == 1 else "",
                        "secure_supported": secure_supported,
                    })

        return entries

    def _parse_catalog_xml(
        self, zf: zipfile.ZipFile, folder: str, namelist: list[str]
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        """
        Liest Catalog.xml.
        Returns (name_map, hw2prog_map, section_map): je ProductRefId → Name,
        Hardware2ProgramRefId bzw. (kleingeschriebener) Pfad der
        CatalogSection-Hierarchie, in der das Produkt einsortiert ist
        (z.B. "physikalische sensoren weather stations"). Manche Hersteller
        tragen Hardware2ProgramRefId nur hier ein (nicht am Product-Element
        in Hardware.xml), z.B. bei Sammel-Produktdatenbanken. Der
        Katalogbaum-Pfad dient als Fallback-Signal für die Kategorie-
        Erkennung, wenn Hardware.xml kein ApplicationArea führt (z.B. Theben).
        """
        cat_path = f"{folder}/Catalog.xml"
        if cat_path not in namelist:
            return {}, {}, {}

        try:
            xml_bytes = zf.read(cat_path)
            root = self._parse_xml(xml_bytes)
        except Exception as e:
            logger.warning(f"Catalog.xml in {folder} nicht lesbar: {e}")
            return {}, {}, {}

        name_map: dict[str, str] = {}
        hw2prog_map: dict[str, str] = {}
        section_map: dict[str, str] = {}

        def _walk(elem: ET.Element, section_path: str) -> None:
            tag = elem.tag.rsplit("}", 1)[-1]
            if tag == "CatalogSection":
                name = elem.get("Name", "")
                if name:
                    section_path = f"{section_path} {name}".strip()
            elif tag == "CatalogItem":
                ref_id = elem.get("ProductRefId", "")
                name = elem.get("Name", "")
                if ref_id and name:
                    name_map[ref_id] = name
                h2p_id = elem.get("Hardware2ProgramRefId", "")
                if ref_id and h2p_id:
                    hw2prog_map[ref_id] = h2p_id
                if ref_id:
                    section_map[ref_id] = section_path.lower()
            for child in elem:
                _walk(child, section_path)

        _walk(root, "")
        return name_map, hw2prog_map, section_map

    def _parse_hw2prog_map(
        self, zf: zipfile.ZipFile, folder: str, namelist: list[str]
    ) -> dict[str, str]:
        """
        Liest Hardware2Program→ApplicationProgram-Mapping aus Hardware.xml.
        Returns {hardware2program_id: application_program_id}
        """
        hw_path = f"{folder}/Hardware.xml"
        if hw_path not in namelist:
            return {}

        try:
            xml_bytes = zf.read(hw_path)
            root = self._parse_xml(xml_bytes)
        except Exception as e:
            logger.debug(f"hw2prog_map aus {hw_path} nicht lesbar: {e}")
            return {}

        hw2prog_map: dict[str, str] = {}
        for elem in root.iter():
            if not elem.tag.endswith("Hardware2Program"):
                continue
            h2p_id = elem.get("Id", "")
            if not h2p_id:
                continue
            for child in elem:
                if child.tag.endswith("ApplicationProgramRef"):
                    app_ref = child.get("RefId", "")
                    if app_ref:
                        hw2prog_map[h2p_id] = app_ref
                    break

        return hw2prog_map

    def _parse_app_programs(
        self, zf: zipfile.ZipFile, folder: str, namelist: list[str]
    ) -> dict[str, list[ComObjectInfo]]:
        """
        Liest ComObjects aus Applikationsprogramm-XMLs.
        Returns {application_program_id: [ComObjectInfo]}

        Applikations-XMLs liegen je nach Hersteller/ETS-Version entweder flach
        direkt im Herstellerordner (M-XXXX/M-XXXX_A-YYYY-ZZ.xml, 2 Segmente)
        oder in einem eigenen Unterordner (M-XXXX/M-XXXX_A-YYYY-ZZ/M-XXXX_A-YYYY-ZZ.xml,
        3 Segmente) - beide Formen sind gültig.
        """
        result: dict[str, list[ComObjectInfo]] = {}
        app_prefix = f"{folder}/{folder}_A-"

        for name in namelist:
            # Nur XML-Dateien im App-Pfad (flach oder in Unterordner)
            parts = name.split("/")
            if len(parts) not in (2, 3):
                continue
            if not name.startswith(app_prefix):
                continue
            if not name.endswith(".xml"):
                continue

            app_id = parts[1] if len(parts) == 3 else parts[1][:-4]  # Vorläufige ID aus Ordner-/Dateiname

            try:
                xml_bytes = zf.read(name)
                root = self._parse_xml(xml_bytes)
            except Exception as e:
                logger.debug(f"App-XML {name} nicht lesbar: {e}")
                continue

            # Echte AppProgram-ID aus XML-Attribut
            for elem in root.iter():
                if elem.tag.endswith("ApplicationProgram"):
                    app_id = elem.get("Id", app_id)
                    break

            com_objects = self._extract_com_objects(root)
            if com_objects:
                result[app_id] = com_objects
                logger.debug(
                    f"App {app_id}: {len(com_objects)} ComObjects gelesen"
                )

        return result

    def _extract_com_objects(self, root: ET.Element) -> list[ComObjectInfo]:
        """Extrahiert ComObjects aus einem Applikationsprogramm-XML.

        KNXPROD trennt die Basisdefinition (<ComObject>, im ComObjectTable) von
        der pro Applikation/Kanal konkretisierten <ComObjectRef> (RefId ->
        ComObject.Id). Viele Hersteller setzen DatapointType und/oder
        Flag-Overrides nur auf dem Ref, nicht auf dem Basisobjekt - deshalb
        werden beide gelesen und je Ref mit den Basiswerten als Fallback
        gemergt (Ref-Attribute haben Vorrang). Basisobjekte ohne zugehörigen
        Ref (Hersteller, die ganz ohne Refs arbeiten) werden ebenfalls als
        eigenständiges ComObject übernommen.

        Refs desselben Basisobjekts, die nach dem Merge identisch sind, werden
        nur einmal übernommen: z.B. bietet das Viessmann Vitogate je
        Objektplatz sieben per Parameter umschaltbare Grössenvarianten
        (1 Bit .. 4 Byte), von denen in der ETS genau eine aktiv ist -- ohne
        Zusammenfassen erschiene jedes Objekt siebenfach und der GA-Bedarf
        wäre versiebenfacht.
        """
        def _flag(attrs: dict, attr: str) -> bool:
            return attrs.get(attr, "Disabled").lower() == "enabled"

        def _build(attrs: dict) -> ComObjectInfo:
            try:
                number = int(attrs.get("Number", 0))
            except (ValueError, TypeError):
                number = 0
            return ComObjectInfo(
                number=number,
                name=attrs.get("Name", ""),
                function_text=attrs.get("Text", attrs.get("FunctionText", "")),
                datapoint_type=attrs.get("DatapointType", ""),
                communication_flag=_flag(attrs, "CommunicationFlag"),
                read_flag=_flag(attrs, "ReadFlag"),
                write_flag=_flag(attrs, "WriteFlag"),
                transmit_flag=_flag(attrs, "TransmitFlag"),
                update_flag=_flag(attrs, "UpdateFlag"),
            )

        base_by_id: dict[str, dict] = {}
        refs: list[dict] = []
        for elem in root.iter():
            if elem.tag.endswith("ComObjectRef"):
                refs.append(dict(elem.attrib))
            elif elem.tag.endswith("ComObject"):
                eid = elem.get("Id", "")
                if eid:
                    base_by_id[eid] = dict(elem.attrib)

        com_objects: list[ComObjectInfo] = []
        consumed_base_ids: set[str] = set()
        seen: set[tuple] = set()

        for ref in refs:
            ref_id = ref.get("RefId", "")
            base = base_by_id.get(ref_id, {})
            consumed_base_ids.add(ref_id)
            merged = {**base, **ref}
            co = _build(merged)
            key = (ref_id, *co.to_dict().values())
            if key in seen:
                continue
            seen.add(key)
            com_objects.append(co)

        for base_id, base in base_by_id.items():
            if base_id not in consumed_base_ids:
                com_objects.append(_build(base))

        return com_objects

    def _parse_xml(self, data: bytes) -> ET.Element:
        """Parst XML-Bytes, entfernt ggf. störende Namespaces."""
        try:
            return ET.fromstring(data)
        except ET.ParseError:
            cleaned = data.lstrip(b"\xef\xbb\xbf")
            return ET.fromstring(cleaned)

    # Katalogbaum-Stichworte -> Kategorie (Fallback wenn Hardware.xml kein
    # ApplicationArea führt, z.B. Theben-Exporte). Deutsch/Englisch gemischt,
    # da Hersteller-Kataloge je Sprache unterschiedlich benannt sind.
    _SECTION_TO_CATEGORY: tuple[tuple[tuple[str, ...], str], ...] = (
        (("sensor", "fühler", "fuehler", "melder", "wetterstation", "weather"), "sensor"),
        (("koppler", "coupler", "netzteil", "power supply", "schnittstelle",
          "interface", "router", "gateway"), "infrastructure"),
    )

    def _infer_category_from_section(self, section_path: str) -> str:
        """Best-Effort Kategorie-Erkennung anhand des ETS-Katalogbaums
        (CatalogSection-Pfad), falls Hardware.xml kein ApplicationArea führt."""
        if not section_path:
            return ""
        for keywords, cat in self._SECTION_TO_CATEGORY:
            if any(k in section_path for k in keywords):
                return cat
        return ""

    # Eingangs-Schnittstellen (Taster, Fensterkontakte) sind Sensoren, auch
    # wenn ihr Name "Interface"/"Schnittstelle" enthält -- wird vor den
    # Katalogbaum-Stichworten geprüft.
    _NAME_SENSOR_KEYWORDS: tuple[str, ...] = (
        "universal interface", "universalschnittstelle", "tasterschnittstelle",
        "fensterschnittstelle", "binäreingang", "binaereingang", "binary input",
    )

    def _infer_category_from_name(self, product_name: str) -> str:
        """Letzter Ausweg, wenn weder Hardware.xml (ApplicationArea) noch der
        Katalogbaum eine Kategorie liefern: Stichworte im Produktnamen."""
        name = product_name.lower()
        if any(k in name for k in self._NAME_SENSOR_KEYWORDS):
            return "sensor"
        return self._infer_category_from_section(name)

    def _infer_device_type(self, product_name: str, category: str,
                           section_path: str = "") -> str:
        """Leitet den Gerätetyp aus Produktname und Katalogbaum-Pfad ab
        (Best-Effort). `section_path` hilft bei Herstellern, deren
        Produktnamen selbst keine erkennbaren Stichworte enthalten
        (z.B. "Meteodata 140" statt "Wetterstation")."""
        name_lower = f"{product_name.lower()} {section_path}"

        if category == "infrastructure":
            if "linienkoppler" in name_lower or "line coupler" in name_lower:
                return "Linienkoppler"
            if "bereichskoppler" in name_lower or "area coupler" in name_lower:
                return "Bereichskoppler"
            if "ip router" in name_lower or "ip-router" in name_lower:
                return "IP-Router"
            if "netzteil" in name_lower or "power supply" in name_lower:
                return "Netzteil"
            if "dali" in name_lower:
                return "DALI-Gateway"
            return "Sonstiges"

        if category == "actor":
            if "jalousie" in name_lower or "shutter" in name_lower:
                return "Jalousieaktor"
            if "dimm" in name_lower or "dim" in name_lower:
                return "Dimmaktor"
            if "heizung" in name_lower or "heat" in name_lower:
                return "Heizungsaktor"
            if "dali" in name_lower:
                return "DALI-Gateway"
            return "Schaltaktor"

        if category == "sensor":
            if "taster" in name_lower or "push" in name_lower:
                return "Tastereinheit"
            if "thermostat" in name_lower or "temperatur" in name_lower:
                return "Raumthermostat"
            if "präsenz" in name_lower or "praesenz" in name_lower or "presence" in name_lower:
                return "Praesenzmelder"
            if "bewegung" in name_lower or "motion" in name_lower:
                return "Bewegungsmelder"
            if "wetter" in name_lower or "weather" in name_lower:
                return "Wetterstation"
            return "Sensor"

        return "Sonstiges"
