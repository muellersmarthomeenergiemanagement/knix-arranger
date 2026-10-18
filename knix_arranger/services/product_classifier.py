"""
Einordnung von Katalogprodukten: Kategorie, Gerätetyp und Kanalzahl aus
Produktname (deutsch, englisch, französisch) und Kommunikationsobjekten.

KNXPROD-Dateien führen die Produktklasse oft nicht (ApplicationArea fehlt);
bisher landete dann alles als "Schaltaktor" in der Kategorie Aktor --
Bedienelemente, Präsenzmelder, Raumtemperaturregler, Sicherheitsmodule --
und fast alle Gateways als "Sonstiges". Die Regeln hier sind an den
Produktnamen echter Herstellerkataloge (ABB, Busch-Jaeger, Hager, Theben,
MDT, Gira, Siemens, Weinzierl, …) ausgerichtet; die erste passende gilt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ACTOR, SENSOR, INFRA = "actor", "sensor", "infrastructure"

# Gerätetypen nach Gruppe (Reihenfolge = Anzeige im Produktdialog)
TYPE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Aktoren", ("Schaltaktor", "Dimmaktor", "Jalousieaktor", "Schalt-/Jalousieaktor",
                 "Heizungsaktor", "Fan-Coil-Aktor", "Analogaktor", "Ein-/Ausgabemodul")),
    ("Bedienung & Sensoren", ("Tastereinheit", "Raumthermostat", "Praesenzmelder",
                              "Bewegungsmelder", "Binäreingang", "Analogeingang",
                              "Wetterstation", "Temperaturfuehler", "Fensterkontakt",
                              "Energiezähler", "Sensor")),
    ("Gateways & Schnittstellen", ("DALI-Gateway", "DMX-KNX-Gateway", "Multimedia-Gateway",
                                   "Heizungs-Gateway", "Modbus-KNX-Gateway", "EnOcean-Gateway",
                                   "Klima-KNX-Gateway", "KNX-Schnittstelle",
                                   "Visualisierung / Server")),
    ("Systemgeräte", ("Linienkoppler", "Bereichskoppler", "IP-Router", "Netzteil",
                      "Logik / Zeit", "Sicherheit", "Zubehör", "Sonstiges")),
)


def type_group(device_type: str) -> str:
    for group, types in TYPE_GROUPS:
        if device_type in types:
            return group
    return "Systemgeräte"


@dataclass(frozen=True)
class Classification:
    category: str
    device_type: str
    channels: int = 0


def _r(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


# (Muster im Namen, Kategorie, Gerätetyp) -- spezifische vor allgemeinen.
# Reihenfolge in classify(): _EARLY_RULES, bei ausdrücklichem Aktor/Ausgang
# im Namen _ACTOR_RULES, dann _LATE_RULES, dann _ACTOR_RULES -- so bleibt
# "Dimmer 200 W + 2 inputs" ein Dimmaktor, "Universal Interface" ein Eingang.
_EARLY_RULES: tuple[tuple[re.Pattern, str, str], ...] = (
    # Systemgeräte
    (_r(r"area coupler|bereichskoppler|coupleur de zone"), INFRA, "Bereichskoppler"),
    (_r(r"line coupler|linienkoppler|coupleur de ligne|medienkoppler|media coupler|"
        r"coupleur de m[ée]dia|\bcoupler\b|\bkoppler\b"), INFRA, "Linienkoppler"),
    (_r(r"router|routeur"), INFRA, "IP-Router"),
    (_r(r"power supply|netzteil|spannungsversorgung|alimentation"), INFRA, "Netzteil"),
    # Gateways und Schnittstellen
    (_r(r"\bdali\b"), INFRA, "DALI-Gateway"),
    (_r(r"\bdmx\b"), INFRA, "DMX-KNX-Gateway"),
    (_r(r"revox|sonos|multiroom|audio gateway"), INFRA, "Multimedia-Gateway"),
    (_r(r"ot-box|opentherm|vitogate|boiler|chiller|heat pump|wärmepumpe|"
        r"waermepumpe|heizkessel|pompe à chaleur"), INFRA, "Heizungs-Gateway"),
    (_r(r"modbus"), INFRA, "Modbus-KNX-Gateway"),
    (_r(r"enocean"), INFRA, "EnOcean-Gateway"),
    (_r(r"pulse gateway|passerelle .*impulsion|tastere?i?n?gang|tasteriengang"),
     SENSOR, "Binäreingang"),
    (_r(r"schaltuhr|time switch|zeitschalt|\btimer\b|horloge"), INFRA, "Logik / Zeit"),
    (_r(r"split[ -]?unit|klima|air[ -]?condition|hvac gateway|climatisation|"
        r"\bac ir\b|ir gateway"),
     INFRA, "Klima-KNX-Gateway"),
    (_r(r"\busb\b|ip[ /-]*(?:knx )?interface|ip\s?secure interface|ip[ -]?schnittstelle|"
        r"knx[ /-]*ip|smart connect"), INFRA, "KNX-Schnittstelle"),
    # "display" allein nicht: "RTR fan coil with display" ist ein Regler
    (_r(r"domovea|visu|server|\btouch\b|roomtouch|smarttouch|smart touch|écran"),
     INFRA, "Visualisierung / Server"),
    (_r(r"\bac500\b|\bplc\b|\bsps\b|application controller|bacnet|"
        r"building automation controller"), INFRA, "Logik / Zeit"),
    (_r(r"gateway|passerelle"), INFRA, "KNX-Schnittstelle"),
    # Messen und Zähler
    (_r(r"meter|zähler|zaehler|energy analy|energie|compteur|consommation"),
     SENSOR, "Energiezähler"),
    # Sensoren und Bedienung
    (_r(r"weather|wetter|météo|meteo"), SENSOR, "Wetterstation"),
    (_r(r"presence|präsenz|praesenz|présence|compact (?:office|passage|passimo)|"
        r"eco-ir|thepa|theronda|planocentro|pirios|quattro"), SENSOR, "Praesenzmelder"),
    (_r(r"motion|bewegung|wächter|waechter|watchdog|mouvement"), SENSOR, "Bewegungsmelder"),
    (_r(r"room temperature controller|raumtemperaturregler|thermostat|"
        r"\brtr\b|hvac[\w/ ]{0,8}device|hvac-(?:slave-)?gerät|régulateur|regulateur"),
     SENSOR, "Raumthermostat"),
    (_r(r"window contact|fensterkontakt|contact de fenêtre|d[ée]tecteur d.ouverture|"
        r"opening detector"), SENSOR, "Fensterkontakt"),
    (_r(r"dämm?erung|daemm?erung|twilight|crépusculaire|leak|enthalpie|salva|"
        r"humidity|feuchte|"
        r"luftqualität|air quality|co2|luminosit|helligkeitssensor|light sensor|"
        r"lichtsensor|brightness sensor|détecteur|detecteur"), SENSOR, "Sensor"),
    (_r(r"temperature sensor|temperaturfühler|temperaturfuehler|"
        r"temperatursensor|sonde"), SENSOR, "Temperaturfuehler"),
    (_r(r"analog(?:ue)? input|analogeingang|entrée analogique"), SENSOR, "Analogeingang"),
    (_r(r"logic|logik|time switch|zeitschalt|astro|horloge"), INFRA, "Logik / Zeit"),
    (_r(r"security|sicherheit|alarm"), INFRA, "Sicherheit"),
)

_ACTOR_WORDS = _r(r"aktor|actuator|\bactor\b|sorties?\b|\boutputs?\b|ausgang|ausgänge|"
                  r"relais|relay|variateur|dimmer")

_LATE_RULES: tuple[tuple[re.Pattern, str, str], ...] = (
    (_r(r"binary input|binäreingang|binaereingang|universal interface|"
        r"universalschnittstelle|tasterschnittstelle|fensterschnittstelle|"
        r"pulse|impulsion|entrées?\b|"
        r"\binputs?\b"), SENSOR, "Binäreingang"),
    (_r(r"push[ -]?button|taster|control element|bedienelement|tastsensor|"
        r"triton|tacteo|solo|future|priOn|\bgang\b|\d+gang|télécommande|"
        r"telecommande|remote control|poussoir"), SENSOR, "Tastereinheit"),
    (_r(r"overvoltage|überspannung|dummy|cover|abdeckung|rahmen|frame|choke|"
        r"drossel|card holder"), INFRA, "Zubehör"),
)

# Aktoren (Kombi vor Einzel)
_ACTOR_RULES: tuple[tuple[re.Pattern, str, str], ...] = (
    (_r(r"switch/shutter|schalt-?/jalousie|switch.{0,4}blind"), ACTOR,
     "Schalt-/Jalousieaktor"),
    (_r(r"fan ?coil|ventilo"), ACTOR, "Fan-Coil-Aktor"),
    (_r(r"dimm|dimming|\bdim\b|variateur|dimmer"), ACTOR, "Dimmaktor"),
    (_r(r"shutter|blind|jalousie|rollladen|volet|store"), ACTOR, "Jalousieaktor"),
    (_r(r"heating|heizung|valve|ventil|vanne|chauffage|triac|thermal|thermo|"
        r"stellantrieb|positioner"), ACTOR, "Heizungsaktor"),
    (_r(r"analog(?:ue)? (?:actuator|output)|analogaktor"), ACTOR, "Analogaktor"),
    (_r(r"i/o|ein-?/ausgabe|concentrator"), ACTOR, "Ein-/Ausgabemodul"),
    (_r(r"switch|schalt|sorties?|outputs?|ausgang|ausgänge|relais|relay|actuator|aktor"),
     ACTOR, "Schaltaktor"),
    # Allgemeine Schnittstellen erst zum Schluss (Universal Interface = Eingang)
    (_r(r"interface|schnittstelle"), INFRA, "KNX-Schnittstelle"),
)

# Kurzbezeichnungen (Theben, ABB) ohne sprechenden Namen
_CODE_RULES: tuple[tuple[re.Pattern, str, str], ...] = (
    (re.compile(r"^(?:SA/S|RM|RMG|SU/S)\b"), ACTOR, "Schaltaktor"),
    (re.compile(r"^(?:JA/S|JM|JMG|JRA/S)\b"), ACTOR, "Jalousieaktor"),
    (re.compile(r"^(?:UD/S|DM|DMG|DG/S)\b"), ACTOR, "Dimmaktor"),
    (re.compile(r"^(?:HA/S|HM|HMG|VAA/S)\b"), ACTOR, "Heizungsaktor"),
    (re.compile(r"^(?:BE/S|US/U|BM|BMG|TA)\b"), SENSOR, "Binäreingang"),
    (re.compile(r"^(?:ZS|TR|SU)\b"), INFRA, "Logik / Zeit"),
)

# Kommunikationsobjekte -> Gerätetyp, wenn der Name nichts hergibt
_CO_HINTS: tuple[tuple[re.Pattern, str, str], ...] = (
    (_r(r"jalousie|shutter|blind|lamelle|slat|volet|auf/ab|up/down"), ACTOR, "Jalousieaktor"),
    (_r(r"dimm|helligkeit|brightness|variation"), ACTOR, "Dimmaktor"),
    (_r(r"stellgr|heizen|heating|valve|ventil"), ACTOR, "Heizungsaktor"),
    (_r(r"taste|button|wippe|rocker"), SENSOR, "Tastereinheit"),
    (_r(r"schalten|switch|commutation"), ACTOR, "Schaltaktor"),
)

_CHANNELS = re.compile(
    r"(\d+)\s*[-‑]?\s*(?:fach|fold|f\b|gang|kanal|kanäle|channels?|sorties|"
    r"entrées|ausgänge|outputs?|inputs?|eingänge|voies)", re.I)
# ABB-Typenbezeichnung: SA/S8.10…, BE/S4.20… -- die Zahl ist nur bei
# Aktoren und Eingängen die Kanalzahl (SV/S30 = 30 V, MG/S11, LK/S4 …)
_ABB_CHANNELS = re.compile(r"\b[A-Z]{1,3}/[A-Z](\d+)\.\d")


def _channels_from_name(name: str, category: str) -> int:
    m = _CHANNELS.search(name)
    if not m and category in (ACTOR, SENSOR):
        m = _ABB_CHANNELS.search(name)
    n = int(m.group(1)) if m else 0
    return n if 0 < n <= 64 else 0


_DALI_GROUP = re.compile(r"\b(?:Gruppe|Group|Groupe)\s*(\d+)\b", re.I)


def dali_groups(com_objects) -> int:
    """Zahl der DALI-Gruppen eines Gateways aus den KOs («Gruppe 1» …
    «Gruppe 16»), 0 ohne erkennbare Gruppen. Bei DALI-Gateways ist das die
    Kapazität -- die Zahl im Namen nicht (ABB DLR/S8.16.1M «8f»: 8 Ausgänge,
    16 Gruppen)."""
    groups = set()
    for co in com_objects or []:
        for text in (co.get("name") or "", co.get("function_text") or ""):
            m = _DALI_GROUP.search(text)
            if m:
                groups.add(int(m.group(1)))
                break
    return len(groups) if len(groups) > 1 else 0


def _from_com_objects(com_objects) -> tuple[str, str] | None:
    if not com_objects:
        return None
    text = " ".join((co.get("function_text") or co.get("name") or "")
                    for co in com_objects[:400])
    best, best_count = None, 0
    for pattern, category, device_type in _CO_HINTS:
        count = len(pattern.findall(text))
        if count > best_count:
            best, best_count = (category, device_type), count
    return best if best_count >= 2 else None


def classify(product_name: str, order_number: str = "", category_hint: str = "",
             com_objects=None) -> Classification:
    """Kategorie, Gerätetyp und Kanalzahl eines Produkts.

    category_hint: Kategorie aus der Herstellerdatei (ApplicationArea), falls
    vorhanden -- bei einem Namen ohne Stichwort gilt sie mit einem
    allgemeinen Typ."""
    name = f"{product_name} {order_number}"
    rules = _EARLY_RULES + (_ACTOR_RULES if _ACTOR_WORDS.search(name) else ()) \
        + _LATE_RULES + _ACTOR_RULES
    found = next(((c, t) for p, c, t in rules if p.search(name)), None)
    if found is None:
        found = next(((c, t) for p, c, t in _CODE_RULES
                      if p.search(product_name) or p.search(order_number)), None)
    if found is None:
        found = _from_com_objects(com_objects)
    if found is None:
        found = {ACTOR: (ACTOR, "Schaltaktor"), SENSOR: (SENSOR, "Sensor")}.get(
            category_hint, (INFRA, "Sonstiges"))
    category, device_type = found
    channels = _channels_from_name(product_name, category)
    if not channels and com_objects:
        from .product_zones import zone_scheme, zones_of
        product = {"com_objects": com_objects}
        scheme = zone_scheme(product)
        if scheme is not None and scheme.label in ("Kanal", "Kanal C", "Ausgang", "Motor"):
            channels = len(zones_of(product))
    if device_type == "DALI-Gateway":
        channels = dali_groups(com_objects) or channels
    return Classification(category, device_type, channels)
