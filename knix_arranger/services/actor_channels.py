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


def device_channels(device, fallback_count: int = 0) -> list[DeviceChannel]:
    """Kanäle des Geräts in der Benennung des Herstellers (aus den KOs, siehe
    product_zones); ohne erkennbare Kanäle "Kanal 1…n" nach der Kanalzahl."""
    from .knxprod_catalog_service import unique_com_objects
    from .product_zones import co_zone, zone_label, zone_scheme
    product = {"com_objects": _co_dicts(device)}
    scheme = zone_scheme(product)
    if scheme is not None:
        # Je KO-Nummer ein Eintrag (echter Text vor "{{0:GO}}"-Varianten)
        by_id = {id(data): co for co, data in zip(device.communication_objects,
                                                  product["com_objects"])}
        by_zone: dict[int, list] = {}
        for data in unique_com_objects(product["com_objects"]):
            zone = co_zone(data, scheme)
            if zone is not None:
                by_zone.setdefault(zone, []).append(by_id[id(data)])
        return [DeviceChannel(z, zone_label(product, z), cos)
                for z, cos in sorted(by_zone.items())]
    from .belegungsplan_service import BelegungsplanService
    count = fallback_count or BelegungsplanService._parse_channel_count(device.product)
    if count >= 999:   # unbekannt
        count = 0
    return [DeviceChannel(n, f"Kanal {n}") for n in range(1, count + 1)]


def channel_names(device) -> dict[int, str]:
    """Kanalnummer -> Name, nur wenn die KOs Kanäle erkennen lassen."""
    from .product_zones import zone_scheme
    if zone_scheme({"com_objects": _co_dicts(device)}) is None:
        return {}
    return {ch.number: ch.label for ch in device_channels(device)}


def _element_text(project, room, gewerk_code: str, element_number: int) -> str:
    """"Licht 1 «Decke»" aus Gewerkname und Element-Bezeichnung."""
    gewerk = project.gewerk_catalog.get(gewerk_code)
    text = f"{gewerk.name if gewerk else gewerk_code} {element_number}"
    assignment = next((a for a in (room.gewerk_assignments if room else [])
                       if a.gewerk_code == gewerk_code), None)
    label = assignment.element_label(element_number) if assignment else ""
    return f"{text} «{label}»" if label else text


def device_circuits(project, device) -> list[Circuit]:
    """Stromkreise, die das Gerät laut Belegungsplan bedient, mit aktuellem
    Kanal und GA-Funktionen."""
    from .belegungsplan_service import BelegungsplanService
    rows = [r for r in BelegungsplanService().generate(project).actor_rows
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
    "SPERREN": ("disable", "lock", "blocage"),
    "SZENE": ("scene", "scène"),
}
_FEEDBACK_FUNCTION = re.compile(r"^(RM|STATUS)\b")
_WEAK_KEYWORDS = frozenset({"position", "wert", "value", "status", "meldung"})


def _is_feedback(co) -> bool:
    """Rückmeldung -- auch englisch/französisch ("Height feedback")."""
    text = f"{co.object_function or ''} {co.name or ''}".lower()
    return _is_feedback_co(co) or "feedback" in text or "état" in text


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
        text = f"{co.object_function} {co.name}".lower()
        # Allgemeine Wörter zählen halb: "Height" schlägt "Position"
        score = sum(0.5 if kw in _WEAK_KEYWORDS else 1 for kw in keywords if kw in text)
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
    return result


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
