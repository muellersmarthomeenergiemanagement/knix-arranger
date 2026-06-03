"""
KNXPROJ-Export Service (FA-2400 bis FA-2406)

Exportiert ein KnxProject als natives ETS6-Projektformat (.knxproj).
Das Format ist ein ZIP-Archiv mit XML-Dateien gemaess KNX-Standard
(Namespace http://knx.org/xml/project/23).

Enthalten im Export:
- Projektmetadaten (project.xml)
- Gruppenadressen (vollstaendige Hierarchie mit DPT)
- KNX-Topologie (Bereiche, Linien, Geraete mit phys. Adressen)
- Gebaeude-/Raumstruktur (Locations)
- CO-GA-Verknuepfungen (aus Device.communication_objects)

Nicht enthalten (erfordert ETS-Programmierung):
- Applikationsprogramme der Geraete
- KNXPROD-spezifische Konfigurationsparameter
"""
from __future__ import annotations
import io
import logging
import os
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger("knix_arranger.knxproj_export")

# KNX-Standard XML-Namespace (ETS6, Version 23)
_NS = "http://knx.org/xml/project/23"
_NS_PREFIX = f"{{{_NS}}}"

# Namespace als Standard-Namespace registrieren, damit ET keine ns0:-Prefixe generiert
ET.register_namespace("", _NS)


def _el(tag: str, **attribs) -> ET.Element:
    """Erstellt ein Element mit dem KNX-Namespace."""
    return ET.Element(f"{_NS_PREFIX}{tag}", **{k: str(v) for k, v in attribs.items()})


def _sub(parent: ET.Element, tag: str, **attribs) -> ET.Element:
    """Fuegt ein Kindelement mit dem KNX-Namespace ein."""
    return ET.SubElement(parent, f"{_NS_PREFIX}{tag}",
                         **{k: str(v) for k, v in attribs.items()})


class _PuidCounter:
    """Vergibt sequenzielle Puid-Werte (ETS6-interne Eindeutigkeits-IDs)."""
    def __init__(self, start: int = 1):
        self._n = start

    def next(self) -> str:
        v = self._n
        self._n += 1
        return str(v)


def _encode_ga(main: int, middle: int, sub: int) -> int:
    """Kodiert eine Gruppenadresse als 16-Bit-Integer."""
    return (main << 11) | (middle << 8) | sub


@dataclass
class ExportSummary:
    """Zusammenfassung des KNXPROJ-Exports fuer die Benutzeranzeige (FA-2405)."""
    ga_count: int = 0
    device_count: int = 0
    co_link_count: int = 0
    missing_co_devices: int = 0     # Geraete ohne CO-Verknuepfung
    warnings: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = [
            f"Gruppenadressen exportiert:    {self.ga_count}",
            f"Geraete in Topologie:          {self.device_count}",
            f"Geplante CO-GA-Verknuepfungen: {self.co_link_count}"
            "  (Referenz; in ETS6 manuell einzutragen)",
        ]
        if self.missing_co_devices:
            lines.append(
                f"Aktoren ohne CO-Plan:          {self.missing_co_devices}  "
                "(CO-Verknuepfung in KNX Arranger ausfuehren)"
            )
        if self.warnings:
            lines.append("")
            lines.append("Hinweise:")
            lines.extend(f"  - {w}" for w in self.warnings)
        return "\n".join(lines)


class KnxprojExportService:
    """
    Exportiert ein KnxProject als .knxproj-Datei (FA-2401 bis FA-2406).

    Aufruf:
        summary = KnxprojExportService().export(project, "/pfad/projekt.knxproj")
        print(summary.as_text())
    """

    def export(
        self, project, filepath: str, base_project: str | None = None
    ) -> ExportSummary:
        """
        Hauptmethode: Erstellt die .knxproj-ZIP-Datei.

        FA-2406: Prueft ob Mindestdaten vorhanden sind.
        FA-2401: Schreibt ZIP mit project.xml und 0.xml.

        base_project: Optionaler Pfad zu einer bestehenden ETS6-.knxproj-Datei.
                      Deren Signatur/Zertifikat-Dateien werden uebernommen,
                      damit ETS6 die Datei als legitim erkennt (Basis-Projekt-Modus).
        """
        warnings = self._validate(project)
        summary = ExportSummary(warnings=warnings)

        if base_project:
            project_id = self._read_project_id(base_project)
            if not project_id:
                project_id = f"P-{uuid4().hex[:4].upper()}"
                logger.warning("Basis-Projekt: Projekt-ID nicht lesbar, neue ID vergeben.")
        else:
            project_id = f"P-{uuid4().hex[:4].upper()}"

        # Wenn Ziel == Basis-Datei: Basis zuerst vollstaendig in Speicher lesen,
        # damit das spätere Ueberschreiben die Quelle nicht korrumpiert.
        base_bytes: bytes | None = None
        if base_project and os.path.abspath(base_project) == os.path.abspath(filepath):
            with open(base_project, "rb") as f:
                base_bytes = f.read()
            base_project_source: str | bytes = base_bytes
        else:
            base_project_source = base_project  # type: ignore[assignment]

        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf_out:
            if base_project:
                self._copy_base_files(base_project_source, zf_out, project_id)

            zf_out.writestr(
                f"{project_id}/project.xml",
                self._project_xml(project, project_id),
            )
            main_xml, summary = self._main_xml(project, project_id, summary)
            zf_out.writestr(f"{project_id}/0.xml", main_xml)

        mode = "Basis-Projekt" if base_project else "Standalone"
        logger.info(
            f"KNXPROJ-Export ({mode}): '{project.name}' → {filepath}  "
            f"({summary.ga_count} GAs, {summary.device_count} Geraete, "
            f"{summary.co_link_count} CO-Links)"
        )
        return summary

    def export_ets5_compat(self, project, filepath: str) -> ExportSummary:
        """
        Exportiert als ETS5-kompatibles .knxproj (Namespace project/20).

        ETS5-Projekte haben keine kryptographische Signaturpflicht.
        ETS6 kann ETS5-Projekte ueber 'Datei → Importieren' laden.
        DeviceInstances liegen direkt in Line (kein Segment-Element).
        """
        warnings = self._validate(project)
        summary = ExportSummary(warnings=warnings)
        project_id = f"P-{uuid4().hex[:4].upper()}"

        exporter = _Ets5Exporter(project_id)
        with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{project_id}/project.xml", exporter.project_xml(project))
            main_xml, summary = exporter.main_xml(project, summary)
            zf.writestr(f"{project_id}/0.xml", main_xml)

        logger.info(
            f"KNXPROJ-Export ETS5-Compat: '{project.name}' → {filepath}  "
            f"({summary.ga_count} GAs, {summary.device_count} Geraete)"
        )
        return summary

    def _read_project_id(self, base_project: str) -> str | None:
        """Liest die Projekt-ID (z.B. 'P-06C2') aus einer bestehenden .knxproj-Datei."""
        try:
            with zipfile.ZipFile(base_project, "r") as zf:
                for name in zf.namelist():
                    if name.endswith("/project.xml") and name.count("/") == 1:
                        return name.split("/")[0]
        except Exception as e:
            logger.warning(f"Basis-Projekt nicht lesbar: {e}")
        return None

    def _copy_base_files(
        self, base_project: str | bytes, zf_out: zipfile.ZipFile, project_id: str
    ) -> None:
        """
        Kopiert alle Dateien aus dem Basis-Projekt AUSSER project.xml und 0.xml
        des Projekts (diese werden von uns neu geschrieben).
        Signaturen, Zertifikate, knx_master.xml und Herstellerdaten werden
        unveraendert uebernommen, damit ETS6 das Zertifikat akzeptiert.
        base_project kann ein Dateipfad (str) oder bereits gelesene Bytes sein.
        """
        skip = {f"{project_id}/project.xml", f"{project_id}/0.xml"}
        source = io.BytesIO(base_project) if isinstance(base_project, bytes) else base_project
        try:
            with zipfile.ZipFile(source, "r") as zf_in:
                for item in zf_in.infolist():
                    if item.filename in skip:
                        continue
                    if item.filename.endswith("/") and item.file_size == 0:
                        continue  # Leere Verzeichnis-Eintraege ueberspringen
                    zf_out.writestr(item, zf_in.read(item.filename))
        except Exception as e:
            logger.error(f"Fehler beim Kopieren der Basis-Projekt-Dateien: {e}")
            raise

    # ------------------------------------------------------------------
    # Validierung (FA-2406)
    # ------------------------------------------------------------------

    def _validate(self, project) -> list[str]:
        warnings: list[str] = []
        if not project.name:
            warnings.append("Kein Projektname vergeben (Einstellungen > Projektinfo).")
        n_ga = len(project.group_addresses.all_addresses())
        if n_ga == 0:
            warnings.append(
                "Keine Gruppenadressen vorhanden — "
                "Wizard Schritt 8 (GA-Generierung) zuerst ausfuehren."
            )
        areas = project.topology.areas
        if not areas or all(not a.lines for a in areas):
            warnings.append(
                "Keine Topologie vorhanden — "
                "Wizard Schritt 6 (Topologie) zuerst ausfuehren."
            )
        warnings.append(
            "Applikationsprogramme sind nicht enthalten — "
            "Geraete muessen in ETS weiterhin programmiert werden."
        )
        return warnings

    # ------------------------------------------------------------------
    # knxmaster.xml
    # ------------------------------------------------------------------

    def _knxmaster_xml(self) -> str:
        """Minimale knxmaster.xml (wird von ETS erwartet)."""
        root = _el("KNX")
        master = _sub(root, "MasterData", Version="23")
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )

    # ------------------------------------------------------------------
    # project.xml
    # ------------------------------------------------------------------

    def _project_xml(self, project, project_id: str) -> str:
        """Projektmetadaten gemaess ETS6-Format."""
        root = _el("KNX")
        proj = _sub(root, "Project", Id=project_id)
        info_attribs = {
            "Name": project.name or "Unbenanntes Projekt",
            "GroupAddressStyle": "ThreeLevel",
            "LastModified": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ProjectStart": project.created or datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "LastUsedPuid": "10000",
        }
        if project.project_number:
            info_attribs["Comment"] = f"Projektnr.: {project.project_number}"
        _sub(proj, "ProjectInformation", **info_attribs)
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )

    # ------------------------------------------------------------------
    # 0.xml – Hauptdaten
    # ------------------------------------------------------------------

    def _main_xml(
        self, project, project_id: str, summary: ExportSummary
    ) -> tuple[str, ExportSummary]:
        """
        Baut die 0.xml mit GAs, Topologie, Gebaeude und CO-Links.
        FA-2402: Alle Projektbestandteile.
        FA-2403: Geraete-Definitionen.
        FA-2404: CO-GA-Verknuepfungen.
        """
        root = _el("KNX")
        proj_elem = _sub(root, "Project", Id=project_id)
        installations = _sub(proj_elem, "Installations")
        inst = _sub(installations, "Installation", Name="", BCUKey="4294967295",
                    IPRoutingLatencyTolerance="2000")
        puid = _PuidCounter(1)

        # KNX Secure: Installation-Schlüssel (FA-2706)
        knx_secure = getattr(project, "knx_secure", None)
        if knx_secure and knx_secure.enabled:
            sec_attribs: dict[str, str] = {}
            if knx_secure.backbone_key:
                sec_attribs["InstallationKey"] = knx_secure.backbone_key
            if knx_secure.group_key:
                sec_attribs["GroupKey"] = knx_secure.group_key
            if sec_attribs:
                _sub(inst, "Security", **sec_attribs)

        # 1. Topologie (muss vor Locations sein; baut Device-ID-Map auf)
        dev_count, co_count, missing, dev_id_map = self._write_topology(
            inst, project.topology, puid,
            secure_cfg=knx_secure if (knx_secure and knx_secure.enabled) else None,
        )
        summary.device_count = dev_count
        summary.co_link_count = co_count
        summary.missing_co_devices = missing

        # 2. Gruppenadressen
        summary.ga_count = self._write_group_addresses(
            inst, project.group_addresses, puid
        )

        # 3. Gebaeude-/Raumstruktur (referenziert Device-IDs aus Topologie)
        self._write_buildings(inst, project.areal, project.topology, puid, dev_id_map)

        xml_str = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )
        return xml_str, summary

    # ------------------------------------------------------------------
    # Schritt 1: Gruppenadressen
    # ------------------------------------------------------------------

    def _write_group_addresses(
        self, parent: ET.Element, structure, puid: _PuidCounter
    ) -> int:
        """Schreibt die vollstaendige GA-Hierarchie (FA-2402)."""
        ga_root = _sub(parent, "GroupAddresses")
        ranges = _sub(ga_root, "GroupRanges")
        count = 0

        for hg in structure.main_groups:
            hg_start = _encode_ga(hg.number, 0, 0)
            hg_end   = _encode_ga(hg.number, 7, 255)
            hg_elem  = _sub(ranges, "GroupRange",
                            Id=f"P-GR-HG{hg.number}",
                            Name=hg.name or f"Hauptgruppe {hg.number}",
                            RangeStart=hg_start,
                            RangeEnd=hg_end,
                            Puid=puid.next())
            for mg in hg.middle_groups:
                mg_start = _encode_ga(hg.number, mg.number, 0)
                mg_end   = _encode_ga(hg.number, mg.number, 255)
                mg_elem  = _sub(hg_elem, "GroupRange",
                                Id=f"P-GR-HG{hg.number}-MG{mg.number}",
                                Name=mg.name or f"Mittelgruppe {mg.number}",
                                RangeStart=mg_start,
                                RangeEnd=mg_end,
                                Puid=puid.next())
                for ga in mg.group_addresses:
                    if ga.is_placeholder:
                        continue
                    attribs: dict[str, str] = {
                        "Id":      f"P-GA-{ga.id[:8]}",
                        "Address": str(_encode_ga(
                            ga.main_group, ga.middle_group, ga.sub_group
                        )),
                        "Name": ga.designation,
                        "Puid": puid.next(),
                    }
                    if ga.datapoint_type:
                        attribs["DatapointType"] = ga.datapoint_type
                    if ga.description:
                        attribs["Description"] = ga.description
                    if ga.central == "true":
                        attribs["Central"] = "true"
                    if ga.security and ga.security != "Auto":
                        attribs["Security"] = ga.security
                    _sub(mg_elem, "GroupAddress", **attribs)
                    count += 1

        return count

    # ------------------------------------------------------------------
    # Schritt 2: Topologie
    # ------------------------------------------------------------------

    def _write_topology(
        self, parent: ET.Element, topology, puid: _PuidCounter,
        secure_cfg=None,
    ) -> tuple[int, int, int, dict]:
        """
        Schreibt Bereiche, Linien und Geraete (FA-2402/2403).
        Gibt (device_count, co_link_count, missing_co_count, dev_id_map) zurueck.
        dev_id_map: device.id -> XML-Element-ID (fuer DeviceInstanceRef in Locations).
        """
        topo_elem = _sub(parent, "Topology")

        # Backbone / Bereichslinie (wird von ETS erwartet)
        area0 = _sub(topo_elem, "Area", Address="0", Name="Bereichslinie",
                     Id="P-AR-0", Puid=puid.next())
        line0 = _sub(area0, "Line", Address="0", Name="Hauptlinie",
                     Id="P-LN-0-0", Puid=puid.next())
        _sub(line0, "Segment", Id="P-SEG-0-0", Number="0",
             MediumTypeRefId="MT-0", Puid=puid.next())

        dev_count = 0
        co_count  = 0
        missing   = 0
        dev_id_map: dict[str, str] = {}

        for area in topology.areas:
            area_elem = _sub(topo_elem, "Area",
                             Id=f"P-AR-{area.area_number}",
                             Address=str(area.area_number),
                             Name=area.name or f"Bereich {area.area_number}",
                             Puid=puid.next())

            for line in area.lines:
                line_id = f"P-LN-{area.area_number}-{line.line_number}"
                line_elem = _sub(area_elem, "Line",
                                 Id=line_id,
                                 Address=str(line.line_number),
                                 Name=line.name or f"Linie {line.line_number}",
                                 Puid=puid.next())

                # ETS6 erwartet DeviceInstances innerhalb eines Segment-Elements
                seg_id = f"P-SEG-{area.area_number}-{line.line_number}"
                seg_elem = _sub(line_elem, "Segment",
                                Id=seg_id, Number="0",
                                MediumTypeRefId="MT-0",
                                Puid=puid.next())

                for device in line.devices:
                    if not device.physical_address:
                        continue
                    parts = device.physical_address.split(".")
                    if len(parts) != 3:
                        continue
                    try:
                        dev_addr = int(parts[2])
                    except ValueError:
                        continue

                    dev_xml_id = f"D-{device.id[:8]}"
                    dev_attribs: dict[str, str] = {
                        "Id":      dev_xml_id,
                        "Address": str(dev_addr),
                        "Name":    device.product_name or device.product or "Unbekannt",
                        "Puid":    puid.next(),
                    }
                    if device.manufacturer:
                        dev_attribs["Description"] = device.manufacturer
                    if device.installation_location:
                        dev_attribs["Comment"] = device.installation_location
                    dev_inst = _sub(seg_elem, "DeviceInstance", **dev_attribs)
                    dev_id_map[device.id] = dev_xml_id

                    # KNX Secure: Geräteschlüssel (FA-2706)
                    if secure_cfg is not None:
                        dev_info = secure_cfg.device_infos.get(device.id)
                        if dev_info and dev_info.tool_key:
                            sec_dev_attribs: dict[str, str] = {
                                "ToolKey": dev_info.tool_key
                            }
                            _sub(dev_inst, "Security", **sec_dev_attribs)

                    # CO-GA-Links (FA-2404): Im ETS6-Format referenziert
                    # ComObjectInstanceRef.RefId die geraetespezifische
                    # App-Programm-CO-ID aus der .knxprod-Datei, die wir
                    # ohne KNXPROD nicht kennen. Die CO-Planung (KNX Arranger
                    # CO-Linking) dient als Referenz fuer die ETS-Programmierung.
                    linked_gas = sum(
                        len(co.connected_gas) for co in device.communication_objects
                    )
                    co_count += linked_gas
                    if device.device_type == "actor" and not linked_gas:
                        missing += 1

                    dev_count += 1

        return dev_count, co_count, missing, dev_id_map

    def _ga_id(self, main: int, middle: int, sub: int) -> str:
        """Baut eine GA-Referenz-ID aus Hauptgruppe/Mittelgruppe/Untergruppe."""
        # Wir koennen keine UUID haben ohne Zugriff auf das GA-Objekt;
        # stattdessen eine deterministische ID aus der Adresse.
        return f"{_encode_ga(main, middle, sub):05d}"

    # ------------------------------------------------------------------
    # Schritt 3: Gebaeude-/Raumstruktur
    # ------------------------------------------------------------------

    def _write_buildings(
        self, parent: ET.Element, areal, topology,
        puid: _PuidCounter, dev_id_map: dict
    ) -> None:
        """
        Schreibt die Gebaeude-/Raumstruktur als Locations/Space-Baum
        und verknuepft Raeume mit Topologie-Geraeten (FA-2402).
        """
        loc_elem = _sub(parent, "Locations")

        # Geraete nach room_id indexieren
        room_devices: dict[str, list] = {}
        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.room_id:
                        room_devices.setdefault(device.room_id, []).append(device)

        for building in areal.buildings:
            bldg_elem = _sub(loc_elem, "Space",
                             Id=f"P-BLD-{building.id[:8]}",
                             Type="Building",
                             Name=building.name or "Gebaeude",
                             Puid=puid.next())
            for wing in building.wings:
                for floor in wing.floors:
                    floor_elem = _sub(bldg_elem, "Space",
                                      Id=f"P-FLR-{floor.id[:8]}",
                                      Type="BuildingPart",
                                      Name=floor.name or "Stockwerk",
                                      Puid=puid.next())
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            room_elem = _sub(floor_elem, "Space",
                                            Id=f"P-RM-{room.id[:8]}",
                                            Type="Room",
                                            Name=room.name or room.number or "Raum",
                                            Number=room.number or "",
                                            Puid=puid.next())
                            # Geraete des Raums referenzieren (via dev_id_map fuer konsistente IDs)
                            for device in room_devices.get(room.id, []):
                                xml_id = dev_id_map.get(device.id, f"D-{device.id[:8]}")
                                _sub(room_elem, "DeviceInstanceRef", RefId=xml_id)


# ---------------------------------------------------------------------------
# ETS5-kompatibler Exporter (Namespace project/20, keine Signaturpflicht)
# ---------------------------------------------------------------------------

_NS5 = "http://knx.org/xml/project/20"
_NS5_PREFIX = f"{{{_NS5}}}"
ET.register_namespace("", _NS5)


def _el5(tag: str, **attribs) -> ET.Element:
    return ET.Element(f"{_NS5_PREFIX}{tag}", **{k: str(v) for k, v in attribs.items()})


def _sub5(parent: ET.Element, tag: str, **attribs) -> ET.Element:
    return ET.SubElement(parent, f"{_NS5_PREFIX}{tag}",
                         **{k: str(v) for k, v in attribs.items()})


class _Ets5Exporter:
    """Erstellt ETS5-kompatible XML-Inhalte (Namespace project/20)."""

    def __init__(self, project_id: str):
        self._pid = project_id
        self._puid = _PuidCounter(1)

    def _xml_header(self, root: ET.Element) -> str:
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )

    def project_xml(self, project) -> str:
        root = _el5("KNX")
        proj = _sub5(root, "Project", Id=self._pid)
        _sub5(proj, "ProjectInformation",
              Name=project.name or "Unbenanntes Projekt",
              GroupAddressStyle="ThreeLevel",
              LastModified=datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"))
        return self._xml_header(root)

    def main_xml(self, project, summary: ExportSummary) -> tuple[str, ExportSummary]:
        root = _el5("KNX")
        proj_elem = _sub5(root, "Project", Id=self._pid)
        installations = _sub5(proj_elem, "Installations")
        inst = _sub5(installations, "Installation", Name="")

        # Topologie (DeviceInstance direkt in Line – ETS5-Stil, kein Segment)
        dev_count, dev_id_map = self._write_topology(inst, project.topology)
        summary.device_count = dev_count

        # Gruppenadressen
        summary.ga_count = self._write_group_addresses(inst, project.group_addresses)

        # Gebäudestruktur
        self._write_buildings(inst, project.areal, project.topology, dev_id_map)

        return self._xml_header(root), summary

    def _write_group_addresses(self, parent: ET.Element, structure) -> int:
        ga_root = _sub5(parent, "GroupAddresses")
        ranges = _sub5(ga_root, "GroupRanges")
        count = 0
        for hg in structure.main_groups:
            hg_elem = _sub5(ranges, "GroupRange",
                            Id=f"P-GR-HG{hg.number}",
                            Name=hg.name or f"Hauptgruppe {hg.number}",
                            RangeStart=str(_encode_ga(hg.number, 0, 0)),
                            RangeEnd=str(_encode_ga(hg.number, 7, 255)))
            for mg in hg.middle_groups:
                mg_elem = _sub5(hg_elem, "GroupRange",
                                Id=f"P-GR-HG{hg.number}-MG{mg.number}",
                                Name=mg.name or f"Mittelgruppe {mg.number}",
                                RangeStart=str(_encode_ga(hg.number, mg.number, 0)),
                                RangeEnd=str(_encode_ga(hg.number, mg.number, 255)))
                for ga in mg.group_addresses:
                    if ga.is_placeholder:
                        continue
                    attribs: dict[str, str] = {
                        "Id": f"P-GA-{ga.id[:8]}",
                        "Address": str(_encode_ga(ga.main_group, ga.middle_group, ga.sub_group)),
                        "Name": ga.designation,
                    }
                    if ga.datapoint_type:
                        attribs["DatapointType"] = ga.datapoint_type
                    if ga.description:
                        attribs["Description"] = ga.description
                    _sub5(mg_elem, "GroupAddress", **attribs)
                    count += 1
        return count

    def _write_topology(self, parent: ET.Element, topology) -> tuple[int, dict]:
        topo_elem = _sub5(parent, "Topology")
        area0 = _sub5(topo_elem, "Area", Address="0", Name="Bereichslinie", Id="P-AR-0")
        _sub5(area0, "Line", Address="0", Name="Hauptlinie", Id="P-LN-0-0")

        dev_count = 0
        dev_id_map: dict[str, str] = {}

        for area in topology.areas:
            area_elem = _sub5(topo_elem, "Area",
                              Id=f"P-AR-{area.area_number}",
                              Address=str(area.area_number),
                              Name=area.name or f"Bereich {area.area_number}")
            for line in area.lines:
                line_elem = _sub5(area_elem, "Line",
                                  Id=f"P-LN-{area.area_number}-{line.line_number}",
                                  Address=str(line.line_number),
                                  Name=line.name or f"Linie {line.line_number}")
                for device in line.devices:
                    if not device.physical_address:
                        continue
                    parts = device.physical_address.split(".")
                    if len(parts) != 3:
                        continue
                    try:
                        dev_addr = int(parts[2])
                    except ValueError:
                        continue
                    dev_xml_id = f"D-{device.id[:8]}"
                    dev_attribs: dict[str, str] = {
                        "Id":      dev_xml_id,
                        "Address": str(dev_addr),
                        "Name":    device.product_name or device.product or "Unbekannt",
                    }
                    if device.manufacturer:
                        dev_attribs["Description"] = device.manufacturer
                    _sub5(line_elem, "DeviceInstance", **dev_attribs)
                    dev_id_map[device.id] = dev_xml_id
                    dev_count += 1

        return dev_count, dev_id_map

    def _write_buildings(self, parent: ET.Element, areal, topology, dev_id_map: dict) -> None:
        loc_elem = _sub5(parent, "Locations")
        room_devices: dict[str, list] = {}
        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.room_id:
                        room_devices.setdefault(device.room_id, []).append(device)

        for building in areal.buildings:
            bldg_elem = _sub5(loc_elem, "Space",
                              Id=f"P-BLD-{building.id[:8]}",
                              Type="Building",
                              Name=building.name or "Gebaeude")
            for wing in building.wings:
                for floor in wing.floors:
                    floor_elem = _sub5(bldg_elem, "Space",
                                       Id=f"P-FLR-{floor.id[:8]}",
                                       Type="BuildingPart",
                                       Name=floor.name or "Stockwerk")
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            room_elem = _sub5(floor_elem, "Space",
                                             Id=f"P-RM-{room.id[:8]}",
                                             Type="Room",
                                             Name=room.name or room.number or "Raum",
                                             Number=room.number or "")
                            for device in room_devices.get(room.id, []):
                                xml_id = dev_id_map.get(device.id, f"D-{device.id[:8]}")
                                _sub5(room_elem, "DeviceInstanceRef", RefId=xml_id)
