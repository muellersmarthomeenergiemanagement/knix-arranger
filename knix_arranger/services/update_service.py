"""
Update-Pruefung (NFA-111 bis NFA-115)
Prüft ob eine neuere Version verfuegbar ist.

Server: GitHub Releases API
  URL-Format: https://api.github.com/repos/<USER>/<REPO>/releases/latest
  Alternativ: eigene version.json mit {"latest_version":…, "download_url":…, "changelog":…}
"""
from __future__ import annotations
import logging
import json
from dataclasses import dataclass
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger("knix_arranger.update")

# GitHub Releases API – hier GitHub-Benutzername und Repository-Name einsetzen:
#   https://github.com/<USER>/<REPO>/releases
# Beispiel: "https://api.github.com/repos/mmueller-smarthome/knix-arranger/releases/latest"
DEFAULT_UPDATE_URL = "https://api.github.com/repos/muellersmarthomeenergiemanagement/knix-arranger/releases/latest"


@dataclass
class UpdateInfo:
    """Ergebnis der Update-Pruefung (NFA-113)."""
    available: bool = False
    latest_version: str = ""
    current_version: str = ""
    download_url: str = ""
    changelog: str = ""
    error: str = ""


class UpdateService:
    """Prüft auf verfügbare Updates (NFA-111).

    Unterstuetzt zwei Server-Formate:
    1. GitHub Releases API  (empfohlen)
    2. Eigene version.json  {"latest_version": "1.2.0", "download_url": "...", "changelog": "..."}
    """

    def __init__(self, update_url: str = DEFAULT_UPDATE_URL):
        self._update_url = update_url

    def check_for_updates(self, current_version: str,
                          timeout: float = 5.0) -> UpdateInfo:
        """Prüft ob eine neuere Version verfuegbar ist (NFA-112, NFA-115)."""
        info = UpdateInfo(current_version=current_version)

        if "GITHUB_USER" in self._update_url or "GITHUB_REPO" in self._update_url:
            info.error = "Update-URL nicht konfiguriert (GITHUB_USER/GITHUB_REPO)"
            logger.warning(info.error)
            return info

        try:
            req = Request(
                self._update_url,
                headers={
                    "User-Agent": f"KNiXArranger/{current_version}",
                    "Accept": "application/vnd.github+json",
                },
            )
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            self._parse_response(data, info)

            if info.latest_version and self._is_newer(info.latest_version, current_version):
                info.available = True
                logger.info(
                    f"Update verfuegbar: {info.latest_version} "
                    f"(aktuell: {current_version})"
                )
            else:
                logger.info(f"Kein Update verfuegbar (aktuell: {current_version})")

        except URLError as e:
            info.error = f"Server nicht erreichbar: {e.reason}"
            logger.warning(f"Update-Pruefung fehlgeschlagen: {info.error}")
        except (json.JSONDecodeError, KeyError) as e:
            info.error = f"Ungültiges Antwortformat: {e}"
            logger.warning(f"Update-Pruefung fehlgeschlagen: {info.error}")
        except Exception as e:
            info.error = str(e)
            logger.warning(f"Update-Pruefung fehlgeschlagen: {info.error}")

        return info

    def _parse_response(self, data: dict, info: UpdateInfo) -> None:
        """Erkennt automatisch GitHub API- oder einfaches JSON-Format."""
        if "tag_name" in data:
            self._parse_github_release(data, info)
        else:
            self._parse_simple_json(data, info)

    def _parse_github_release(self, data: dict, info: UpdateInfo) -> None:
        """Parst eine GitHub Releases API-Antwort."""
        # "v1.2.0" → "1.2.0"
        tag = data.get("tag_name", "").lstrip("v")
        info.latest_version = tag
        info.changelog = data.get("body", "")

        # Ersten .exe-Asset als Download-URL nehmen
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".exe"):
                info.download_url = asset.get("browser_download_url", "")
                break

        # Fallback: GitHub Release-Seite
        if not info.download_url:
            info.download_url = data.get("html_url", "")

    def _parse_simple_json(self, data: dict, info: UpdateInfo) -> None:
        """Parst ein einfaches version.json-Format."""
        info.latest_version = data.get("latest_version", "")
        info.download_url = data.get("download_url", "")
        info.changelog = data.get("changelog", "")

    @staticmethod
    def _is_newer(latest: str, current: str) -> bool:
        """Vergleicht Versionsnummern (semver-aehnlich)."""
        try:
            latest_parts = [int(x) for x in latest.split(".")]
            current_parts = [int(x) for x in current.split(".")]
            while len(latest_parts) < 3:
                latest_parts.append(0)
            while len(current_parts) < 3:
                current_parts.append(0)
            return tuple(latest_parts) > tuple(current_parts)
        except (ValueError, AttributeError):
            return False
