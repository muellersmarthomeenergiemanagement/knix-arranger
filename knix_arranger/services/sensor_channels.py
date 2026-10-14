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

from .actor_channels import _FEEDBACK_FUNCTION, _co_by_dpt, _norm, circuit_key, suggest_co
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


def ga_key(ga) -> str:
    """Stabiler Schlüssel einer GA: Element und Funktion, ohne Element die
    Bezeichnung (Zentral, Szenen, Zusatzsensorik)."""
    if ga.room_id and ga.gewerk_code and ga.element_number:
        return f"{circuit_key(ga.room_id, ga.gewerk_code, ga.element_number)}|{ga.function_name}"
    if ga.assignment_id.startswith("be:"):
        return f"{ga.assignment_id}|{ga.function_name}"
    return f"GA|{ga.designation}"


def sensor_plan(project):
    """Belegungsplan mit aufgefrischten Funktionszuordnungen, ohne das
    Projekt zu verändern -- für mehrere sensor_links-Aufrufe einmal."""
    from .belegungsplan_service import BelegungsplanService
    from .sensor_service import project_for_export
    return BelegungsplanService().generate(project_for_export(project))


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
    return links


def _receives(ga, device) -> bool:
    """Empfängt das Gerät die GA? Am KO gleichen Namens erkennbar (Schreib-
    Flag, kein Senden), sonst an der Funktion (RM/Status)."""
    co = _named_co(device.communication_objects, ga.function_name)
    if co is not None:
        flags = co.flags or ""
        return ("Ü" in flags or "W" in flags) and "S" not in flags
    return bool(_FEEDBACK_FUNCTION.match(ga.function_name or ""))


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


def _channel_cos(cos: list, channel: str) -> list:
    """KOs, deren Text zur Taste/zum Kanal passt ("Taste 1" -> "Taste 1",
    "T1", "Kanal 1", "Button 1"); ohne Treffer alle."""
    found = _NUMBER.search(channel or "")
    if not found:
        return cos
    n = found.group(1)
    pattern = re.compile(rf"(?:taste|kanal|button|channel|wippe|rocker|t|k|p|ch)\s*{n}\b",
                         re.IGNORECASE)
    own = [co for co in cos if pattern.search(f"{co.name} {co.object_function}")]
    return own or cos


# Sendende KOs für Befehle an den Aktor, nach Vorrang: ein Melder schaltet
# das Licht über seinen Ausgang (6131/40: «P1: Bewegung (Master)»,
# Obj_SwitchOnOff), ein Taster über «Schalten»
_SEND_KEYWORDS = {
    "E/A": ("switchonoff", "ausgang", "output", "schalten", "switch", "master"),
}


def _sends(co) -> bool:
    return "S" in (co.flags or "")


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
    for link in rest:
        candidates = [c for c in _channel_cos(all_cos, link.channel)
                      if c.object_number not in used]
        co = None
        # Den Befehl sendet der Sensor (S-Flag), die Rückmeldung empfängt er
        # (LED, Status)
        if not link.feedback:
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
        if co is None and link.dpt:
            co = _co_by_dpt(candidates, link.dpt, link.feedback, used)
        if co is not None:
            result[link.key] = co.object_number
            used.add(co.object_number)
    return result


def sensor_co_map(device) -> dict[str, int]:
    return dict((device.co_map or {}).get(SENSOR_CO_KEY) or {})


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
    return next((co for co in device.communication_objects if co.object_number == number), None)
