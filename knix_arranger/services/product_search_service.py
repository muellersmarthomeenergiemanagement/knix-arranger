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
import sqlite3
from typing import TYPE_CHECKING

from .com_object_store import ComObjectStore, unpack_com_object

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


# Eigener Katalog: Format 1 = KOs als Dict in der JSON-Datei, Format 2 = KOs
# als Zeile, Format 3 = KOs in product_com_objects.sqlite (com_object_store),
# in der JSON-Datei nur "co_count". Ältere Formate werden beim Laden
# einmalig übernommen.
_USER_CATALOG_FORMAT = 3


# Stand der Einordnung (product_classifier): eigene Produkte mit kleinerem
# "classified" werden beim Laden neu eingeordnet -- ausser von Hand
# bearbeitete ("user_edited").
_CLASSIFY_VERSION = 3   # 2: Touch-Panels, Controller, pirios, Salva; 3: DALI-Gruppen


def _com_object_store_path() -> str:
    return os.path.join(os.path.dirname(_user_catalog_path()),
                        "product_com_objects.sqlite")


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
    # ComObjects aus KNXPROD-Import (liste von dicts, kompatibel mit
    # ComObjectInfo.to_dict()); aus dem Katalog erst beim ersten Zugriff
    # geladen (com_objects_loader, siehe unten)
    com_objects: list = field(default_factory=list)
    ga_min: int = 0           # Minimaler GA-Bedarf (Basis-ComObjects)
    ga_max: int = 0           # Maximaler GA-Bedarf (alle aktiven ComObjects)
    # Bestellnummer des Nachfolgeprodukts (gleicher Hersteller), falls dieses
    # Produkt manuell als veraltet markiert wurde ("" = aktuell/nicht markiert)
    superseded_by: str = ""
    # True, wenn der Eintrag aus dem Online-Katalog stammt (FA-1303/1402)
    online: bool = False
    # Vom Nutzer ausgeblendet (nur sichtbar mit "Ausgeblendete anzeigen")
    hidden: bool = False
    # Anzahl KOs, ohne sie zu laden (0 = keine KNXPROD-Daten)
    co_count: int = 0
    # Lädt die KOs beim ersten Zugriff auf com_objects (eigener Katalog)
    com_objects_loader: object = field(default=None, repr=False, compare=False)

    def display_type(self) -> str:
        """Gibt den anzuzeigenden Gerätetyp zurück (kategorie-unabhängig)."""
        return self.device_type or self.actor_type or self.sensor_type or "–"


def _get_com_objects(self) -> list:
    loader = self.__dict__.get("com_objects_loader")
    if loader is not None:
        self.__dict__["com_objects_loader"] = None
        self.__dict__["_com_objects"] = loader()
    return self.__dict__.setdefault("_com_objects", [])


def _set_com_objects(self, value) -> None:
    self.__dict__["_com_objects"] = value


# Nach @dataclass: __init__ setzt com_objects über die Property
ProductSuggestion.com_objects = property(_get_com_objects, _set_com_objects)


class ProductSearchService:
    """Sucht passende KNX-Produkte aus lokaler Datenbank (FA-1303)."""

    def __init__(self, online_service=None):
        from .online_catalog_service import OnlineCatalogService
        self._catalog: list[dict] = []
        self._user_products: list[dict] = []  # nur Nutzer-Importe, für Persistenz
        self._online = online_service or OnlineCatalogService()
        self._online_keys: set[tuple[str, str]] = set()
        # Vom Nutzer ausgeblendete Produkte (Schlüssel wie _key), z.B. ein
        # Vorgängermodell, das nicht mehr verbaut wird
        self._hidden: set[tuple[str, str]] = set()
        # Schlüssel -> Position je Liste (_upsert), siehe _index_for
        self._indexes: dict[int, tuple[list, dict, int]] = {}
        # KOs der eigenen Produkte (com_object_store); noch nicht
        # gespeicherte KOs je Schlüssel ([] = Eintrag entfernen)
        self._store = ComObjectStore(_com_object_store_path())
        self._pending_com_objects: dict[tuple[str, str], list] = {}
        # Parametertexte je Applikation, bis zum nächsten Speichern
        self._pending_parameters: dict[str, dict] = {}
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
                    data = json.load(f)
                loaded = data.get("products", [])
                if data.get("format", 1) == 2:
                    for prod in loaded:
                        if prod.get("com_objects"):
                            prod["com_objects"] = [unpack_com_object(r)
                                                   for r in prod["com_objects"]]
                self._hidden = {tuple(k) for k in data.get("hidden", []) if len(k) == 2}
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Nutzereigener Produktkatalog konnte nicht gelesen werden: {e}")
                loaded = []
            # Aeltere Importe tragen den Hersteller in verschiedenen
            # Schreibweisen ("ABB" / "ABB AG - STOTZ-KONTAKT"): beim
            # Vereinheitlichen fallen solche Dubletten zusammen.
            self._user_products = []
            for prod in loaded:
                prod = canonicalize_product(prod)
                self._detach_com_objects(prod)   # Format 1/2: KOs in die Datenbank
                self._upsert(self._user_products, prod)
            for prod in self._user_products:
                self._upsert(self._catalog, prod)
                self._online_keys.discard(self._key(prod))
            if self._user_products:
                logger.info(f"Nutzereigener Produktkatalog geladen: {len(self._user_products)} Produkte")
                migrate = loaded and data.get("format", 1) < _USER_CATALOG_FORMAT
                if self._reclassify() or migrate:
                    self._save_user_catalog()   # einmalig: KOs in die Datenbank

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

    def _index_for(self, target: list[dict]) -> dict:
        """Schlüssel -> erste Position in target. Wird neu aufgebaut, wenn die
        Liste ersetzt oder ausserhalb von _upsert verändert wurde."""
        cached = self._indexes.get(id(target))
        if cached and cached[0] is target and cached[2] == len(target):
            return cached[1]
        index: dict = {}
        for i, existing in enumerate(target):
            index.setdefault(self._key(existing), i)
        self._indexes[id(target)] = (target, index, len(target))
        return index

    def _upsert(self, target: list[dict], product: dict) -> None:
        """Fügt product zu target hinzu, oder ersetzt einen bestehenden Eintrag
        mit gleichem (manufacturer, order_number) -- verhindert Duplikate bei
        wiederholtem Import derselben KNXPROD-Datei. Über einen Index statt
        durch Vergleich mit allen Einträgen (Laden war quadratisch: 3 s bei
        ~800 eigenen Produkten)."""
        index = self._index_for(target)
        key = self._key(product)
        i = index.get(key)
        if i is not None:
            target[i] = product
            return
        index[key] = len(target)
        target.append(product)
        self._indexes[id(target)] = (target, index, len(target))

    # ------------------------------------------------------------------
    # Kommunikationsobjekte (eigene Produkte: com_object_store)

    def _detach_com_objects(self, product: dict) -> None:
        """KOs eines eigenen Produkts zum Speichern vormerken; im Katalog
        bleibt nur die Anzahl ("co_count")."""
        parameters = product.pop("parameters", None)
        if parameters and product.get("application_program_id"):
            self._pending_parameters[product["application_program_id"]] = parameters
        if "com_objects" not in product:
            return
        com_objects = product.pop("com_objects") or []
        product["co_count"] = len(com_objects)
        self._pending_com_objects[self._key(product)] = com_objects

    def com_objects_of(self, product: dict) -> list[dict]:
        """KOs eines Katalogeintrags (bei eigenen Produkten aus der Datenbank)."""
        if "com_objects" in product:
            return list(product["com_objects"] or [])
        if not product.get("co_count"):
            return []
        key = self._key(product)
        if key in self._pending_com_objects:
            return list(self._pending_com_objects[key])
        return self._store.get(key)

    def parameters_of(self, product: dict) -> dict:
        """Parametertexte der Applikation eines Produkts ({ParameterRef/
        Parameter-Id: [Block, Name, {Wert: Text}, sichtbar]})."""
        if product.get("parameters"):
            return product["parameters"]
        app_id = product.get("application_program_id", "")
        if app_id in self._pending_parameters:
            return self._pending_parameters[app_id]
        return self._store.get_parameters(app_id)

    def _co_loader(self, product: dict):
        return lambda: self.com_objects_of(product)

    @staticmethod
    def _co_count(product: dict) -> int:
        if "com_objects" in product:
            return len(product["com_objects"] or [])
        return int(product.get("co_count") or 0)

    def _reclassify(self) -> bool:
        """Eigene Produkte einmalig neu einordnen (Kategorie, Gerätetyp,
        Kanäle aus Name und KOs, product_classifier). Früher landete alles
        ohne Herstellerangabe als "Schaltaktor". Gibt True zurück, wenn
        sich etwas geändert hat."""
        from .product_classifier import classify
        changed = False
        for product in self._user_products:
            if (product.get("classified", 0) >= _CLASSIFY_VERSION
                    or product.get("user_edited")):
                continue
            found = classify(product.get("product_name", ""),
                             product.get("order_number", ""),
                             product.get("category", ""),
                             self.com_objects_of(product))
            channels = product.get("channels") or found.channels
            if found.device_type == "DALI-Gateway" and found.channels:
                channels = found.channels   # Gruppen statt Zahl im Namen
            product.update(
                category=found.category, device_type=found.device_type,
                actor_type=found.device_type if found.category == "actor" else "",
                sensor_type=found.device_type if found.category == "sensor" else "",
                channels=channels,
                classified=_CLASSIFY_VERSION,
            )
            changed = True
        return changed

    def _save_user_catalog(self) -> None:
        from .product_sync import set_shared_catalog
        set_shared_catalog(self)   # dieser Stand gilt für die ganze Sitzung
        for product in self._user_products:
            self._detach_com_objects(product)   # z.B. nach edit_product
        path = _user_catalog_path()
        try:
            # Zuerst die KOs: die JSON-Datei verweist per co_count darauf
            self._store.put_many(self._pending_com_objects)
            self._pending_com_objects = {}
            self._store.put_parameters(self._pending_parameters)
            self._pending_parameters = {}
            # Erst vollständig in eine Zwischendatei, dann ersetzen: ein
            # Abbruch beim Schreiben lässt den bisherigen Katalog intakt
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"format": _USER_CATALOG_FORMAT,
                           "products": self._user_products,
                           "hidden": sorted(list(k) for k in self._hidden)},
                          f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
        except (OSError, sqlite3.Error) as e:
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
            if self.is_hidden(prod) or self.is_shadowed(prod):
                continue
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
                co_count=self._co_count(prod),
                com_objects_loader=self._co_loader(prod),
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
            if self.is_hidden(prod) or self.is_shadowed(prod):
                continue
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
                co_count=self._co_count(prod),
                com_objects_loader=self._co_loader(prod),
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
            if self.is_hidden(prod) or self.is_shadowed(prod):
                continue
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
                co_count=self._co_count(prod),
                com_objects_loader=self._co_loader(prod),
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
        include_hidden: bool = False,
    ) -> list[ProductSuggestion]:
        """
        Sucht über alle Kategorien (FA-2303).

        Args:
            query: Freitextsuche über Produktname und Bestellnummer.
            category_filter: "actor", "sensor", "infrastructure" oder "" für alle.
            include_hidden: auch ausgeblendete Produkte (hidden=True).
        """
        results = []
        q = query.lower()
        q_order = normalize_order_number(query)

        for prod in self._catalog:
            hidden = self.is_hidden(prod)
            if (hidden or self.is_shadowed(prod)) and not include_hidden:
                continue
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
                co_count=self._co_count(prod),
                com_objects_loader=self._co_loader(prod),
                ga_min=prod.get("ga_min", 0),
                ga_max=prod.get("ga_max", 0),
                superseded_by=prod.get("superseded_by", ""),
                online=self._is_online(prod),
                hidden=hidden,
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
        product = canonicalize_product(dict(product))
        product.setdefault("classified", _CLASSIFY_VERSION)
        self._detach_com_objects(product)
        self._upsert(self._catalog, product)
        self._upsert(self._user_products, product)
        self._online_keys.discard(self._key(product))
        self._hidden.discard(self._key(product))   # Neuimport blendet wieder ein
        self._save_user_catalog()

    def add_products(self, products: list[dict]) -> None:
        """Wie add_product(), aber für mehrere Produkte in einem Rutsch --
        ein einziger Schreibvorgang statt einem pro Produkt (z.B. beim
        Import einer KNXPROD-Datei mit hunderten Produkten)."""
        for product in products:
            product = canonicalize_product(dict(product))
            product.setdefault("classified", _CLASSIFY_VERSION)
            self._detach_com_objects(product)
            self._upsert(self._catalog, product)
            self._upsert(self._user_products, product)
            self._online_keys.discard(self._key(product))
            self._hidden.discard(self._key(product))
        if products:
            self._save_user_catalog()
            # Belegungen der KO-Varianten aus den neuen Bedingungen
            from .ets_parameters import reset_family_cache
            reset_family_cache()

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

    # ------------------------------------------------------------------
    # Katalogpflege: ausblenden, bearbeiten

    def is_hidden(self, product: dict) -> bool:
        return self._key(product) in self._hidden

    def set_hidden(self, manufacturer: str, order_number: str, hidden: bool,
                   product_name: str = "") -> None:
        """Blendet ein Produkt in der Produktsuche aus bzw. wieder ein. Der
        Eintrag bleibt erhalten (auch Online- und Basisprodukte, die sonst bei
        der nächsten Aktualisierung zurückkämen); bestehende Zuweisungen in
        Projekten bleiben unverändert."""
        key = product_key(manufacturer, order_number, product_name)
        if hidden:
            self._hidden.add(key)
        else:
            self._hidden.discard(key)
        self._save_user_catalog()

    EDITABLE_FIELDS = ("manufacturer", "order_number", "product_name", "actor_type",
                       "sensor_type", "device_type", "channels", "price_hint", "url")

    def edit_product(self, manufacturer: str, order_number: str, changes: dict,
                     product_name: str = "") -> dict | None:
        """Ändert Stammdaten eines Produkts (EDITABLE_FIELDS); Kommunikations-
        objekte und ETS-Kennungen bleiben. Der geänderte Eintrag wird als
        eigener Eintrag gespeichert (überschreibt Online-/Basisprodukt).
        Ändert sich Hersteller oder Bestellnummer, verschwindet der alte
        Eintrag (bleibt ausgeblendet, falls er als Online-/Basisprodukt
        wiederkäme). Gibt den neuen Eintrag zurück (None = nicht gefunden)."""
        old = self.find_product(manufacturer, order_number, product_name)
        if old is None:
            return None
        old_key = self._key(old)
        product = dict(old)
        for name, value in changes.items():
            if name in self.EDITABLE_FIELDS:
                product[name] = value
        if product.get("manufacturer") != old.get("manufacturer"):
            product.pop("manufacturer_id", None)   # neu aus dem Namen bestimmen
        product["user_edited"] = True
        product = canonicalize_product(product)
        new_key = self._key(product)
        if new_key != old_key:
            if any(self._key(p) == new_key for p in self._catalog):
                raise ValueError("Ein Produkt mit diesem Hersteller und dieser "
                                 "Bestellnummer steht bereits im Katalog.")
            self._user_products = [p for p in self._user_products
                                   if self._key(p) != old_key]
            self._catalog = [p for p in self._catalog if self._key(p) != old_key]
            self._online_keys.discard(old_key)
            # Käme sonst als Online-/Basisprodukt zurück
            self._hidden.add(old_key)
            self._pending_com_objects[old_key] = []   # KOs ziehen mit um
        self._detach_com_objects(product)
        self._upsert(self._catalog, product)
        self._upsert(self._user_products, product)
        self._online_keys.discard(new_key)
        self._save_user_catalog()
        return self.find_product(product.get("manufacturer", ""),
                                 product.get("order_number", ""),
                                 product.get("product_name", ""))

    def products_for_manufacturer(self, manufacturer: str) -> list[dict]:
        """Gibt alle Katalogeinträge eines Herstellers zurück (für die
        Nachfolgerauswahl beim Markieren als veraltet)."""
        name = manufacturer_display_name(manufacturer)
        return [p for p in self._catalog if p.get("manufacturer", "") == name]

    def duplicate_variants(self) -> dict[tuple[str, str], dict]:
        """Produktschlüssel eines Eintrags ohne KOs -> Katalogeintrag desselben
        Geräts mit KOs (gleicher Hersteller, Typbezeichnung im Namen bzw. in
        der Bestellnummer), z.B. ABB «VAA/S6.230.2.1» (0 KOs) -> «2CDG 110
        116 R0011 – VAA/S6.230.2.1 Valve Drive Actuator» (82 KOs). Der
        Katalog kennt solche Geräte doppelt: aus der Basis-Datenbank und aus
        der KNXPROD; unerkannt eingebaut fehlen die KOs (FA-622)."""
        stamp = (len(self._catalog), id(self._catalog))
        cached = getattr(self, "_duplicates", None)
        if cached and cached[0] == stamp:
            return cached[1]
        with_kos: dict[str, list[tuple[str, dict]]] = {}
        for prod in self._catalog:
            if self._co_count(prod) and not self.is_hidden(prod):
                text = f"{prod.get('order_number', '')} {prod.get('product_name', '')}".lower()
                with_kos.setdefault(prod.get("manufacturer", ""), []).append((text, prod))
        result = {}
        for prod in self._catalog:
            if self._co_count(prod):
                continue
            token = (prod.get("order_number") or "").strip().lower()
            if len(token) < 4 or token == "dummy":   # Platzhalter (Feller «Dummy»)
                continue
            for text, other in with_kos.get(prod.get("manufacturer", ""), []):
                if token in text and other.get("order_number") != prod.get("order_number"):
                    result[self._key(prod)] = other
                    break
        self._duplicates = (stamp, result)
        return result

    def base_name_of(self, manufacturer: str, order_number: str,
                     product_name: str = "") -> str:
        """Deutscher Name aus der Basis-Datenbank für ein KNXPROD-Produkt,
        das sie ohne KOs auch führt («2CDG 110 116 R0011» -> «Heizungsaktor
        6-fach 230V REG»); "" sonst. Für Anzeige, Materialliste und Offerte --
        die KNXPROD von ABB kennt nur «Valve Drive Actuator, 6f»."""
        key = product_key(manufacturer, order_number, product_name)
        names = getattr(self, "_base_names", None)
        stamp = (len(self._catalog), id(self._catalog))
        if names is None or names[0] != stamp:
            index = {self._key(p): p for p in self._catalog}
            names = (stamp, {self._key(other): index[base].get("product_name", "")
                             for base, other in self.duplicate_variants().items()
                             if base in index})
            self._base_names = names
        return names[1].get(key, "")

    def is_shadowed(self, product: dict) -> bool:
        """Eintrag ohne KOs, den der Katalog auch mit KOs kennt: in der
        Produktsuche nicht anbieten (bestehende Zuweisungen bleiben, die
        Validierung meldet sie, FA-622). Entsteht, weil die Basis-Datenbank
        die Typbezeichnung als Bestellnummer führt (ABB «VAA/S6.230.2.1»),
        die KNXPROD die echte Bestellnummer («2CDG 110 116 R0011»)."""
        return not self._co_count(product) and self._key(product) in self.duplicate_variants()

    def duplicate_of(self, manufacturer: str, order_number: str,
                     product_name: str = "") -> dict | None:
        """Katalogeintrag mit KOs zu einem Produkt ohne KOs (siehe
        duplicate_variants), sonst None."""
        return self.duplicate_variants().get(product_key(manufacturer, order_number,
                                                         product_name))

    def variant_with_com_objects(self, prod: ProductSuggestion) -> ProductSuggestion | None:
        """Gleiches Gerät mit KOs aus der KNXPROD, wenn prod keine hat: der
        Katalog kennt manche Geräte doppelt, z.B. ABB «VAA/S6.230.2.1 –
        Heizungsaktor 6-fach» (ohne KOs) und «2CDG 110 116 R0011 –
        VAA/S6.230.2.1 Valve Drive Actuator» (82 KOs), siehe
        duplicate_variants."""
        if prod.co_count or prod.com_objects or not prod.order_number:
            return None
        duplicate = self.duplicate_of(prod.manufacturer, prod.order_number, prod.product_name)
        if duplicate is None:
            return None
        return next((c for c in self.search_all(query=duplicate.get("order_number", ""))
                     if self._key({"manufacturer": c.manufacturer, "order_number": c.order_number,
                                   "product_name": c.product_name}) == self._key(duplicate)),
                    None)

    def find_product(self, manufacturer: str, order_number: str,
                     product_name: str = "") -> dict | None:
        """Sucht einen Katalogeintrag nach (Hersteller, Bestellnummer); bei
        Platzhalter-Bestellnummern ("Dummy") zusaetzlich nach Produktname.
        Gibt eine Kopie mit den Kommunikationsobjekten zurück."""
        key = product_key(manufacturer, order_number, product_name)
        i = self._index_for(self._catalog).get(key)
        if i is None:
            return None
        prod = self._catalog[i]
        return {**prod, "com_objects": self.com_objects_of(prod)}

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
            from .product_sync import reset_shared_catalog
            reset_shared_catalog()
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
