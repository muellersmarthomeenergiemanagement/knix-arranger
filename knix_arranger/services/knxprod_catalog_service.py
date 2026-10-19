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
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..utils.manufacturers import canonical_manufacturer
from .ko_size import dpt_from_size

logger = logging.getLogger("knix_arranger.knxprod_catalog")

# Version des Einlesens: steigt, wenn dieselbe Datei andere Produktdaten
# ergibt. Ältere Einträge im Produktordner-Index gelten als neu einzulesen
# (product_folder.pending_files). 2: Name/Objektfunktion richtig, deutsche
# Übersetzung, Grösse (1.4.10); 3: Parameterbedingungen je KO-Variante
# aus dem Dynamic-Abschnitt (ETS-Parametrier-Anleitung); 4: Module je Instanz
# (MDT, Theben MIX), Bedingungen als Alternativen
READER_VERSION = 4

# Objektfunktion, die nur die Grösse nennt ("1 bit", "4 Byte")
_SIZE_ONLY = re.compile(r"\s*\d+\s*(bit|bits|byte|bytes)\s*", re.IGNORECASE)

# Platzhalter in KO-Texten, die die ETS aus Parametern füllt, z.B.
# "{{0}}Leckage Alarm Text" oder "{{0:Room 1}}: Room Status" (mit Standardtext)
_PLACEHOLDER_RE = re.compile(r"\{\{\s*\d*\s*(?::([^}]*))?\}\}")


def clean_co_text(text: str) -> str:
    """KO-Text wie die ETS ihn ohne Parameter zeigt: Platzhalter mit
    Standardtext durch diesen ersetzt, sonst entfernt.
    "{{0}}Leckage Alarm Text" -> "Leckage Alarm Text",
    "{{0:Room 1}}: Room Status" -> "Room 1: Room Status"."""
    text = _PLACEHOLDER_RE.sub(lambda m: (m.group(1) or "").strip() or " ", text or "")
    return " ".join(text.split()).lstrip(":-–| ").strip()


_PLACEHOLDER_ONLY = re.compile(r"\s*(?:\{\{[^}]*\}\}\s*)*")


def is_placeholder_text(text: str) -> bool:
    """Nur ETS-Platzhalter wie "{{0:GO}}" (oder leer): der Text hängt von
    Parametern ab und sagt nichts über die Funktion."""
    return bool(_PLACEHOLDER_ONLY.fullmatch(text or ""))


_ARGUMENT_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def _argument_substitution(values: dict[str, str]):
    """Setzt Argumente einer Modul-Instanz in Texte ein: «F{{ChNo}}: {{0}}»
    mit ChNo=2 -> «F2: {{0}}» ({{0}} = Textparameter, bleibt)."""
    def subst(text: str) -> str:
        return _ARGUMENT_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text or "")
    return subst


_MAX_ALTERNATIVES = 6


def condition_alternatives(conditions: list) -> list[list]:
    """Bedingungen einer Variante als Alternativen (jede eine Liste von
    [Parameter, Test], die alle gelten müssen). Ältere Daten (READER 3 vor
    Stufe 2) führten eine einzige flache Liste."""
    if not conditions:
        return []
    return conditions if _is_alternatives(conditions) else [conditions]


def _is_alternatives(conditions: list) -> bool:
    """Liste von Alternativen (Listen von Paaren) statt einer flachen Kette
    von Paaren [Parameter, Test]; eine leere Alternative = immer aktiv."""
    return all(isinstance(alt, list) and (not alt or not isinstance(alt[0], str))
               for alt in conditions)


def reduce_alternatives(chains: list, canon=None) -> list[list]:
    """Fundstellen einer Variante zu Alternativen zusammenfassen: gleiche
    entfallen; zwei, die sich nur im Wert EINES Parameters unterscheiden,
    werden eine ohne diesen Parameter (Feller: dieselbe Taste unter
    «Szenenfunktion = lokal» und «= dezentral» -> die Szenenfunktion
    entscheidet nicht). Andere bleiben getrennt (MDT: «Schalten» unter
    «Einzel-Tastenfunktion = Schalten, Unterfunktion = Schalten» ODER «=
    Werte senden, Unterfunktion (Werte) = Werte senden, DPT 1.001») -- sonst
    entstünde eine Mischung, die es in der ETS nicht gibt. Höchstens
    _MAX_ALTERNATIVES, die kürzesten.

    canon(param, test) -> (Parameter-Sicht, Wert-Sicht): verglichen wird, was
    die ETS zeigt (Seite, Name, Wert als Text) -- Feller führt «Funktion
    Taste» je Szenen-Zweig als eigenen Parameter mit gleichem Namen."""
    canon = canon or (lambda param, test: (param, test))
    alternatives: list[dict] = []      # Sicht -> (Parameter, Test, Wert-Sicht)
    for chain in chains:
        conds = {}
        for ref, test in chain:
            view, value = canon(ref, test)
            conds.setdefault(view, (ref, test, value))
        if not any(_same_values(conds, other) for other in alternatives):
            alternatives.append(conds)
    changed = True
    while changed and len(alternatives) > 1:
        changed = False
        for i, a in enumerate(alternatives):
            for b in alternatives[i + 1:]:
                if a.keys() != b.keys():
                    continue
                differing = [k for k in a if a[k][2] != b[k][2]]
                if len(differing) == 1:
                    merged = {k: v for k, v in a.items() if k != differing[0]}
                    alternatives = [x for x in alternatives if x is not a and x is not b]
                    if not any(_same_values(merged, other) for other in alternatives):
                        alternatives.append(merged)
                    changed = True
                    break
            if changed:
                break
    alternatives.sort(key=len)
    return [[[ref, test] for ref, test, _value in alt.values()]
            for alt in alternatives[:_MAX_ALTERNATIVES]]


def _same_values(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(a[k][2] == b[k][2] for k in a)


def merge_conditions(*chains: list, canon=None) -> list:
    """Bedingungen mehrerer Fundstellen zusammenführen (Alternativen, siehe
    reduce_alternatives); nimmt flache Ketten und Alternativen-Listen."""
    flat = []
    for chain in chains:
        if chain and _is_alternatives(chain):
            flat.extend(chain)          # bereits Alternativen
        else:
            flat.append(chain)
    return reduce_alternatives(flat, canon)


_NOT_ALNUM = re.compile(r"[^a-z0-9]")
_TEST_OPERATOR = re.compile(r"^\s*(!=|<=|>=|<|>|=)\s*(-?\d+(?:\.\d+)?)\s*$")


def when_matches(test: str, value: str) -> bool:
    """Erfüllt der Parameterwert die Bedingung einer when-Klausel? «3»,
    «1 2 3» (einer davon), «!=0», «>2» …"""
    found = _TEST_OPERATOR.match(test or "")
    if found:
        try:
            left, right = float(value), float(found.group(2))
        except ValueError:
            return False
        return {"!=": left != right, "<=": left <= right, ">=": left >= right,
                "<": left < right, ">": left > right, "=": left == right}[found.group(1)]
    return value in (test or "").split()


def product_fixed_values(parameters: dict, product_name: str, order_number: str = "") -> dict:
    """Parameter, deren Wert das Gerät selbst festlegt: genau ein Wert
    heisst wie das Gerät (Theben MIX «Art des Grundmoduls» = «HMG 6 T..»
    beim HMG 6 T). {Parameter-Id: Wert}."""
    names = {_NOT_ALNUM.sub("", t.lower()) for t in (product_name, order_number) if t}
    names = {n for n in names if len(n) >= 4}
    fixed = {}
    for param, (_block, _label, values, visible) in parameters.items():
        if not visible or "|" in param:
            continue
        matches = []
        for value, text in values.items():
            norm = _NOT_ALNUM.sub("", (text or "").lower())
            if norm and any(norm == n or (len(norm) > len(n) and norm.startswith(n))
                            for n in names):
                matches.append(value)
        if len(matches) == 1:
            fixed[param] = matches[0]
    return fixed


def restrict_to_product(com_objects: list, parameters: dict, product_name: str,
                        order_number: str = "") -> list:
    """Nur die KO-Varianten, die bei den vom Gerät festgelegten Parametern
    (product_fixed_values) bestehen; diese Parameter fallen aus den
    Bedingungen (keine Anweisung nötig). Varianten ohne Bedingungen bleiben."""
    import dataclasses
    fixed = product_fixed_values(parameters, product_name, order_number)
    if not fixed:
        return com_objects
    result = []
    for co in com_objects:
        alternatives = condition_alternatives(co.conditions)
        if not alternatives:
            result.append(co)
            continue
        kept = [[[p, t] for p, t in alt if p not in fixed] for alt in alternatives
                if all(when_matches(t, fixed[p]) for p, t in alt if p in fixed)]
        if kept:
            result.append(dataclasses.replace(co, conditions=kept))
    return result


def unique_com_objects(com_objects: list[dict]) -> list[dict]:
    """Ein ComObject je Nummer: Applikationen führen dieselbe Nummer in
    mehreren Parametervarianten (Elsner Leak: KO 2 «Leckage Alarm» zweimal).
    Ausgewählt wird nach Nummer -- doppelte Zeilen hoben sich sonst auf.
    Steht in der ersten Variante nur ein Platzhalter ("{{0:GO}}", Griesser
    JAX-9), gilt die erste mit echtem Funktionstext."""
    chosen: dict = {}
    for co in com_objects:
        number = co.get("number")
        if number is None:          # ohne Nummer: nicht zusammenfassen
            number = ("ohne Nummer", id(co))
        if number not in chosen:
            chosen[number] = co
        elif (is_placeholder_text(chosen[number].get("function_text", ""))
              and not is_placeholder_text(co.get("function_text", ""))):
            chosen[number] = co
    return list(chosen.values())

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
    name: str = ""                # Text-Attribut = ETS-Spalte «Name», z.B. "Kanal C1"
    function_text: str = ""       # FunctionText = ETS «Objektfunktion», z.B. "Dimmwert"
    datapoint_type: str = ""      # z.B. "DPT-1", "DPT-5.001"
    object_size: str = ""         # ObjectSize, z.B. "1 Bit", "1 Byte"
    # Parameterbedingungen, unter denen diese Variante in der ETS aktiv ist
    # ([ParameterRef-Id, Test], z.B. [..._P-12_R-34, "3"]); Texte dazu in
    # KnxprodProduct.parameters
    conditions: list = field(default_factory=list)
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
        """Flags in ETS-Schreibweise K L S Ü A I, z.B. 'K-S---' (Empfänger),
        'KL-Ü--' (Status). Ältere Daten mit fünf Stellen ('K-Ü--', Schreiben
        als Ü) deutet ko_links.parse_flags weiterhin richtig."""
        return "".join([
            "K" if self.communication_flag else "-",
            "L" if self.read_flag else "-",
            "S" if self.write_flag else "-",
            "Ü" if self.transmit_flag else "-",
            "A" if self.update_flag else "-",
            "-",
        ])

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "function_text": self.function_text,
            "datapoint_type": self.datapoint_type,
            "object_size": self.object_size,
            **({"conditions": [list(c) for c in self.conditions]} if self.conditions else {}),
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
            object_size=data.get("object_size", ""),
            conditions=[list(c) for c in data.get("conditions") or []],
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
    # ETS-Kennungen fuer den Projekt-Export (DeviceInstance ProductRefId /
    # Hardware2ProgramRefId) und die zugehoerige Applikation
    product_ref_id: str = ""
    hw2prog_id: str = ""
    application_program_id: str = ""
    actor_type: str = ""
    sensor_type: str = ""
    com_objects: list[ComObjectInfo] = field(default_factory=list)
    secure_supported: bool = False   # KNX Secure Unterstuetzung (FA-2705)
    # Parameter der Bedingungen: {ParameterRef-Id: [Block, Name, {Wert: Text},
    # sichtbar]} (aus dem Dynamic-Abschnitt der Applikation)
    parameters: dict = field(default_factory=dict)

    @property
    def ga_min(self) -> int:
        """Minimaler GA-Bedarf: ComObjects mit Schreib- oder Sendeobjekt
        (je Nummer einmal -- Parametervarianten zählen nicht mehrfach)."""
        return len({
            co.number for co in self.com_objects
            if co.communication_flag and (co.write_flag or co.transmit_flag)
        })

    @property
    def ga_max(self) -> int:
        """Maximaler GA-Bedarf: alle aktiven ComObjects (je Nummer einmal)."""
        return len({co.number for co in self.com_objects if co.needs_ga})

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
            "product_ref_id": self.product_ref_id,
            "hw2prog_id": self.hw2prog_id,
            "application_program_id": self.application_program_id,
            **({"parameters": self.parameters} if self.parameters else {}),
        }


class KnxprodCatalogService:
    """Liest Produktdaten aus .knxprod-Dateien (FA-2304)."""

    def __init__(self):
        # Applikationen mit IsSecureEnabled="true" (KNX Secure, FA-2705) --
        # manche Hersteller (z.B. Weinzierl) setzen SupportsTPSecure an der
        # Hardware nicht, nur an der Applikation.
        self._secure_app_ids: set[str] = set()
        # Parametertabelle je Applikation (_dynamic_conditions)
        self._app_parameters: dict[str, dict] = {}

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
            secure_app_ids = self._secure_app_ids

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
                category_hint = (
                    hw.get("category")
                    or self._infer_category_from_section(section_path)
                    or self._infer_category_from_name(full_name)
                )

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
                # Eine Applikation für mehrere Geräte (Theben MIX: «Art des
                # Grundmoduls» = RMG 8 S, HMG 6 T …): nur die KOs dieses Geräts
                parameters = self._app_parameters.get(app_id) or (
                    next(iter(self._app_parameters.values()))
                    if len(app_comobjects) == 1 and self._app_parameters else {})
                com_objects = restrict_to_product(
                    com_objects, parameters, full_name or order_number, order_number)

                # Gerätetyp und Kanäle aus Name und KOs (product_classifier).
                # Die Kategorie der Herstellerdatei (ApplicationArea) behält
                # Vorrang; ohne sie gilt die Einordnung (früher: alles "actor")
                from .product_classifier import classify
                found = classify(full_name, order_number, category_hint,
                                 [co.to_dict() for co in com_objects])
                category = hw.get("category") or found.category
                device_type = found.device_type
                channels = channels or found.channels
                if device_type == "DALI-Gateway" and found.channels:
                    channels = found.channels   # Gruppen, nicht die Zahl im Namen

                prod = KnxprodProduct(
                    manufacturer=mfr_name,
                    manufacturer_id=mfr_id,
                    product_ref_id=hw.get("product_ref_id", ""),
                    hw2prog_id=hw2prog_id,
                    application_program_id=app_id,
                    order_number=order_number,
                    product_name=full_name or order_number,
                    channels=channels,
                    category=category,
                    device_type=device_type,
                    actor_type=device_type if category == "actor" else "",
                    sensor_type=device_type if category == "sensor" else "",
                    com_objects=com_objects,
                    parameters=parameters,
                    secure_supported=(
                        hw.get("secure_supported", False) or app_id in secure_app_ids
                    ),
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
                        "product_ref_id": product.get("Id", ""),
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
                    if elem.get("IsSecureEnabled", "").lower() == "true":
                        self._secure_app_ids.add(app_id)
                    break

            com_objects = self._extract_com_objects(root)
            if self._last_parameters:
                self._app_parameters[app_id] = self._last_parameters
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
            # ETS: Text = «Name» ("Kanal C1"), FunctionText = «Objekt-
            # funktion» ("Dimmwert"). Bis 1.4.9 galt Text als Funktion --
            # bei 87 % der KOs ging so die Funktion verloren. Name ist nur
            # die interne Kennung.
            name = attrs.get("Text") or attrs.get("Name", "")
            internal = attrs.get("Name", "")
            if is_placeholder_text(name) and internal and not is_placeholder_text(internal):
                # Nur Platzhalter ohne Standardtext (Theben-Module «{{ObjName}}
                # {{ChannelNr}} {{0}}»): dann die Kennung, falls sprechend.
                # «{{0:Kanal A}}» (ABB) bleibt -- daraus wird «Kanal A».
                name = internal
            function = attrs.get("FunctionText") or ""
            size = attrs.get("ObjectSize", "")
            if not function or _SIZE_ONLY.fullmatch(function):
                # «1 Byte» als Objektfunktion (Viessmann) sagt nichts
                function = attrs.get("Text", "")
            return ComObjectInfo(
                number=number,
                name=name,
                function_text=function,
                datapoint_type=attrs.get("DatapointType", "") or dpt_from_size(size),
                object_size=size,
                communication_flag=_flag(attrs, "CommunicationFlag"),
                read_flag=_flag(attrs, "ReadFlag"),
                write_flag=_flag(attrs, "WriteFlag"),
                transmit_flag=_flag(attrs, "TransmitFlag"),
                update_flag=_flag(attrs, "UpdateFlag"),
            )

        base_by_id: dict[str, dict] = {}
        refs: list[dict] = []
        module_refs: list[dict] = []          # ComObjectRefs in Bausteinen (_MD-)
        param_ref_target: dict[str, str] = {}
        param_value: dict[str, str] = {}
        for elem in root.iter():
            tag = self._local(elem.tag)
            if tag == "ComObjectRef":
                (module_refs if "_MD-" in elem.get("Id", "") else refs).append(dict(elem.attrib))
            elif tag == "ComObject":
                eid = elem.get("Id", "")
                if eid:
                    base_by_id[eid] = dict(elem.attrib)
            elif tag == "ParameterRef":
                param_ref_target[elem.get("Id", "")] = elem.get("RefId", "")
            elif tag == "Parameter":
                param_value[elem.get("Id", "")] = elem.get("Value", "")

        # Deutsche Texte (Übersetzung je Id), sonst die Grundsprache
        german = self._german_texts(root)
        # Parameterbedingungen je (Geltungsbereich, ComObjectRef) und die
        # Modul-Instanzen (Dynamic-Abschnitt)
        conditions, self._last_parameters = self._dynamic_conditions(root)

        def _translated(attrs: dict) -> dict:
            return {**attrs, **german.get(attrs.get("Id", ""), {})}

        com_objects: list[ComObjectInfo] = []
        consumed_base_ids: set[str] = set()
        seen: dict[tuple, ComObjectInfo] = {}

        def add(co: ComObjectInfo, key: tuple) -> None:
            if key in seen:
                # Gleiche Variante an anderer Stelle: es gelten nur die
                # Bedingungen, die beide Stellen teilen
                kept = seen[key]
                kept.conditions = merge_conditions(kept.conditions, co.conditions,
                                                   canon=self._last_canon)
                return
            seen[key] = co
            com_objects.append(co)

        for ref in refs:
            ref_id = ref.get("RefId", "")
            base = base_by_id.get(ref_id, {})
            consumed_base_ids.add(ref_id)
            # Texte der Ref (auch übersetzt) haben Vorrang vor dem Basisobjekt
            merged = {**_translated(base), **_translated(ref)}
            if "{{" in merged.get("Text", "") and merged.get("TextParameterRefId"):
                # «Logik 1 {{0}}»: {{0}} = Textparameter, dessen Vorgabe
                default = param_value.get(param_ref_target.get(
                    merged["TextParameterRefId"], ""), "")
                merged["Text"] = " ".join(_PLACEHOLDER_RE.sub(
                    lambda m: default or (m.group(1) or ""), merged["Text"]).split()).rstrip(" :")
            co = _build(merged)
            co.conditions = conditions.get(("", ref.get("Id", "")), [])
            # Varianten, die sich nur in der Grösse unterscheiden, sind ein KO
            # (Viessmann Vitogate: sieben Grössen je Objektplatz)
            add(co, (ref_id, co.number, co.name, co.function_text,
                     merged.get("DatapointType", ""), co.flags_display))

        # Bausteine (Stufe 2): je Instanz die KOs, die ihr Dynamic-Abschnitt
        # nennt -- Nummer = Basis-Argument + relative Nummer, Texte mit den
        # Argumenten («F{{ChNo}}: {{0}}» -> «F2: …»)
        by_module: dict[str, list[dict]] = {}
        for ref in module_refs:
            by_module.setdefault(ref.get("Id", "").split("_O-")[0], []).append(ref)
        argument_names = {a.get("Id", ""): a.get("Name", "") for a in root.iter()
                          if self._local(a.tag) == "Argument"} if self._last_instances else {}
        for instance, module_id, values in self._last_instances:
            subst = _argument_substitution(values)
            args = argument_names
            for ref in by_module.get(module_id, []):
                key = (instance, ref.get("Id", ""))
                if key not in conditions:
                    continue        # in dieser Instanz nie aktiv
                base = base_by_id.get(ref.get("RefId", ""), {})
                merged = {**_translated(base), **_translated(ref)}
                default = param_value.get(param_ref_target.get(
                    merged.get("TextParameterRefId", ""), ""), "")
                for attr in ("Text", "FunctionText", "Name"):
                    if merged.get(attr):
                        text = subst(merged[attr])
                        # {{0}} = Textparameter: dessen Vorgabe, sonst Standardtext
                        text = _PLACEHOLDER_RE.sub(lambda m: default or (m.group(1) or ""),
                                                   text)
                        # «F2: » mit leerem Textparameter -> «F2»
                        merged[attr] = " ".join(text.split()).rstrip(" :")
                try:
                    offset = int(values.get(args.get(base.get("BaseNumber", ""), ""), 0) or 0)
                except ValueError:
                    offset = 0
                co = _build(merged)
                co.number += offset
                co.conditions = conditions[key]
                add(co, (instance, ref.get("RefId", ""), co.number, co.name,
                         co.function_text, merged.get("DatapointType", ""), co.flags_display))
            for base_id in base_by_id:
                if base_id.startswith(module_id + "_"):
                    consumed_base_ids.add(base_id)

        for base_id, base in base_by_id.items():
            if base_id not in consumed_base_ids and "_MD-" not in base_id:
                com_objects.append(_build(_translated(base)))

        return com_objects

    _last_instances: list = []
    _last_canon = None

    _last_parameters: dict = {}

    @staticmethod
    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def _dynamic_conditions(self, root: ET.Element) -> tuple[dict, dict]:
        """Unter welchen Parameterwerten ist eine KO-Variante aktiv?

        Wertet den Dynamic-Abschnitt der Applikation aus (choose/when über
        Parameter, KNX-Standard): je ComObjectRef die Kette der expliziten
        Bedingungen [ParameterRef-Id, Test] bis zum ComObjectRefRef (erste
        Fundstelle; Standardzweige «sonst» zählen nicht). Dazu die Texte der
        beteiligten Parameter: {ParameterRef-Id: [Block, Name, {Wert: Text},
        sichtbar]} -- Block = Parameterseite, auf der die ETS den Parameter
        zeigt («Taste 1, links»); unsichtbare Parameter stehen in keinem Block.
        Module (ModuleDef, Stufe 2) werden nicht aufgelöst."""
        local = self._local
        self._last_instances = []
        self._last_canon = None
        program = next((el for el in root.iter() if local(el.tag) == "ApplicationProgram"),
                       None)
        dynamic = next((el for el in (program if program is not None else [])
                        if local(el.tag) == "Dynamic"), None)
        if dynamic is None:
            return {}, {}
        german = self._german_all_texts(root)

        def text_of(el) -> str:
            return ((german.get(el.get("Id", "")) or {}).get("Text")
                    or el.get("Text") or "")

        # Bausteine (ModuleDef, z.B. MDT «ModuleDefOneButton»): Argumente
        # (Id -> Name) und eigener Dynamic-Abschnitt
        module_defs: dict[str, tuple[dict, ET.Element | None]] = {}
        for el in program.iter():
            if local(el.tag) == "ModuleDef":
                args = {a.get("Id", ""): a.get("Name", "") for a in el.iter()
                        if local(a.tag) == "Argument"}
                own_dynamic = next((c for c in el if local(c.tag) == "Dynamic"), None)
                module_defs[el.get("Id", "")] = (args, own_dynamic)

        # Bedingungen je (Geltungsbereich, ComObjectRef-Id); Geltungsbereich ""
        # = Applikation, sonst die Modul-Instanz («…_MD-1_M-2»). Parameter
        # eines Bausteins gelten je Instanz: ihre Kennung wird «Instanz|Id»
        chains: dict[tuple, list] = {}
        placed: dict[str, str] = {}
        self._last_instances = []

        def walk(el, conds, block, choose_param=None, scope="", subst=None):
            tag = local(el.tag)

            def scoped(ref_id: str) -> str:
                return f"{scope}|{ref_id}" if scope and "_MD-" in ref_id else ref_id

            if tag in ("ParameterBlock", "Channel"):
                text = text_of(el) or el.get("Name", "")
                block = clean_co_text(subst(text) if subst else text).rstrip(" :") or block
            elif tag == "ParameterRefRef":
                placed.setdefault(scoped(el.get("RefId", "")), block)
                return
            elif tag == "ComObjectRefRef":
                chains.setdefault((scope, el.get("RefId", "")), []).append(list(conds))
                return
            elif tag == "choose":
                for child in el:
                    walk(child, conds, block, scoped(el.get("ParamRefId", "")), scope, subst)
                return
            elif tag == "when":
                test = el.get("test")
                new = conds + [(choose_param, test)] if test is not None and choose_param \
                    else conds
                for child in el:
                    walk(child, new, block, None, scope, subst)
                return
            elif tag == "Module" and el.get("RefId") in module_defs:
                args, own_dynamic = module_defs[el.get("RefId")]
                values = {args.get(a.get("RefId", ""), ""): a.get("Value", "")
                          for a in el if local(a.tag) in ("NumericArg", "TextArg")}
                instance = el.get("Id", "")
                self._last_instances.append((instance, el.get("RefId"), values))
                if own_dynamic is not None:
                    module_subst = _argument_substitution(values)
                    walk(own_dynamic, conds, block, None, instance, module_subst)
                return
            for child in el:
                walk(child, conds, block, choose_param, scope, subst)

        walk(dynamic, [], "")
        params, param_refs, type_values = {}, {}, {}
        for el in program.iter():
            tag = local(el.tag)
            if tag == "Parameter":
                params[el.get("Id", "")] = el
            elif tag == "ParameterRef":
                param_refs[el.get("Id", "")] = el
            elif tag == "ParameterType":
                values = {}
                for item in el.iter():
                    if local(item.tag) == "Enumeration":
                        values[item.get("Value", "")] = text_of(item)
                if values:
                    type_values[el.get("Id", "")] = values
        # Bedingungen über den Parameter selbst: mehrere ParameterRefs zeigen
        # auf denselben Parameter (Feller «Anzahl Tasten» = 2 bzw. 4); in
        # Bausteinen je Instanz («Instanz|Parameter-Id»)
        def split(scoped_id: str) -> tuple[str, str]:
            scope, _sep, raw = scoped_id.rpartition("|")
            return scope, raw

        def parameter_of(scoped_ref: str) -> str:
            scope, raw = split(scoped_ref)
            ref = param_refs.get(raw)
            param = ref.get("RefId", raw) if ref is not None else raw
            return f"{scope}|{param}" if scope else param

        refs_of: dict[str, list[str]] = {}
        for ref_id, ref in param_refs.items():
            refs_of.setdefault(ref.get("RefId", ""), []).append(ref_id)
        substs = {instance: _argument_substitution(values)
                  for instance, _md, values in self._last_instances}
        converted_by_key = {
            key: [[(parameter_of(ref), test) for ref, test in chain] for chain in found]
            for key, found in chains.items()}
        used = {param for found in converted_by_key.values() for chain in found
                for param, _test in chain}
        table = {}
        for param_id in used:
            scope, raw = split(param_id)
            subst = substs.get(scope)
            par = params.get(raw)
            own_refs = [f"{scope}|{r}" if scope else r for r in refs_of.get(raw, [])]
            ref = next((param_refs[split(r)[1]] for r in own_refs
                        if text_of(param_refs[split(r)[1]])), None)
            name = (text_of(ref) if ref is not None else "") \
                or (text_of(par) if par is not None else "") \
                or (par.get("Name", "") if par is not None else "")
            if subst:
                name = clean_co_text(subst(name))
            values = type_values.get(par.get("ParameterType", ""), {}) if par is not None else {}
            block = next((placed[r] for r in own_refs if r in placed), "")
            table[param_id] = [block, " ".join(name.split()).rstrip(" :"), values,
                               any(r in placed for r in own_refs)]

        # Dieselbe Variante an mehreren Stellen (z.B. unter «Szenenfunktion
        # = lokal» und «= dezentral»): verglichen wird, was die ETS zeigt
        def canon(param: str, test: str) -> tuple:
            info = table.get(param)
            if not info:
                return param, test
            block, label, values, _visible = info
            return (block, label), values.get(test, test)

        self._last_canon = canon
        result = {key: merge_conditions(*found, canon=canon)
                  for key, found in converted_by_key.items()}
        used = {param for alternatives in result.values() for alt in alternatives
                for param, _test in alt}
        return result, {param: info for param, info in table.items() if param in used}

    def _german_all_texts(self, root: ET.Element) -> dict[str, dict[str, str]]:
        """Deutsche Texte aller Elemente ({Id: {Attribut: Text}}), für
        Parameter, Aufzählungswerte und Parameterseiten."""
        by_language: dict[str, dict] = {}
        for language in root.iter():
            if self._local(language.tag) != "Language":
                continue
            identifier = language.get("Identifier", "")
            if not identifier.lower().startswith("de"):
                continue
            texts = by_language.setdefault(identifier.lower(), {})
            for element in language.iter():
                if self._local(element.tag) == "TranslationElement":
                    for translation in element:
                        if translation.get("Text"):
                            texts.setdefault(element.get("RefId", ""), {})[
                                translation.get("AttributeName", "")] = translation.get("Text")
        for identifier in self._GERMAN:
            if identifier.lower() in by_language:
                return by_language[identifier.lower()]
        return next(iter(by_language.values()), {})

    # Bevorzugte Sprachen der Übersetzungen (Schweiz zuerst)
    _GERMAN = ("de-CH", "de-DE", "de-AT", "de")

    def _german_texts(self, root: ET.Element) -> dict[str, dict[str, str]]:
        """Übersetzte Texte der ComObjects/Refs: {Id: {"Text": …,
        "FunctionText": …}} aus <Languages><Language Identifier="de-DE">.
        Leer, wenn die Applikation nur eine Sprache hat."""
        by_language: dict[str, dict[str, dict[str, str]]] = {}
        for language in root.iter():
            if not language.tag.endswith("Language"):
                continue
            identifier = language.get("Identifier", "")
            if not identifier.lower().startswith("de"):
                continue
            texts = by_language.setdefault(identifier, {})
            for element in language.iter():
                if not element.tag.endswith("TranslationElement"):
                    continue
                ref_id = element.get("RefId", "")
                if "_O-" not in ref_id:
                    continue        # nur Kommunikationsobjekte
                for translation in element:
                    attr = translation.get("AttributeName", "")
                    if attr in ("Text", "FunctionText") and translation.get("Text"):
                        texts.setdefault(ref_id, {})[attr] = translation.get("Text")
        for identifier in self._GERMAN:
            for found, texts in by_language.items():
                if found.lower() == identifier.lower():
                    return texts
        return next(iter(by_language.values()), {})

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
