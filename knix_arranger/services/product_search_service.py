"""
Produkt-Suche und Vorschlaege (FA-1303/1304, FA-1402/1403, FA-2303)
Lokale Produktdatenbank mit gaengigen KNX-Produkten, ergaenzt um den
Online-Katalog (siehe online_catalog_service) und nutzereigene KNXPROD-Importe.
"""
from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..utils.manufacturers import (
    canonicalize_product, manufacturer_display_name, normalize_order_number, product_key,
)

if TYPE_CHECKING:
    from .knxprod_catalog_service import ComObjectInfo

logger = logging.getLogger("knix_arranger.product_search")


def _user_catalog_path() -> str:
    """Pfad zur nutzereigenen Katalog-Erweiterung (persistiert KNXPROD-Importe).

    Liegt unter %APPDATA%, nicht im Installationsordner der App (dort läge
    die mitgelieferte Basis-Datenbank) -- Importe überleben so App-Updates
    und Neuinstallationen, und stehen projektübergreifend in jedem Projekt
    zur Verfügung (FA-2304).
    """
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    data_dir = os.path.join(appdata, "KNiX Arranger")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "product_catalog_user.json")


@dataclass
class ProductSuggestion:
    """Produktvorschlag für Aktoren/Sensoren/Infrastruktur."""
    manufacturer: str = ""
    manufacturer_id: str = ""  # KNX-Hersteller-ID "M-XXXX" ("" = unbekannt)
    # ETS-Kennungen aus dem KNXPROD-Import ("" = unbekannt, z.B. aeltere
    # Katalogeintraege vor dem Neuimport)
    product_ref_id: str = ""
    hw2prog_id: str = ""
    application_program_id: str = ""
    secure_supported: bool = False   # KNX Secure-faehig (FA-2705)
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
    # Bestellnummer des Nachfolgeprodukts (gleicher Hersteller), falls dieses
    # Produkt manuell als veraltet markiert wurde ("" = aktuell/nicht markiert)
    superseded_by: str = ""
    # True, wenn der Eintrag aus dem Online-Katalog stammt (FA-1303/1402)
    online: bool = False

    def display_type(self) -> str:
        """Gibt den anzuzeigenden Gerätetyp zurück (kategorie-unabhängig)."""
        return self.device_type or self.actor_type or self.sensor_type or "–"


class ProductSearchService:
    """Sucht passende KNX-Produkte aus lokaler Datenbank (FA-1303)."""

    def __init__(self, online_service=None):
        from .online_catalog_service import OnlineCatalogService
        self._catalog: list[dict] = []
        self._user_products: list[dict] = []  # nur Nutzer-Importe, für Persistenz
        self._online = online_service or OnlineCatalogService()
        self._online_keys: set[tuple[str, str]] = set()
        self._load_catalog()

    def _load_catalog(self):
        """Lädt die mitgelieferte Basis-Produktdatenbank, den zwischengespeicherten
        Online-Katalog und die nutzereigene Katalog-Erweiterung (persistierte
        KNXPROD-Importe, siehe add_product/add_products) und führt sie in dieser
        Reihenfolge zusammen -- spätere Quellen überschreiben frühere bei
        gleichem (Hersteller, Bestellnummer)."""
        catalog_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "product_catalog.json",
        )
        if os.path.exists(catalog_path):
            with open(catalog_path, "r", encoding="utf-8") as f:
                self._catalog = [
                    canonicalize_product(p) for p in json.load(f).get("products", [])
                ]
            logger.info(f"Produktkatalog geladen: {len(self._catalog)} Produkte")
        else:
            logger.warning(f"Produktkatalog nicht gefunden: {catalog_path}")

        self._merge_online(self._online.load_cached().products)

        user_path = _user_catalog_path()
        if os.path.exists(user_path):
            try:
                with open(user_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f).get("products", [])
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Nutzereigener Produktkatalog konnte nicht gelesen werden: {e}")
                loaded = []
            # Aeltere Importe tragen den Hersteller in verschiedenen
            # Schreibweisen ("ABB" / "ABB AG - STOTZ-KONTAKT"): beim
            # Vereinheitlichen fallen solche Dubletten zusammen.
            self._user_products = []
            for prod in loaded:
                self._upsert(self._user_products, canonicalize_product(prod))
            for prod in self._user_products:
                self._upsert(self._catalog, prod)
                self._online_keys.discard(self._key(prod))
            if self._user_products:
                logger.info(f"Nutzereigener Produktkatalog geladen: {len(self._user_products)} Produkte")

    @staticmethod
    def _key(product: dict) -> tuple[str, str]:
        return product_key(
            product.get("manufacturer", ""), product.get("order_number", ""),
            product.get("product_name", ""),
        )

    def _merge_online(self, products: list[dict]) -> None:
        """Übernimmt Online-Produkte in den Katalog. Eigene Importe des Nutzers
        mit gleichem Schlüssel haben Vorrang und bleiben unverändert."""
        user_keys = {self._key(p) for p in self._user_products}
        for prod in products:
            prod = canonicalize_product(dict(prod))
            key = self._key(prod)
            if key in user_keys:
                continue
            self._upsert(self._catalog, prod)
            self._online_keys.add(key)

    def _is_online(self, prod: dict) -> bool:
        return self._key(prod) in self._online_keys

    @staticmethod
    def _upsert(target: list[dict], product: dict) -> None:
        """Fügt product zu target hinzu, oder ersetzt einen bestehenden Eintrag
        mit gleichem (manufacturer, order_number) -- verhindert Duplikate bei
        wiederholtem Import derselben KNXPROD-Datei."""
        key = ProductSearchService._key(product)
        for i, existing in enumerate(target):
            if ProductSearchService._key(existing) == key:
                target[i] = product
                return
        target.append(product)

    def _save_user_catalog(self) -> None:
        path = _user_catalog_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"products": self._user_products}, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"Nutzereigener Produktkatalog konnte nicht gespeichert werden: {e}")

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
                manufacturer_id=prod.get("manufacturer_id", ""),
                product_ref_id=prod.get("product_ref_id", ""),
                hw2prog_id=prod.get("hw2prog_id", ""),
                application_program_id=prod.get("application_program_id", ""),
                secure_supported=prod.get("secure_supported", False),
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
                superseded_by=prod.get("superseded_by", ""),
                online=self._is_online(prod),
            ))

        # Bevorzugte Hersteller zuerst (FA-1304)
        if preferred_manufacturers:
            pref_lower = [manufacturer_display_name(m).lower() for m in preferred_manufacturers]
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
                manufacturer_id=prod.get("manufacturer_id", ""),
                product_ref_id=prod.get("product_ref_id", ""),
                hw2prog_id=prod.get("hw2prog_id", ""),
                application_program_id=prod.get("application_program_id", ""),
                secure_supported=prod.get("secure_supported", False),
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
                superseded_by=prod.get("superseded_by", ""),
                online=self._is_online(prod),
            ))

        if preferred_manufacturers:
            pref_lower = [manufacturer_display_name(m).lower() for m in preferred_manufacturers]
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
                manufacturer_id=prod.get("manufacturer_id", ""),
                product_ref_id=prod.get("product_ref_id", ""),
                hw2prog_id=prod.get("hw2prog_id", ""),
                application_program_id=prod.get("application_program_id", ""),
                secure_supported=prod.get("secure_supported", False),
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
                superseded_by=prod.get("superseded_by", ""),
                online=self._is_online(prod),
            ))

        if preferred_manufacturers:
            pref_lower = [manufacturer_display_name(m).lower() for m in preferred_manufacturers]
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
        q_order = normalize_order_number(query)

        for prod in self._catalog:
            cat = prod.get("category", "")
            if category_filter and cat != category_filter:
                continue

            name_hit = not q or q in prod.get("product_name", "").lower()
            num_hit = (
                not q
                or q in prod.get("order_number", "").lower()
                or bool(q_order) and q_order in normalize_order_number(prod.get("order_number", ""))
            )
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
                manufacturer_id=prod.get("manufacturer_id", ""),
                product_ref_id=prod.get("product_ref_id", ""),
                hw2prog_id=prod.get("hw2prog_id", ""),
                application_program_id=prod.get("application_program_id", ""),
                secure_supported=prod.get("secure_supported", False),
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
                superseded_by=prod.get("superseded_by", ""),
                online=self._is_online(prod),
            ))

        if preferred_manufacturers:
            pref_lower = [manufacturer_display_name(m).lower() for m in preferred_manufacturers]
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
        """Fügt ein Produkt zum Katalog hinzu (z.B. aus KNXPROD-Import) und
        persistiert es dauerhaft (%APPDATA%/KNiX Arranger/product_catalog_user.json) --
        steht damit nach App-Neustart und in jedem Projekt zur Verfügung.
        Für mehrere Produkte auf einmal: add_products() (ein Schreibvorgang
        statt einem pro Produkt)."""
        product = canonicalize_product(product)
        self._upsert(self._catalog, product)
        self._upsert(self._user_products, product)
        self._online_keys.discard(self._key(product))
        self._save_user_catalog()

    def add_products(self, products: list[dict]) -> None:
        """Wie add_product(), aber für mehrere Produkte in einem Rutsch --
        ein einziger Schreibvorgang statt einem pro Produkt (z.B. beim
        Import einer KNXPROD-Datei mit hunderten Produkten)."""
        for product in products:
            product = canonicalize_product(product)
            self._upsert(self._catalog, product)
            self._upsert(self._user_products, product)
            self._online_keys.discard(self._key(product))
        if products:
            self._save_user_catalog()

    ETS_ID_FIELDS = ("manufacturer_id", "product_ref_id", "hw2prog_id", "application_program_id")

    def fill_ets_ids(self, products: list[dict]) -> int:
        """Ergaenzt bei vorhandenen eigenen Katalogeintraegen nur die
        ETS-Kennungen aus frisch gelesenen KNXPROD-Produkten (gleicher
        Hersteller/Bestellnummer). Alles andere bleibt unveraendert (z.B.
        "veraltet"-Markierung, Preis, URL). Gibt die Anzahl ergaenzter
        Eintraege zurueck."""
        ids_by_key = {}
        for p in products:
            p = canonicalize_product(dict(p))
            ids_by_key[self._key(p)] = {f: p.get(f, "") for f in self.ETS_ID_FIELDS}
        filled = 0
        for target in (self._user_products, self._catalog):
            for prod in target:
                ids = ids_by_key.get(self._key(prod))
                if not ids:
                    continue
                changed = False
                for field_name, value in ids.items():
                    if value and not prod.get(field_name):
                        prod[field_name] = value
                        changed = True
                if changed and target is self._user_products:
                    filled += 1
        if filled:
            self._save_user_catalog()
        return filled

    def mark_superseded(self, manufacturer: str, order_number: str, superseded_by: str,
                        product_name: str = "") -> None:
        """Markiert ein Produkt als veraltet, ersetzt durch die Bestellnummer
        `superseded_by` (gleicher Hersteller). `superseded_by=""` hebt die
        Markierung wieder auf.

        Funktioniert auch für Produkte aus der mitgelieferten Basis-Datenbank:
        der volle Eintrag wird dafür in den nutzereigenen Katalog kopiert und
        dort dauerhaft mit der Markierung persistiert -- die schreibgeschützte
        Basis-Datei selbst bleibt unverändert.
        """
        key = product_key(manufacturer, order_number, product_name)
        for prod in self._catalog:
            if self._key(prod) == key:
                prod["superseded_by"] = superseded_by
                self._upsert(self._user_products, dict(prod))
                self._online_keys.discard(key)
                self._save_user_catalog()
                return
        logger.warning(
            f"mark_superseded: Produkt {manufacturer} / {order_number} nicht im Katalog gefunden."
        )

    def products_for_manufacturer(self, manufacturer: str) -> list[dict]:
        """Gibt alle Katalogeinträge eines Herstellers zurück (für die
        Nachfolgerauswahl beim Markieren als veraltet)."""
        name = manufacturer_display_name(manufacturer)
        return [p for p in self._catalog if p.get("manufacturer", "") == name]

    def find_product(self, manufacturer: str, order_number: str,
                     product_name: str = "") -> dict | None:
        """Sucht einen Katalogeintrag nach (Hersteller, Bestellnummer); bei
        Platzhalter-Bestellnummern ("Dummy") zusaetzlich nach Produktname."""
        key = product_key(manufacturer, order_number, product_name)
        for prod in self._catalog:
            if self._key(prod) == key:
                return prod
        return None

    def online_catalog_status(self):
        """Stand des zwischengespeicherten Online-Katalogs (OnlineCatalogResult)."""
        return self._online.load_cached()

    def update_online_catalog(self, timeout: float = 10.0):
        """Lädt den Online-Katalog neu herunter und übernimmt ihn in den
        Katalog (FA-1303/1402). Gibt das OnlineCatalogResult zurück; bei einem
        Fehler bleibt der bisherige Katalog unverändert."""
        result = self._online.fetch(timeout=timeout)
        if result.ok:
            self._merge_online(result.products)
        return result

    def search_online(
        self,
        query: str = "",
        category_filter: str = "",
        preferred_manufacturers: list[str] | None = None,
        timeout: float = 10.0,
    ) -> list[ProductSuggestion]:
        """Aktualisiert den Online-Katalog und liefert die passenden Produkte
        daraus (FA-1303 Aktoren, FA-1402 Sensoren). Bevorzugte Hersteller
        zuerst (FA-1304/1403). Ohne Internetverbindung werden die zuletzt
        geladenen Online-Produkte durchsucht."""
        self.update_online_catalog(timeout=timeout)
        return [
            r for r in self.search_all(query, category_filter, preferred_manufacturers)
            if r.online
        ]
