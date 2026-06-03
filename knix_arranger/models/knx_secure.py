"""
KNX Secure Konfigurationsmodell (FA-2700).

Verwaltet KNX Secure Schlüssel, GA-Sicherheitskonfiguration und
Gerätekompatibilitätsinformationen gemäss ISO 22510 / EN 50090-3-4.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import secrets


# ── Schlüsseltypen-Beschreibungen ─────────────────────────────────────────────

KEY_TYPE_LABELS = {
    "backbone_key": "Backbone Key (KNX IP Secure Routing)",
    "group_key":    "Group Key (Standard Runtime Key für alle GAs)",
    "tool_key":     "Tool Key (Inbetriebnahme-Schlüssel pro Gerät)",
}

# GA-Sicherheitsmodi
GA_SECURITY_MODES = ["Auto", "Ein", "Aus"]

# KNX Secure-Modi (Gap 4)
SECURE_MODES = ["data_secure", "ip_secure", "both"]
SECURE_MODE_LABELS = {
    "data_secure": "KNX Data Secure (TP, medienunabhängig, EN 50090-3-4)",
    "ip_secure":   "KNX IP Secure (IP-Backbone / Routing, ISO 22510)",
    "both":        "KNX Data Secure + KNX IP Secure",
}

# Schlüssellänge: 128 bit = 16 Bytes
KEY_LENGTH_BYTES = 16

# FDSK-Länge: 128 bit = 32 Hex-Zeichen
FDSK_HEX_LENGTH = 32


def generate_knx_key() -> str:
    """Erzeugt einen zufälligen AES-128-Schlüssel als Hex-String (32 Zeichen)."""
    return secrets.token_bytes(KEY_LENGTH_BYTES).hex().upper()


def is_valid_knx_key(key: str) -> bool:
    """Prüft ob ein Schlüssel 32 gültige Hex-Zeichen enthält."""
    return len(key) == FDSK_HEX_LENGTH and all(c in "0123456789ABCDEFabcdef" for c in key)


@dataclass
class DeviceSecureInfo:
    """Secure-Kompatibilitätsinformation für ein einzelnes Gerät (FA-2704).

    Schlüsselhierarchie pro Gerät:
    - FDSK: Factory Default Setup Key, ab Werk aufgedruckt (QR-Code / alphanumerisch).
      Wird einmalig verwendet, um den Tool Key verschlüsselt zu übertragen.
      Wird NICHT über den Bus übertragen – nur manuell in ETS eingegeben.
    - Tool Key: von ETS generiert, via FDSK verschlüsselt zum Gerät übertragen.
      Danach für alle weiteren Schlüsselübertragungen (Runtime Keys) verwendet.
    """
    device_id: str = ""
    device_name: str = ""
    physical_address: str = ""
    secure_supported: bool = False    # aus KNXPROD-Daten
    line_id: str = ""
    area_id: str = ""
    # Schlüssel pro Gerät (KNX Standard)
    fdsk: str = ""                    # Factory Default Setup Key (ab Werk, 32 Hex)
    tool_key: str = ""                # Tool Key, via FDSK verschlüsselt übertragen

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "physical_address": self.physical_address,
            "secure_supported": self.secure_supported,
            "line_id": self.line_id,
            "area_id": self.area_id,
            "fdsk": self.fdsk,
            "tool_key": self.tool_key,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DeviceSecureInfo:
        return cls(
            device_id=d.get("device_id", ""),
            device_name=d.get("device_name", ""),
            physical_address=d.get("physical_address", ""),
            secure_supported=d.get("secure_supported", False),
            line_id=d.get("line_id", ""),
            area_id=d.get("area_id", ""),
            fdsk=d.get("fdsk", ""),
            tool_key=d.get("tool_key", ""),
        )


@dataclass
class KnxSecureConfig:
    """KNX Secure Projektkonfiguration (FA-2701, FA-2702).

    Speichert alle projektweiten und gerätespezifischen Secure-Schlüssel.
    Die Schlüssel werden im .knxarr-Format AES-128-verschlüsselt gespeichert
    (FA-2706); in diesem Datenmodell werden sie im Klartext gehalten und erst
    beim Serialisieren verschlüsselt.

    Schlüsselhierarchie (KNX Standard):
    1. FDSK: ab Werk pro Gerät (einmalige Nutzung für Tool-Key-Übertragung)
    2. Tool Key: pro Gerät, via FDSK verschlüsselt übertragen (Inbetriebnahme)
    3. GA Runtime Keys (ga_keys): pro GA-Adresse, via Tool Key zum Gerät übertragen
    4. Group Key: gemeinsamer Standard-Runtime-Key wenn keine GA-spezifischen Keys
    5. Backbone Key: für KNX IP Secure Routing (Multicast 224.0.23.12)
    """
    enabled: bool = False
    secure_mode: str = "data_secure"   # "data_secure", "ip_secure", "both"

    # Projektweite Schlüssel (FA-2702)
    backbone_key: str = ""            # 32 Hex = 128 bit, nur für KNX IP Secure
    group_key: str = ""               # Standard Runtime Key für alle GAs

    # GA-spezifische Runtime Keys: ga_address → 32 Hex-Zeichen (Gap 3)
    # Laufzeitschlüssel werden via Tool Key verschlüsselt an Geräte übertragen.
    # line_keys waren kein KNX-Standard – ersetzt durch ga_keys.
    ga_keys: dict[str, str] = field(default_factory=dict)

    # Geräteschlüssel: device_id → DeviceSecureInfo
    device_infos: dict[str, DeviceSecureInfo] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "secure_mode": self.secure_mode,
            "backbone_key": self.backbone_key,
            "group_key": self.group_key,
            "ga_keys": dict(self.ga_keys),
            "device_infos": {k: v.to_dict() for k, v in self.device_infos.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> KnxSecureConfig:
        cfg = cls(
            enabled=d.get("enabled", False),
            secure_mode=d.get("secure_mode", "data_secure"),
            backbone_key=d.get("backbone_key", ""),
            group_key=d.get("group_key", ""),
            # line_keys (altes Format) werden verworfen – waren kein KNX-Standard
            ga_keys=dict(d.get("ga_keys", {})),
        )
        cfg.device_infos = {
            k: DeviceSecureInfo.from_dict(v)
            for k, v in d.get("device_infos", {}).items()
        }
        return cfg
