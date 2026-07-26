"""
KnxSecureService – Verwaltung des KNX-Secure-Archivs (FA-2701, FA-2703–2706, überarbeitet).

Verantwortlich für:
- Auto-Vorschlag GA-Sicherheitsmodi (FA-2703)
- Gerätekompatibilitätsliste aus KNXPROD-Daten (FA-2704)
- Mischlinien-Prüfung (FA-2705)
- Passwortbasierte Verschlüsselung der sensiblen Archivfelder: FDSK je Gerät,
  ETS6-Projektpasswort, Notiz (FA-2706)

KNiX Arranger generiert und verwaltet KEINE KNX-Secure-Laufzeitschlüssel
(Backbone/Group/GA/Tool Key) -- diese werden ausschliesslich von ETS6 aus dem
geräteindividuellen Zertifikat (FDSK) abgeleitet und sind KNiX Arranger nicht
bekannt. Siehe models/knx_secure.py für die Begründung.
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass

from ..models.knx_secure import KnxSecureConfig, DeviceSecureInfo

logger = logging.getLogger("knix_arranger.knx_secure")

# Funktionsnamen, die automatisch als "Ein" vorgeschlagen werden (FA-2703)
_SECURE_FUNCTION_KEYWORDS = frozenset([
    "schalten", "szene", "zentral", "sperren", "on_off", "switch",
    "scene", "central", "lock", "alarm", "notaus", "emergency",
])

_PBKDF2_ITERATIONS = 100_000


class KnxSecureWrongPassword(Exception):
    """Das Master-Passwort für das Zugangsdaten-Archiv ist falsch."""


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

    # ── Passwortbasierte Verschlüsselung des Zugangsdaten-Archivs (FA-2706) ──
    #
    # Nur die tatsächlich sensiblen Werte werden verschlüsselt: FDSK je Gerät,
    # ETS6-Projektpasswort und die zugehörige Notiz. Gerätestruktur und
    # secure_supported bleiben im Klartext, da sie keine Geheimnisse sind
    # (Herstellerdaten) und sonst z.B. die Mischlinien-Prüfung ohne Passwort-
    # Eingabe unmöglich wäre.
    #
    # Das Master-Passwort wird selbst gewählt (vom Planer, wie bei einem
    # Passwort-Manager-Tresor) und NICHT im Projekt gespeichert. Geht es
    # verloren, sind die verschlüsselten Werte nicht wiederherstellbar.

    @staticmethod
    def _derive_fernet_key(password: str, salt: bytes) -> bytes:
        raw = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
        )
        return base64.urlsafe_b64encode(raw)

    @staticmethod
    def encrypt_config(config: KnxSecureConfig, password: str) -> dict:
        """Serialisiert die Config; FDSK/Projektpasswort/Notiz werden mit einem
        aus `password` abgeleiteten AES-128-Schlüssel (Fernet, PBKDF2-HMAC-
        SHA256, 100 000 Iterationen, zufälliges Salt) verschlüsselt."""
        from cryptography.fernet import Fernet

        sensitive = {
            "ets_project_password": config.ets_project_password,
            "ets_password_note": config.ets_password_note,
            "fdsk": {
                dev_id: info.fdsk
                for dev_id, info in config.device_infos.items() if info.fdsk
            },
        }
        salt = os.urandom(16)
        f = Fernet(KnxSecureService._derive_fernet_key(password, salt))
        ciphertext = f.encrypt(json.dumps(sensitive).encode("utf-8"))

        data = config.to_dict()
        data["ets_project_password"] = ""
        data["ets_password_note"] = ""
        for dev in data["device_infos"].values():
            dev["fdsk"] = ""
        data["secure_blob"] = {
            "algorithm": "AES-128-Fernet-PBKDF2",
            "salt": base64.b64encode(salt).decode("ascii"),
            "ciphertext": ciphertext.decode("ascii"),
        }
        return data

    @staticmethod
    def decrypt_config(data: dict, password: str) -> KnxSecureConfig:
        """Lädt eine KnxSecureConfig aus `data` und entschlüsselt die sensiblen
        Felder mit `password`. Wirft KnxSecureWrongPassword bei falschem
        Passwort oder beschädigtem Archiv."""
        config = KnxSecureConfig.from_dict(data)
        blob = data.get("secure_blob")
        if not blob:
            return config

        from cryptography.fernet import Fernet, InvalidToken

        salt = base64.b64decode(blob["salt"])
        f = Fernet(KnxSecureService._derive_fernet_key(password, salt))
        try:
            plaintext = f.decrypt(blob["ciphertext"].encode("ascii"))
        except InvalidToken as exc:
            raise KnxSecureWrongPassword() from exc

        sensitive = json.loads(plaintext)
        config.ets_project_password = sensitive.get("ets_project_password", "")
        config.ets_password_note = sensitive.get("ets_password_note", "")
        for dev_id, fdsk in sensitive.get("fdsk", {}).items():
            if dev_id in config.device_infos:
                config.device_infos[dev_id].fdsk = fdsk
        return config

    @staticmethod
    def unlock(config: KnxSecureConfig, password: str) -> KnxSecureConfig:
        """Entsperrt eine Config: setzt entweder erstmalig ein neues
        Master-Passwort (falls noch kein Archiv verschlüsselt war) oder
        entschlüsselt ein bestehendes Archiv. Wirft KnxSecureWrongPassword
        bei falschem Passwort. Gibt die (ggf. neue) entsperrte Config zurück."""
        if config._locked_blob is None:
            config._session_password = password
            return config
        unlocked = KnxSecureService.decrypt_config(config._locked_blob, password)
        unlocked._session_password = password
        unlocked._locked_blob = None
        return unlocked

    # ── Statistik ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_summary(config: KnxSecureConfig, project) -> dict:
        """Gibt eine Zusammenfassung der KNX Secure-Konfiguration zurück."""
        all_gas = list(project.group_addresses.all_addresses())
        return {
            "enabled": config.enabled,
            "secure_mode": config.secure_mode,
            "locked": config.is_locked,
            "ets_password_set": bool(config.ets_project_password),
            "device_infos_count": len(config.device_infos),
            "secure_devices": sum(1 for d in config.device_infos.values() if d.secure_supported),
            "fdsk_entered": sum(1 for d in config.device_infos.values() if d.fdsk),
            "ga_security_on": sum(1 for ga in all_gas if ga.security == "Ein"),
            "ga_security_off": sum(1 for ga in all_gas if ga.security == "Aus"),
            "ga_security_auto": sum(1 for ga in all_gas if ga.security == "Auto"),
        }
