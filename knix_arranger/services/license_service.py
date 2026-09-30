"""
Offline-Lizenzpruefung (NFA-098) – RSA-signierte Lizenzdateien (.knxlic)
"""
from __future__ import annotations
import json
import os
import shutil
import logging
from datetime import datetime, date, timedelta
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
WARNING_DAYS = 7         # Hinweis erst ab 7 Tagen vor Ablauf
CLOCK_TOLERANCE_DAYS = 1 # Zeitzonen/kleine Uhrkorrekturen nicht als Rückstellung werten

# Zuletzt gesehenes Datum -- doppelt abgelegt (Datei + Registry), damit ein
# Zurückstellen der Systemuhr eine abgelaufene Lizenz nicht verlängert.
_LAST_SEEN_FILE = "usage.dat"
_REGISTRY_KEY = r"Software\KNiX Arranger"
_REGISTRY_VALUE = "LastSeen"

# Lizenznehmer der laufenden Sitzung (für Info-Dialog und Berichte)
_licensed_to = ""


def licensed_to() -> str:
    """Name des Lizenznehmers, sobald eine gültige Lizenz geprüft wurde."""
    return _licensed_to


def _read_registry_last_seen() -> str:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY) as key:
            return str(winreg.QueryValueEx(key, _REGISTRY_VALUE)[0])
    except (ImportError, OSError):
        return ""


def _write_registry_last_seen(value: str) -> None:
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY) as key:
            winreg.SetValueEx(key, _REGISTRY_VALUE, 0, winreg.REG_SZ, value)
    except (ImportError, OSError) as e:
        logger.debug(f"LastSeen nicht in Registry gespeichert: {e}")


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
        # Stichtag für den Ablauf: Systemdatum, aber nie vor dem zuletzt
        # gesehenen Datum (Schutz gegen zurückgestellte Uhr)
        self.today: date = date.today()

    def days_until_expiry(self) -> int | None:
        """Positive Zahl = noch gültig; negative = bereits abgelaufen."""
        if not self.expiry_date:
            return None
        try:
            expiry = datetime.strptime(self.expiry_date, "%Y-%m-%d").date()
            return (expiry - self.today).days
        except ValueError:
            return None

    def is_expired(self) -> bool:
        days = self.days_until_expiry()
        return days is not None and days < 0


# ── Lizenzschlüssel (Copy-Paste statt Datei) ───────────────────────────────────
# Ein Lizenzschlüssel ist die komplette signierte Lizenzdatei, kompakt als
# Base64url codiert und mit Präfix versehen. Die Signaturprüfung ist dieselbe
# wie bei der Datei -- ein veränderter Schlüssel wird abgelehnt.

LICENSE_KEY_PREFIX = "KNIX1-"


def encode_license_key(license_data: dict) -> str:
    """Macht aus dem Inhalt einer .knxlic-Datei einen kopierbaren Schlüssel."""
    raw = json.dumps(license_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return LICENSE_KEY_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_license_key(text: str) -> dict:
    """Liest einen eingefügten Lizenzschlüssel. Leerzeichen und Zeilenumbrüche
    (z.B. vom Kopieren aus einer E-Mail) werden ignoriert. ValueError, wenn der
    Text kein Lizenzschlüssel ist."""
    compact = "".join((text or "").split())
    if not compact.upper().startswith(LICENSE_KEY_PREFIX):
        raise ValueError("Der Text beginnt nicht mit «KNIX1-» und ist kein Lizenzschlüssel.")
    body = compact[len(LICENSE_KEY_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("Der Lizenzschlüssel ist unvollständig oder beschädigt. "
                         "Bitte den ganzen Block aus der E-Mail kopieren.") from None
    if not isinstance(data, dict) or "payload" not in data or "signature" not in data:
        raise ValueError("Der Lizenzschlüssel ist unvollständig oder beschädigt.")
    return data


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
        self._last_seen_file = os.path.join(APPDATA_DIR, _LAST_SEEN_FILE)

    # ── Zuletzt gesehenes Datum ────────────────────────────────────────────────

    def _last_seen(self) -> date | None:
        """Spätestes je gesehenes Datum aus Datei und Registry."""
        values = [_read_registry_last_seen()]
        try:
            with open(self._last_seen_file, "r", encoding="utf-8") as f:
                values.append(f.read().strip())
        except OSError:
            pass
        dates = []
        for v in values:
            try:
                dates.append(date.fromisoformat(v))
            except (TypeError, ValueError):
                pass
        return max(dates) if dates else None

    def _record_last_seen(self, today: date) -> None:
        last = self._last_seen()
        if last is not None and last >= today:
            return
        value = today.isoformat()
        try:
            os.makedirs(APPDATA_DIR, exist_ok=True)
            with open(self._last_seen_file, "w", encoding="utf-8") as f:
                f.write(value)
        except OSError as e:
            logger.debug(f"LastSeen nicht gespeichert: {e}")
        _write_registry_last_seen(value)

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

            last_seen = self._last_seen()
            clock_behind = (last_seen is not None and
                            info.today < last_seen - timedelta(days=CLOCK_TOLERANCE_DAYS))
            if last_seen is not None and last_seen > info.today:
                info.today = last_seen

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
                if clock_behind:
                    info.message += (
                        f". Das Systemdatum liegt vor dem zuletzt verwendeten Datum "
                        f"({last_seen.strftime('%d.%m.%Y')}) – bitte Datum und Uhrzeit prüfen."
                    )
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

    def import_license_key(self, text: str) -> LicenseInfo:
        """Prüft einen eingefügten Lizenzschlüssel und speichert ihn als
        Lizenzdatei -- gleiche Prüfung wie beim Import einer .knxlic-Datei."""
        info = LicenseInfo()
        try:
            data = decode_license_key(text)
        except ValueError as e:
            info.message = str(e)
            return info

        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".knxlic")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            info = self.import_license(tmp_path)
        finally:
            os.remove(tmp_path)
        return info

    def check_license(self) -> LicenseInfo:
        """Prüft die gespeicherte Lizenz und merkt sich den Lizenznehmer."""
        global _licensed_to
        info = self.validate_license_file(self._license_file)
        if info.is_valid:
            self._record_last_seen(date.today())
            _licensed_to = info.customer
        else:
            _licensed_to = ""
        return info

    # ── EULA-Akzeptanz (NFA-081) ───────────────────────────────────────────────

    def is_eula_accepted(self) -> bool:
        path = os.path.join(APPDATA_DIR, "eula_accepted.dat")
        return os.path.exists(path)

    def mark_eula_accepted(self):
        os.makedirs(APPDATA_DIR, exist_ok=True)
        path = os.path.join(APPDATA_DIR, "eula_accepted.dat")
        with open(path, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
