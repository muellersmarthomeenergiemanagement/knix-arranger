"""
Produkte mit Kommunikationsobjekten je Zone: ein Gerät bedient mehrere
Räume oder Kanäle, z.B.
- Revox Multiuser 3.0: "R_1_ROOM_ON_OFF" … "R_15_VOLUME_VALUE" (15 Räume)
  plus Systemobjekte (SYSTEM_OFF, Szenen, KNX-Actions),
- Theben KNX-OT-Box: "H1 Max. Stellgrösse Zone/Raum 5 …",
- Aktoren und Ein-/Ausgabemodule: "Kanal 5, …", "Channel C …", "Ausgang 3 …".

Ohne Zone erzeugte jeder KNiX-Raum mit dem Produkt die GAs aller
ausgewählten Zonen -- bei 6 Räumen sechsmal dieselben (Projekt_23 Chalet
Franziska: 780 statt 130 GAs). Mit Zone erzeugt ein Raum nur die KOs seiner
Zone, die Systemobjekte (KOs ohne Zone) nur der Raum, der sie trägt.

Das Muster wird je Produkt bestimmt (zone_scheme): von den bekannten
Schreibweisen diejenige, die die meisten KOs abdeckt. Eingänge, Tasten und
kurze Kürzel ("R1:") zählen bewusst nicht -- zu mehrdeutig.

Im Produkt (GewerkAssignment.linked_product / element_products):
  "zone": int            -- Zone dieses Raums (fehlt/0 = alle KOs wie bisher)
  "system_objects": bool -- Systemobjekte (KOs ohne Zone) hier anlegen
Die KO-Auswahl (excluded_co_numbers) gilt je Funktion: eine Funktion, die
in irgendeiner Zone ausgewählt ist, gilt für alle Zonen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ZoneScheme:
    """Schreibweise der Zone in den KOs eines Produkts."""
    label: str              # "Raum", "Zone", "Kanal", "Ausgang"
    pattern: re.Pattern     # Gruppe 1 = Nummer bzw. Buchstabe
    name_only: bool = False  # nur im KO-Namen suchen (Revox "R_3_…")
    letters: bool = False    # "Kanal A" = Zone 1


_SCHEMES = (
    ZoneScheme("Raum", re.compile(r"^R_(\d+)_"), name_only=True),
    ZoneScheme("Raum", re.compile(r"\b(?:Zone/Raum|Raum|Room)\s*(\d+)\b", re.I)),
    ZoneScheme("Zone", re.compile(r"\bZone\s*(\d+)\b", re.I)),
    ZoneScheme("Kanal", re.compile(r"\b(?:Kanal|Channel)\s*(\d+)\b", re.I)),
    ZoneScheme("Kanal", re.compile(r"\b(?:[Kk]anal|[Cc]hannel)\s+([A-Z])\b"), letters=True),
    ZoneScheme("Ausgang", re.compile(r"\b(?:Ausgang|Output)\s*(\d+)\b", re.I)),
)
# Mindestens so viele KOs müssen eine Zone tragen (Anteil), und es braucht
# mindestens zwei verschiedene Zonen
_MIN_SHARE = 0.25


def _match(co: dict, scheme: ZoneScheme):
    """(Feld, Match) der ersten Fundstelle: zuerst im Namen, dann im Text."""
    fields = ("name",) if scheme.name_only else ("name", "function_text")
    for field_name in fields:
        m = scheme.pattern.search(co.get(field_name, "") or "")
        if m:
            return field_name, m
    return None, None


def _zone_number(scheme: ZoneScheme, m) -> int:
    value = m.group(1)
    return ord(value) - ord("A") + 1 if scheme.letters else int(value)


_scheme_cache: dict[int, tuple[list, ZoneScheme | None]] = {}


def zone_scheme(product: dict | None) -> ZoneScheme | None:
    """Muster des Produkts, None = keine Zonen."""
    cos = (product or {}).get("com_objects") or []
    if len(cos) < 2:
        return None
    cached = _scheme_cache.get(id(cos))
    if cached and cached[0] is cos:
        return cached[1]
    best, best_count = None, 0
    for scheme in _SCHEMES:
        zones, count = set(), 0
        for co in cos:
            _f, m = _match(co, scheme)
            if m:
                zones.add(_zone_number(scheme, m))
                count += 1
        if len(zones) > 1 and count >= len(cos) * _MIN_SHARE and count > best_count:
            best, best_count = scheme, count
    if len(_scheme_cache) > 256:
        _scheme_cache.clear()
    _scheme_cache[id(cos)] = (cos, best)
    return best


def co_zone(co: dict, scheme: ZoneScheme | None) -> int | None:
    """Zone eines Kommunikationsobjekts, None = Systemobjekt (ohne Zone)."""
    if scheme is None:
        return None
    _f, m = _match(co, scheme)
    return _zone_number(scheme, m) if m else None


def zone_function(co: dict, scheme: ZoneScheme | None) -> str:
    """Funktion ohne Zone: "R_3_VOLUME_VALUE" -> "R_#_VOLUME_VALUE",
    "Kanal 5, Jalousiesensor" -> "Kanal #, Jalousiesensor"."""
    field_name, m = _match(co, scheme) if scheme else (None, None)
    if not m:
        return co.get("name", "")
    text = co.get(field_name, "")
    return f"{field_name}:{text[:m.start(1)]}#{text[m.end(1):]}"


def zone_label(product: dict | None, zone: int) -> str:
    """"Raum 3", "Kanal C", "Ausgang 5"."""
    scheme = zone_scheme(product)
    if scheme is None or not zone:
        return ""
    value = chr(ord("A") + zone - 1) if scheme.letters else str(zone)
    return f"{scheme.label} {value}"


def zones_of(product: dict | None) -> list[int]:
    """Alle Zonen des Produkts (leer = keine Zonen)."""
    scheme = zone_scheme(product)
    if scheme is None:
        return []
    return sorted({z for co in product.get("com_objects") or []
                   if (z := co_zone(co, scheme)) is not None})


def is_zoned(product: dict | None) -> bool:
    return zone_scheme(product) is not None


def selected_zones(product: dict) -> list[int]:
    """Zonen mit mindestens einem ausgewählten KO."""
    scheme = zone_scheme(product)
    excluded = set(product.get("excluded_co_numbers") or [])
    return sorted({z for co in product.get("com_objects") or []
                   if co.get("number") not in excluded
                   and (z := co_zone(co, scheme)) is not None})


def zone_excluded_numbers(product: dict) -> set[int]:
    """Nicht anzulegende KOs: die gewählten (excluded_co_numbers) und, wenn
    eine Zone gesetzt ist, alle KOs anderer Zonen bzw. die Systemobjekte."""
    cos = product.get("com_objects") or []
    excluded = set(product.get("excluded_co_numbers") or [])
    zone = product.get("zone") or 0
    scheme = zone_scheme(product)
    if not zone or scheme is None:
        return excluded
    zoned = [(co, co_zone(co, scheme)) for co in cos]
    functions = {zone_function(co, scheme) for co, z in zoned
                 if z is not None and co.get("number") not in excluded}
    with_system = product.get("system_objects", False)
    result = set()
    for co, z in zoned:
        if z is None:
            keep = with_system and co.get("number") not in excluded
        else:
            keep = z == zone and zone_function(co, scheme) in functions
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
