"""
Online-Produktkatalog (FA-1303, FA-1402)

Laedt eine gepflegte Produktliste aus dem oeffentlichen Release-Repository
auf GitHub und legt sie als Zwischenspeicher unter %APPDATA% ab. Der
ProductSearchService fuehrt den Zwischenspeicher mit der mitgelieferten
Basis-Datenbank und den nutzereigenen KNXPROD-Importen zusammen - die
Vorschlaege stehen damit auch ohne Internetverbindung zur Verfuegung,
sobald der Katalog einmal geladen wurde.

Dateiformat (gleiche Produktfelder wie data/product_catalog.json):
    {"updated": "2026-09-23", "products": [{"category": "actor", ...}, ...]}
"""
from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("knix_arranger.online_catalog")

ONLINE_CATALOG_URL = (
    "https://raw.githubusercontent.com/muellersmarthomeenergiemanagement/"
    "knix-arranger-releases/main/product_catalog_online.json"
)

VALID_CATEGORIES = ("actor", "sensor", "infrastructure")


def online_cache_path() -> str:
    """Zwischenspeicher des Online-Katalogs (neben product_catalog_user.json)."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    data_dir = os.path.join(appdata, "KNiX Arranger")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "product_catalog_online.json")


@dataclass
class OnlineCatalogResult:
    """Ergebnis eines Downloads des Online-Katalogs."""
    products: list[dict] = field(default_factory=list)
    updated: str = ""       # Stand laut Katalogdatei (vom Pfleger gesetzt)
    fetched_at: str = ""    # Zeitpunkt des Downloads (ISO)
    skipped: int = 0        # ungueltige Eintraege, die verworfen wurden
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def validate_products(raw: object) -> tuple[list[dict], int]:
    """Prueft die Produktliste und verwirft unbrauchbare Eintraege.

    Pflichtfelder: manufacturer, order_number und eine gueltige category.
    Gibt (gueltige Produkte, Anzahl verworfener Eintraege) zurueck.
    """
    if not isinstance(raw, list):
        return [], 0
    valid: list[dict] = []
    skipped = 0
    for prod in raw:
        if (
            isinstance(prod, dict)
            and str(prod.get("manufacturer", "")).strip()
            and str(prod.get("order_number", "")).strip()
            and prod.get("category") in VALID_CATEGORIES
        ):
            valid.append(prod)
        else:
            skipped += 1
    return valid, skipped


class OnlineCatalogService:
    """Download und Zwischenspeicher des Online-Produktkatalogs."""

    def __init__(self, url: str = ONLINE_CATALOG_URL, cache_path: str | None = None):
        self._url = url
        self._cache_path = cache_path or online_cache_path()

    def fetch(self, timeout: float = 10.0) -> OnlineCatalogResult:
        """Laedt den Katalog herunter und aktualisiert den Zwischenspeicher.

        Bei einem Fehler bleibt der bisherige Zwischenspeicher unveraendert.
        """
        result = OnlineCatalogResult()
        try:
            req = Request(self._url, headers={"User-Agent": "KNiXArranger"})
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            result.error = f"Der Online-Katalog ist zurzeit nicht verfügbar (HTTP {e.code})."
        except URLError as e:
            result.error = f"Server nicht erreichbar: {e.reason}"
        except (json.JSONDecodeError, UnicodeDecodeError):
            result.error = "Der Online-Katalog hat ein ungültiges Format."
        except Exception as e:  # z.B. Timeout
            result.error = f"Download fehlgeschlagen: {e}"
        if result.error:
            logger.warning(f"Online-Katalog: {result.error}")
            return result

        if not isinstance(data, dict):
            result.error = "Der Online-Katalog hat ein ungültiges Format."
            return result

        result.products, result.skipped = validate_products(data.get("products"))
        result.updated = str(data.get("updated", ""))
        result.fetched_at = datetime.now().isoformat(timespec="seconds")
        self._write_cache(result)
        logger.info(
            f"Online-Katalog geladen: {len(result.products)} Produkte "
            f"(Stand {result.updated or 'unbekannt'}, {result.skipped} verworfen)"
        )
        return result

    def load_cached(self) -> OnlineCatalogResult:
        """Liest den Zwischenspeicher (leeres Ergebnis, falls nicht vorhanden)."""
        result = OnlineCatalogResult()
        if not os.path.exists(self._cache_path):
            return result
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Zwischenspeicher des Online-Katalogs unlesbar: {e}")
            return result
        if not isinstance(data, dict):
            return result
        result.products, result.skipped = validate_products(data.get("products"))
        result.updated = str(data.get("updated", ""))
        result.fetched_at = str(data.get("fetched_at", ""))
        return result

    def _write_cache(self, result: OnlineCatalogResult) -> None:
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "updated": result.updated,
                        "fetched_at": result.fetched_at,
                        "products": result.products,
                    },
                    f, ensure_ascii=False, indent=2,
                )
        except OSError as e:
            logger.error(f"Online-Katalog konnte nicht gespeichert werden: {e}")
