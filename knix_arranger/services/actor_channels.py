"""
Kanäle und Kommunikationsobjekte eines Aktors/Gateways den Stromkreisen
zuordnen (Materialliste › «Kanäle und KOs zuordnen…»).

Ohne Zuordnung verteilt der Belegungsplan die Stromkreise eines Geräts der
Reihe nach auf Kanal 1, 2, 3 … (nach Raumnummer). Mit Zuordnung gilt:
- Device.channel_map: Stromkreis -> Kanal im Gerät (Nummer, Name aus den
  KOs des Herstellers, z.B. "Kanal C", "Ausgang 5");
- Device.co_map: Stromkreis -> {GA-Funktion: KO-Nummer, -1 = nicht
  verknüpfen}. Die KO-Verknüpfung (co_linking_service) verbindet die GA
  dann mit genau diesem KO; KOs, die niemand braucht, bleiben frei.

Ein Stromkreis ist ein Element eines Gewerks in einem Raum, Schlüssel
circuit_key(room_id, gewerk_code, element_nr).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gewerk_channel_matching import _FUNCTION_KEYWORDS, _is_feedback_co


def circuit_key(room_id: str, gewerk_code: str, element_number: int) -> str:
    return f"{room_id}|{gewerk_code}|{element_number}"


@dataclass
class Circuit:
    """Ein Stromkreis, den ein Gerät bedient."""
    key: str
    room_number: str
    room_name: str
    gewerk_code: str
    element_number: int
    channel: int                                   # aktueller Kanal (Belegungsplan)
    functions: list[tuple[str, str]] = field(default_factory=list)  # (Funktion, GA)
    element_text: str = ""                         # z.B. "Licht 1 «Decke»"
    dpts: dict[str, str] = field(default_factory=dict)  # Funktion -> DPT der GA

    @property
    def label(self) -> str:
        element = self.element_text or f"{self.gewerk_code} {self.element_number}"
        return f"{self.room_number} {self.room_name} · {element}"


@dataclass
class DeviceChannel:
    """Ein Kanal im Gerät mit seinen KOs (leer ohne KNXPROD-Daten)."""
    number: int
    label: str
    com_objects: list = field(default_factory=list)


def _co_dicts(device) -> list[dict]:
    return [{"number": co.object_number, "name": co.name,
             "function_text": co.object_function}
            for co in device.communication_objects]


# Kanalerkennung je KO-Liste (Nummer, Name, Funktion) -> [(Kanal, Name,
# Positionen der KOs)] bzw. None ohne erkennbare Kanäle. Die Erkennung prüft
# jeden KO gegen alle Schreibweisen (product_zones) und lief je Neuberechnung
# hunderte Male für dieselben Geräte (Projekt_23: 1 s je Klick).
_ZONE_CACHE: dict[tuple, list | None] = {}
_ZONE_CACHE_MAX = 512


def _zones(device) -> list | None:
    from .knxprod_catalog_service import unique_com_objects
    from .product_zones import co_zone, zone_label, zone_scheme
    key = tuple((co.object_number, co.name, co.object_function)
                for co in device.communication_objects)
    if key in _ZONE_CACHE:
        return _ZONE_CACHE[key]
    product = {"com_objects": _co_dicts(device)}
    scheme = zone_scheme(product)
    result = None
    if scheme is not None:
        # Je KO-Nummer ein Eintrag (echter Text vor "{{0:GO}}"-Varianten)
        position = {id(data): i for i, data in enumerate(product["com_objects"])}
        by_zone: dict[int, list[int]] = {}
        for data in unique_com_objects(product["com_objects"]):
            zone = co_zone(data, scheme)
            if zone is not None:
                by_zone.setdefault(zone, []).append(position[id(data)])
        result = [(z, zone_label(product, z), positions)
                  for z, positions in sorted(by_zone.items())]
    if len(_ZONE_CACHE) >= _ZONE_CACHE_MAX:
        _ZONE_CACHE.clear()
    _ZONE_CACHE[key] = result
    return result


def device_channels(device, fallback_count: int = 0) -> list[DeviceChannel]:
    """Kanäle des Geräts in der Benennung des Herstellers (aus den KOs, siehe
    product_zones); ohne erkennbare Kanäle "Kanal 1…n" nach der Kanalzahl."""
    zones = _zones(device)
    if zones is not None:
        cos = device.communication_objects
        return [DeviceChannel(z, label, [cos[i] for i in positions])
                for z, label, positions in zones]
    from .belegungsplan_service import BelegungsplanService
    count = fallback_count or BelegungsplanService._parse_channel_count(device.product)
    if count >= 999:   # unbekannt
        count = 0
    return [DeviceChannel(n, f"Kanal {n}") for n in range(1, count + 1)]


def device_com_objects(device) -> list:
    """Alle KOs des Geräts, je Nummer einer (echter Text vor Platzhalter) --
    zur Auswahl von Hand, wenn die Kanäle nicht erkannt werden."""
    from .knxprod_catalog_service import unique_com_objects
    dicts = _co_dicts(device)
    by_id = {id(d): co for co, d in zip(device.communication_objects, dicts)}
    return [by_id[id(d)] for d in unique_com_objects(dicts)]


def channel_names(device) -> dict[int, str]:
    """Kanalnummer -> Name, nur wenn die KOs Kanäle erkennen lassen."""
    zones = _zones(device)
    return {} if zones is None else {z: label for z, label, _p in zones}


def _element_text(project, room, gewerk_code: str, element_number: int) -> str:
    """"Licht 1 «Decke»" aus Gewerkname und Element-Bezeichnung."""
    gewerk = project.gewerk_catalog.get(gewerk_code)
    text = f"{gewerk.name if gewerk else gewerk_code} {element_number}"
    assignment = next((a for a in (room.gewerk_assignments if room else [])
                       if a.gewerk_code == gewerk_code), None)
    label = assignment.element_label(element_number) if assignment else ""
    return f"{text} «{label}»" if label else text


def device_circuits(project, device, plan=None) -> list[Circuit]:
    """Stromkreise, die das Gerät laut Belegungsplan bedient, mit aktuellem
    Kanal und GA-Funktionen. plan: bereits erzeugter Belegungsplan (für
    viele Geräte nacheinander, sonst je Aufruf neu)."""
    from .belegungsplan_service import BelegungsplanService
    if plan is None:
        plan = BelegungsplanService().generate(project)
    rows = [r for r in plan.actor_rows
            if r.physical_address == device.physical_address and r.room_id
            and r.gewerk_code and r.channel_number.isdigit()]
    rooms = {room.id: room for room in project.all_rooms}
    circuits: dict[str, Circuit] = {}
    for r in rows:
        key = circuit_key(r.room_id, r.gewerk_code, r.element_number)
        if key not in circuits:
            circuits[key] = Circuit(
                key=key, room_number=r.room_number, room_name=r.room_name,
                gewerk_code=r.gewerk_code, element_number=r.element_number,
                channel=int(r.channel_number),
                element_text=_element_text(project, rooms.get(r.room_id),
                                           r.gewerk_code, r.element_number))
        circuits[key].functions.append((r.function_name, r.ga_address))
        circuits[key].dpts[r.function_name] = r.dpt
    return sorted(circuits.values(), key=lambda c: (c.channel, c.label))


# Zusätzliche englische/französische Stichworte zu _FUNCTION_KEYWORDS
_EXTRA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "E/A": ("switch", "on/off", "commutation"),
    "RM": ("status", "feedback", "état", "etat"),
    "DIM": ("dimming", "relative", "variation"),
    "WERT": ("value", "brightness", "valeur"),
    "RM WERT": ("value", "brightness"),
    # Griesser JAX-9: "End position" = Auf/Ab, "Tilt" = Schritt/Stopp
    "AUF/AB": ("up/down", "move", "montée", "monter", "end position", "endlage"),
    "STOPP": ("stop", "step", "tilt", "wippen", "arrêt"),
    "POSITION HOEHE": ("position height", "height", "position"),
    "POSITION LAMELLEN": ("slat position", "slat", "lamelle", "angle", "winkel"),
    "STATUS POSITION HOEHE": ("height", "position"),
    "STATUS POSITION LAMELLEN": ("angle", "slat", "winkel"),
    "BESCHATTUNG": ("shading", "sun protection", "ombrage"),
    "SPERREN": ("disable", "lock", "blocage", "blocking"),
    "SZENE": ("scene", "scène"),
    # Heizung (ABB VC/S "Actuating Value", Siemens "Positioning value")
    "STELLGROESSE": ("stellgr", "actuating value", "positioning value", "control value",
                     "valve", "vanne", "heating value"),
    "IST": ("actual temperature", "ist-temperatur", "istwert", "actual value"),
    "BASIS-SOLL": ("setpoint", "sollwert", "basic setpoint", "consigne"),
    "STOERUNG": ("fault", "error", "malfunction", "störung", "défaut"),
}
_FEEDBACK_FUNCTION = re.compile(r"^(RM|STATUS)\b")
_CAMEL = re.compile(r"(?<=[a-zäöü])(?=[A-ZÄÖÜ])")
_NOT_ALNUM = re.compile(r"[^a-z0-9äöüéè]")


def _norm(text: str) -> str:
    """Programmnamen lesbar machen: "Obj_TravelUpDown" -> "obj travel up down"."""
    return _CAMEL.sub(" ", text or "").replace("_", " ").lower()


def _compact(text: str) -> str:
    return _NOT_ALNUM.sub("", text)
_WEAK_KEYWORDS = frozenset({"position", "wert", "value", "status", "meldung"})


def _is_feedback(co) -> bool:
    """Rückmeldung -- auch englisch/französisch ("Height feedback") oder,
    ohne sprechenden Text, an den Flags (senden/lesen, nicht schreiben)."""
    text = _norm(f"{co.object_function or ''} {co.name or ''}")
    if _is_feedback_co(co) or "feedback" in text or "état" in text or "status" in text:
        return True
    from .ko_links import TRANSMIT, WRITE, parse_flags
    flags = parse_flags(co.flags)
    return bool(flags) and WRITE not in flags and TRANSMIT in flags


def suggest_co(channel_cos: list, function: str, used=frozenset()):
    """KO des Kanals für eine GA-Funktion (z.B. "E/A" -> "Kanal A:
    Schalten"); der mit den meisten passenden Stichworten, ohne bereits
    vergebene (used: KO-Nummern). None, wenn keiner passt."""
    keywords = _FUNCTION_KEYWORDS.get(function, ()) + _EXTRA_KEYWORDS.get(function, ())
    if not keywords:
        keywords = (function.lower(),)
    feedback = bool(_FEEDBACK_FUNCTION.match(function))
    best, best_score = None, 0
    for co in channel_cos:
        if co.object_number in used or _is_feedback(co) != feedback:
            continue
        text = _norm(f"{co.object_function} {co.name}")
        compact = _compact(text)
        # Allgemeine Wörter zählen halb: "Height" schlägt "Position";
        # zusammengeschrieben zählt auch ("TravelUpDown" ~ "up/down")
        score = sum(0.5 if kw in _WEAK_KEYWORDS else 1 for kw in keywords
                    if kw in text or (len(_compact(kw)) >= 4 and _compact(kw) in compact))
        if score > best_score:
            best, best_score = co, score
    return best


def suggested_co_map(channel: DeviceChannel | None, circuit: Circuit) -> dict[str, int]:
    """Vorschlag GA-Funktion -> KO-Nummer für einen Stromkreis auf einem
    Kanal; jeder KO höchstens einmal."""
    if channel is None or not channel.com_objects:
        return {}
    result, used = {}, set()
    for function, _ga in circuit.functions:
        co = suggest_co(channel.com_objects, function, used)
        if co is not None:
            result[function] = co.object_number
            used.add(co.object_number)
    # Rückfall Datenpunkttyp: Hersteller ohne Funktionstext (Hager: alle KOs
    # heissen "Output 1") -- der erste freie KO mit dem DPT der GA
    for function, _ga in circuit.functions:
        if function in result or not circuit.dpts.get(function):
            continue
        co = _co_by_dpt(channel.com_objects, circuit.dpts[function],
                        bool(_FEEDBACK_FUNCTION.match(function)), used)
        if co is not None:
            result[function] = co.object_number
            used.add(co.object_number)
    return result


_DPT_RE = re.compile(r"DPS?T-(\d+)(?:-(\d+))?")


def _dpt_key(dpt: str) -> tuple[str, str]:
    """("1", "8") aus "DPST-1-8" bzw. "DPT-1 DPST-1-8"; ("1", "") ohne Untertyp."""
    found = _DPT_RE.findall(dpt or "")
    if not found:
        return "", ""
    main, sub = max(found, key=lambda m: bool(m[1]))
    return main, sub


def _co_by_dpt(channel_cos: list, dpt: str, feedback: bool, used: set):
    """Erster freier KO mit passendem DPT; Rückmeldung bevorzugt passend."""
    main, sub = _dpt_key(dpt)
    if not main:
        return None

    def fits(co) -> bool:
        co_main, co_sub = _dpt_key(co.data_type)
        return co_main == main and (not sub or not co_sub or co_sub == sub)

    candidates = [co for co in channel_cos if co.object_number not in used and fits(co)]
    preferred = [co for co in candidates if _is_feedback(co) == feedback]
    return (preferred or candidates or [None])[0]


def unneeded_functions(channel: DeviceChannel | None, circuit: Circuit,
                       selection: dict[str, int]) -> list[str]:
    """GA-Funktionen, für die der Kanal keinen KO hat und keiner gewählt ist,
    z.B. DIM/WERT eines Lichtkreises an einem Schaltaktor. Ohne KOs (kein
    KNXPROD) ist nichts bekannt -> leer. Ein bewusst nicht verknüpfter,
    aber vorhandener KO zählt nicht: die GA kann anderswo gebraucht werden."""
    if channel is None or not channel.com_objects:
        return []
    # Sicherung: hat schon die Hauptfunktion des Stromkreises (die erste,
    # z.B. E/A, AUF/AB) keinen KO, sind die Texte des Herstellers nicht
    # verstanden -- dann nichts weglassen (sonst fiele AUF/AB weg)
    if not circuit.functions or selection.get(circuit.functions[0][0], -1) < 0:
        return []
    # Bereits anderen Funktionen zugeordnete KOs zählen nicht (RM WERT ist
    # nicht "Status Schalten", wenn der schon RM gehört)
    used = {n for n in selection.values() if n >= 0}
    return [function for function, _ga in circuit.functions
            if selection.get(function, -1) < 0
            and suggest_co(channel.com_objects, function, used) is None]


def omit_functions(project, circuit_key_: str, functions: list[str]) -> int:
    """Funktionen eines Stromkreises weglassen (GewerkAssignment.omitted_
    functions): die GA entfällt, ihr Platz im Block bleibt Reserve. Gibt die
    Anzahl neu weggelassener Funktionen zurück."""
    room_id, gewerk_code, element = circuit_key_.split("|")
    room = next((r for r in project.all_rooms if r.id == room_id), None)
    assignment = next((a for a in (room.gewerk_assignments if room else [])
                       if a.gewerk_code == gewerk_code), None)
    if assignment is None:
        return 0
    omitted = assignment.omitted_functions.setdefault(int(element), [])
    new = [f for f in functions if f not in omitted]
    omitted.extend(new)
    return len(new)


def apply_channel_overrides(device, circuit_rows: dict[str, list]) -> None:
    """Belegungsplan: Kanäle eines Geräts nach Device.channel_map setzen.
    circuit_rows: Stromkreis-Schlüssel -> ActorRows in Belegungsreihenfolge.
    Nicht zugeordnete Stromkreise erhalten der Reihe nach die freien Kanäle;
    erkennbare Kanalnamen (Kanal C, Ausgang 5) stehen in channel_name."""
    mapping = {key: ch for key, ch in (device.channel_map or {}).items()
               if key in circuit_rows and ch}
    used = set(mapping.values())
    free = (n for n in range(1, 1000) if n not in used)
    names = channel_names(device)
    for key, rows in circuit_rows.items():
        number = mapping.get(key) or next(free)
        for row in rows:
            row.channel_number = str(number)
            row.channel_name = names.get(number, "")
