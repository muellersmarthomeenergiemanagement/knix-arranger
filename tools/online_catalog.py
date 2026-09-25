"""
KNiX Arranger – Online-Produktkatalog pflegen (FA-1303, FA-1402)

Die App laedt den Katalog von
    https://github.com/muellersmarthomeenergiemanagement/knix-arranger-releases
    (Datei product_catalog_online.json im Branch main)

Befehle:
    python tools/online_catalog.py pruefen <datei>
        Prueft eine Katalogdatei und listet unvollstaendige Eintraege.

    python tools/online_catalog.py uebernehmen <datei> [--hersteller MDT ...]
        Uebernimmt Produkte aus dem eigenen Katalog (KNXPROD-Importe unter
        %APPDATA%/KNiX Arranger/product_catalog_user.json) in die Katalogdatei.
        Bestehende Eintraege mit gleichem Hersteller und Bestellnummer werden
        ersetzt, das Feld "updated" wird auf heute gesetzt.
        Kommunikationsobjekte werden nicht uebernommen (Dateigroesse: mit
        ihnen wird der Katalog schnell mehrere hundert MB gross; ausserdem
        sind es Herstellerdaten). ga_min/ga_max bleiben erhalten.
        Herstellernamen werden vereinheitlicht (knix_arranger/utils/
        manufacturers.py), gleiche Produkte in verschiedenen Schreibweisen
        fallen dabei zusammen. Eintraege, deren Hersteller-Code ("M-XXXX")
        nicht im KNX-Register steht, werden uebersprungen.

Danach die Datei ins Release-Repository committen und pushen.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from knix_arranger.services.online_catalog_service import validate_products  # noqa: E402
from knix_arranger.services.product_search_service import _user_catalog_path  # noqa: E402
from knix_arranger.utils.manufacturers import (  # noqa: E402
    canonicalize_product, manufacturer_display_name, product_key,
)


_MANUFACTURER_CODE = re.compile(r"M-[0-9A-Fa-f]{4}")


def _for_online(prod: dict) -> dict:
    """Produkt ohne Kommunikationsobjekte (siehe Moduldoku)."""
    return {k: v for k, v in prod.items() if k != "com_objects"}


def _load(path: Path) -> dict:
    if not path.exists():
        return {"updated": "", "products": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pruefen(path: Path) -> int:
    data = _load(path)
    raw = data.get("products", [])
    valid, skipped = validate_products(raw)
    print(f"{path.name}: {len(valid)} gültige Produkte, Stand {data.get('updated') or '-'}")
    if skipped:
        print(f"{skipped} unvollständige Einträge (Hersteller, Bestellnummer "
              f"und Kategorie actor/sensor/infrastructure sind Pflicht):")
        for i, prod in enumerate(raw):
            if not validate_products([prod])[0]:
                print(f"  Eintrag {i + 1}: {json.dumps(prod, ensure_ascii=False)[:120]}")
        return 1
    keys = [product_key(p["manufacturer"], p["order_number"], p.get("product_name", "")) for p in valid]
    dupes = {k for k in keys if keys.count(k) > 1}
    for m, o in sorted(dupes):
        print(f"  Doppelt: {manufacturer_display_name(m)} {o}")
    return 1 if dupes else 0


def uebernehmen(path: Path, hersteller: list[str]) -> int:
    user_path = Path(_user_catalog_path())
    own = [canonicalize_product(p) for p in _load(user_path).get("products", [])]
    if hersteller:
        wanted = {manufacturer_display_name(h).lower() for h in hersteller}
        own = [p for p in own if p.get("manufacturer", "").lower() in wanted]
    codes = [p for p in own if _MANUFACTURER_CODE.fullmatch(p.get("manufacturer", ""))]
    own = [_for_online(p) for p in own
           if not _MANUFACTURER_CODE.fullmatch(p.get("manufacturer", ""))]
    own, skipped = validate_products(own)
    if codes:
        print(f"{len(codes)} Einträge mit Hersteller-Code statt Namen übersprungen.")
    if not own:
        print(f"Keine passenden Produkte in {user_path} gefunden.")
        return 1

    data = _load(path)
    products = []
    index: dict[tuple[str, str], int] = {}
    for p in data.get("products", []):
        p = canonicalize_product(p)
        key = product_key(p.get("manufacturer", ""), p.get("order_number", ""), p.get("product_name", ""))
        if key in index:
            products[index[key]] = p
        else:
            index[key] = len(products)
            products.append(p)
    added = replaced = 0
    for prod in own:
        key = product_key(prod["manufacturer"], prod["order_number"], prod.get("product_name", ""))
        if key in index:
            products[index[key]] = prod
            replaced += 1
        else:
            index[key] = len(products)
            products.append(prod)
            added += 1

    data["products"] = products
    data["updated"] = date.today().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"{added} Produkte hinzugefügt, {replaced} ersetzt, {skipped} unvollständige "
          f"übersprungen. Katalog enthält jetzt {len(products)} Produkte.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Online-Produktkatalog pflegen")
    sub = parser.add_subparsers(dest="befehl", required=True)
    p_check = sub.add_parser("pruefen", help="Katalogdatei prüfen")
    p_check.add_argument("datei", type=Path)
    p_take = sub.add_parser("uebernehmen", help="Produkte aus dem eigenen Katalog übernehmen")
    p_take.add_argument("datei", type=Path)
    p_take.add_argument("--hersteller", nargs="*", default=[],
                        help="nur diese Hersteller übernehmen (Standard: alle)")
    args = parser.parse_args()

    if args.befehl == "pruefen":
        return pruefen(args.datei)
    return uebernehmen(args.datei, args.hersteller)


if __name__ == "__main__":
    sys.exit(main())
