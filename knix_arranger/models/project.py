"""
KnxProject - Root-Objekt des gesamten KNX-Projekts
Serialisierung zu/von JSON und SQLite (.knxarr)
Gemaess Datenmodell Abschnitt 5.1
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import copy
import json
import sqlite3
import os
import uuid
from datetime import datetime

from .building import Areal, Building, Wing, Floor, Apartment, Room
from .topology import Topology
from .group_address import GroupAddressStructure
from .gewerk import Gewerk, GewerkCatalog
from .scene import Scene
from .quotation import Supplier, QuotationRequest, CustomerQuote
from .documentation import (
    AcceptanceProtocol, CommissioningChecklist, RevisionRecord, UserManualSettings,
)
from .company_profile import CompanyProfile, ProjectInfo
from .client_profile import ClientProfile
from .ets_corrections import EtsCorrections
from .material_list import MaterialList
from .dali_config import DaliGateway
from .knx_secure import KnxSecureConfig
from .time_program import TimeProgram, ProjectLocation

from ..utils.manufacturers import manufacturer_display_name

# Gateway-Gewerke mit standardmässig einem gemeinsamen Gateway für das ganze
# Projekt (Entscheid 2026-10-06): Multimedia (Revox teilt die Zonen selbst
# ein), Wärmepumpe, Energie (PV, Speicher, Wallbox), Lüftung/Klima. DALI und
# DMX bleiben je Linie -- der Bus ist an seine Leuchten gebunden.
SHARED_GATEWAY_DEFAULTS = frozenset({"MM", "WP", "PV", "SP", "EV", "LU", "KL"})


@dataclass
class ProjectConfig:
    """Projekt-Konfiguration."""
    mg_variant: str = "A"         # "A" oder "B" (Mittelgruppen-Variante)
    topology_mode: str = "TP-256" # "TP-64" oder "TP-256"
    backbone_type: str = "TP"     # "TP" oder "IP"
    preferred_manufacturers: list[str] = field(default_factory=list)
    # Gateway-Gewerke (FA-1307): "project" = ein gemeinsames Gateway für das
    # ganze Projekt (z.B. Revox teilt die Zonen selbst ein), "line" = je
    # Linie. Nur Abweichungen von SHARED_GATEWAY_DEFAULTS stehen hier.
    gateway_scope: dict[str, str] = field(default_factory=dict)
    # Linie (Line.id) des gemeinsamen Gateways je Gewerk; leer = automatisch
    gateway_line: dict[str, str] = field(default_factory=dict)

    def gateway_shared(self, gewerk_code: str) -> bool:
        scope = self.gateway_scope.get(gewerk_code)
        if scope:
            return scope == "project"
        return gewerk_code in SHARED_GATEWAY_DEFAULTS

    def to_dict(self) -> dict:
        return {
            "mg_variant": self.mg_variant,
            "topology_mode": self.topology_mode,
            "backbone_type": self.backbone_type,
            "preferred_manufacturers": self.preferred_manufacturers,
            "gateway_scope": dict(self.gateway_scope),
            "gateway_line": dict(self.gateway_line),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectConfig:
        return cls(
            mg_variant=data.get("mg_variant", "A"),
            topology_mode=data.get("topology_mode", "TP-256"),
            backbone_type=data.get("backbone_type", "TP"),
            preferred_manufacturers=list(dict.fromkeys(
                manufacturer_display_name(m) for m in data.get("preferred_manufacturers", [])
            )),
            gateway_scope=dict(data.get("gateway_scope", {})),
            gateway_line=dict(data.get("gateway_line", {})),
        )


@dataclass
class ChangelogEntry:
    """Ein Eintrag im Projekt-Änderungsprotokoll.

    Checkpoint-basiert: automatische Einträge bei wichtigen Ereignissen
    (Projekt erstellt, ETS-Import/Re-Import, Revisionspaket erstellt) plus
    freie Notizen. Bewusst keine feldweise Änderungsverfolgung -- für ein
    Solo-Planungswerkzeug wäre das reines Rauschen ohne Mehrwert.
    """
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    category: str = "Notiz"   # "Projekt", "Import", "Re-Import", "Revision", "Notiz"
    message: str = ""

    def to_dict(self) -> dict:
        return {"timestamp": self.timestamp, "category": self.category, "message": self.message}

    @classmethod
    def from_dict(cls, data: dict) -> ChangelogEntry:
        return cls(
            timestamp=data.get("timestamp", ""),
            category=data.get("category", "Notiz"),
            message=data.get("message", ""),
        )


@dataclass
class KnxProject:
    """Root-Objekt eines KNX-Projekts."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    project_number: str = ""
    created: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    modified: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    version: str = "1.0"

    config: ProjectConfig = field(default_factory=ProjectConfig)
    project_info: ProjectInfo = field(default_factory=ProjectInfo)
    client_profile: ClientProfile = field(default_factory=ClientProfile)
    # Korrekturen an importierten ETS-Daten (Korrekturschicht, siehe
    # services/ets_corrections) -- die ETS-Daten selbst bleiben unverändert
    ets_corrections: EtsCorrections = field(default_factory=EtsCorrections)
    # Stand der ETS-Arbeitsliste (services/ets_worklist): Runde, letzter Import,
    # Aufgaben mit erstem Auftreten und Erledigt-Datum
    ets_worklist: dict = field(default_factory=dict)
    areal: Areal = field(default_factory=Areal)
    topology: Topology = field(default_factory=Topology)
    group_addresses: GroupAddressStructure = field(default_factory=GroupAddressStructure)
    scenes: list[Scene] = field(default_factory=list)
    suppliers: list[Supplier] = field(default_factory=list)
    quotation_requests: list[QuotationRequest] = field(default_factory=list)
    customer_quotes: list[CustomerQuote] = field(default_factory=list)
    acceptance_protocol: Optional[AcceptanceProtocol] = None
    checklists: list[CommissioningChecklist] = field(default_factory=list)
    # Erstellte Revisionsstände der Revisionsunterlagen (FA-2106)
    revisions: list[RevisionRecord] = field(default_factory=list)
    # Anpassungen der Bedienungsanleitung (FA-2005)
    manual_settings: UserManualSettings = field(default_factory=UserManualSettings)
    custom_gewerk_templates: dict[str, dict] = field(default_factory=dict)
    material_list: MaterialList = field(default_factory=MaterialList)
    # DALI-Konfigurationen: gateway_device_id → DaliGateway (FA-2801)
    dali_configs: dict[str, DaliGateway] = field(default_factory=dict)
    # KNX Secure Konfiguration (FA-2701)
    knx_secure: KnxSecureConfig = field(default_factory=KnxSecureConfig)
    # Zeitsteuerung (FA-3301)
    time_programs: list[TimeProgram] = field(default_factory=list)
    location: ProjectLocation = field(default_factory=ProjectLocation)
    # Änderungsprotokoll (checkpoint-basiert, siehe ChangelogEntry)
    changelog: list[ChangelogEntry] = field(default_factory=list)
    # Benutzerdefinierte Gewerke (FA-303), z.B. für Fremdsystem-Gateways ohne
    # Standard-Katalogeintrag. Gespeichert als Gewerk.to_dict(); werden beim
    # ersten Zugriff auf gewerk_catalog in den Katalog übernommen (siehe dort).
    custom_gewerke: list[dict] = field(default_factory=list)
    # Manuell zugewiesener Zielraum für einen aus dem Einbauort abgeleiteten
    # Verteiler-Pseudo-Raum (XlsxImportService.create_verteiler_rooms legt bei
    # jedem Import wieder einen neuen an, z.B. "HV  HV") -- Schlüssel ist der
    # kanonische Verteiler-Key (siehe xlsx_import_service._vt_key, z.B. "HV",
    # "UV2"), Wert [floor_short_code, room_number] des echten Zielraums (z.B.
    # ["EG", "01"] für "Technikraum"). Wird bei jedem Import automatisch
    # erneut angewendet (XlsxImportService.apply_verteiler_room_overrides),
    # damit eine einmal in Schritt 3b vorgenommene Zuordnung Re-Importe
    # übersteht.
    verteiler_room_overrides: dict[str, list[str]] = field(default_factory=dict)
    # Zuletzt importierte ETS-Excel-Reports: {"topology_xlsx"|"ga_report"|
    # "building_report": Pfad}. Jeder Import zieht die übrigen nach (siehe
    # ImportPipeline) -- gehört zum Projekt, nicht zur Sitzung.
    import_files: dict[str, str] = field(default_factory=dict)

    # Nicht serialisiert - wird zur Laufzeit geladen
    _gewerk_catalog: Optional[GewerkCatalog] = field(
        default=None, repr=False, compare=False
    )
    _file_path: str = field(default="", repr=False, compare=False)

    @property
    def folder_path(self) -> str | None:
        """Ordner der gespeicherten Projektdatei (für Berichte/Revisionen, FA-1601)."""
        return os.path.dirname(self._file_path) if self._file_path else None

    @property
    def gewerk_catalog(self) -> GewerkCatalog:
        if self._gewerk_catalog is None:
            self._gewerk_catalog = GewerkCatalog()
            self._gewerk_catalog.load_defaults()
            for cg in self.custom_gewerke:
                self._gewerk_catalog.add_custom(Gewerk.from_dict(cg))
        return self._gewerk_catalog

    def add_custom_gewerk(self, gewerk: Gewerk) -> None:
        """Fügt ein benutzerdefiniertes Gewerk zum Katalog hinzu und
        persistiert es mit dem Projekt (FA-303) -- z.B. für Fremdsystem-
        Gateways ohne Standard-Katalogeintrag (Musikanlage, individuelle
        Wärmepumpe, ...) oder Zusatzfunktionen von Kombigeräten."""
        self.gewerk_catalog.add_custom(gewerk)
        self.custom_gewerke = [
            g.to_dict() for g in self.gewerk_catalog.all_gewerke() if g.is_custom
        ]

    @property
    def all_floors(self) -> list[Floor]:
        return self.areal.all_floors

    def shared_gateways(self) -> dict[str, str]:
        """Gateway-Gewerke mit gemeinsamem Gateway: Gewerk -> Linie (Line.id,
        leer = automatisch). Für die Aktor-Ermittlung (FA-1307)."""
        from .device import GEWERK_TO_ACTOR_TYPE, GATEWAY_ACTOR_TYPES
        return {code: self.config.gateway_line.get(code, "")
                for code, actor_type in GEWERK_TO_ACTOR_TYPE.items()
                if actor_type in GATEWAY_ACTOR_TYPES and self.config.gateway_shared(code)}

    @property
    def all_rooms(self) -> list[Room]:
        return self.areal.all_rooms

    def touch(self):
        """Aktualisiert das Aenderungsdatum."""
        self.modified = datetime.now().strftime("%Y-%m-%d")

    def add_changelog_entry(self, category: str, message: str) -> None:
        """Fügt einen Eintrag zum Änderungsprotokoll hinzu (siehe ChangelogEntry)."""
        self.changelog.append(ChangelogEntry(category=category, message=message))

    def content_fingerprint(self) -> str:
        """Prüfsumme des Inhalts ohne Änderungsdatum. Erkennt ungespeicherte
        Änderungen auch dort, wo eine Ansicht sie nicht meldet (siehe
        MainWindow.closeEvent). Nur die Prüfsumme bleibt im Speicher."""
        import hashlib
        data = self.to_dict(_plain_secure=True)
        data.pop("modified", None)
        text = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def to_dict(self, _plain_secure: bool = False) -> dict:
        """Serialisiert das Projekt als Dictionary. _plain_secure: KNX Secure
        unverschlüsselt (nur für content_fingerprint -- die Verschlüsselung
        verwendet jedes Mal ein neues Salt)."""
        data = {
            "id": self.id,
            "name": self.name,
            "project_number": self.project_number,
            "created": self.created,
            "modified": self.modified,
            "version": self.version,
            "config": self.config.to_dict(),
            "project_info": self.project_info.to_dict(),
            "client_profile": self.client_profile.to_dict(),
            "ets_corrections": self.ets_corrections.to_dict(),
            "ets_worklist": copy.deepcopy(self.ets_worklist),
            "areal": self.areal.to_dict(),
            "topology": self.topology.to_dict(),
            "group_addresses": self.group_addresses.to_dict(),
            "scenes": [s.to_dict() for s in self.scenes],
            "suppliers": [s.to_dict() for s in self.suppliers],
            "quotation_requests": [qr.to_dict() for qr in self.quotation_requests],
            "customer_quotes": [cq.to_dict() for cq in self.customer_quotes],
            "checklists": [c.to_dict() for c in self.checklists],
            "revisions": [r.to_dict() for r in self.revisions],
            "manual_settings": self.manual_settings.to_dict(),
            "custom_gewerk_templates": self.custom_gewerk_templates,
            "material_list": self.material_list.to_dict(),
            "dali_configs": {k: v.to_dict() for k, v in self.dali_configs.items()},
        }
        # Zeitsteuerung (FA-3301)
        data["time_programs"] = [tp.to_dict() for tp in self.time_programs]
        data["location"] = self.location.to_dict()
        # Änderungsprotokoll
        data["changelog"] = [e.to_dict() for e in self.changelog]
        # Benutzerdefinierte Gewerke
        data["custom_gewerke"] = self.custom_gewerke
        data["verteiler_room_overrides"] = self.verteiler_room_overrides
        data["import_files"] = self.import_files
        # KNX Secure: sensible Felder (FDSK/ETS6-Projektpasswort/Notiz)
        # passwortbasiert verschlüsselt speichern (FA-2706).
        ks = self.knx_secure
        if ks._locked_blob is not None:
            # In dieser Sitzung nie entsperrt -> bestehendes Archiv unveraendert
            # zurueckschreiben, damit es nicht verloren geht.
            data["knx_secure"] = ks._locked_blob
        elif ks._session_password and not _plain_secure:
            from ..services.knx_secure_service import KnxSecureService
            data["knx_secure"] = KnxSecureService.encrypt_config(
                ks, ks._session_password
            )
        else:
            data["knx_secure"] = ks.to_dict()
        if self.acceptance_protocol:
            data["acceptance_protocol"] = self.acceptance_protocol.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> KnxProject:
        """Deserialisiert ein Projekt aus einem Dictionary."""
        project = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            project_number=data.get("project_number", ""),
            created=data.get("created", ""),
            modified=data.get("modified", ""),
            version=data.get("version", "1.0"),
        )
        project.config = ProjectConfig.from_dict(data.get("config", {}))
        project.project_info = ProjectInfo.from_dict(data.get("project_info", {}))
        project.client_profile = ClientProfile.from_dict(data.get("client_profile", {}))
        project.ets_corrections = EtsCorrections.from_dict(data.get("ets_corrections"))
        project.ets_worklist = copy.deepcopy(data.get("ets_worklist") or {})
        project.revisions = [RevisionRecord.from_dict(r) for r in data.get("revisions", [])]
        project.manual_settings = UserManualSettings.from_dict(data.get("manual_settings"))
        project.areal = Areal.from_dict(data.get("areal", {}))
        project.topology = Topology.from_dict(data.get("topology", {}))
        project.group_addresses = GroupAddressStructure.from_dict(
            data.get("group_addresses", {})
        )
        project.scenes = [Scene.from_dict(s) for s in data.get("scenes", [])]
        project.suppliers = [
            Supplier.from_dict(s) for s in data.get("suppliers", [])
        ]
        project.quotation_requests = [
            QuotationRequest.from_dict(qr) for qr in data.get("quotation_requests", [])
        ]
        project.customer_quotes = [
            CustomerQuote.from_dict(cq) for cq in data.get("customer_quotes", [])
        ]
        project.checklists = [
            CommissioningChecklist.from_dict(c) for c in data.get("checklists", [])
        ]
        project.custom_gewerk_templates = data.get("custom_gewerk_templates", {})
        if "acceptance_protocol" in data and data["acceptance_protocol"]:
            project.acceptance_protocol = AcceptanceProtocol.from_dict(
                data["acceptance_protocol"]
            )
        project.material_list = MaterialList.from_dict(
            data.get("material_list", {})
        )
        project.dali_configs = {
            k: DaliGateway.from_dict(v)
            for k, v in data.get("dali_configs", {}).items()
        }
        # Zeitsteuerung laden
        project.time_programs = [
            TimeProgram.from_dict(tp) for tp in data.get("time_programs", [])
        ]
        project.location = ProjectLocation.from_dict(data.get("location", {}))
        project.changelog = [
            ChangelogEntry.from_dict(e) for e in data.get("changelog", [])
        ]
        project.custom_gewerke = data.get("custom_gewerke", [])
        project.verteiler_room_overrides = data.get("verteiler_room_overrides", {})
        project.import_files = data.get("import_files", {})
        # KNX Secure laden: unverschlüsselte Felder sofort verfügbar; falls ein
        # verschlüsseltes Archiv (secure_blob) vorhanden ist, bleibt dieses
        # gesperrt, bis in der UI das Master-Passwort eingegeben wird
        # (siehe KnxSecureService.unlock).
        secure_data = data.get("knx_secure", {})
        project.knx_secure = KnxSecureConfig.from_dict(secure_data) if secure_data else KnxSecureConfig()
        if secure_data.get("secure_blob"):
            project.knx_secure._locked_blob = secure_data
        return project

    def to_json(self) -> str:
        """Serialisiert als JSON-String."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> KnxProject:
        """Deserialisiert aus JSON-String."""
        return cls.from_dict(json.loads(json_str))

    def save(self, filepath: str):
        """Speichert das Projekt als .knxarr SQLite-Datei (NFA-044)."""
        self.touch()
        self._file_path = filepath

        conn = sqlite3.connect(filepath)
        try:
            # SQLite behält überschriebene Stände im freien Speicher der Datei
            # -- darin standen z.B. FDSK-Schlüssel, bevor das Secure-Archiv
            # verschlüsselt wurde. secure_delete nullt freigegebene Seiten,
            # VACUUM (nach dem Commit) entfernt sie aus der Datei.
            conn.execute("PRAGMA secure_delete = ON")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS project "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS datasheets "
                "(id TEXT PRIMARY KEY, filename TEXT, data BLOB)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO project (key, value) VALUES (?, ?)",
                ("project_data", self.to_json()),
            )
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()

    @classmethod
    def load(cls, filepath: str) -> KnxProject:
        """Lädt ein Projekt aus einer .knxarr SQLite-Datei."""
        conn = sqlite3.connect(filepath)
        try:
            cursor = conn.execute(
                "SELECT value FROM project WHERE key = ?", ("project_data",)
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Keine Projektdaten in {filepath}")
            project = cls.from_json(row[0])
            project._file_path = filepath
            return project
        finally:
            conn.close()
