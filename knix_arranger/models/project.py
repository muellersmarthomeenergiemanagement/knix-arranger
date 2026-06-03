"""
KnxProject - Root-Objekt des gesamten KNX-Projekts
Serialisierung zu/von JSON und SQLite (.knxarr)
Gemaess Datenmodell Abschnitt 5.1
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json
import sqlite3
import os
import uuid
from datetime import datetime

from .building import Areal, Building, Wing, Floor, Apartment, Room
from .topology import Topology
from .group_address import GroupAddressStructure
from .gewerk import GewerkCatalog
from .scene import Scene
from .quotation import Supplier, QuotationRequest, CustomerQuote
from .documentation import AcceptanceProtocol, CommissioningChecklist
from .company_profile import CompanyProfile, ProjectInfo
from .client_profile import ClientProfile
from .material_list import MaterialList
from .dali_config import DaliGateway
from .knx_secure import KnxSecureConfig
from .time_program import TimeProgram, ProjectLocation


@dataclass
class ProjectConfig:
    """Projekt-Konfiguration."""
    mg_variant: str = "A"         # "A" oder "B" (Mittelgruppen-Variante)
    topology_mode: str = "TP-256" # "TP-64" oder "TP-256"
    backbone_type: str = "TP"     # "TP" oder "IP"
    preferred_manufacturers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mg_variant": self.mg_variant,
            "topology_mode": self.topology_mode,
            "backbone_type": self.backbone_type,
            "preferred_manufacturers": self.preferred_manufacturers,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectConfig:
        return cls(
            mg_variant=data.get("mg_variant", "A"),
            topology_mode=data.get("topology_mode", "TP-256"),
            backbone_type=data.get("backbone_type", "TP"),
            preferred_manufacturers=data.get("preferred_manufacturers", []),
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
    areal: Areal = field(default_factory=Areal)
    topology: Topology = field(default_factory=Topology)
    group_addresses: GroupAddressStructure = field(default_factory=GroupAddressStructure)
    scenes: list[Scene] = field(default_factory=list)
    suppliers: list[Supplier] = field(default_factory=list)
    quotation_requests: list[QuotationRequest] = field(default_factory=list)
    customer_quotes: list[CustomerQuote] = field(default_factory=list)
    acceptance_protocol: Optional[AcceptanceProtocol] = None
    checklists: list[CommissioningChecklist] = field(default_factory=list)
    custom_gewerk_templates: dict[str, dict] = field(default_factory=dict)
    material_list: MaterialList = field(default_factory=MaterialList)
    # DALI-Konfigurationen: gateway_device_id → DaliGateway (FA-2801)
    dali_configs: dict[str, DaliGateway] = field(default_factory=dict)
    # KNX Secure Konfiguration (FA-2701)
    knx_secure: KnxSecureConfig = field(default_factory=KnxSecureConfig)
    # Zeitsteuerung (FA-3301)
    time_programs: list[TimeProgram] = field(default_factory=list)
    location: ProjectLocation = field(default_factory=ProjectLocation)

    # Nicht serialisiert - wird zur Laufzeit geladen
    _gewerk_catalog: Optional[GewerkCatalog] = field(
        default=None, repr=False, compare=False
    )
    _file_path: str = field(default="", repr=False, compare=False)

    @property
    def gewerk_catalog(self) -> GewerkCatalog:
        if self._gewerk_catalog is None:
            self._gewerk_catalog = GewerkCatalog()
            self._gewerk_catalog.load_defaults()
        return self._gewerk_catalog

    @property
    def all_floors(self) -> list[Floor]:
        return self.areal.all_floors

    @property
    def all_rooms(self) -> list[Room]:
        return self.areal.all_rooms

    def touch(self):
        """Aktualisiert das Aenderungsdatum."""
        self.modified = datetime.now().strftime("%Y-%m-%d")

    def to_dict(self) -> dict:
        """Serialisiert das Projekt als Dictionary."""
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
            "areal": self.areal.to_dict(),
            "topology": self.topology.to_dict(),
            "group_addresses": self.group_addresses.to_dict(),
            "scenes": [s.to_dict() for s in self.scenes],
            "suppliers": [s.to_dict() for s in self.suppliers],
            "quotation_requests": [qr.to_dict() for qr in self.quotation_requests],
            "customer_quotes": [cq.to_dict() for cq in self.customer_quotes],
            "checklists": [c.to_dict() for c in self.checklists],
            "custom_gewerk_templates": self.custom_gewerk_templates,
            "material_list": self.material_list.to_dict(),
            "dali_configs": {k: v.to_dict() for k, v in self.dali_configs.items()},
        }
        # Zeitsteuerung (FA-3301)
        data["time_programs"] = [tp.to_dict() for tp in self.time_programs]
        data["location"] = self.location.to_dict()
        # KNX Secure: Schlüssel verschlüsselt speichern (FA-2706)
        if self.knx_secure.enabled and (
            self.knx_secure.backbone_key or self.knx_secure.group_key
        ):
            try:
                from ..services.knx_secure_service import KnxSecureService
                data["knx_secure"] = KnxSecureService.encrypt_config(
                    self.knx_secure, self.id
                )
            except Exception:
                data["knx_secure"] = self.knx_secure.to_dict()
        else:
            data["knx_secure"] = self.knx_secure.to_dict()
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
        # KNX Secure laden (evtl. verschlüsselt)
        secure_data = data.get("knx_secure", {})
        if secure_data:
            try:
                from ..services.knx_secure_service import KnxSecureService
                project.knx_secure = KnxSecureService.decrypt_config(
                    secure_data, project.id
                )
            except Exception:
                project.knx_secure = KnxSecureConfig.from_dict(secure_data)
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
