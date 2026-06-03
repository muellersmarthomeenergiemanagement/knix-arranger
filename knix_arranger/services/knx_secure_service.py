"""
KnxSecureService – Verwaltung von KNX Secure Konfigurationen (FA-2701–FA-2706).

Verantwortlich für:
- Schlüsselgenerierung (AES-128, FA-2702)
- Auto-Vorschlag GA-Sicherheitsmodi (FA-2703)
- Gerätekompatibilitätsliste (FA-2704)
- Mischlinien-Prüfung (FA-2705)
- AES-128-Verschlüsselung der Schlüssel im .knxarr-Format (FA-2706)
"""
from __future__ import annotations
import json
import logging
import os
import secrets
from dataclasses import dataclass

from ..models.knx_secure import KnxSecureConfig, DeviceSecureInfo, generate_knx_key

logger = logging.getLogger("knix_arranger.knx_secure")

# Funktionsnamen, die automatisch als "Ein" vorgeschlagen werden (FA-2703)
_SECURE_FUNCTION_KEYWORDS = frozenset([
    "schalten", "szene", "zentral", "sperren", "on_off", "switch",
    "scene", "central", "lock", "alarm", "notaus", "emergency",
])


@dataclass
class MixedLineWarning:
    """Warnung für eine Linie mit gemischten Secure/Non-Secure Geräten (FA-2705)."""
    area_number: int
    line_number: int
    line_name: str
    secure_devices: list[str]      # Gerätenamen (oder phys. Adressen)
    non_secure_devices: list[str]

    @property
    def message(self) -> str:
        non_sec = ', '.join(self.non_secure_devices[:5])
        suffix = "…" if len(self.non_secure_devices) > 5 else ""
        return (
            f"Linie {self.area_number}.{self.line_number} ({self.line_name}): "
            f"Gemischte KNX Secure-Konfiguration – "
            f"{len(self.secure_devices)} Secure-Gerät(e) und "
            f"{len(self.non_secure_devices)} Non-Secure-Gerät(e). "
            f"Non-Secure: {non_sec}{suffix}"
        )


class KnxSecureService:
    """Verwaltung aller KNX Secure-Aspekte eines Projekts."""

    # ── Schlüsselgenerierung (FA-2702) ────────────────────────────────────────

    def generate_all_project_keys(self, config: KnxSecureConfig, project) -> int:
        """Generiert alle fehlenden Projektschlüssel.

        Überschreibt keine bereits vorhandenen Schlüssel.
        Gibt die Anzahl neu generierter Schlüssel zurück.

        Schlüsselhierarchie (KNX Standard):
        - Backbone Key: einmal pro Projekt (KNX IP Secure Routing)
        - Group Key: einmal pro Projekt (Standard Runtime Key)
        - GA Keys: pro GA-Adresse (individuelle Runtime Keys)
        - Tool Key: pro Gerät (FDSK wird NICHT generiert – kommt vom Gerät)
        """
        count = 0

        if not config.backbone_key:
            config.backbone_key = generate_knx_key()
            count += 1

        if not config.group_key:
            config.group_key = generate_knx_key()
            count += 1

        # GA-spezifische Runtime Keys (ersetzt line_keys – kein KNX-Standard)
        for ga in project.group_addresses.all_addresses():
            addr = ga.address
            if addr and addr not in config.ga_keys:
                config.ga_keys[addr] = generate_knx_key()
                count += 1

        # Geräteschlüssel (Tool Key) – FDSK wird nicht generiert
        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.id not in config.device_infos:
                        dev_name = (device.product_name or device.product
                                    or device.physical_address)
                        info = DeviceSecureInfo(
                            device_id=device.id,
                            device_name=dev_name,
                            physical_address=device.physical_address,
                            line_id=line.id,
                            area_id=area.id,
                        )
                        config.device_infos[device.id] = info
                    existing = config.device_infos[device.id]
                    if not existing.tool_key:
                        existing.tool_key = generate_knx_key()
                        count += 1

        logger.info(f"KnxSecureService: {count} neue Schlüssel generiert.")
        return count

    def regenerate_key(self, config: KnxSecureConfig, key_type: str,
                       scope_id: str = "") -> str:
        """Regeneriert einen einzelnen Schlüssel. Gibt den neuen Schlüssel zurück."""
        new_key = generate_knx_key()
        if key_type == "backbone_key":
            config.backbone_key = new_key
        elif key_type == "group_key":
            config.group_key = new_key
        elif key_type == "ga_key":
            config.ga_keys[scope_id] = new_key
        elif key_type == "tool_key" and scope_id in config.device_infos:
            config.device_infos[scope_id].tool_key = new_key
        return new_key

    # ── GA-Sicherheits-Auto-Vorschlag (FA-2703) ───────────────────────────────

    def auto_suggest_ga_security(self, project) -> int:
        """Setzt GA-Security auf 'Ein' für sicherheitsrelevante GAs (FA-2703).

        Betrifft GAs mit Schlüsselwörtern in Bezeichnung oder Funktionsname:
        Schalten, Szenen, Zentralfunktionen, Sperren, Alarm.
        Gibt Anzahl geänderter GAs zurück.

        Gemäss KNX-Standard sind Mischanlagen (Secure + Non-Secure) erlaubt;
        es werden daher nur explizit sicherheitsrelevante GAs auf 'Ein' gesetzt.
        """
        changed = 0
        for ga in project.group_addresses.all_addresses():
            text = (
                (ga.designation or "") + " " +
                (ga.function_name or "") + " " +
                (ga.description or "")
            ).lower()
            if any(kw in text for kw in _SECURE_FUNCTION_KEYWORDS):
                if ga.security != "Ein":
                    ga.security = "Ein"
                    changed += 1
        logger.info(f"KnxSecureService: GA-Sicherheit gesetzt → {changed} GAs.")
        return changed

    def reset_ga_security_to_auto(self, project) -> int:
        """Setzt alle GAs auf 'Auto' zurück."""
        changed = sum(1 for ga in project.group_addresses.all_addresses()
                      if ga.security != "Auto")
        for ga in project.group_addresses.all_addresses():
            ga.security = "Auto"
        return changed

    # ── Gerätekompatibilität (FA-2704) ────────────────────────────────────────

    def update_device_compatibility(self, config: KnxSecureConfig, project,
                                    catalog=None) -> list[DeviceSecureInfo]:
        """Aktualisiert die Secure-Kompatibilitätsliste aus der Topologie.

        Falls ein Produktkatalog-Eintrag vorhanden ist (via material_list),
        wird dessen Secure-Flag übernommen.
        Gibt die vollständige Liste zurück.
        """
        # Materialliste: device_id → MaterialEntry
        mat_map = {}
        for entry in project.material_list.entries:
            if entry.device_id:
                mat_map[entry.device_id] = entry

        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    dev_name = (device.product_name or device.product
                                or device.physical_address)
                    if device.id not in config.device_infos:
                        config.device_infos[device.id] = DeviceSecureInfo(
                            device_id=device.id,
                            device_name=dev_name,
                            physical_address=device.physical_address,
                            line_id=line.id,
                            area_id=area.id,
                        )
                    info = config.device_infos[device.id]
                    info.device_name = dev_name
                    # Secure-Unterstützung aus Materialliste lesen
                    mat = mat_map.get(device.id)
                    if mat:
                        info.secure_supported = getattr(mat, "secure_supported", False)

        return list(config.device_infos.values())

    # ── Mischlinien-Prüfung (FA-2705) ─────────────────────────────────────────

    def check_mixed_lines(self, config: KnxSecureConfig, project) -> list[MixedLineWarning]:
        """Prüft alle Linien auf gemischte Secure/Non-Secure Besetzung (FA-2705).

        Eine Warnung wird erzeugt, wenn eine Linie sowohl Secure- als auch
        Non-Secure-fähige Geräte enthält.
        """
        warnings = []
        for area in project.topology.areas:
            for line in area.lines:
                secure_names = []
                non_secure_names = []
                for device in line.devices:
                    info = config.device_infos.get(device.id)
                    label = (device.product_name or device.product
                             or device.physical_address)
                    if info and info.secure_supported:
                        secure_names.append(label)
                    else:
                        non_secure_names.append(label)

                if secure_names and non_secure_names:
                    warnings.append(MixedLineWarning(
                        area_number=area.area_number,
                        line_number=line.line_number,
                        line_name=line.name or f"Linie {area.area_number}.{line.line_number}",
                        secure_devices=secure_names,
                        non_secure_devices=non_secure_names,
                    ))
        return warnings

    # ── Schlüsselverschlüsselung für .knxarr (FA-2706) ───────────────────────

    @staticmethod
    def encrypt_config(config: KnxSecureConfig, project_id: str) -> dict:
        """Verschlüsselt die Schlüssel für Speicherung im .knxarr-Format (AES-128).

        Verwendet Fernet (AES-128-CBC + HMAC) mit einem aus der project_id
        via PBKDF2-HMAC-SHA256 abgeleiteten Schlüssel (100 000 Iterationen).
        Der abgeleitete Schlüssel selbst wird NICHT gespeichert.

        Hinweis: Dies ist die lokale Dateiverschlüsselung für das .knxarr-Format.
        Die KNX-Bus-Kommunikation verwendet AES-128-CCM gemäss ISO 18033-3.
        """
        from cryptography.fernet import Fernet
        import base64, hashlib
        # PBKDF2 statt rohem SHA-256 – erschwert Brute-Force-Angriffe (Gap 6)
        raw = hashlib.pbkdf2_hmac(
            "sha256",
            project_id.encode("utf-8"),
            b"knxarr-secure-v2",
            100_000,
        )
        fernet_key = base64.urlsafe_b64encode(raw)
        f = Fernet(fernet_key)

        plaintext = json.dumps(config.to_dict()).encode("utf-8")
        return {
            "encrypted": True,
            "algorithm": "AES-128-Fernet-PBKDF2",
            "ciphertext": f.encrypt(plaintext).decode("ascii"),
        }

    @staticmethod
    def decrypt_config(blob: dict, project_id: str) -> KnxSecureConfig:
        """Entschlüsselt eine KnxSecureConfig aus dem .knxarr-Blob."""
        if not blob.get("encrypted"):
            return KnxSecureConfig.from_dict(blob)

        from cryptography.fernet import Fernet, InvalidToken
        import base64, hashlib

        algorithm = blob.get("algorithm", "AES-128-Fernet")
        if algorithm == "AES-128-Fernet-PBKDF2":
            raw = hashlib.pbkdf2_hmac(
                "sha256",
                project_id.encode("utf-8"),
                b"knxarr-secure-v2",
                100_000,
            )
        else:
            # Rückwärtskompatibilität mit altem SHA-256-Format
            raw = hashlib.sha256(f"knxarr-secure:{project_id}".encode()).digest()

        fernet_key = base64.urlsafe_b64encode(raw)
        f = Fernet(fernet_key)

        try:
            plaintext = f.decrypt(blob["ciphertext"].encode("ascii"))
            return KnxSecureConfig.from_dict(json.loads(plaintext))
        except (InvalidToken, Exception) as e:
            logger.error(f"KNX Secure: Entschlüsselung fehlgeschlagen: {e}")
            return KnxSecureConfig()

    # ── Statistik ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_summary(config: KnxSecureConfig, project) -> dict:
        """Gibt eine Zusammenfassung der KNX Secure-Konfiguration zurück."""
        all_gas = list(project.group_addresses.all_addresses())
        return {
            "enabled": config.enabled,
            "secure_mode": config.secure_mode,
            "backbone_key_set": bool(config.backbone_key),
            "group_key_set": bool(config.group_key),
            "ga_keys_count": len(config.ga_keys),
            "device_infos_count": len(config.device_infos),
            "secure_devices": sum(1 for d in config.device_infos.values() if d.secure_supported),
            "fdsk_entered": sum(1 for d in config.device_infos.values() if d.fdsk),
            "ga_security_on": sum(1 for ga in all_gas if ga.security == "Ein"),
            "ga_security_off": sum(1 for ga in all_gas if ga.security == "Aus"),
            "ga_security_auto": sum(1 for ga in all_gas if ga.security == "Auto"),
        }
