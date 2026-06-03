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
            mfr_name = self._resolve_manufacturer_name(zf, folder, namelist)

            # Hardware.xml, Catalog.xml lesen
            hardware_entries = self._parse_hardware_xml(zf, folder, namelist)
            catalog_names = self._parse_catalog_xml(zf, folder, namelist)

            # Applikationsprogramm-XMLs und Hardware2Program-Mapping lesen
            hw2prog_map = self._parse_hw2prog_map(zf, folder, namelist)
            app_comobjects = self._parse_app_programs(zf, folder, namelist)

            for hw in hardware_entries:
                # Produktname aus Catalog.xml ergänzen
                full_name = catalog_names.get(hw["id"], hw.get("name", ""))
                order_number = hw.get("order_number", "")
                channels = hw.get("channels", 0)
                category = hw.get("category", "actor")
                device_type = self._infer_device_type(full_name, category)

                # ComObjects über Hardware2Program → ApplikationsprogrammID auflösen
                hw2prog_id = hw.get("hw2prog_id", "")
                app_id = hw2prog_map.get(hw2prog_id, "")
                com_objects = app_comobjects.get(app_id, [])

                # Fallback: wenn kein direkter Match, alle ComObjects aus diesem Ordner
                if not com_objects and app_comobjects:
                    all_cos = []
                    for cos in app_comobjects.values():
                        all_cos.extend(cos)
                    com_objects = all_cos

                prod = KnxprodProduct(
                    manufacturer=mfr_name,
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
        """Versucht den Herstellernamen aus Catalog.xml zu lesen."""
        catalog_path = f"{folder}/Catalog.xml"
        if catalog_path not in namelist:
            return folder

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

                    app_area = hw.get("ApplicationArea", "")
                    category = _AREA_TO_CATEGORY.get(app_area, "actor")

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
                        "secure_supported": secure_supported,
                    })

        return entries

    def _parse_catalog_xml(
        self, zf: zipfile.ZipFile, folder: str, namelist: list[str]
    ) -> dict[str, str]:
        """Liest Produktnamen aus Catalog.xml (ID → Name-Mapping)."""
        cat_path = f"{folder}/Catalog.xml"
        if cat_path not in namelist:
            return {}

        try:
            xml_bytes = zf.read(cat_path)
            root = self._parse_xml(xml_bytes)
        except Exception as e:
            logger.warning(f"Catalog.xml in {folder} nicht lesbar: {e}")
            return {}

        name_map: dict[str, str] = {}
        for elem in root.iter():
            if not elem.tag.endswith("CatalogItem"):
                continue
            ref_id = elem.get("ProductRefId", "")
            name = elem.get("Name", "")
            if ref_id and name:
                name_map[ref_id] = name

        return name_map

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

        Applikations-XMLs liegen in Unterordnern: M-XXXX/M-XXXX_A-YYYY-ZZ/M-XXXX_A-YYYY-ZZ.xml
        """
        result: dict[str, list[ComObjectInfo]] = {}
        app_prefix = f"{folder}/{folder}_A-"

        for name in namelist:
            # Nur XML-Dateien in App-Unterordnern
            parts = name.split("/")
            if len(parts) != 3:
                continue
            if not name.startswith(app_prefix):
                continue
            if not parts[2].endswith(".xml"):
                continue

            app_id = parts[1]  # Vorläufige ID aus Ordnername

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
        """Extrahiert alle ComObject-Elemente aus einem Applikationsprogramm-XML."""
        com_objects: list[ComObjectInfo] = []

        def _flag(elem: ET.Element, attr: str) -> bool:
            return elem.get(attr, "Disabled").lower() == "enabled"

        for co in root.iter():
            if not co.tag.endswith("ComObject"):
                continue

            # Objektnummer: Number oder ParentObjectId
            try:
                number = int(co.get("Number", 0))
            except (ValueError, TypeError):
                number = 0

            info = ComObjectInfo(
                number=number,
                name=co.get("Name", ""),
                function_text=co.get("Text", co.get("FunctionText", "")),
                datapoint_type=co.get("DatapointType", ""),
                communication_flag=_flag(co, "CommunicationFlag"),
                read_flag=_flag(co, "ReadFlag"),
                write_flag=_flag(co, "WriteFlag"),
                transmit_flag=_flag(co, "TransmitFlag"),
                update_flag=_flag(co, "UpdateFlag"),
            )
            com_objects.append(info)

        return com_objects

    def _parse_xml(self, data: bytes) -> ET.Element:
        """Parst XML-Bytes, entfernt ggf. störende Namespaces."""
        try:
            return ET.fromstring(data)
        except ET.ParseError:
            cleaned = data.lstrip(b"\xef\xbb\xbf")
            return ET.fromstring(cleaned)

    def _infer_device_type(self, product_name: str, category: str) -> str:
        """Leitet den Gerätetyp aus dem Produktnamen ab (Best-Effort)."""
        name_lower = product_name.lower()

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
