"""
KNX Secure Konfigurationsmodell (FA-2700, ueberarbeitet).

WICHTIGE KORREKTUR gegenueber der urspruenglichen Fassung:
KNiX Arranger kann und darf keine KNX-Secure-Laufzeitschluessel (Backbone Key,
Group Key, GA-Schluessel, Tool Key) selbst generieren oder verwalten. Diese
werden ausschliesslich von der ETS6 aus dem geraeteindividuellen Zertifikat
(FDSK, Factory Default Setup Key -- wird dem Geraet ab Werk beigelegt) abgeleitet
und bleiben KNiX Arranger unbekannt.

Die Rolle dieses Moduls ist daher rein archivarisch:
- FDSK/Zertifikat je Geraet aufbewahren (das einzige Geheimnis, das der
  Planer tatsaechlich in Papierform erhaelt und verlieren kann).
- Das ETS6-Projektpasswort dokumentieren -- ohne dieses ist das ETS6-Projekt
  unwiederbringlich verloren (kein Reset, keine Wiederherstellung durch KNX
  oder den Hersteller moeglich).
- Secure-Kompatibilitaet der Geraete (aus KNXPROD-Herstellerdaten) und
  GA-Sicherheitsklassifikation (Auto/Ein/Aus) verwalten -- das sind keine
  Geheimnisse, sondern Planungsmetadaten.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# GA-Sicherheitsmodi
GA_SECURITY_MODES = ["Auto", "Ein", "Aus"]

# KNX Secure-Modi
SECURE_MODES = ["data_secure", "ip_secure", "both"]
SECURE_MODE_LABELS = {
    "data_secure": "KNX Data Secure (TP, medienunabhängig, EN 50090-3-4)",
    "ip_secure":   "KNX IP Secure (IP-Backbone / Routing, ISO 22510)",
    "both":        "KNX Data Secure + KNX IP Secure",
}

# FDSK-Länge: 128 bit = 32 Hex-Zeichen
FDSK_HEX_LENGTH = 32


def is_valid_knx_key(key: str) -> bool:
    """Prüft ob ein Wert (z.B. FDSK) 32 gültige Hex-Zeichen enthält."""
    return len(key) == FDSK_HEX_LENGTH and all(c in "0123456789ABCDEFabcdef" for c in key)


@dataclass
class DeviceSecureInfo:
    """Secure-Kompatibilitäts- und Zertifikatsinformation für ein Gerät (FA-2704).

    - secure_supported: aus KNXPROD-Herstellerdaten (SupportsTPSecure/IPSecure),
      keine Eingabe/Vermutung von KNiX Arranger.
    - fdsk: Factory Default Setup Key, ab Werk mit dem Gerät mitgeliefert
      (Aufkleber/QR-Code/Zertifikatskarte). Wird von ETS6 einmalig verwendet,
      um die eigentlichen Runtime-Schlüssel zu erzeugen und sicher zu
      übertragen. KNiX Arranger generiert diesen Wert NICHT -- er muss vom
      Planer vom mitgelieferten Zertifikat abgetippt/archiviert werden.
    """
    device_id: str = ""
    device_name: str = ""
    physical_address: str = ""
    secure_supported: bool = False    # aus KNXPROD-Daten
    line_id: str = ""
    area_id: str = ""
    fdsk: str = ""                    # Factory Default Setup Key (Zertifikat, 32 Hex)

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "physical_address": self.physical_address,
            "secure_supported": self.secure_supported,
            "line_id": self.line_id,
            "area_id": self.area_id,
            "fdsk": self.fdsk,
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
        )


@dataclass
class KnxSecureConfig:
    """KNX-Secure-Archiv eines Projekts (FA-2701, FA-2704--2706, überarbeitet).

    Enthält KEINE kryptographischen Laufzeitschlüssel (die kennt nur ETS6).
    Sensible Felder (FDSK je Gerät, ETS6-Projektpasswort, Notiz) werden beim
    Speichern passwortbasiert verschlüsselt (siehe KnxSecureService). Die
    beiden Laufzeit-Attribute (_session_password, _locked_blob) werden nicht
    serialisiert -- sie steuern nur das Sperren/Entsperren innerhalb der
    laufenden Sitzung, analog zu KnxProject._file_path.
    """
    enabled: bool = False
    secure_mode: str = "data_secure"   # "data_secure", "ip_secure", "both"

    # ETS6-Projektpasswort: schützt den Zugriff auf das ETS6-Projekt selbst.
    # KRITISCH: ohne dieses Passwort ist das ETS6-Projekt nicht wiederherstellbar.
    ets_project_password: str = ""
    ets_password_note: str = ""        # z.B. Hinterlegungsort / Wiederherstellungsplan

    # Geräteschlüssel: device_id → DeviceSecureInfo (secure_supported + FDSK)
    device_infos: dict[str, DeviceSecureInfo] = field(default_factory=dict)

    # Nicht serialisiert -- nur zur Laufzeit im Speicher, siehe KnxSecureService
    _session_password: Optional[str] = field(default=None, repr=False, compare=False)
    _locked_blob: Optional[dict] = field(default=None, repr=False, compare=False)

    @property
    def is_locked(self) -> bool:
        """True wenn verschlüsselte Daten vorhanden sind, aber in dieser
        Sitzung noch kein gültiges Passwort eingegeben wurde."""
        return self._locked_blob is not None

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "secure_mode": self.secure_mode,
            "ets_project_password": self.ets_project_password,
            "ets_password_note": self.ets_password_note,
            "device_infos": {k: v.to_dict() for k, v in self.device_infos.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> KnxSecureConfig:
        cfg = cls(
            enabled=d.get("enabled", False),
            secure_mode=d.get("secure_mode", "data_secure"),
            ets_project_password=d.get("ets_project_password", ""),
            ets_password_note=d.get("ets_password_note", ""),
        )
        cfg.device_infos = {
            k: DeviceSecureInfo.from_dict(v)
            for k, v in d.get("device_infos", {}).items()
        }
        return cfg
