"""
Produkt-Suche und Vorschlaege (FA-1303/1304, FA-1402/1403, FA-2303)
Lokale Produktdatenbank mit gaengigen KNX-Produkten.
"""
from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .knxprod_catalog_service import ComObjectInfo

logger = logging.getLogger("knix_arranger.product_search")


@dataclass
class ProductSuggestion:
    """Produktvorschlag für Aktoren/Sensoren/Infrastruktur."""
    manufacturer: str = ""
    order_number: str = ""
    product_name: str = ""
    channels: int = 0
    category: str = ""        # "actor", "sensor" oder "infrastructure"
    actor_type: str = ""      # z.B. "Schaltaktor", "Dimmaktor"
    sensor_type: str = ""     # z.B. "Taster 4-fach", "Präsenzmelder"
    device_type: str = ""     # Infrastruktur: "Linienkoppler", "Netzteil", etc.
    url: str = ""             # Hersteller-URL (optional)
    price_hint: str = ""      # Unverbindliche Preisangabe
    # ComObjects aus KNXPROD-Import (liste von dicts, kompatibel mit ComObjectInfo.to_dict())
    com_objects: list = field(default_factory=list)
    ga_min: int = 0           # Minimaler GA-Bedarf (Basis-ComObjects)
    ga_max: int = 0           # Maximaler GA-Bedarf (alle aktiven ComObjects)

    def display_type(self) -> str:
        """Gibt den anzuzeigenden Gerätetyp zurück (kategorie-unabhängig)."""
        return self.device_type or self.actor_type or self.sensor_type or "–"


class ProductSearchService:
    """Sucht passende KNX-Produkte aus lokaler Datenbank (FA-1303)."""

    def __init__(self):
        self._catalog: list[dict] = []
        self._load_catalog()

    def _load_catalog(self):
        """Lädt die lokale Produktdatenbank."""
        catalog_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "product_catalog.json",
        )
        if os.path.exists(catalog_path):
            with open(catalog_path, "r", encoding="utf-8") as f:
                self._catalog = json.load(f).get("products", [])
            logger.info(f"Produktkatalog geladen: {len(self._catalog)} Produkte")
        else:
            logger.warning(f"Produktkatalog nicht gefunden: {catalog_path}")

    def search_actors(self, actor_type: str,
                      preferred_manufacturers: list[str] | None = None,
                      min_channels: int = 1) -> list[ProductSuggestion]:
        """
        Sucht passende Aktoren (FA-1303).

        Bevorzugte Hersteller werden zuerst angezeigt (FA-1304).
        """
        results = []
        for prod in self._catalog:
            if prod.get("category") != "actor":
                continue
            if actor_type and actor_type.lower() not in prod.get("actor_type", "").lower():
                continue
            if prod.get("channels", 0) < min_channels:
                continue

            results.append(ProductSuggestion(
                manufacturer=prod.get("manufacturer", ""),
                order_number=prod.get("order_number", ""),
                product_name=prod.get("product_name", ""),
                channels=prod.get("channels", 0),
                category="actor",
                actor_type=prod.get("actor_type", ""),
                url=prod.get("url", ""),
                price_hint=prod.get("price_hint", ""),
                com_objects=prod.get("com_objects", []),
                ga_min=prod.get("ga_min", 0),
                ga_max=prod.get("ga_max", 0),
            ))

        # Bevorzugte Hersteller zuerst (FA-1304)
        if preferred_manufacturers:
            pref_lower = [m.lower() for m in preferred_manufacturers]
            results.sort(
                key=lambda p: (
                    0 if p.manufacturer.lower() in pref_lower else 1,
                    p.manufacturer,
                    p.channels,
                )
            )

        return results

    def search_sensors(self, sensor_type: str,
                       preferred_manufacturers: list[str] | None = None) -> list[ProductSuggestion]:
        """
        Sucht passende Sensoren (FA-1402).

        Bevorzugte Hersteller werden zuerst angezeigt (FA-1403).
        """
        results = []
        for prod in self._catalog:
            if prod.get("category") != "sensor":
                continue
            if sensor_type and sensor_type.lower() not in prod.get("sensor_type", "").lower():
                continue

            results.append(ProductSuggestion(
                manufacturer=prod.get("manufacturer", ""),
                order_number=prod.get("order_number", ""),
                product_name=prod.get("product_name", ""),
                channels=prod.get("channels", 0),
                category="sensor",
                sensor_type=prod.get("sensor_type", ""),
                url=prod.get("url", ""),
                price_hint=prod.get("price_hint", ""),
                com_objects=prod.get("com_objects", []),
                ga_min=prod.get("ga_min", 0),
                ga_max=prod.get("ga_max", 0),
            ))

        if preferred_manufacturers:
            pref_lower = [m.lower() for m in preferred_manufacturers]
            results.sort(
                key=lambda p: (
                    0 if p.manufacturer.lower() in pref_lower else 1,
                    p.manufacturer,
                )
            )

        return results

    def search_infrastructure(
        self,
        device_type: str = "",
        preferred_manufacturers: list[str] | None = None,
    ) -> list[ProductSuggestion]:
        """
        Sucht Infrastruktur-Geräte (Koppler, Netzteile, Gateways) (FA-2303).
        """
        results = []
        for prod in self._catalog:
            if prod.get("category") != "infrastructure":
                continue
            if device_type and device_type.lower() not in prod.get("device_type", "").lower():
                continue

            results.append(ProductSuggestion(
                manufacturer=prod.get("manufacturer", ""),
                order_number=prod.get("order_number", ""),
                product_name=prod.get("product_name", ""),
                channels=prod.get("channels", 0),
                category="infrastructure",
                device_type=prod.get("device_type", ""),
                url=prod.get("url", ""),
                price_hint=prod.get("price_hint", ""),
                com_objects=prod.get("com_objects", []),
                ga_min=prod.get("ga_min", 0),
                ga_max=prod.get("ga_max", 0),
            ))

        if preferred_manufacturers:
            pref_lower = [m.lower() for m in preferred_manufacturers]
            results.sort(
                key=lambda p: (
                    0 if p.manufacturer.lower() in pref_lower else 1,
                    p.manufacturer,
                    p.device_type,
                )
            )

        return results

    def search_all(
        self,
        query: str = "",
        category_filter: str = "",
        preferred_manufacturers: list[str] | None = None,
    ) -> list[ProductSuggestion]:
        """
        Sucht über alle Kategorien (FA-2303).

        Args:
            query: Freitextsuche über Produktname und Bestellnummer.
            category_filter: "actor", "sensor", "infrastructure" oder "" für alle.
        """
        results = []
        q = query.lower()

        for prod in self._catalog:
            cat = prod.get("category", "")
            if category_filter and cat != category_filter:
                continue

            name_hit = not q or q in prod.get("product_name", "").lower()
            num_hit = not q or q in prod.get("order_number", "").lower()
            type_hit = (
                not q
                or q in prod.get("actor_type", "").lower()
                or q in prod.get("sensor_type", "").lower()
                or q in prod.get("device_type", "").lower()
            )
            manu_hit = not q or q in prod.get("manufacturer", "").lower()

            if not (name_hit or num_hit or type_hit or manu_hit):
                continue

            results.append(ProductSuggestion(
                manufacturer=prod.get("manufacturer", ""),
                order_number=prod.get("order_number", ""),
                product_name=prod.get("product_name", ""),
                channels=prod.get("channels", 0),
                category=cat,
                actor_type=prod.get("actor_type", ""),
                sensor_type=prod.get("sensor_type", ""),
                device_type=prod.get("device_type", ""),
                url=prod.get("url", ""),
                price_hint=prod.get("price_hint", ""),
                com_objects=prod.get("com_objects", []),
                ga_min=prod.get("ga_min", 0),
                ga_max=prod.get("ga_max", 0),
            ))

        if preferred_manufacturers:
            pref_lower = [m.lower() for m in preferred_manufacturers]
            results.sort(
                key=lambda p: (
                    0 if p.manufacturer.lower() in pref_lower else 1,
                    p.manufacturer,
                )
            )

        return results

    def known_manufacturers(self) -> list[str]:
        """Gibt alle im Katalog vorhandenen Hersteller zurück."""
        seen: set[str] = set()
        result: list[str] = []
        for prod in self._catalog:
            m = prod.get("manufacturer", "")
            if m and m not in seen:
                seen.add(m)
                result.append(m)
        return sorted(result)

    def known_device_types(self, category: str = "") -> list[str]:
        """Gibt alle im Katalog vorhandenen Gerätetypen zurück."""
        seen: set[str] = set()
        result: list[str] = []
        for prod in self._catalog:
            if category and prod.get("category") != category:
                continue
            t = (prod.get("device_type")
                 or prod.get("actor_type")
                 or prod.get("sensor_type", ""))
            if t and t not in seen:
                seen.add(t)
                result.append(t)
        return sorted(result)

    def add_product(self, product: dict):
        """Fügt ein Produkt zum Laufzeit-Katalog hinzu (z.B. aus KNXPROD-Import)."""
        self._catalog.append(product)

    def search_online(self, query: str) -> list[ProductSuggestion]:
        """
        Placeholder für zukuenftige Online-Suche.

        In einer spaeteren Version kann hier eine API-Anbindung
        an Herstellerkataloge implementiert werden.
        """
        raise NotImplementedError(
            "Online-Produktsuche ist für eine spaetere Version vorgesehen. "
            "Verwenden Sie die lokale Produktdatenbank."
        )
