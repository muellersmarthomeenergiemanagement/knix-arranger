"""
Offline-Lizenzpruefung (NFA-098) – RSA-signierte Lizenzdateien (.knxlic)
"""
from __future__ import annotations
import json
import os
import shutil
import logging
from datetime import datetime, date
import base64

from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger("knix_arranger.license")

APPDATA_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "KNiX Arranger"
)

# RSA-2048 public key – privater Schlüssel liegt nur beim Entwickler
_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsks6fawVniZKM5pggLzG
zmk7sFP4Kr3FNsp8AA1hxYlifQ+3cDFo0JZvlUHj+UfQxZCyWmEMTuP6MOjpowx3
5wL9iEdY/xzi8Lh/c3qXjqVY1Uiu510z80mD8ZsQYY/StoNGbsx9W0VOBfCl5AWN
zhTn77IfDcPO/USQD3iloImRMM+85KSXKcWGnusEIgn0TnJIeVx08S9Or3rWkeu+
H+zUwW4RqBwUenPed2UwJlE9ZxCV0CQDgAVXV12joLwE/eGS+xN0CIrmIQWhx7Oz
FllaGkhBZsnzTYeVtHoIORiJmUbO4fJmgUnP0x1ON+NI0Qq+Uh6wkB8Vd0M51k+x
owIDAQAB
-----END PUBLIC KEY-----"""


GRACE_PERIOD_DAYS = 14   # App startet noch, tägl. Hinweis
WARNING_DAYS = 30        # Gelbe Warnung vor Ablauf


class LicenseInfo:
    """Lizenzinformationen."""

    def __init__(self):
        self.customer: str = ""
        self.email: str = ""
        self.license_type: str = ""   # "single", "annual", "trial"
        self.expiry_date: str = ""    # ISO-Format YYYY-MM-DD
        self.issued_date: str = ""
        self.is_valid: bool = False
        self.in_grace_period: bool = False   # abgelaufen aber noch innerhalb Kulanz
        self.warning: str = ""               # Hinweis für UI (leer = kein Hinweis)
        self.message: str = ""

    def days_until_expiry(self) -> int | None:
        """Positive Zahl = noch gültig; negative = bereits abgelaufen."""
        if not self.expiry_date:
            return None
        try:
            expiry = datetime.strptime(self.expiry_date, "%Y-%m-%d").date()
            return (expiry - date.today()).days
        except ValueError:
            return None

    def is_expired(self) -> bool:
        days = self.days_until_expiry()
        return days is not None and days < 0


class LicenseService:
    """
    Offline-Lizenzvalidierung via RSA-signierter Lizenzdatei (NFA-098).

    Lizenzdatei-Format (.knxlic):
        {
          "payload": {"customer": "...", "email": "...", "type": "...",
                      "expiry": "YYYY-MM-DD", "issued": "YYYY-MM-DD"},
          "signature": "<base64url RSA-PSS SHA-256>"
        }
    """

    def __init__(self):
        self._license_file = os.path.join(APPDATA_DIR, "license.knxlic")

    # ── Validierung ────────────────────────────────────────────────────────────

    def validate_license_file(self, path: str) -> LicenseInfo:
        """Prüft eine Lizenzdatei (.knxlic) auf Signatur und Ablauf."""
        info = LicenseInfo()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            payload = data["payload"]
            sig_b64 = data["signature"]

            # RSA-PSS Signaturprüfung
            public_key = serialization.load_pem_public_key(_PUBLIC_KEY_PEM)
            canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
            sig = base64.b64decode(sig_b64)
            public_key.verify(
                sig, canonical,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )

            info.customer = payload.get("customer", "")
            info.email = payload.get("email", "")
            info.license_type = payload.get("type", "single")
            info.expiry_date = payload.get("expiry", "")
            info.issued_date = payload.get("issued", "")

            days = info.days_until_expiry()

            if days is not None and days < 0:
                days_over = abs(days)
                if days_over <= GRACE_PERIOD_DAYS:
                    # Abgelaufen, aber innerhalb Kulanz
                    info.is_valid = True
                    info.in_grace_period = True
                    info.warning = (
                        f"Ihre Lizenz ist seit {days_over} Tag(en) abgelaufen. "
                        f"Die Anwendung startet noch {GRACE_PERIOD_DAYS - days_over} Tag(e). "
                        f"Bitte erneuern Sie Ihre Lizenz."
                    )
                    info.message = f"Lizenz abgelaufen (Kulanz bis {GRACE_PERIOD_DAYS - days_over} Tage)"
                else:
                    info.message = f"Lizenz abgelaufen am {info.expiry_date}"
                return info

            info.is_valid = True
            info.message = f"Lizenz gültig bis {info.expiry_date}"

            if days is not None and days <= WARNING_DAYS:
                info.warning = (
                    f"Ihre Lizenz läuft in {days} Tag(en) ab ({info.expiry_date}). "
                    f"Bitte erneuern Sie rechtzeitig."
                )

        except FileNotFoundError:
            info.message = "Keine Lizenzdatei gefunden"
        except InvalidSignature:
            info.message = "Ungültige Lizenzdatei (Signatur stimmt nicht)"
        except (json.JSONDecodeError, KeyError) as e:
            info.message = f"Lizenzdatei beschädigt ({e})"
        except Exception as e:
            logger.error(f"Lizenzfehler: {e}", exc_info=True)
            info.message = "Fehler beim Prüfen der Lizenz"

        return info

    def import_license(self, source_path: str) -> LicenseInfo:
        """Validiert und kopiert eine Lizenzdatei nach APPDATA."""
        info = self.validate_license_file(source_path)
        if info.is_valid:
            os.makedirs(APPDATA_DIR, exist_ok=True)
            shutil.copy2(source_path, self._license_file)
            logger.info(f"Lizenz importiert: {info.customer} ({info.license_type})")
        return info

    def check_license(self) -> LicenseInfo:
        """Prüft die gespeicherte Lizenz."""
        return self.validate_license_file(self._license_file)

    # ── EULA-Akzeptanz (NFA-081) ───────────────────────────────────────────────

    def is_eula_accepted(self) -> bool:
        path = os.path.join(APPDATA_DIR, "eula_accepted.dat")
        return os.path.exists(path)

    def mark_eula_accepted(self):
        os.makedirs(APPDATA_DIR, exist_ok=True)
        path = os.path.join(APPDATA_DIR, "eula_accepted.dat")
        with open(path, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
