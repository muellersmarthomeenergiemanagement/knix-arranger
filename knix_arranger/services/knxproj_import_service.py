"""
ETS6 KNXPROJ Import (FA-521 bis FA-526)
Liest natives ETS6-Projektformat (.knxproj = ZIP mit XML).
"""
from __future__ import annotations
import logging
import os
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

from ..models.project import KnxProject
from ..models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)
from ..models.topology import Topology, Area, Line, Device, CommunicationObject
from ..models.building import Areal, Building, Wing, Floor, Apartment, Room, Verteiler, Bedienelement

logger = logging.getLogger("knix_arranger.knxproj_import")

# XML-Namespace der KNXPROJ-Dateien
_NS = "http://knx.org/xml/project/23"
_NSM = {"k": _NS}


def _tag(local: str) -> str:
    return f"{{{_NS}}}{local}"


class KnxprojImportError(Exception):
    """Wird bei ungueltigen oder nicht unterstuetzten KNXPROJ-Dateien ausgeloest."""


class KnxprojPasswordRequired(Exception):
    """Das KNXPROJ-Projekt ist verschluesselt und benoetigt ein Passwort."""
    def __init__(self, project_id: str):
        self.project_id = project_id
        super().__init__(f"Passwort benoetigt fuer Projekt: {project_id}")


class KnxprojPasswordWrong(Exception):
    """Das angegebene Passwort ist falsch."""


class KnxprojImportService:
    """
    Importiert ETS6-Projektdateien (.knxproj) gemaess FA-521 bis FA-526.

    Unterstuetzt:
    - ETS5/ETS6 (Formatversionen 20/21/23)
    - Gruppenadressen (3-Ebenen)
    - Gebaeudestruktur (Locations)
    - Topologie (Bereiche, Linien, Geraete, KOs)
    """

    def import_knxproj(self, filepath: str, password: str | None = None) -> KnxProject:
        """
        Hauptmethode: Liest eine .knxproj-Datei und gibt ein KnxProject zurueck.

        FA-521: ZIP-Archiv mit XML-Struktur.
        FA-524: Passwortschutz erkennen.
        FA-525: Fehler bei beschaedigter Datei.

        password: Optionales ETS6-Projektpasswort fuer verschluesselte Projekte
                  (neueres ETS6-Format mit P-XXXX.zip).
        Raises:
            KnxprojPasswordRequired  – Passwort noetig, aber nicht uebergeben.
            KnxprojPasswordWrong     – Uebergebenes Passwort ist falsch.
            KnxprojImportError       – Sonstiger Import-Fehler.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"KNXPROJ-Datei nicht gefunden: {filepath}")

        try:
            zf = zipfile.ZipFile(filepath, "r")
        except zipfile.BadZipFile as exc:
            raise KnxprojImportError(
                f"Datei ist kein gueltiges ZIP-Archiv: {filepath}"
            ) from exc

        with zf:
            # Klassisches Format: verschluesselte Eintraege direkt im aeusseren ZIP
            self._check_password_protection(zf)

            # Neueres ETS6-Format: P-XXXX.zip (verschachteltes ZIP, ggf. AES)
            nested_name = self._find_nested_zip_name(zf)
            if nested_name:
                project = self._import_nested(zf, nested_name, password)
            else:
                project = self._import_classic(zf)

        n_ga = len(project.group_addresses.all_addresses())
        n_dev = sum(
            len(line.devices)
            for area in project.topology.areas
            for line in area.lines
        )
        logger.info(
            f"KNXPROJ-Import: '{project.name}' — "
            f"{n_ga} Gruppenadressen, {n_dev} Geraete importiert."
        )
        return project

    def _import_classic(self, zf: zipfile.ZipFile) -> KnxProject:
        """Importiert das klassische KNXPROJ-Format (P-XXXX/-Ordner im ZIP)."""
        project_folder = self._find_project_folder(zf)
        project = self._parse_project_info(zf, project_folder)
        hw_lookup = self._build_hardware_lookup(zf)

        main_xml = self._read_xml(zf, f"{project_folder}/0.xml")
        installation = main_xml.find("k:Project/k:Installations/k:Installation", _NSM)
        if installation is None:
            raise KnxprojImportError("Keine Installation in 0.xml gefunden.")

        project.group_addresses = self._parse_group_addresses(installation)
        project.areal, room_device_refs = self._parse_building(installation)
        ga_xml_lookup = self._build_ga_xml_id_lookup(installation)
        app_co_lookup = self._build_app_co_lookup(zf)
        project.topology, device_id_to_line = self._parse_topology(
            installation, hw_lookup, ga_xml_lookup, app_co_lookup
        )
        project.topology.is_imported = True
        self._link_rooms_to_lines(room_device_refs, device_id_to_line)
        self._create_bedienelemente_from_topology(project.topology, project.areal)
        return project

    def _find_nested_zip_name(self, zf: zipfile.ZipFile) -> str | None:
        """Gibt den Namen der P-XXXX.zip im aeusseren ZIP zurueck, oder None."""
        for name in zf.namelist():
            if name.startswith("P-") and name.endswith(".zip") and "/" not in name:
                return name
        return None

    def _import_nested(
        self, outer_zf: zipfile.ZipFile, nested_name: str, password: str | None
    ) -> KnxProject:
        """
        Neueres ETS6-Format: Projektdaten in P-XXXX.zip innerhalb des aeusseren ZIP.
        Wenn der innere ZIP AES-verschluesselt ist, wird der Schluessel vom
        ETS6-Cloud-Lizenz-Zertifikat abgeleitet – das kann KNiX Arranger nicht
        ohne Zugriff auf die ETS6-internen Schluessel entschluesseln.
        """
        import io

        project_id = nested_name[:-4]  # 'P-XXXX.zip' → 'P-XXXX'
        inner_data = outer_zf.read(nested_name)

        # Pruefen ob das innere ZIP verschluesselt ist (flag_bits & 0x1 = WinZip AES)
        import zipfile as _zf
        try:
            with _zf.ZipFile(io.BytesIO(inner_data)) as probe:
                is_encrypted = any(
                    info.flag_bits & 0x1
                    for info in probe.infolist()
                    if not info.filename.endswith("/")
                )
        except _zf.BadZipFile:
            is_encrypted = False

        pwd_bytes: bytes | None = None
        if is_encrypted:
            # ETS6-Cloud-Lizenz-Zertifikat pruefen
            cert_name = f"{project_id}.certificate"
            has_cloud_cert = cert_name in outer_zf.namelist() and (
                b"CloudLicense" in outer_zf.read(cert_name)
            )
            if has_cloud_cert:
                raise KnxprojImportError(
                    "Dieses Projekt ist mit der ETS6-Cloud-Lizenz verschluesselt.\n\n"
                    "Der Verschluesselungsschluessel ist an Ihre ETS6-Installation "
                    "gebunden und kann von KNiX Arranger nicht entschluesselt werden.\n\n"
                    "Bitte exportieren Sie in ETS6:\n"
                    "  - Gruppenadress-Report als XLSX\n"
                    "  - Topologie-Report als XLSX\n"
                    "und importieren Sie diese Dateien."
                )
            if not password:
                raise KnxprojPasswordRequired(project_id)
            try:
                import pyzipper
            except ImportError as exc:
                raise KnxprojImportError(
                    "Fuer passwortgeschuetzte ETS6-Projekte wird das Paket "
                    "'pyzipper' benoetigt (siehe requirements.txt)."
                ) from exc
            inner_cls = pyzipper.AESZipFile
            pwd_bytes = password.encode("utf-8")
        else:
            # Nicht verschluesselt: normaler Import aus dem inneren ZIP
            try:
                import pyzipper
                inner_cls = pyzipper.AESZipFile
            except ImportError:
                inner_cls = _zf.ZipFile

        try:
            with inner_cls(io.BytesIO(inner_data)) as inner:
                if pwd_bytes is not None:
                    inner.setpassword(pwd_bytes)
                project = self._parse_project_info_from_zip(inner)
                hw_lookup = self._build_hardware_lookup(outer_zf)

                try:
                    raw_main = inner.read("0.xml")
                except (KeyError, RuntimeError) as exc:
                    if pwd_bytes is not None:
                        raise KnxprojPasswordWrong() from exc
                    raise KnxprojImportError(f"0.xml konnte nicht gelesen werden: {exc}") from exc

                try:
                    root = ET.fromstring(raw_main.decode("utf-8-sig"))
                except ET.ParseError as exc:
                    raise KnxprojImportError(f"XML-Fehler in 0.xml: {exc}") from exc

                installation = self._find_installation(root)
                project.group_addresses = self._parse_group_addresses(installation)
                project.areal, room_device_refs = self._parse_building(installation)
                ga_xml_lookup = self._build_ga_xml_id_lookup(installation)
                app_co_lookup = self._build_app_co_lookup(outer_zf)
                project.topology, device_id_to_line = self._parse_topology(
                    installation, hw_lookup, ga_xml_lookup, app_co_lookup
                )
                project.topology.is_imported = True
                self._link_rooms_to_lines(room_device_refs, device_id_to_line)
                self._create_bedienelemente_from_topology(project.topology, project.areal)
        except RuntimeError as exc:
            if pwd_bytes is not None:
                raise KnxprojPasswordWrong() from exc
            raise

        return project

    # ------------------------------------------------------------------
    # Hilfsmethoden: ZIP / XML
    # ------------------------------------------------------------------

    def _check_password_protection(self, zf: zipfile.ZipFile):
        """FA-524: Prueft ob das Projekt passwortgeschuetzt ist."""
        names = zf.namelist()
        # Passwortgeschuetzte Projekte enthalten verschluesselte Eintraege
        for info in zf.infolist():
            if info.flag_bits & 0x1:  # Bit 0 = encrypted
                raise KnxprojImportError(
                    "Das Projekt ist passwortgeschuetzt und kann nicht importiert werden. "
                    "Bitte exportieren Sie aus ETS6 die Gruppenadressen als XLSX-Report "
                    "und die Topologie als XLSX-Report und importieren Sie diese Dateien einzeln."
                )

    def _parse_project_info_from_zip(self, inner_zf) -> KnxProject:
        """Liest Projektmetadaten aus project.xml im inneren ZIP (kein Unterordner)."""
        try:
            raw = inner_zf.read("project.xml")
            root = ET.fromstring(raw.decode("utf-8-sig"))
        except Exception:
            return KnxProject()
        info = root.find("k:Project/k:ProjectInformation", _NSM)
        if info is None:
            info = root.find(".//ProjectInformation")
        project = KnxProject()
        if info is not None:
            project.name = info.get("Name", "")
            modified = info.get("LastModified", "")
            if modified:
                project.modified = modified[:10]
        return project

    def _find_installation(self, root: ET.Element) -> ET.Element:
        """Sucht Installation-Element, probiert bekannte Namespaces."""
        el = root.find("k:Project/k:Installations/k:Installation", _NSM)
        if el is not None:
            return el
        # Fallback: namespace-freie Suche (neuere ETS-Versionen)
        el = root.find(".//Installation")
        if el is not None:
            return el
        raise KnxprojImportError("Keine Installation in 0.xml gefunden.")

    def _find_project_folder(self, zf: zipfile.ZipFile) -> str:
        """Findet den Projektordner (P-XXXX/) im ZIP-Archiv."""
        for name in zf.namelist():
            parts = name.split("/")
            if parts[0].startswith("P-") and len(parts) > 1:
                return parts[0]
        raise KnxprojImportError(
            "Kein Projektordner (P-XXXX) im KNXPROJ-Archiv gefunden."
        )

    def _read_xml(self, zf: zipfile.ZipFile, path: str) -> ET.Element:
        """Liest und parst eine XML-Datei aus dem ZIP-Archiv."""
        try:
            raw = zf.read(path)
        except KeyError as exc:
            raise KnxprojImportError(f"Datei nicht im Archiv: {path}") from exc
        try:
            return ET.fromstring(raw.decode("utf-8-sig"))
        except ET.ParseError as exc:
            raise KnxprojImportError(f"XML-Fehler in {path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Schritt 1: Projektmetadaten
    # ------------------------------------------------------------------

    def _parse_project_info(
        self, zf: zipfile.ZipFile, project_folder: str
    ) -> KnxProject:
        """Liest Projektmetadaten aus project.xml."""
        try:
            root = self._read_xml(zf, f"{project_folder}/project.xml")
        except KnxprojImportError:
            # Fallback: leeres Projekt
            return KnxProject()

        info = root.find("k:Project/k:ProjectInformation", _NSM)
        project = KnxProject()
        if info is not None:
            project.name = info.get("Name", "")
            modified = info.get("LastModified", "")
            if modified:
                project.modified = modified[:10]  # nur Datum
        return project

    # ------------------------------------------------------------------
    # Schritt 2a: Hardware-Lookup
    # ------------------------------------------------------------------

    def _build_hardware_lookup(self, zf: zipfile.ZipFile) -> dict:
        """
        Baut einen Lookup ProductRefId -> (product_name, order_number, manufacturer_id).
        Liest dazu alle M-XXXX/Hardware.xml Dateien im Archiv.
        """
        lookup: dict[str, tuple[str, str, str]] = {}
        mfr_folders = {
            name.split("/")[0]
            for name in zf.namelist()
            if name.startswith("M-") and "/" in name
        }
        for folder in mfr_folders:
            hw_path = f"{folder}/Hardware.xml"
            if hw_path not in zf.namelist():
                continue
            try:
                root = self._read_xml(zf, hw_path)
            except KnxprojImportError:
                continue
            for hw in root.findall(".//k:Hardware", _NSM):
                for product in hw.findall("k:Products/k:Product", _NSM):
                    pid = product.get("Id", "")
                    name = product.get("Text", "") or hw.get("Name", "")
                    order = product.get("OrderNumber", "")
                    if pid:
                        lookup[pid] = (name, order, folder)
        return lookup

    # ------------------------------------------------------------------
    # Schritt 2a-2: App-Programm CO-Lookup
    # ------------------------------------------------------------------

    def _build_app_co_lookup(self, zf: zipfile.ZipFile) -> dict:
        """
        Scannt alle M-XXXX/M-XXXX_A-*.xml Applikationsprogramm-Dateien im ZIP
        und baut ein Lookup {ComObjectRef.Id → CO-Metadaten-Dict}.

        Struktur eines Eintrags:
          {
            "name": "Ausgang A",          # ComObject.Name
            "number": 0,                  # ComObject.Number
            "function_text": "Switch",    # ComObject.FunctionText (ggf. durch Ref überschrieben)
            "object_size": "1 Bit",       # ComObject.ObjectSize → data_type
            "flags": "KSUE-A",            # Kompakter Flags-String
            "priority": "Niedrig",        # ComObject.Priority (DE)
            "write_flag": True,           # WriteFlag (für device_type-Heuristik)
            "transmit_flag": True,        # TransmitFlag (für device_type-Heuristik)
          }
        """
        import re as _re
        lookup: dict[str, dict] = {}
        pattern = _re.compile(r"^M-\w+/M-\w+_A-[\w.-]+\.xml$")
        for name in zf.namelist():
            if not pattern.match(name):
                continue
            try:
                root = self._read_xml(zf, name)
            except KnxprojImportError:
                continue
            self._extract_app_co_refs(root, lookup)
        logger.debug(f"App-CO-Lookup: {len(lookup)} ComObjectRef-Einträge aus {sum(1 for n in zf.namelist() if pattern.match(n))} App-Programmen")
        return lookup

    def _extract_app_co_refs(self, root: ET.Element, lookup: dict) -> None:
        """Extrahiert ComObject+ComObjectRef-Paare aus einem App-Programm-XML."""
        _PRIO_MAP = {"Low": "Niedrig", "High": "Hoch", "Alert": "Alarm"}

        # ComObjects nach vollständiger Id indizieren
        co_by_id: dict[str, dict] = {}
        for co in root.iter(_tag("ComObject")):
            co_id = co.get("Id", "")
            if not co_id:
                continue
            co_by_id[co_id] = {
                "name": co.get("Name", ""),
                "number": int(co.get("Number", "0") or "0"),
                "function_text": co.get("FunctionText", ""),
                "object_size": co.get("ObjectSize", ""),
                "flags": self._co_flags(co),
                "priority": _PRIO_MAP.get(co.get("Priority", ""), "Niedrig"),
                "write_flag": co.get("WriteFlag", "") == "Enabled",
                "transmit_flag": co.get("TransmitFlag", "") == "Enabled",
            }

        # ComObjectRefs: Basis aus ComObject übernehmen, Ref-Overrides anwenden
        for cor in root.iter(_tag("ComObjectRef")):
            cor_id = cor.get("Id", "")
            ref_id = cor.get("RefId", "")
            if not cor_id or ref_id not in co_by_id:
                continue
            meta = co_by_id[ref_id].copy()
            # Optionale Attribute aus ComObjectRef überschreiben die ComObject-Basis
            if cor.get("Name"):
                meta["name"] = cor.get("Name")
            if cor.get("FunctionText"):
                meta["function_text"] = cor.get("FunctionText")
            if cor.get("ObjectSize"):
                meta["object_size"] = cor.get("ObjectSize")
            if cor.get("WriteFlag"):
                meta["write_flag"] = cor.get("WriteFlag") == "Enabled"
                meta["flags"] = self._co_flags(cor) or meta["flags"]
            lookup[cor_id] = meta

    @staticmethod
    def _co_flags(elem: ET.Element) -> str:
        """Erzeugt einen kompakten Flags-String aus ETS-Boolean-Attributen.

        Format: 6 Zeichen, jeder Buchstabe steht für ein Flag (Enabled),
        '-' steht für Disabled. Reihenfolge: K S U E A I
          K = CommunicationFlag (Kommunikation)
          S = WriteFlag        (Schreiben)
          U = TransmitFlag     (Übertragen)
          E = ReadFlag         (Einlesen)
          A = UpdateFlag       (Aktualisieren)
          I = ReadOnInitFlag   (Initialisierungslesen)
        """
        flag_map = [
            ("CommunicationFlag", "K"),
            ("WriteFlag",         "S"),
            ("TransmitFlag",      "U"),
            ("ReadFlag",          "E"),
            ("UpdateFlag",        "A"),
            ("ReadOnInitFlag",    "I"),
        ]
        return "".join(
            char if elem.get(attr) == "Enabled" else "-"
            for attr, char in flag_map
        )

    @staticmethod
    def _infer_device_type(product_name: str, co_metas: list[dict]) -> str:
        """Heuristik zur Gerätekategorie aus Produktname und CO-Flags.

        Reihenfolge:
        1. Sensor-Keywords zuerst (spezifischer, z.B. "Taster" schlägt "rgb")
        2. Aktor-Keywords als zweite Prüfung
        3. CO-Flag-Muster als Fallback
        """
        name_lower = product_name.lower()
        # Infrastrukturgeräte zuerst prüfen (schlagen sensor/actor)
        infra_kw = (
            "remote access", "ip router", "ip interface", "usb interface",
            "knx router", "knx interface", "knx gateway", "knxnet",
            "line coupler", "area coupler", "backbone coupler",
            "power supply", "speisegerät", "netzteil",
        )
        sensor_kw = (
            "sensor", "button", "taster", "push", "presence", "präsenz",
            "temperature", "temperatur", "weather", "wetter", "detector",
            "bewegungsmelder", "raumthermostat", "thermostat",
        )
        actor_kw = (
            "actuator", "aktor", "switch act", "schaltakt", "dimm",
            "jalousie", "shutter", "blind", "hvac", "heating ctrl",
            "dali", "rgb led", "led driver",
        )
        if any(kw in name_lower for kw in infra_kw):
            return "other"
        if any(kw in name_lower for kw in sensor_kw):
            return "sensor"
        if any(kw in name_lower for kw in actor_kw):
            return "actor"

        # CO-Flag-Heuristik: Mehrheit der COs mit WriteFlag → Aktor
        if co_metas:
            n_write = sum(1 for m in co_metas if m.get("write_flag"))
            if n_write / len(co_metas) >= 0.5:
                return "actor"
            n_transmit_only = sum(
                1 for m in co_metas
                if m.get("transmit_flag") and not m.get("write_flag")
            )
            if n_transmit_only / len(co_metas) >= 0.5:
                return "sensor"
        return "other"

    @staticmethod
    def _app_program_id(hw2prog_ref: str) -> str:
        """Leitet die ApplicationProgram.Id aus Hardware2ProgramRefId ab.

        Beispiel:
          "M-0002_H-GH.20Q631.200047.20R0111-1_HP-4701-11-952C"
          → "M-0002_A-4701-11-952C"
        """
        if not hw2prog_ref:
            return ""
        parts = hw2prog_ref.split("_")
        mfr = parts[0]          # z.B. "M-0002"
        last = parts[-1]        # z.B. "HP-4701-11-952C"
        if last.startswith("HP-"):
            return f"{mfr}_A-{last[3:]}"
        return ""

    # ------------------------------------------------------------------
    # Schritt 2b: Gruppenadress-Parser
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_address(raw: int) -> tuple[int, int, int]:
        """Dekodiert eine 16-Bit-KNX-Gruppenadresse in (main, middle, sub)."""
        return (raw >> 11) & 0x1F, (raw >> 8) & 0x07, raw & 0xFF

    def _build_ga_xml_id_lookup(
        self, installation: ET.Element
    ) -> dict[str, str]:
        """Baut ein Lookup ETS-GA-Referenz → KNX-Adressstring (main/middle/sub).

        ETS6 referenziert GAs in ComObjectInstanceRef.Links mit dem Suffix
        des GA-Id-Attributs, z.B. 'GA-1381' aus 'P-06C2-0_GA-1381'.
        Das Lookup speichert sowohl den Suffix als auch die vollständige Id
        als Schlüssel, um beide ETS-Varianten abzudecken.
        """
        lookup: dict[str, str] = {}
        ga_root = installation.find("k:GroupAddresses/k:GroupRanges", _NSM)
        if ga_root is None:
            return lookup
        for ga_elem in ga_root.iter(_tag("GroupAddress")):
            full_id = ga_elem.get("Id", "")
            raw_addr = ga_elem.get("Address", "")
            if not full_id or not raw_addr:
                continue
            try:
                m, mi, s = self._decode_address(int(raw_addr))
                knx_addr = f"{m}/{mi}/{s}"
                # Vollständige Id als Schlüssel (ETS5-Stil)
                lookup[full_id] = knx_addr
                # Suffix nach '_' als Schlüssel (ETS6-Stil: "GA-1381")
                suffix = full_id.rsplit("_", 1)[-1]
                if suffix != full_id:
                    lookup[suffix] = knx_addr
            except (ValueError, TypeError):
                pass
        return lookup

    def _parse_group_addresses(
        self, installation: ET.Element
    ) -> GroupAddressStructure:
        """
        FA-522: Extrahiert die Gruppenadress-Hierarchie.
        Struktur: GroupRanges > GroupRange (HG) > GroupRange (MG) > GroupAddress
        """
        structure = GroupAddressStructure()
        ga_root = installation.find("k:GroupAddresses/k:GroupRanges", _NSM)
        if ga_root is None:
            return structure

        for hg_elem in ga_root.findall("k:GroupRange", _NSM):
            hg_start = int(hg_elem.get("RangeStart", "0"))
            main_num = (hg_start >> 11) & 0x1F
            hg = MainGroup(number=main_num, name=hg_elem.get("Name", ""))
            structure.main_groups.append(hg)

            for mg_elem in hg_elem.findall("k:GroupRange", _NSM):
                mg_start = int(mg_elem.get("RangeStart", "0"))
                mid_num = (mg_start >> 8) & 0x07
                mg = MiddleGroup(number=mid_num, name=mg_elem.get("Name", ""))
                hg.middle_groups.append(mg)

                for ga_elem in mg_elem.findall("k:GroupAddress", _NSM):
                    raw = int(ga_elem.get("Address", "0"))
                    m, mi, s = self._decode_address(raw)
                    ga = GroupAddress(
                        main_group=m,
                        middle_group=mi,
                        sub_group=s,
                        designation=ga_elem.get("Name", ""),
                        description=ga_elem.get("Description", "")
                                    or ga_elem.get("Comment", ""),
                        datapoint_type=ga_elem.get("DatapointType", ""),
                        security="Auto",
                    )
                    mg.group_addresses.append(ga)

        logger.debug(
            f"GA-Import: {len(structure.all_addresses())} Adressen in "
            f"{len(structure.main_groups)} Hauptgruppen"
        )
        return structure

    # ------------------------------------------------------------------
    # Schritt 3: Gebäudestruktur-Parser (FA-523)
    # ------------------------------------------------------------------

    def _parse_building(
        self, installation: ET.Element
    ) -> tuple[Areal, dict[str, list[str]]]:
        """
        FA-523: Extrahiert die Gebaeudestruktur aus Locations/Space.
        Space-Typen: Building, BuildingPart (=Stockwerk), Room, DistributionBoard.
        Gibt zusaetzlich room_device_refs zurueck: {room.id: [xml_device_id, ...]}.
        """
        areal = Areal()
        room_device_refs: dict[str, list[str]] = {}
        loc_root = installation.find("k:Locations", _NSM)
        if loc_root is None:
            return areal, room_device_refs

        for space in loc_root.findall("k:Space", _NSM):
            space_type = space.get("Type", "")
            if space_type == "Building":
                building = Building(name=space.get("Name", "Gebaeude"))
                wing = Wing(name="")
                building.wings.append(wing)
                areal.buildings.append(building)
                self._parse_building_children(space, wing, room_device_refs)

        if not areal.buildings:
            # Fallback: alle BuildingParts direkt in ein Gebaeude
            building = Building(name="Gebaeude")
            wing = Wing(name="")
            building.wings.append(wing)
            areal.buildings.append(building)
            for space in loc_root.findall("k:Space", _NSM):
                self._parse_floor_or_room(space, wing, room_device_refs)

        n_rooms = len(areal.all_rooms)
        logger.debug(f"Gebaeude-Import: {len(areal.buildings)} Geb., {n_rooms} Raeume")
        return areal, room_device_refs

    def _parse_building_children(
        self, parent: ET.Element, wing: Wing, room_device_refs: dict
    ):
        """Iteriert ueber direkte Kind-Space-Elemente eines Building."""
        for space in parent.findall("k:Space", _NSM):
            self._parse_floor_or_room(space, wing, room_device_refs)

    def _parse_floor_or_room(
        self, space: ET.Element, wing: Wing, room_device_refs: dict
    ):
        """Verarbeitet ein Space-Element als Stockwerk oder Raum."""
        space_type = space.get("Type", "")
        name = space.get("Name", "").strip()

        if space_type in ("BuildingPart", "Floor", "Stairway", "Corridor"):
            floor = Floor(name=name, short_code=self._extract_short_code(name))
            apt = Apartment(name="")
            floor.apartments.append(apt)
            wing.floors.append(floor)
            # Unterraeume durchsuchen
            for child in space.findall("k:Space", _NSM):
                child_type = child.get("Type", "")
                child_name = child.get("Name", "").strip()
                if child_type == "Room":
                    raw_name = child_name
                    number = child.get("Number", "")
                    room_name = raw_name
                    if not number:
                        number, room_name = self._split_room_number(raw_name)
                    room = Room(number=number, name=room_name)
                    # Verschachteltes DistributionBoard → Verteiler im Raum anlegen
                    nested_db = child.find("k:Space[@Type='DistributionBoard']", _NSM)
                    if nested_db is not None:
                        db_name = nested_db.get("Name", "").strip()
                        vt = Verteiler(
                            name=db_name,
                            verteiler_type=self._detect_hv_uv_type(db_name),
                        )
                        room.verteiler.append(vt)
                        # Geraete aus dem DistributionBoard dem Raum zuordnen
                        refs = self._collect_device_refs(nested_db)
                        if refs:
                            room_device_refs.setdefault(room.id, []).extend(refs)
                    # Geraete direkt im Raum
                    refs = self._collect_device_refs(child)
                    if refs:
                        room_device_refs.setdefault(room.id, []).extend(refs)
                    apt.rooms.append(room)
                elif child_type == "DistributionBoard":
                    # Direkte Verteilung im Stockwerk als eigener Raum mit Verteiler
                    vt_type = self._detect_hv_uv_type(child_name)
                    vt = Verteiler(name=child_name, verteiler_type=vt_type)
                    room = Room(number="", name=child_name)
                    room.verteiler.append(vt)
                    refs = self._collect_device_refs(child)
                    if refs:
                        room_device_refs[room.id] = refs
                    apt.rooms.append(room)

        elif space_type == "Room":
            # Raum direkt unter Building (kein Stockwerk)
            if not wing.floors:
                floor = Floor(name="EG", short_code="EG")
                floor.apartments.append(Apartment(name=""))
                wing.floors.append(floor)
            room = Room(
                number=space.get("Number", ""),
                name=name,
            )
            refs = self._collect_device_refs(space)
            if refs:
                room_device_refs[room.id] = refs
            wing.floors[-1].apartments[0].rooms.append(room)

    # ------------------------------------------------------------------
    # Schritt 4: Topologie-Parser
    # ------------------------------------------------------------------

    def _parse_topology(
        self, installation: ET.Element, hw_lookup: dict,
        ga_xml_lookup: dict | None = None,
        app_co_lookup: dict | None = None,
    ) -> tuple[Topology, dict[str, tuple]]:
        """
        FA-522: Extrahiert Bereiche, Linien und Geraete aus Topology/Area/Line.
        Physikalische Adresse: B.L.T (Bereich.Linie.Teilnehmer).
        Gibt device_id_to_info zurueck: {xml_id: (Line, Device)}.
        ga_xml_lookup:  {ETS-GA-XML-ID -> "main/middle/sub"} für connected_gas.
        app_co_lookup:  {ComObjectRef.Id -> CO-Metadaten} für CO-Anreicherung.
        """
        topology = Topology()
        device_id_to_info: dict[str, tuple] = {}
        topo_root = installation.find("k:Topology", _NSM)
        if topo_root is None:
            return topology, device_id_to_info

        for area_elem in topo_root.findall("k:Area", _NSM):
            area_num = int(area_elem.get("Address", "0"))
            area = Area(
                area_number=area_num,
                name=area_elem.get("Name", f"Bereich {area_num}"),
            )
            topology.areas.append(area)

            for line_elem in area_elem.findall("k:Line", _NSM):
                line_num = int(line_elem.get("Address", "0"))
                line = Line(
                    line_number=line_num,
                    name=line_elem.get("Name", f"Linie {line_num}"),
                    coupler_address=f"{area_num}.{line_num}.0",
                )
                area.lines.append(line)
                self._parse_devices(
                    line_elem, line, area_num, line_num, hw_lookup,
                    device_id_to_info, ga_xml_lookup, app_co_lookup,
                )
                # Segmente (ETS6 Segment-Koppler)
                for seg_elem in line_elem.findall("k:Segment", _NSM):
                    self._parse_devices(
                        seg_elem, line, area_num, line_num, hw_lookup,
                        device_id_to_info, ga_xml_lookup, app_co_lookup,
                    )
                line.update_device_count()

        logger.debug(
            f"Topologie-Import: {len(topology.areas)} Bereiche, "
            f"{sum(len(a.lines) for a in topology.areas)} Linien"
        )
        return topology, device_id_to_info

    def _collect_device_refs(self, space: ET.Element) -> list[str]:
        """Sammelt DeviceInstanceRef/@RefId-Werte eines Space-Elements."""
        return [
            ref
            for dr in space.findall("k:DeviceInstanceRef", _NSM)
            if (ref := dr.get("RefId", ""))
        ]

    # ------------------------------------------------------------------
    # FA-1404: Bedienelemente aus importierter Topologie erzeugen
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_element_type(product_name: str) -> str:
        """Leitet den Bedienelement-Typ aus dem Produktnamen ab."""
        nl = product_name.lower()
        if any(kw in nl for kw in ("präsenz", "praesenz", "presence")):
            return "Präsenzmelder"
        if any(kw in nl for kw in ("bewegungsmelder", "motion detector", "motion sensor")):
            return "Bewegungsmelder"
        if any(kw in nl for kw in ("thermostat", "raumthermostat", "room controller", "room thermostat",
                                   "rtr", "raumtemperatur", "temperature controller", "clima sensor")):
            return "Raumthermostat"
        if any(kw in nl for kw in ("temperaturfühler", "temperature sensor", "temp sensor", "temperatursensor")):
            return "Temperaturfuehler"
        if any(kw in nl for kw in ("fensterkontakt", "window contact", "window sensor")):
            return "Fensterkontakt"
        if any(kw in nl for kw in ("türkontakt", "door contact", "door sensor")):
            return "Türkontakt"
        if any(kw in nl for kw in ("wetter", "weather")):
            return "Wetterstation"
        # Tastereinheit / Button als breiteste Sensor-Kategorie
        if any(kw in nl for kw in ("taster", "button", "push", "tastatur", "keypad")):
            return "Tastereinheit"
        return "Tastereinheit"  # Fallback für unbekannte Sensoren

    @staticmethod
    def _infer_channel_count(product_name: str) -> int:
        """Versucht die Kanalanzahl aus dem Produktnamen zu lesen.

        Erkennt Muster wie '4-fach', '4-fold', '4gang', '1-8fach' (→ 8),
        '2-6 fold' (→ 6). Gibt 1 zurück wenn kein Muster gefunden.
        """
        import re
        # "1-8fach" oder "2-6 fold" → nimm die höhere Zahl
        m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*(?:fach|fold|gang|kanal|channel)', product_name.lower())
        if m:
            return min(int(m.group(2)), 16)
        # "4-fach", "4-fold", "4gang"
        m = re.search(r'(\d+)\s*[-–]?\s*(?:fach|fold|gang|kanal|channel)', product_name.lower())
        if m:
            return min(int(m.group(1)), 16)
        return 1

    @staticmethod
    def _create_bedienelemente_from_topology(topology, areal) -> None:
        """FA-1404: Erzeugt Bedienelement-Einträge in Räumen für importierte Sensor-Devices.

        Iteriert über alle Devices mit device_type='sensor' und einem gesetzten
        room_id und legt je ein Bedienelement im zugehörigen Raum an – sofern
        dort noch kein Bedienelement mit derselben physikalischen Adresse existiert.
        Wird sowohl nach KNXproj- als auch nach XLSX-Import aufgerufen.
        """
        room_by_id: dict[str, Room] = {r.id: r for r in areal.all_rooms}
        count = 0
        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.device_type != "sensor" or not device.room_id:
                        continue
                    room = room_by_id.get(device.room_id)
                    if room is None:
                        continue
                    # Keine Duplikate anlegen (z.B. bei erneutem Aufruf)
                    if any(be.participant_number == device.physical_address
                           for be in room.bedienelemente):
                        continue
                    product_label = device.product or device.product_name
                    be = Bedienelement(
                        element_type=KnxprojImportService._infer_element_type(product_label),
                        channels=KnxprojImportService._infer_channel_count(product_label),
                        participant_number=device.physical_address,
                        manufacturer=device.manufacturer,
                        order_number=device.order_number,
                        product_name=product_label,
                    )
                    room.bedienelemente.append(be)
                    count += 1
        logger.debug(f"FA-1404: {count} Bedienelemente aus Topologie-Import erzeugt.")

    def _link_rooms_to_lines(
        self,
        room_device_refs: dict[str, list[str]],
        device_id_to_info: dict[str, tuple],
    ):
        """Setzt assigned_room_ids auf Linien und room_id auf Geraeten."""
        for room_id, ref_ids in room_device_refs.items():
            seen_lines: set[int] = set()
            for ref_id in ref_ids:
                info = device_id_to_info.get(ref_id)
                if info is None:
                    continue
                line, device = info
                # device.room_id direkt setzen
                device.room_id = room_id
                # Linie einmalig mit Raum verknüpfen
                if id(line) not in seen_lines:
                    seen_lines.add(id(line))
                    if room_id not in line.assigned_room_ids:
                        line.assigned_room_ids.append(room_id)

    def _parse_devices(
        self,
        parent: ET.Element,
        line: Line,
        area_num: int,
        line_num: int,
        hw_lookup: dict,
        device_id_to_info: dict | None = None,
        ga_xml_lookup: dict | None = None,
        app_co_lookup: dict | None = None,
    ):
        """Liest DeviceInstance-Elemente und haengt sie an die Linie.

        ga_xml_lookup:  {ETS-GA-XML-ID -> "main/middle/sub"} → connected_gas-Auflösung.
        app_co_lookup:  {ComObjectRef.Id -> CO-Metadaten} → CO-Anreicherung (Name,
                        Funktion, Datentyp, Flags).
        """
        import re as _re
        for di in parent.findall("k:DeviceInstance", _NSM):
            xml_id = di.get("Id", "")
            addr = int(di.get("Address", "0"))
            phys_addr = f"{area_num}.{line_num}.{addr}"

            # Produktinfo aus Hardware-Lookup
            prod_ref = di.get("ProductRefId", "")
            product_name, order_num, mfr_id = hw_lookup.get(
                prod_ref, ("", "", "")
            )

            # App-Programm-ID für CO-Lookup ableiten
            hw2prog = di.get("Hardware2ProgramRefId", "")
            ap_id = self._app_program_id(hw2prog)

            # Geraetetyp: Koppler/Speisegerät zuerst prüfen (FA-516/FA-517),
            # Aktor/Sensor via Heuristik später (nach CO-Parsing).
            if addr == 0:
                dev_type = "coupler"
            elif addr < 0:
                dev_type = "power_supply"
            else:
                dev_type = None  # wird nach CO-Parsing gesetzt

            device = Device(
                physical_address=phys_addr,
                manufacturer=mfr_id,
                order_number=order_num,
                product=product_name,
                application_program=hw2prog,
                installation_location=di.get("InstallationHints", ""),
                device_type=dev_type or "other",
                # Alle aus ETS importierten Geräte gelten als programmiert:
                # Ihre physikalische Adresse wurde per ETS-Download ins Gerät
                # übertragen und darf nicht automatisch geändert werden.
                # Speisegeräte (power_supply) haben keine echte Busadresse →
                # kein is_programmed.
                is_programmed=(dev_type != "power_supply"),
            )

            # Kommunikationsobjekte (ComObjectInstanceRefs)
            co_metas: list[dict] = []
            for co_ref in di.findall(
                "k:ComObjectInstanceRefs/k:ComObjectInstanceRef", _NSM
            ):
                ref_id = co_ref.get("RefId", "")
                links_str = co_ref.get("Links", "")
                raw_gas = links_str.split() if links_str else []

                # Problem 1: ETS-XML-IDs zu KNX-Adressen auflösen
                connected_gas = (
                    [ga_xml_lookup.get(ref, ref) for ref in raw_gas]
                    if ga_xml_lookup else raw_gas
                )

                # Probleme 2-4: CO-Metadaten aus App-Programm-Lookup
                meta: dict | None = None
                if app_co_lookup and ap_id:
                    meta = app_co_lookup.get(f"{ap_id}_{ref_id}")
                co_metas.append(meta or {})

                # object_number: aus Lookup, sonst aus RefId-Muster "O-{n}_R-{x}"
                obj_num = meta["number"] if meta else 0
                if not meta:
                    m = _re.match(r"O-(\d+)", ref_id)
                    if m:
                        obj_num = int(m.group(1))

                co = CommunicationObject(
                    object_number=obj_num,
                    name=meta["name"] if meta else ref_id,
                    object_function=meta.get("function_text", "") if meta else "",
                    data_type=meta.get("object_size", "") if meta else "",
                    flags=meta.get("flags", "") if meta else "",
                    priority=meta.get("priority", "Niedrig") if meta else "Niedrig",
                    connected_gas=connected_gas,
                )
                device.communication_objects.append(co)

            # device_type-Heuristik für reguläre Teilnehmer
            if dev_type is None:
                device.device_type = self._infer_device_type(product_name, co_metas)

            line.devices.append(device)
            if device_id_to_info is not None and xml_id:
                device_id_to_info[xml_id] = (line, device)

    @staticmethod
    def _detect_hv_uv_type(name: str) -> str:
        """Erkennt ob ein Verteilungsraum eine HV oder UV ist."""
        upper = name.upper()
        if "HV" in upper or "HAUPTVERTEIL" in upper:
            return "HV"
        return "UV"

    @staticmethod
    def _split_room_number(raw_name: str) -> tuple[str, str]:
        """Trennt Raumnummer und Raumname aus ETS6-Raumbezeichnungen.

        ETS6 kodiert Raumnummer oft als Präfix im Namen, z.B. '02  Bibliothek'.
        Gibt (number, name) zurück, z.B. ('02', 'Bibliothek').
        """
        import re
        m = re.match(r'^(\d+)\s+(.*)', raw_name)
        if m:
            return m.group(1), m.group(2).strip()
        return "", raw_name

    @staticmethod
    def _extract_short_code(name: str) -> str:
        """Leitet einen Kurzcode aus dem Stockwerk-Namen ab (z.B. 'OG' aus '1. OG')."""
        upper = name.upper()
        for code in ("UG", "EG", "DG"):
            if code in upper:
                return code
        for code in ("3.OG", "2.OG", "1.OG", "OG"):
            if code in upper:
                return code
        return name[:4] if name else ""
