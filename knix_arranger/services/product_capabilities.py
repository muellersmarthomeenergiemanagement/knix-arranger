"""
Fähigkeiten eines realen Produkts aus seinen KOs (FA-1411): Anzahl Tasten
(Wippen: jede Seite eine Taste) und eingebaute Fühler (Temperatur, Feuchte,
CO2, Helligkeit, Präsenz).

Abgeleitet aus Name, Funktionstext, DPT und Flags der KOs -- nur, was sicher
erkennbar ist; KOs ohne Text («Object 27») tragen nichts bei. Beispiele:
Feller EDIZIOdue colore 1-8fach RGB Temp: 8 Tasten (4 Wippen), Temperatur
KO 70 «Raumtemperatur»; Rth Taster EDIZIOdue 1-4fach: Temperatur KO 55
«Room temperature, actual value».

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TEMPERATURE = "temperatur"
HUMIDITY = "feuchte"
CO2 = "co2"
BRIGHTNESS = "helligkeit"
PRESENCE = "praesenz"

SENSOR_LABELS = {
    TEMPERATURE: "Temperatur",
    HUMIDITY: "Feuchte",
    CO2: "CO₂",
    BRIGHTNESS: "Helligkeit",
    PRESENCE: "Präsenz",
}

# Messwert-KO: Text-Muster und Haupttyp des DPT (falls bekannt)
_SENSOR_PATTERNS: dict[str, tuple[re.Pattern, str]] = {
    TEMPERATURE: (re.compile(r"temperatur|temperature", re.I), "9"),
    HUMIDITY: (re.compile(r"feuchte|humidity", re.I), "9"),
    CO2: (re.compile(r"\bco2\b|co₂", re.I), "9"),
    BRIGHTNESS: (re.compile(r"helligkeit|brightness|\blux\b", re.I), "9"),
    PRESENCE: (re.compile(r"präsenz|praesenz|presence|bewegung|motion", re.I), "1"),
}
# Kein Messwert: Sollwerte, Grenzwerte, Alarme, Fremd-/Externwerte, Einstellungen
_NOT_MEASUREMENT = re.compile(
    r"soll|set ?value|setpoint|basic|basis|grenz|limit|threshold|schwelle|alarm|"
    r"extern|fremd|offset|korrektur|correction|anpassung|sperr|disable|enable|"
    r"freigabe|status|anzeige|display|störung|stoerung|fault|\bmin\b|\bmax\b", re.I)

_KEY = re.compile(r"\b(?:taste|button|key|wippe|rocker)\s*(\d+)", re.I)
_RIGHT_SIDE = re.compile(r"\b(?:rechts|right|droite|destra)\b", re.I)
# Produktname «Taster 1-8fach», «4-fach», «4fach»: höchste Zahl = Tasten
_FOLD = re.compile(r"(?:(\d+)\s*-\s*)?(\d+)\s*-?\s*fach", re.I)
_PUSH_BUTTON = re.compile(r"taster|tastsensor|push.?button|button", re.I)


@dataclass
class Capabilities:
    keys: int = 0                     # Tasten (Wippe = 2), 0 = unbekannt
    rocker: bool = False
    sensors: dict[str, object] = field(default_factory=dict)   # Art -> CommunicationObject

    @property
    def summary(self) -> str:
        parts = []
        if self.keys:
            parts.append(f"{self.keys} Tasten" + (f" ({self.keys // 2} Wippen)"
                                                  if self.rocker else ""))
        parts += [f"{SENSOR_LABELS[kind]} (KO {co.object_number})"
                  for kind, co in self.sensors.items()]
        return " · ".join(parts)


def _text(co) -> str:
    return f"{co.name or ''} {co.object_function or ''}"


def _dpt_main(dpt: str) -> str:
    """Haupttyp, auch bei mehreren Angaben ("DPT-9 DPST-9-1", "9.001")."""
    first = (dpt or "").upper().split()[0] if (dpt or "").strip() else ""
    parts = first.replace("DPST-", "DPT-").replace(".", "-").split("-")
    if parts and parts[0] == "DPT":
        parts = parts[1:]
    return parts[0] if parts and parts[0].isdigit() else ""


def _is_measurement(co, pattern: re.Pattern, main: str) -> bool:
    from .ko_links import TRANSMIT, parse_flags
    text = _text(co)
    if not pattern.search(text) or _NOT_MEASUREMENT.search(text):
        return False
    flags = parse_flags(co.flags)
    if flags and TRANSMIT not in flags:
        return False
    dpt = _dpt_main(co.data_type)
    if dpt and dpt != main:
        return False
    # Ohne DPT nur mit eindeutigem Text (Ist-/Raumwert)
    return bool(dpt) or bool(re.search(r"\bist\b|actual|raum|room|messwert|value|wert",
                                       text, re.I))


def keys_from_name(product_name: str) -> int:
    """Tasten aus dem Produktnamen, wenn die KOs keine Namen tragen (Feller
    EDIZIOdue colore im Katalog: «Object 1» …): «1-8fach» -> 8."""
    if not _PUSH_BUTTON.search(product_name or ""):
        return 0
    found = _FOLD.search(product_name or "")
    return int(found.group(2)) if found else 0


def capabilities(cos: list, product_name: str = "") -> Capabilities:
    """Fähigkeiten aus den KOs eines Geräts bzw. Produkts; die Tastenzahl
    ersatzweise aus dem Produktnamen."""
    caps = Capabilities()
    numbers = {int(m.group(1)) for co in cos if (m := _KEY.search(_text(co)))}
    caps.rocker = any(_RIGHT_SIDE.search(_text(co)) for co in cos if _KEY.search(_text(co)))
    # Aus den KOs, mindestens aber nach dem Produktnamen: sind nur einige
    # KO-Namen bekannt (aus einem ETS-Projekt gelernt, ko_names), sähe der
    # Taster sonst kleiner aus, als er ist
    from_kos = max(numbers) * (2 if caps.rocker else 1) if numbers else 0
    caps.keys = max(from_kos, keys_from_name(product_name))
    for kind, (pattern, main) in _SENSOR_PATTERNS.items():
        co = next((c for c in sorted(cos, key=lambda c: c.object_number)
                   if _is_measurement(c, pattern, main)), None)
        if co is not None:
            caps.sensors[kind] = co
    return caps


# Fähigkeiten je KO-Liste und Produktname: hängen nur daran, die Topologie
# fragte sie bei jedem Aufbau für alle Geräte neu ab (Projekt_23: 0,3 s)
_CAPS_CACHE: dict[tuple, Capabilities] = {}
_CAPS_CACHE_MAX = 512


def device_capabilities(device) -> Capabilities:
    if not device.communication_objects:
        return Capabilities()
    name = device.product_name or device.product
    key = (name, tuple((co.object_number, co.name, co.object_function, co.flags, co.data_type)
                       for co in device.communication_objects))
    caps = _CAPS_CACHE.get(key)
    if caps is None:
        if len(_CAPS_CACHE) >= _CAPS_CACHE_MAX:
            _CAPS_CACHE.clear()
        # alle Parametervarianten: erst sie zeigen bei Feller die Wippen
        # («Taste 1, rechts» steht nicht in der ersten Variante «Object 4»)
        caps = _CAPS_CACHE[key] = capabilities(device.communication_objects, name)
    # Kopie: Aufrufer dürfen sensors nicht für andere Geräte verändern;
    # die KOs gehören zu diesem Gerät (gleiche Nummer)
    from .ko_links import _by_number
    by_number = _by_number(device.communication_objects)
    return Capabilities(caps.keys, caps.rocker,
                        {kind: by_number.get(co.object_number, co)
                         for kind, co in caps.sensors.items()})


# ── Abgleich Planung ↔ Produkt (FA-1411a) ──

HEATING_GEWERKE = ("H",)


@dataclass
class KeyShortage:
    device: object
    room: object
    planned: int
    available: int
    bedienelement: object = None


def planned_keys(be) -> int:
    """Geplante Tasten: Funktionen ohne langen Tastendruck (die Kanalzahl
    folgt beim Zuweisen eines Produkts dessen Kanälen)."""
    from .button_move import _main_functions
    return len(_main_functions(be))


@dataclass
class TemperatureOffer:
    """Taster mit Temperaturfühler in einem Raum mit Heizung, deren IST noch
    nicht von ihm kommt."""
    device: object
    room: object
    bedienelement: object
    assignment: object        # GewerkAssignment der Heizung
    element_number: int
    co: object                # Temperatur-KO
    thermostats: list         # Bedienelemente Raumthermostat für dieses Element


def _thermostats(room, gewerk_code: str, nr: int) -> list:
    return [be for be in room.bedienelemente
            if not be.suppressed and be.element_type == "Raumthermostat"
            and any(sf.gewerk_code == gewerk_code and str(sf.element_number) == str(nr)
                    for sf in be.funktionen)]


def plan_conflicts(project) -> tuple[list[KeyShortage], list[TemperatureOffer]]:
    """Geplante Bedienelemente gegen die Fähigkeiten ihres Geräts."""
    from .button_move import bedienelement_of_device
    shortages, offers = [], []
    if project.topology.is_imported:
        return shortages, offers
    for area in project.topology.areas:
        for line in area.lines:
            for device in line.devices:
                if device.device_type != "sensor" or not device.communication_objects:
                    continue
                room, be = bedienelement_of_device(project, device)
                if be is None:
                    continue
                caps = device_capabilities(device)
                planned = planned_keys(be)
                if caps.keys and be.element_type == "Tastereinheit" and planned > caps.keys:
                    shortages.append(KeyShortage(device, room, planned, caps.keys, be))
                co = caps.sensors.get(TEMPERATURE)
                # Raumthermostat regelt selbst; die Wetterstation misst draussen
                if co is None or be.element_type in ("Raumthermostat", "Wetterstation"):
                    continue
                for assignment in room.gewerk_assignments:
                    if assignment.gewerk_code not in HEATING_GEWERKE:
                        continue
                    for nr in range(1, assignment.count + 1):
                        source = assignment.temperature_sources.get(nr)
                        if source is not None:
                            continue        # schon festgelegt (dieser oder ein anderer Taster)
                        if assignment.actor_code(nr) != assignment.gewerk_code:
                            continue        # nur Ein/Aus (Spiegel-, Rohrbegleitheizung)
                        offers.append(TemperatureOffer(
                            device, room, be, assignment, nr, co,
                            _thermostats(room, assignment.gewerk_code, nr)))
    return shortages, offers


def use_taster_temperature(project, offer: TemperatureOffer, remove_thermostats: bool) -> int:
    """Raumtemperatur des Heizungselements über den Taster erfassen; auf
    Wunsch die Raumthermostate dieses Elements entfernen. Anzahl entfernter."""
    from .button_move import remove_bedienelement
    offer.assignment.temperature_sources[offer.element_number] = offer.bedienelement.taster_index
    removed = 0
    if remove_thermostats:
        for be in offer.thermostats:
            remove_bedienelement(offer.room, be)
            removed += 1
    return removed


def temperature_source_of(room, assignment, nr: int):
    """Bedienelement, das die Raumtemperatur des Elements liefert, sonst None."""
    index = assignment.temperature_sources.get(nr)
    if index is None:
        return None
    return next((be for be in room.bedienelemente if not be.suppressed
                 and be.element_type == "Tastereinheit" and be.taster_index == index), None)


# ── Zu wenige Tasten lösen (FA-1411c) ──

def split_surplus(project, shortage: KeyShortage):
    """Die überzähligen Tasten (die letzten) auf eine zweite Tastereinheit im
    selben Raum legen, wie die Aufteilung eines Aktors. Gibt das neue
    Bedienelement zurück; sein Gerät entsteht bei der Neuberechnung."""
    from .button_move import _main_functions, add_bedienelement, move_button
    be = shortage.bedienelement
    surplus = _main_functions(be)[shortage.available:]
    if not surplus:
        return None
    new_be = add_bedienelement(shortage.room, "Tastereinheit", len(surplus))
    labels = project.ets_corrections.button_labels
    for sf in surplus:
        move_button(be, sf, new_be, labels=labels)
    return new_be


def copy_device_product(source, target) -> None:
    """Produkt eines Geräts auf ein anderes übernehmen (zweiter Taster nach
    dem Aufteilen); die KO-Zuordnung beginnt neu."""
    import copy
    for name in ("manufacturer", "manufacturer_id", "order_number", "product_name",
                 "product_ref_id", "hw2prog_id", "secure_supported", "bus_current"):
        setattr(target, name, getattr(source, name))
    target.communication_objects = [copy.deepcopy(co) for co in source.communication_objects]
    target.channel_map, target.co_map = {}, {}


@dataclass
class ProductOption:
    product: object           # ProductSuggestion
    capabilities: Capabilities
    same_manufacturer: bool


def products_with_keys(catalog, device, needed: int) -> list[ProductOption]:
    """Taster aus dem Katalog mit mindestens needed Tasten, zuerst gleicher
    Hersteller und dieselben Fühler (z.B. Temperatur), dann knapp passend."""
    from .product_sync import communication_objects_of
    current = set(device_capabilities(device).sensors)
    options = []
    for prod in catalog.search_sensors(""):
        if not _PUSH_BUTTON.search(f"{prod.product_name} {prod.sensor_type}"):
            continue
        cos = communication_objects_of(prod.com_objects) if prod.co_count else []
        caps = capabilities(cos, prod.product_name)
        if caps.keys < needed:
            continue
        options.append(ProductOption(
            prod, caps, (prod.manufacturer or "").lower() == (device.manufacturer or "").lower()))
    options.sort(key=lambda o: (not o.same_manufacturer,
                                not current <= set(o.capabilities.sensors),
                                o.capabilities.keys, o.product.product_name))
    return options


def apply_catalog_product(device, prod, be=None) -> None:
    """Katalogprodukt einem Gerät zuweisen wie in der Materialliste."""
    from .product_sync import communication_objects_of
    if (device.manufacturer, device.order_number) != (prod.manufacturer, prod.order_number):
        device.channel_map, device.co_map = {}, {}
    device.apply_product(prod)
    if prod.com_objects:
        device.communication_objects = communication_objects_of(prod.com_objects)
        from .ko_names import apply_to_device
        apply_to_device(device)        # gemerkte KO-Texte (FA-1411d)
    if be is not None:
        keys = capabilities(device.communication_objects, prod.product_name).keys
        if keys or prod.channels:
            be.channels = max(keys or prod.channels, planned_keys(be))


def fit_taster_channels(project, be) -> bool:
    """Tastenzahl einer Tastereinheit auf ihr Produkt setzen (8 bei EDIZIOdue
    1-8fach), nie unter die belegten Tasten: eine entfernte Taste hinterlässt
    so keinen leeren Platz, den das Gerät gar nicht hat. True bei Änderung."""
    if be is None or be.element_type != "Tastereinheit" or not be.participant_number:
        return False
    device = next((d for area in project.topology.areas for line in area.lines
                   for d in line.devices if d.physical_address == be.participant_number), None)
    if device is None:
        return False
    keys = device_capabilities(device).keys
    if not keys:
        return False
    channels = max(keys, planned_keys(be))
    if be.channels == channels:
        return False
    be.channels = channels
    return True


def temperature_gas_of(project, device) -> list:
    """IST-GAs, deren Raumtemperatur dieser Taster liefert (FA-1411b), mit
    dem Temperatur-KO: [(GroupAddress, CommunicationObject | None)]."""
    from .button_move import bedienelement_of_device
    room, be = bedienelement_of_device(project, device)
    if be is None or be.element_type != "Tastereinheit":
        return []
    co = device_capabilities(device).sensors.get(TEMPERATURE)
    result = []
    for assignment in room.gewerk_assignments:
        for nr, index in assignment.temperature_sources.items():
            if index != be.taster_index:
                continue
            ist = next((ga for ga in project.group_addresses.all_addresses()
                        if ga.assignment_id == assignment.id and ga.element_number == nr
                        and ga.function_name == "IST"), None)
            if ist is not None:
                result.append((ist, co))
    return result
