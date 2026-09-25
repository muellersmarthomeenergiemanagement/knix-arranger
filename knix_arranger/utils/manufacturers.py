"""
KNX-Hersteller: Hersteller-ID (M-XXXX) als fester Schluessel, einheitlicher
Anzeigename und normalisierte Bestellnummer fuer den Produktabgleich.

Derselbe Hersteller taucht je nach Quelle unterschiedlich auf: ETS-Projekte
liefern die ID ("M-0002"), Catalog.xml der KNXPROD-Dateien einen Markennamen
("ABB"), knx_master.xml den Firmennamen ("ABB AG - STOTZ-KONTAKT"). Alle
Eingaenge laufen ueber manufacturer_display_name(), damit ueberall derselbe
Name steht und Vergleiche per == funktionieren.

Grundlage ist data/knx_manufacturers.json (offizielles KNX-Herstellerregister,
aktualisieren mit tools/update_manufacturers.py).
"""
from __future__ import annotations
import json
import logging
import os
import re
from functools import lru_cache

logger = logging.getLogger("knix_arranger.manufacturers")

_ID_PATTERN = re.compile(r"M-[0-9A-F]{4}", re.IGNORECASE)

# Kurze Anzeigenamen fuer gaengige Hersteller; alle anderen behalten den
# Namen aus dem KNX-Register. Die Namen muessen eindeutig sein.
_SHORT_NAMES: dict[str, str] = {
    "M-0001": "Siemens",
    "M-0002": "ABB",
    "M-0004": "Jung",
    "M-0005": "Bticino",
    "M-0006": "Berker",
    "M-0007": "Busch-Jaeger",
    "M-0008": "Gira",
    "M-0009": "Hager",
    "M-000A": "Insta",
    "M-000B": "Legrand",
    "M-000C": "Merten",
    "M-001D": "ABB Schweiz",
    "M-001E": "Feller",
    "M-003D": "WAGO",
    "M-0048": "Theben",
    "M-004E": "Somfy",
    "M-0051": "Viessmann",
    "M-0064": "Schneider Electric",
    "M-0071": "Zennio",
    "M-007C": "ise",
    "M-0080": "Esylux",
    "M-0081": "Basalte",
    "M-0083": "MDT",
    "M-008E": "Steinel",
    "M-00A6": "Enertex",
    "M-00C5": "Weinzierl",
    "M-00C8": "B.E.G.",
    "M-00C9": "Elsner",
    "M-00E1": "Lingg & Janke",
    "M-00E8": "Theben HTS",
    "M-00EE": "Griesser",
    "M-00FD": "Siemens HVAC",
    "M-01FC": "Niko",
    "M-0201": "Hörmann",
}

# Schreibvarianten, die weder Kurz- noch Registername sind (z.B. aus
# Catalog.xml der Hersteller oder aelteren Katalogdaten).
_ALIASES: dict[str, str] = {
    "busch-jaeger elektro": "M-0007",
    "busch-jaeger elektro gmbh": "M-0007",
    "busch jaeger": "M-0007",
    "gira giersiepen": "M-0008",
    "hager electro": "M-0009",
    "albrecht jung": "M-0004",
    "theben ag": "M-0048",
    "theben hts ag": "M-00E8",
    "mdt technologies": "M-0083",
    "schneider": "M-0064",
    "elsner elektronik": "M-00C9",
}


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, str], dict[str, str]]:
    """(ID -> Anzeigename, gefalteter Name -> ID)."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "knx_manufacturers.json",
    )
    registry: dict[str, dict] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            registry = json.load(f).get("manufacturers", {})
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"KNX-Herstellerliste nicht lesbar: {e}")

    display = {mid: entry.get("name", "") for mid, entry in registry.items()}
    display.update(_SHORT_NAMES)

    by_name: dict[str, str] = {}
    ambiguous: set[str] = set()
    for mid, entry in registry.items():
        key = _fold(entry.get("name", ""))
        if not key:
            continue
        if key in by_name and by_name[key] != mid:
            ambiguous.add(key)
        by_name[key] = mid
    for key in ambiguous:
        del by_name[key]
    for mid, name in _SHORT_NAMES.items():
        by_name[_fold(name)] = mid
    by_name.update(_ALIASES)
    return display, by_name


def manufacturer_id(value: str) -> str:
    """KNX-Hersteller-ID ("M-0002") zu einer ID oder einem bekannten Namen,
    sonst ""."""
    value = (value or "").strip()
    if _ID_PATTERN.fullmatch(value):
        return value.upper()
    return _tables()[1].get(_fold(value), "")


def manufacturer_display_name(value: str) -> str:
    """Einheitlicher Anzeigename zu einer ID oder einem Namen. Unbekannte
    Werte bleiben (ohne ueberzaehlige Leerzeichen) unveraendert."""
    value = " ".join((value or "").split())
    mid = manufacturer_id(value)
    return _tables()[0].get(mid) or value


def canonical_manufacturer(name: str, mfr_id: str = "") -> tuple[str, str]:
    """(Anzeigename, Hersteller-ID) aus Name und optional bekannter ID.
    Eine ID, die (noch) nicht im Register steht, ueberschreibt einen
    vorhandenen Namen nicht mit der rohen "M-XXXX"-Kennung."""
    mfr_id = manufacturer_id(mfr_id) or manufacturer_id(name)
    display = manufacturer_display_name(name)
    if mfr_id and (mfr_id in _tables()[0] or not display):
        display = manufacturer_display_name(mfr_id)
    return display, mfr_id


def canonicalize_product(product: dict) -> dict:
    """Setzt in einem Katalogeintrag (dict) den einheitlichen Herstellernamen
    und, sofern bekannt, "manufacturer_id". Aendert product und gibt es zurueck."""
    product["manufacturer"], mfr_id = canonical_manufacturer(
        product.get("manufacturer", ""), product.get("manufacturer_id", ""),
    )
    if mfr_id:
        product["manufacturer_id"] = mfr_id
    return product


def normalize_order_number(order_number: str) -> str:
    """Bestellnummer fuer Vergleiche: ohne Leerzeichen und Punkte, gross."""
    return re.sub(r"[\s.]", "", order_number or "").upper()


# Platzhalter-Bestellnummern: mehrere verschiedene Produkte desselben
# Herstellers tragen sie (z.B. Feller "Dummy" und "Dummy Secure" als Hilfe
# fuer die GA-Filter der Linienkoppler) -- dort unterscheidet der Produktname.
_PLACEHOLDER_ORDER_NUMBERS = {"", "DUMMY"}


def product_key(
    manufacturer: str, order_number: str, product_name: str = "",
) -> tuple[str, str]:
    """Vergleichsschluessel (Hersteller, Bestellnummer) fuer ein Produkt.
    Bei Platzhalter-Bestellnummern gehoert der Produktname dazu."""
    mfr = manufacturer_id(manufacturer) or _fold(manufacturer or "")
    order = normalize_order_number(order_number)
    if order in _PLACEHOLDER_ORDER_NUMBERS:
        order = f"{order}|{_fold(product_name or '')}"
    return mfr, order
