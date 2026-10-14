"""
Produkt des Geräts und Produkt der GA-Planung abgleichen (Sensoren).

Ein Produkt bedeutet an zwei Orten Verschiedenes:
- Schritt 5 (GewerkAssignment.linked_product / element_products): aus
  welchen Kommunikationsobjekten die GAs eines Elements erzeugt werden;
- Materialliste/Topologie (Device): das bestellte, eingebaute Gerät.

Bei Sensoren gehören die Elemente eines Gewerks eindeutig zu einem Gerät
(über sein Bedienelement), z.B. Projekt_23 Technik: Gewerk A Element 2
«Wassermelder» = 1.2.113 Elsner Leak. Hat das Gerät ein Produkt mit
Kommunikationsobjekten, die GA-Planung aber ein anderes oder keins, passen
GAs und Gerät nicht zusammen -- product_mismatches() findet das,
apply_device_product() übernimmt das Geräteprodukt für die GAs.
Aktoren bedienen viele Räume und Gewerke, dort bleibt Schritt 5 eine
eigene Entscheidung.

Bedient ein Sensor ein Gewerk mit Aktor (z.B. Projekt_23 Waschen:
Bewegungsmelder 1.2.105 schaltet L «Deckenlicht» und LDA), gehören die GAs
dem Aktor (Schalten E/A, Rückmeldung) -- der Sensor sendet nur auf die
Schalt-GA. Solche Elemente gleicht product_mismatches() nicht ab.
"""
from __future__ import annotations

from dataclasses import dataclass

from .button_move import bedienelement_of_device


@dataclass
class ProductMismatch:
    device: object          # Sensor-Gerät der Topologie
    room: object            # Raum des Gewerks
    assignment: object      # GewerkAssignment
    element_nr: int

    @property
    def element_text(self) -> str:
        label = self.assignment.element_label(self.element_nr)
        text = f"Gewerk {self.assignment.gewerk_code}"
        if self.assignment.count > 1:
            text += f", Element {self.element_nr}"
        return f"{text} {label}".strip() if label else text


_shared_catalog = None


def shared_catalog():
    """Produktkatalog einmal je Sitzung laden (Prüfung nach jeder Änderung,
    Produktdialog). Speichert ein ProductSearchService den eigenen Katalog,
    wird er der gemeinsame (set_shared_catalog)."""
    global _shared_catalog
    if _shared_catalog is None:
        try:
            from .product_search_service import ProductSearchService
            _shared_catalog = ProductSearchService()
        except Exception:
            return None
    return _shared_catalog


def set_shared_catalog(catalog) -> None:
    global _shared_catalog
    _shared_catalog = catalog


def reset_shared_catalog() -> None:
    global _shared_catalog
    _shared_catalog = None


def _catalog_com_objects(device, catalog) -> list[dict]:
    if catalog is None or not device.order_number:
        return []
    found = catalog.find_product(device.manufacturer, device.order_number,
                                 device.product_name)
    return list((found or {}).get("com_objects") or [])


def _has_com_objects(device, catalog) -> bool:
    """Am Gerät gespeichert (Materialliste) oder im Katalog -- ältere
    Zuweisungen speicherten die Kommunikationsobjekte nicht am Gerät."""
    return bool(device.communication_objects or _catalog_com_objects(device, catalog))


def _same_product(planned: dict | None, device) -> bool:
    return bool(planned) and (
        (planned.get("manufacturer", ""), planned.get("order_number", ""))
        == (device.manufacturer, device.order_number))


def sensor_owns_gewerk(gewerk_code: str) -> bool:
    """Gehören die GAs des Gewerks dem Sensor? Nicht bei Gewerken mit Aktor
    oder Gateway (L, LDA, J, H ...): dort bestimmt der Aktor die GAs."""
    from ..models.device import GEWERK_TO_ACTOR_TYPE
    return gewerk_code not in GEWERK_TO_ACTOR_TYPE


def device_elements(project, device) -> list[tuple]:
    """(Raum, GewerkAssignment, Element-Nr.) der Gewerk-Elemente, die ein
    Sensor-Gerät trägt (über die Funktionen seines Bedienelements)."""
    room, be = bedienelement_of_device(project, device)
    if be is None:
        return []
    rooms = {r.id: r for r in project.all_rooms}
    result, seen = [], set()
    for sf in be.funktionen:
        if not sf.gewerk_code or not sf.element_number or sf.press_of:
            continue
        target = rooms.get(sf.source_room_id) if sf.source_room_id else room
        assignment = next((a for a in (target.gewerk_assignments if target else [])
                           if a.gewerk_code == sf.gewerk_code), None)
        if assignment is None or sf.element_number > assignment.count:
            continue
        key = (assignment.id, sf.element_number)
        if key not in seen:
            seen.add(key)
            result.append((target, assignment, sf.element_number))
    return result


_DEFAULT = object()


def product_mismatches(project, devices=None, catalog=_DEFAULT) -> list[ProductMismatch]:
    """Elemente, deren Sensor-Gerät ein Produkt mit Kommunikationsobjekten
    hat, das nicht dem Produkt der GA-Planung entspricht. Nur geplante
    Projekte -- importierte haben ihre GAs aus der ETS. Gewerke mit Aktor
    zählen nicht (sensor_owns_gewerk)."""
    if project.topology.is_imported:
        return []
    if catalog is _DEFAULT:
        catalog = shared_catalog()
    if devices is None:
        devices = [d for area in project.topology.areas for line in area.lines
                   for d in line.devices]
    result = []
    for device in devices:
        if device.device_type != "sensor" or not device.order_number:
            continue
        elements = [(room, assignment, nr)
                    for room, assignment, nr in device_elements(project, device)
                    if sensor_owns_gewerk(assignment.gewerk_code)
                    and not _same_product(assignment.product_for_element(nr), device)]
        if elements and _has_com_objects(device, catalog):
            result += [ProductMismatch(device, room, assignment, nr)
                       for room, assignment, nr in elements]
    return result


def sensor_products_on_actor_gewerke(project, devices=None) -> list[ProductMismatch]:
    """Elemente eines Gewerks mit Aktor, deren GAs dem Produkt des Sensors
    folgen, der sie bedient -- Rückstand der früheren Übernahme ohne
    sensor_owns_gewerk (Projekt_23 Waschen: L «Deckenlicht» und LDA nach dem
    Bewegungsmelder 6131/40, der Aktor 1.2.13 erhielt «P1: Bewegung» statt
    E/A). devices: nur Elemente, die einer dieser Aktoren bedient."""
    if project.topology.is_imported:
        return []
    circuits = None
    if devices is not None:
        from .actor_channels import device_circuits
        circuits = {c.key for d in devices for c in device_circuits(project, d)}
    from .actor_channels import circuit_key
    result, seen = [], set()
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                if device.device_type != "sensor" or not device.order_number:
                    continue
                for room, assignment, nr in device_elements(project, device):
                    key = (assignment.id, nr)
                    if (key in seen or sensor_owns_gewerk(assignment.gewerk_code)
                            or not _same_product(assignment.product_for_element(nr), device)):
                        continue
                    if circuits is not None and circuit_key(
                            room.id, assignment.gewerk_code, nr) not in circuits:
                        continue
                    seen.add(key)
                    result.append(ProductMismatch(device, room, assignment, nr))
    return result


def release_sensor_products(found: list[ProductMismatch]) -> None:
    """Produkt des Sensors von den Elementen entfernen: die GAs folgen wieder
    dem Standard des Gewerks (danach regenerate_addresses)."""
    for m in found:
        assignment = m.assignment
        if m.element_nr in assignment.element_products:
            del assignment.element_products[m.element_nr]
        else:
            # Produkt für alle Elemente (_same_product hat es geprüft)
            assignment.linked_product = None


def communication_objects_of(com_objects: list[dict]) -> list:
    """Kommunikationsobjekte eines Katalogprodukts für Device.communication_objects."""
    from ..models.topology import CommunicationObject

    def flags(co: dict) -> str:
        return "".join([
            "K" if co.get("communication_flag", True) else "-",
            "L" if co.get("read_flag", False) else "-",
            "Ü" if co.get("write_flag", False) else "-",
            "S" if co.get("transmit_flag", False) else "-",
            "U" if co.get("update_flag", False) else "-",
        ])
    return [CommunicationObject(
        object_number=co.get("number", 0), name=co.get("name", ""),
        object_function=co.get("function_text", ""),
        data_type=co.get("datapoint_type", ""), flags=flags(co),
    ) for co in com_objects]


def _co_dict(co) -> dict:
    """CommunicationObject des Geräts als Katalog-Dict (Flags "KLÜSU")."""
    flags = co.flags or ""
    return {
        "number": co.object_number, "name": co.name,
        "function_text": co.object_function, "datapoint_type": co.data_type,
        "communication_flag": "K" in flags, "read_flag": "L" in flags,
        "write_flag": "Ü" in flags or "W" in flags,
        "transmit_flag": "S" in flags or "T" in flags, "update_flag": "U" in flags,
    }


def device_product(device, catalog=_DEFAULT) -> dict:
    """Produkt eines Geräts in der Form von GewerkAssignment.linked_product:
    Kommunikationsobjekte aus dem Katalog, sonst die am Gerät gespeicherten."""
    if catalog is _DEFAULT:
        catalog = shared_catalog()
    com_objects = _catalog_com_objects(device, catalog)
    if not com_objects:
        com_objects = [_co_dict(co) for co in device.communication_objects]
    return {
        "manufacturer": device.manufacturer,
        "order_number": device.order_number,
        "product_name": device.product_name,
        "com_objects": com_objects,
        "excluded_co_numbers": [],
    }


def default_excluded_numbers(com_objects: list[dict]) -> set[int]:
    """Vorauswahl der KOs, die eine eigene GA bekommen: was der Sensor meldet
    (sendet, ohne Schreiben). Eingänge -- Freigabe, Nachlaufzeit, Schwellen,
    Externer Taster, Aktorstatus -- bleiben ohne eigene GA; sie hängen an
    vorhandenen GAs (sensor_channels.SENSOR_ROLES) oder werden bei Bedarf
    angehakt. Projekt_23 6131/40: 6 statt 40 KOs (P1/P2 Bewegung (Master),
    Status Manuell, BR Helligkeit, BR Alarm). Meldet das Produkt nichts,
    bleibt alles ausgewählt."""
    from .knxprod_catalog_service import ComObjectInfo, unique_com_objects
    infos = [ComObjectInfo.from_dict(co) for co in unique_com_objects(com_objects)]
    relevant = [i for i in infos if i.needs_ga]
    reports = {i.number for i in relevant if i.transmit_flag and not i.write_flag}
    if not reports:
        return set()
    return {i.number for i in relevant if i.number not in reports}


def apply_device_product(mismatches: list[ProductMismatch], product: dict) -> None:
    """Geräteprodukt für die GAs der Elemente übernehmen: bei einem Element
    als Produkt für alle, sonst als Produkt dieses Elements."""
    for m in mismatches:
        if m.assignment.count == 1:
            m.assignment.linked_product = dict(product)
        else:
            m.assignment.element_products[m.element_nr] = dict(product)


def _same_planned_product(a: dict | None, b: dict | None) -> bool:
    """Gleiches Produkt mit gleichen Kommunikationsobjekten und gleicher
    Auswahl (Hersteller in verschiedenen Schreibweisen gelten als gleich)."""
    from ..utils.manufacturers import product_key
    if not a or not b:
        return False
    return (product_key(a.get("manufacturer", ""), a.get("order_number", ""),
                        a.get("product_name", ""))
            == product_key(b.get("manufacturer", ""), b.get("order_number", ""),
                           b.get("product_name", ""))
            and len(a.get("com_objects") or []) == len(b.get("com_objects") or [])
            and sorted(a.get("excluded_co_numbers") or [])
            == sorted(b.get("excluded_co_numbers") or []))


def shared_gateway_targets(project, assignment) -> list[tuple]:
    """(Raum, GewerkAssignment) der anderen Räume mit demselben Gewerk, wenn
    es ein gemeinsames Gateway hat (z.B. Revox: ein Gateway für alle
    Lautsprecher-Zonen) und dort noch ein anderes oder kein Produkt steht.
    Ein Produkt ohne KOs überschreibt nie eines mit KOs."""
    if project.topology.is_imported or assignment.gewerk_code not in project.shared_gateways():
        return []
    product = assignment.linked_product
    without_cos = not (product or {}).get("com_objects")
    return [(room, a) for room in project.all_rooms for a in room.gewerk_assignments
            if a is not assignment and a.gewerk_code == assignment.gewerk_code
            and not _same_planned_product(a.linked_product, product)
            and not (without_cos and (a.linked_product or {}).get("com_objects"))]


def apply_product_to(targets: list[tuple], product: dict) -> None:
    """Produkt für alle Elemente der Zuweisungen übernehmen (Kopie je
    Zuweisung). Zone und Systemobjekte gehören zum Raum (product_zones):
    vorhandene bleiben, sonst ohne -- die Zuordnung folgt danach."""
    import copy
    for _room, assignment in targets:
        old = assignment.linked_product or {}
        new = copy.deepcopy(product)
        new.pop("zone", None)
        new.pop("system_objects", None)
        for name in ("zone", "system_objects"):
            if name in old:
                new[name] = old[name]
        assignment.linked_product = new
