"""
KOs eines Tasters/Sensors den Gruppenadressen zuordnen (FA-3007, Materialliste ›
«Kanäle und KOs zuordnen…», je Gerät).

Bedienelemente bringen weit mehr KOs mit als ihre Tasten: in den .knxprod
von ABB/Busch-Jaeger haben Taster im Median rund 115 KOs (LED, Szenen,
Logik, Temperaturregler, Helligkeit/Annäherung, Display), der Busch-Watchdog
Sky 6131/40 knapp 100. Welcher KO auf welche GA kommt, ist je Gerät zu
wählen -- die KO-Nummern hängen in der ETS zudem von den Parametern ab
(6131/40: KO 1 ist «Freigabe Bewegung» oder «Ausgang 1»).

GAs eines Geräts (sensor_links), je mit Kanal/Taste:
- die es sendet oder empfängt (Belegungsplan: Taste 1 -> L E/A, Status 1 <-
  L RM, Kanal 1 eines Melders -> L E/A);
- die seines eigenen Gewerk-Elements (Gewerk ohne Aktor, z.B. A:
  «P1: Bewegung», product_sync.sensor_owns_gewerk);
- seine Zusatzfunktionen (Taster-Zusatzsensorik, Pseudo-Gewerk TS).

Gespeichert in Device.co_map[SENSOR_CO_KEY] = {ga_key: KO-Nummer, -1 = nicht
verknüpfen}; ga_key bleibt beim Neuerzeugen der GAs gleich (Element und
Funktion statt Adresse). Die KO-Verknüpfung (co_linking_service) verbindet
die GA dann mit genau diesem KO.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .actor_channels import _co_by_dpt, _norm, circuit_key, suggest_co
from .gewerk_channel_matching import _is_feedback_co

SENSOR_CO_KEY = "GA"


@dataclass
class SensorLink:
    key: str              # ga_key
    channel: str          # "Taste 1", "Status 1", "Kanal 1", "Gewerk A 1", "Zusatzfunktion"
    function: str         # "Licht schalten", "P1: Bewegung"
    ga_address: str
    ga_designation: str
    ga_function: str      # Funktion der GA, z.B. "E/A", "RM", "P1: Bewegung"
    dpt: str
    feedback: bool        # GA wird empfangen (LED, Status)
    role: str = ""        # Querverknüpfung (SENSOR_ROLES), z.B. "aktorstatus"


@dataclass(frozen=True)
class SensorRole:
    """KO eines Sensors, der an eine vorhandene GA des Elements gehört, das
    der Sensor bedient -- statt einer eigenen GA."""
    code: str
    label: str
    target: str                  # "befehl" = Befehls-GA (E/A), "rueckmeldung" = RM
    keywords: tuple[str, ...]    # zusammengeschrieben, klein


# Projekt_23 6131/40 schaltet L «Deckenlicht»: «P1: Aktorstatus» hört auf
# die RM des Lichts (Melder weiss, dass jemand von Hand geschaltet hat),
# «P1: Externer Taster» auf dessen E/A (Taster an der Wand)
SENSOR_ROLES: tuple[SensorRole, ...] = (
    SensorRole("aktorstatus", "Aktorstatus", "rueckmeldung",
               ("aktorstatus", "actuatorstatus", "statusaktor", "inputonoff")),
    SensorRole("extern", "Externer Taster", "befehl",
               ("externertaster", "externalswitch", "externalpushbutton",
                "externerschalter", "nebenstelle")),
)


# «Externe Helligkeit»: der Melder misst selbst, kann aber die Helligkeit
# einer Wetterstation (W: HELLIGKEIT SUED/OST/WEST) oder eines anderen
# Melders («BR: Helligkeit») übernehmen -- je Kanal eine Quelle; Vorgabe Süd
# vor Ost/West vor anderen Meldern, im Dialog wählbar (Device.co_map
# [SOURCE_KEY] = {Link-Schlüssel: ga_key der Quelle})
BRIGHTNESS_ROLE = SensorRole("helligkeit", "Externe Helligkeit", "quelle",
                             ("externehelligkeit", "externalbrightness", "helligkeitextern"))
SOURCE_KEY = "GA-Quelle"

# Raumtemperatur aus einem Taster mit eingebautem Fühler (FA-1411b): der
# Taster sendet auf die IST-GA der Heizung seines Raums, wenn das Element
# ihn als Quelle hat (GewerkAssignment.temperature_sources); das KO findet
# product_capabilities (z.B. EDIZIOdue colore KO 70 «Raumtemperatur»)
TEMPERATURE_ROLE = SensorRole("raumtemperatur", "Raumtemperatur", "messwert", ())
_BRIGHTNESS = re.compile(r"helligkeit|brightness|\blux\b", re.IGNORECASE)
_NOT_BRIGHTNESS = re.compile(r"schwelle|threshold|extern|anpassung|unabh", re.IGNORECASE)
_DIRECTION_ORDER = ("SUED", "SÜD", "OST", "WEST")


def brightness_sources(project, device) -> list:
    """GAs, die eine Helligkeit in Lux melden (DPT 9), ohne die eigenen des
    Geräts: Wetterstation zuerst (Süd, Ost, West), dann andere Melder."""
    from .actor_channels import _dpt_key
    from .product_sync import device_elements
    own = {a.id for _room, a, _nr in device_elements(project, device)}
    found = [ga for ga in project.group_addresses.all_addresses()
             if not ga.is_placeholder and ga.assignment_id not in own
             and _dpt_key(ga.datapoint_type)[0] == "9"
             and _BRIGHTNESS.search(ga.function_name or "")
             and not _NOT_BRIGHTNESS.search(ga.function_name or "")]

    def order(ga):
        upper = (ga.function_name or "").upper()
        direction = next((i for i, d in enumerate(_DIRECTION_ORDER) if d in upper),
                         len(_DIRECTION_ORDER))
        return (ga.gewerk_code != "W", direction, ga.main_group, ga.middle_group, ga.sub_group)
    return sorted(found, key=order)


def _add_brightness_links(project, device, links: list) -> None:
    """Je Kanal des Melders ein Link «Externe Helligkeit» zur gewählten bzw.
    vorgegebenen Quelle -- nur, wenn das Gerät einen solchen KO hat."""
    if not _role_cos(device.communication_objects, BRIGHTNESS_ROLE):
        return
    sources = brightness_sources(project, device)
    if not sources:
        return
    by_key = {ga_key(ga): ga for ga in sources}
    chosen = (device.co_map or {}).get(SOURCE_KEY) or {}
    channels = sorted({link.channel for link in links if not link.role
                       and re.match(r"^(?:Kanal|Gewerk \S+) \d+$", link.channel)}) or ["Gerät"]
    for channel in channels:
        key = f"{channel}#{BRIGHTNESS_ROLE.code}"
        ga = by_key.get(chosen.get(key, "")) or sources[0]
        links.append(SensorLink(key, channel, BRIGHTNESS_ROLE.label, ga.address,
                                ga.designation, ga.function_name, ga.datapoint_type,
                                True, BRIGHTNESS_ROLE.code))


def _role_cos(cos: list, role: SensorRole) -> list:
    return [co for co in cos
            if any(kw in re.sub(r"[^a-z0-9äöü]", "", f"{co.name} {co.object_function}".lower())
                   for kw in role.keywords)]


def ga_key(ga) -> str:
    """Stabiler Schlüssel einer GA: Element und Funktion, ohne Element die
    Bezeichnung (Zentral, Szenen, Zusatzsensorik)."""
    if ga.room_id and ga.gewerk_code and ga.element_number:
        return f"{circuit_key(ga.room_id, ga.gewerk_code, ga.element_number)}|{ga.function_name}"
    if ga.assignment_id.startswith("be:"):
        return f"{ga.assignment_id}|{ga.function_name}"
    return f"GA|{ga.designation}"


def sensor_plan(project, fresh: bool = False):
    """Belegungsplan mit aufgefrischten Funktionszuordnungen, ohne das
    Projekt zu verändern -- für mehrere sensor_links-Aufrufe einmal.
    fresh: die Tastenbelegung des Projekts ist schon aktuell (Hauptfenster
    nach refresh_bedienelemente), dann ohne Kopie des ganzen Projekts."""
    from .belegungsplan_service import BelegungsplanService
    from .sensor_service import project_for_export
    return BelegungsplanService().generate(project if fresh else project_for_export(project))


def sensor_links(project, device, plan=None) -> list[SensorLink]:
    """GAs, die ein Sensor sendet, empfängt oder selbst trägt; plan: siehe
    sensor_plan."""
    from .button_move import bedienelement_of_device
    from .product_sync import device_elements, sensor_owns_gewerk

    gas = [ga for ga in project.group_addresses.all_addresses() if not ga.is_placeholder]
    by_address = {ga.address: ga for ga in gas}
    links: list[SensorLink] = []
    seen: set[str] = set()

    def add(ga, channel: str, function: str, feedback: bool) -> None:
        key = ga_key(ga)
        if key in seen:
            return
        seen.add(key)
        links.append(SensorLink(key, channel, function, ga.address, ga.designation,
                                ga.function_name, ga.datapoint_type, feedback))

    # Bedienung laut Belegungsplan
    if plan is None:
        plan = sensor_plan(project)
    for row in plan.sensor_rows:
        ga = by_address.get(row.ga_address)
        if row.physical_address == device.physical_address and ga is not None:
            label = row.taste_label + (f" {row.action_type}" if row.action_type else "")
            add(ga, label.strip(), row.function or ga.function_name, row.is_feedback)

    # Rollen: vorhandene GAs der bedienten Elemente (Aktor-Gewerke)
    _add_role_links(device, links, gas, by_address, sensor_owns_gewerk)

    # Eigenes Element (Gewerk ohne Aktor)
    for _room, assignment, nr in device_elements(project, device):
        if not sensor_owns_gewerk(assignment.gewerk_code):
            continue
        for ga in gas:
            if ga.assignment_id == assignment.id and ga.element_number == nr:
                add(ga, f"Gewerk {assignment.gewerk_code} {nr}", ga.function_name,
                    _receives(ga, device))

    # Zusatzfunktionen des Bedienelements (Taster-Zusatzsensorik)
    _room, be = bedienelement_of_device(project, device)
    if be is not None:
        for ga in gas:
            if ga.assignment_id == f"be:{be.id}":
                add(ga, "Zusatzfunktion", ga.function_name, _receives(ga, device))
    _add_brightness_links(project, device, links)
    _add_temperature_links(project, device, links, gas)
    # Je Taste/Kanal beisammen (Kanal 1: Licht schalten, Aktorstatus, ...)
    links.sort(key=lambda link: [int(part) if part.isdigit() else part
                                 for part in re.split(r"(\d+)", link.channel)])
    return links


def _add_temperature_links(project, device, links: list[SensorLink], gas: list) -> None:
    """IST-GA der Heizungselemente, deren Raumtemperatur dieser Taster liefert."""
    from .button_move import bedienelement_of_device
    room, be = bedienelement_of_device(project, device)
    if be is None or be.element_type != "Tastereinheit":
        return
    for assignment in room.gewerk_assignments:
        for nr, index in assignment.temperature_sources.items():
            if index != be.taster_index:
                continue
            ist = next((ga for ga in gas if ga.assignment_id == assignment.id
                        and ga.element_number == nr and ga.function_name == "IST"), None)
            if ist is None:
                continue
            links.append(SensorLink(
                f"{ga_key(ist)}#{TEMPERATURE_ROLE.code}", "Raumtemperatur",
                TEMPERATURE_ROLE.label, ist.address, ist.designation, ist.function_name,
                ist.datapoint_type, False, TEMPERATURE_ROLE.code))


def _add_role_links(device, links: list[SensorLink], gas: list, by_address: dict,
                    sensor_owns_gewerk) -> None:
    """Je Befehls-GA eines bedienten Elements (Kanal 1 -> L E/A) die Rollen,
    für die das Gerät einen KO hat; die Rückmeldung nur, wenn das Gerät sie
    nicht schon empfängt (Taster-LED)."""
    from .sensor_service import GEWERK_FEEDBACK_FUNCTIONS, GEWERK_PRIMARY_FUNCTIONS
    roles = [role for role in SENSOR_ROLES if _role_cos(device.communication_objects, role)]
    if not roles:
        return
    by_function = {(ga.room_id, ga.gewerk_code, ga.element_number, ga.function_name): ga
                   for ga in gas if ga.room_id}
    received = {link.ga_address for link in links if link.feedback}
    for link in list(links):
        ga = by_address.get(link.ga_address)
        if link.feedback or link.role or ga is None or not ga.room_id:
            continue
        primary = [fn for _l, fn, *_rest in GEWERK_PRIMARY_FUNCTIONS.get(ga.gewerk_code, [])[:1]]
        if sensor_owns_gewerk(ga.gewerk_code) or ga.function_name not in primary:
            continue
        feedback = [fn for _l, fn, _d in GEWERK_FEEDBACK_FUNCTIONS.get(ga.gewerk_code, [])[:1]]
        for role in roles:
            if role.target == "befehl":
                target = ga
            else:
                target = by_function.get((ga.room_id, ga.gewerk_code, ga.element_number,
                                          feedback[0])) if feedback else None
                if target is None or target.address in received:
                    continue
            links.append(SensorLink(
                f"{ga_key(target)}#{role.code}", link.channel, role.label, target.address,
                target.designation, target.function_name, target.datapoint_type,
                True, role.code))


def _receives(ga, device) -> bool:
    """Empfängt das Gerät die GA? Am KO gleichen Namens erkennbar (Schreib-
    Flag, kein Senden), sonst an der Funktion (RM/Status)."""
    co = _named_co(device.communication_objects, ga.function_name)
    if co is not None:
        from .ko_links import TRANSMIT, WRITE, parse_flags
        flags = parse_flags(co.flags)
        return WRITE in flags and TRANSMIT not in flags
    from .ko_plausibility import is_feedback_function
    return is_feedback_function(ga.function_name or "")


def _named_co(cos: list, text: str):
    """KO, dessen Funktion oder Name dem Text entspricht -- die GAs aus
    Produkt-KOs heissen wie der KO, ohne Klammerzusatz («P1: Bewegung
    (Master)» -> «P1: Bewegung», address_generator); bei mehreren der erste."""
    from .address_generator import _com_object_function_name
    target = (text or "").strip().lower()
    if not target:
        return None
    for co in cos:
        if target in ((co.object_function or "").strip().lower(), (co.name or "").strip().lower()):
            return co
    for co in cos:
        name = _com_object_function_name({"function_text": co.object_function, "name": co.name})
        if name.strip().lower() == target:
            return co
    return None


_NUMBER = re.compile(r"(\d+)")
_LEADING_CHANNEL = re.compile(r"^([A-Za-zÄÖÜäöü]+ ?)(\d+)(\b.*)$")


def _nth_channel(function: str, nth: int) -> str:
    """«P1: Bewegung» -> «P2: Bewegung» für das zweite Vorkommen (nth=1)."""
    found = _LEADING_CHANNEL.match(function or "")
    if not found or not nth:
        return function
    prefix, number, rest = found.groups()
    return f"{prefix}{int(number) + nth}{rest}"


_RIGHT_SIDE = re.compile(r"\b(?:rechts|right|droite|destra)\b", re.IGNORECASE)
_KEY_CHANNEL = re.compile(r"^\s*(?:taste|status)\b", re.IGNORECASE)


def _is_rocker_product(cos: list) -> bool:
    """Produkt mit Wippen: KOs je Taste links (ohne Zusatz) und «rechts»
    (Feller EDIZIOdue «Taste 1», «Taste 1, rechts»)."""
    return any(_RIGHT_SIDE.search(f"{co.name} {co.object_function}") for co in cos)


def _channel_cos(cos: list, channel: str) -> list:
    """KOs, deren Text zur Taste/zum Kanal passt ("Taste 1" -> "Taste 1",
    "T1", "Kanal 1", "Button 1"); ohne Treffer alle.

    Wippen-Produkte: KNiX zählt jede Seite als eigene Taste -- Taste 1 =
    Wippe 1 links, Taste 2 = Wippe 1 rechts, Taste 3 = Wippe 2 links usw.
    (ebenso «Status n» für die Rückmeldung der Taste n)."""
    found = _NUMBER.search(channel or "")
    if not found:
        return cos
    n = int(found.group(1))
    rocker = _KEY_CHANNEL.match(channel or "") and _is_rocker_product(cos)
    product_key = (n + 1) // 2 if rocker else n
    pattern = re.compile(
        rf"\b(?:taste|kanal|button|channel|wippe|rocker|t|k|p|ch)\s*{product_key}\b",
        re.IGNORECASE)
    own = [co for co in cos if pattern.search(f"{co.name} {co.object_function}")]
    if rocker:
        right = n % 2 == 0
        own = [co for co in own
               if bool(_RIGHT_SIDE.search(f"{co.name} {co.object_function}")) == right]
    return _with_generic_followers(cos, own) or cos


def _with_generic_followers(cos: list, own: list) -> list:
    """Generische KOs («Object 2») direkt hinter einem KO der Taste gehören
    zur Taste, bis zum nächsten benannten KO (EDIZIOdue: KO 0 «Taste 1, links»,
    KO 1 «Object 2» = Dimmen, KO 2 «Taste 1, links, Signal LED»)."""
    if not own:
        return own
    from .ko_names import is_generic
    own_ids = {id(co) for co in own}
    result = list(own)
    following = False
    for co in sorted(cos, key=lambda c: c.object_number):
        if id(co) in own_ids:
            following = True
        elif not is_generic(co):
            following = False
        elif following:
            result.append(co)
    return result


# Sendende KOs für Befehle an den Aktor, nach Vorrang: ein Melder schaltet
# das Licht über seinen Ausgang (6131/40: «P1: Bewegung (Master)»,
# Obj_SwitchOnOff), ein Taster über «Schalten»
_SEND_KEYWORDS = {
    "E/A": ("switchonoff", "ausgang", "output", "schalten", "switch", "master"),
}


def _sends(co) -> bool:
    from .ko_links import TRANSMIT, parse_flags
    return TRANSMIT in parse_flags(co.flags)


def _is_status(co) -> bool:
    """Status-/Rückmelde-KO am Text -- anders als bei Aktoren (actor_channels.
    _is_feedback) nicht an den Flags: ein Sensor sendet auch seine Befehle."""
    text = _norm(f"{co.object_function or ''} {co.name or ''}")
    return _is_feedback_co(co) or "feedback" in text or "status" in text


def suggested_sensor_co_map(device, links: list[SensorLink], all_cos: list) -> dict[str, int]:
    """Vorschlag ga_key -> KO-Nummer. Zuerst die GAs aus Produkt-KOs (gleicher
    Name), dann die übrigen: Stichworte der GA-Funktion in den KOs der Taste,
    sonst der erste KO der Taste mit passendem DPT. Ein KO darf mehrere GAs
    haben (in der ETS sendet er auf der ersten, hört auf die weiteren) -- ein
    Melder schaltet über «P1: Bewegung (Master)» auch das Licht; innerhalb
    jedes Durchgangs aber nur einmal (Taste 1 kurz und lang)."""
    result: dict[str, int] = {}
    named_used: set[int] = set()
    occurrences: dict[str, int] = {}
    rest = []
    for link in links:
        if link.role:
            rest.append(link)
            continue
        free = [c for c in all_cos if c.object_number not in named_used]
        # Zweites Element mit denselben Namen (Garage: A ×2 an einem 6131/40,
        # beide «P1: Bewegung») -> der zweite Kanal des Geräts «P2: …»
        nth = occurrences.get(link.ga_function, 0)
        occurrences[link.ga_function] = nth + 1
        co = _named_co(free, _nth_channel(link.ga_function, nth)) if nth else None
        if co is None:
            co = _named_co(free, link.ga_function)
        if co is None:
            rest.append(link)
            continue
        result[link.key] = co.object_number
        named_used.add(co.object_number)
    used: set[int] = set()
    # Befehle vor Rückmeldungen: die Rückmeldung kann am KO des Befehls mithören
    rest.sort(key=lambda link: bool(link.feedback))
    for link in rest:
        candidates = [c for c in _channel_cos(all_cos, link.channel)
                      if c.object_number not in used]
        co = None
        role = next((r for r in SENSOR_ROLES + (BRIGHTNESS_ROLE, TEMPERATURE_ROLE)
                     if r.code == link.role), None)
        if role is TEMPERATURE_ROLE:
            from .product_capabilities import TEMPERATURE, capabilities
            co = capabilities(all_cos).sensors.get(TEMPERATURE)
        elif role is not None:
            co = next(iter(_role_cos(candidates, role)), None)
        # Den Befehl sendet der Sensor (S-Flag), die Rückmeldung empfängt er
        # (LED, Status)
        elif not link.feedback:
            sending = [c for c in candidates if _sends(c) and not _is_status(c)]
            for kw in _SEND_KEYWORDS.get(link.ga_function, ()):
                co = next((c for c in sending
                           if kw in f"{c.name} {c.object_function}".lower()), None)
                if co is not None:
                    break
            if co is None:
                co = suggest_co(sending, link.ga_function, used)
        else:
            co = suggest_co(candidates, link.ga_function, used)
        if co is None and link.dpt and role is None:
            co = _co_by_dpt(candidates, link.dpt, link.feedback, used)
        if co is None and role is None:
            # «Taste» ohne Nummer (Einzeltaster) = Taste 1
            channel = link.channel if _NUMBER.search(link.channel or "") \
                else f"{link.channel} 1"
            if _own_channel(all_cos, channel):
                own = [c for c in _channel_cos(all_cos, channel) if c.object_number not in used]
                co = _key_fallback(own, link, result, all_cos)
        if co is not None:
            result[link.key] = co.object_number
            used.add(co.object_number)
    return result


def _own_channel(cos: list, channel: str) -> bool:
    """Hat die Taste/der Kanal eigene KOs (nicht nur alle des Geräts)?"""
    return _channel_cos(cos, channel) is not cos


def _key_fallback(candidates: list, link: SensorLink, result: dict, all_cos: list):
    """Taster mit KOs ohne sprechenden Text und ohne DPT (Feller EDIZIOdue:
    «Taste 1», «Taste 1, Signal-LED»): der Befehl auf das nächste sendende KO
    der Taste (Schalten, dann Dimmen), die Rückmeldung auf das KO des Befehls
    desselben Elements, wenn es schreibt (hört mit), sonst auf ein
    empfangendes KO der Taste (Signal-LED)."""
    from .ko_links import TRANSMIT, WRITE, parse_flags
    if not link.feedback:
        return next((c for c in candidates
                     if TRANSMIT in parse_flags(c.flags) and not _is_status(c)), None)
    # Nur Schaltzustand (1 Bit): ein Wert gehört nicht auf ein Tasten-KO
    dpt = (link.dpt or "").upper().replace("DPST-", "DPT-")
    if dpt.split("-")[1:2] not in (["1"], []) or (not dpt and link.ga_function != "RM"):
        return None
    element = link.key.rsplit("|", 1)[0]
    by_number = {c.object_number: c for c in all_cos}
    for key, number in result.items():
        co = by_number.get(number)
        if key.rsplit("|", 1)[0] == element and co is not None \
                and WRITE in parse_flags(co.flags):
            return co
    return next((c for c in candidates
                 if WRITE in parse_flags(c.flags) and TRANSMIT not in parse_flags(c.flags)),
                None)


def sensor_co_map(device) -> dict[str, int]:
    return dict((device.co_map or {}).get(SENSOR_CO_KEY) or {})


def has_sensor_selection(device) -> bool:
    """Mindestens ein KO zugeordnet -- nur «nicht verknüpfen» (z.B. weil der
    Vorschlag früher nichts fand) gilt als noch nicht zugeordnet."""
    return any(number >= 0 for number in sensor_co_map(device).values())


def chosen_sensor_co(device, ga):
    """KO laut Auswahl für diese GA: CommunicationObject, False für «nicht
    verknüpfen», None ohne Auswahl."""
    selection = sensor_co_map(device)
    key = ga_key(ga)
    if key not in selection:
        return None
    number = selection[key]
    if number < 0:
        return False
    from .ko_links import co_by_number
    return co_by_number(device.communication_objects, number)
