"""
Produkte mit Kommunikationsobjekten je Zone, z.B. Revox Multiuser 3.0:
"R_1_ROOM_ON_OFF" … "R_15_VOLUME_VALUE" (15 Revox-Räume) plus
Systemobjekte (SYSTEM_OFF, Szenen, KNX-Actions).

Ein Gateway bedient alle Räume. Ohne Zone erzeugte jeder KNiX-Raum mit dem
Produkt die GAs aller ausgewählten Zonen -- bei 6 Räumen sechsmal dieselben
(Projekt_23 Chalet Franziska: 780 statt 130 GAs). Mit Zone erzeugt ein Raum
nur die KOs seiner Zone, die Systemobjekte nur der Raum, der sie trägt.

Im Produkt (GewerkAssignment.linked_product / element_products):
  "zone": int            -- Zone dieses Raums (fehlt/0 = alle KOs wie bisher)
  "system_objects": bool -- Systemobjekte (KOs ohne Zone) hier anlegen
Die KO-Auswahl (excluded_co_numbers) gilt je Funktion: eine Funktion, die
in irgendeiner Zone ausgewählt ist, gilt für alle Zonen.
"""
from __future__ import annotations

import re

_ZONE_NAME = re.compile(r"^R_(\d+)_(.+)$")
_ZONE_TEXT = re.compile(r"\{\{0:Room (\d+)\}\}")


def co_zone(co: dict) -> int | None:
    """Zone eines Kommunikationsobjekts, None = Systemobjekt (ohne Zone)."""
    m = _ZONE_NAME.match(co.get("name", ""))
    if m:
        return int(m.group(1))
    m = _ZONE_TEXT.search(co.get("function_text", ""))
    return int(m.group(1)) if m else None


def zone_function(co: dict) -> str:
    """Funktion ohne Zone: "R_3_VOLUME_VALUE" -> "VOLUME_VALUE"."""
    name = co.get("name", "")
    m = _ZONE_NAME.match(name)
    return m.group(2) if m else name


def zones_of(product: dict | None) -> list[int]:
    """Alle Zonen des Produkts (leer = keine Zonen)."""
    return sorted({z for co in (product or {}).get("com_objects") or []
                   if (z := co_zone(co)) is not None})


def is_zoned(product: dict | None) -> bool:
    return len(zones_of(product)) > 1


def selected_zones(product: dict) -> list[int]:
    """Zonen mit mindestens einem ausgewählten KO."""
    excluded = set(product.get("excluded_co_numbers") or [])
    return sorted({z for co in product.get("com_objects") or []
                   if co.get("number") not in excluded
                   and (z := co_zone(co)) is not None})


def zone_excluded_numbers(product: dict) -> set[int]:
    """Nicht anzulegende KOs: die gewählten (excluded_co_numbers) und, wenn
    eine Zone gesetzt ist, alle KOs anderer Zonen bzw. die Systemobjekte."""
    cos = product.get("com_objects") or []
    excluded = set(product.get("excluded_co_numbers") or [])
    zone = product.get("zone") or 0
    if not zone or not is_zoned(product):
        return excluded
    functions = {zone_function(co) for co in cos
                 if co_zone(co) is not None and co.get("number") not in excluded}
    with_system = product.get("system_objects", False)
    result = set()
    for co in cos:
        z = co_zone(co)
        if z is None:
            keep = with_system and co.get("number") not in excluded
        else:
            keep = z == zone and zone_function(co) in functions
        if not keep:
            result.add(co.get("number"))
    return result


def same_product_elements(project, product: dict) -> list[tuple]:
    """(Raum, GewerkAssignment, Element-Nr. oder None) aller Zuweisungen mit
    diesem Produkt (gleicher Hersteller/Bestellnummer); None = Produkt für
    alle Elemente."""
    from ..utils.manufacturers import product_key

    def key(p):
        return product_key(p.get("manufacturer", ""), p.get("order_number", ""),
                           p.get("product_name", ""))
    wanted = key(product)
    result = []
    for room in project.all_rooms:
        for a in room.gewerk_assignments:
            if a.linked_product and key(a.linked_product) == wanted:
                result.append((room, a, None))
            for nr, lp in sorted(a.own_element_products().items()):
                if key(lp) == wanted:
                    result.append((room, a, nr))
    return result


def propose_zones(products: list[dict]) -> None:
    """Zonen ohne Zuordnung der Reihe nach vergeben (bereits vergebene
    überspringen); die Systemobjekte trägt der erste Eintrag, falls sie
    noch niemand trägt."""
    if not products or not is_zoned(products[0]):
        return
    used = {p.get("zone") for p in products if p.get("zone")}
    free = (z for z in zones_of(products[0]) if z not in used)
    for p in products:
        if not p.get("zone"):
            p["zone"] = next(free, 0)
    if not any(p.get("system_objects") for p in products):
        products[0]["system_objects"] = True
