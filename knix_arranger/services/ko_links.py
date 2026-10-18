"""
KO-Verknüpfungen je Gruppenadresse mit ihren Flags (FA-627, FA-628).

Quelle je Gerät:
- verknüpfte KOs (Device.communication_objects[].connected_gas): ETS-Import
  oder übernommene Verknüpfung; die erste GA eines KOs ist die sendende;
- sonst die Zuordnung in KNiX (Device.co_map, «KOs aller Geräte zuordnen»):
  Aktor je Stromkreis und Funktion, Taster/Sensor je GA.
Geräte ohne beides tragen nichts bei (KOs noch nicht zugeordnet).

Flags (DE / EN): K/C Kommunikation, L/R Lesen, S/W Schreiben,
Ü/T Übertragen, A/U Aktualisieren, I Lesen bei Init. In deutschen
Kurzformen steht "U" bzw. "UE" für Ü (z.B. "KSUA").

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

COMMUNICATE, READ, WRITE, TRANSMIT, UPDATE, INIT = "K", "L", "S", "Ü", "A", "I"
_ORDER = (COMMUNICATE, READ, WRITE, TRANSMIT, UPDATE, INIT)
_ENGLISH = {"C": COMMUNICATE, "R": READ, "W": WRITE, "T": TRANSMIT, "U": UPDATE, "I": INIT}
_GERMAN = {"K": COMMUNICATE, "L": READ, "S": WRITE, "Ü": TRANSMIT, "U": TRANSMIT,
           "A": UPDATE, "I": INIT}


# Produktdaten (product_sync.flags, KNXPROD-Katalog): fünf Stellen
# Kommunikation, Lesen, Schreiben, Übertragen, Aktualisieren -- geschrieben als
# "K", "L", "Ü", "S", "U" (Schreiben als "Ü", Übertragen als "S"!), z.B. ein
# Empfangs-KO "K-Ü--", ein Status-KO "KL-S-".
_PRODUCT_POSITIONS = (("K", COMMUNICATE), ("L", READ), ("Ü", WRITE),
                      ("S", TRANSMIT), ("U", UPDATE))


def _product_flags(text: str) -> frozenset[str] | None:
    if len(text) != 5 or any(c not in (letter, "-")
                             for c, (letter, _f) in zip(text, _PRODUCT_POSITIONS)):
        return None
    return frozenset(flag for c, (_l, flag) in zip(text, _PRODUCT_POSITIONS) if c != "-")


def parse_flags(flags: str) -> frozenset[str]:
    """Flags eines KOs als Menge von K, L, S, Ü, A, I; leer, wenn unbekannt.
    Versteht ETS-Report ("K-SÜA-"), knxproj ("KSUE-A"), Englisch ("CRWTU")
    und die Fünf-Stellen-Form der Produktdaten ("K-Ü--")."""
    product = _product_flags((flags or "").upper())
    if product is not None:
        return product
    text = (flags or "").upper().replace("UE", "Ü")
    letters = [c for c in text if c.isalpha()]
    english = any(c in ("C", "R", "W", "T") for c in letters) and not any(
        c in ("K", "L", "S", "Ü") for c in letters)
    table = _ENGLISH if english else _GERMAN
    return frozenset(table[c] for c in letters if c in table)


def flags_text(flags: str) -> str:
    """Einheitliche Anzeige, z.B. "K S Ü"."""
    present = parse_flags(flags)
    return " ".join(f for f in _ORDER if f in present)


@dataclass
class KoLink:
    device: object          # Device
    co: object              # CommunicationObject
    ga_address: str
    sending: bool           # erste GA des KOs: auf sie sendet es
    proposed: bool = False  # nur Vorschlag (KOs noch nicht zugeordnet)

    @property
    def flags(self) -> frozenset[str]:
        return parse_flags(self.co.flags)

    @property
    def label(self) -> str:
        name = self.co.name or self.co.object_function
        return f"{self.device.physical_address} KO {self.co.object_number} «{name}»"


def _by_number(cos: list) -> dict:
    """KO-Nummer -> KO; bei mehreren Varianten derselben Nummer die echte
    (mit Text) vor Platzhaltern «{{0:GO}}», deren Flags alle gesetzt sind
    (Griesser JAX-9: KO 2 «End position» K S, Platzhalter K L S Ü A)."""
    result: dict = {}
    for co in cos:
        known = result.get(co.object_number)
        if known is None or (_is_placeholder(known) and not _is_placeholder(co)):
            result[co.object_number] = co
    return result


def _is_placeholder(co) -> bool:
    return "{{" in f"{co.name or ''} {co.object_function or ''}"


# Objektname ohne Bedeutung aus den Produktdaten: «Object 2», «GO0097»
_GENERIC_NAME = re.compile(r"(object|objekt|go)\s*\d+", re.IGNORECASE)


def flags_unparametrized(link) -> bool:
    """Flags stammen aus Produktdaten und sind offensichtlich nicht
    parametriert: Platzhalter-KO oder Objekt ohne Namen («Object 2») mit
    vollem Flag-Satz K L S Ü. Die echten Flags entstehen erst durch die
    Parametrierung in der ETS (Feller EDIZIOdue). Verknüpfungen aus einem
    ETS-Import (connected_gas) tragen die parametrierten Flags und zählen nie
    als unparametriert."""
    if link.co.connected_gas:
        return False
    return unparametrized_co(link.co)


def unparametrized_co(co) -> bool:
    """Platzhalter («{{0:GO}}») oder Objekt ohne Namen («Object 2») mit vollem
    Flag-Satz K L S Ü. Ein Textbaustein mit echten Flags (Revox «{{0:Room 1}}:
    Mute Status», K Ü) ist parametriert."""
    if not {COMMUNICATE, READ, WRITE, TRANSMIT} <= parse_flags(co.flags):
        return False
    name = (co.name or co.object_function or "").strip()
    return _is_placeholder(co) or bool(_GENERIC_NAME.fullmatch(name))


def co_by_number(cos: list, number: int):
    """Das KO mit dieser Nummer, bei Varianten die echte vor Platzhaltern --
    für «welches KO bekommt bzw. zeigt die GA?»."""
    best = None
    for co in cos:
        if co.object_number == number and (
                best is None or (_is_placeholder(best) and not _is_placeholder(co))):
            best = co
    return best


def co_holding(cos: list, number: int, ga_address: str):
    """Die Variante mit dieser Nummer, an der die GA hängt (Trennen,
    Korrekturen); ohne Treffer die echte Variante."""
    return next((co for co in cos if co.object_number == number
                 and ga_address in co.connected_gas), None) or co_by_number(cos, number)


def _devices(project) -> list:
    return [d for area in project.topology.areas for line in area.lines
            for d in line.devices]


def _planned_gas(project, device, sensor_rows, co_map: dict,
                 actor_plan=None) -> list[tuple[int, str, bool]]:
    """(KO-Nummer, GA, Rückmeldung) aus einer Zuordnung (Device.co_map oder
    Vorschlag von ko_batch.plan_all)."""
    from .actor_channels import device_circuits
    from .sensor_channels import SENSOR_CO_KEY, sensor_links
    result = []
    if device.device_type == "sensor":
        selection = dict(co_map.get(SENSOR_CO_KEY) or {})
        if not selection:
            return []
        for link in sensor_links(project, device, sensor_rows):
            number = selection.get(link.key, -1)
            if number >= 0:
                result.append((number, link.ga_address, link.feedback or bool(link.role)))
        return result
    for circuit in device_circuits(project, device, actor_plan):
        selection = co_map.get(circuit.key) or {}
        for function, ga_address in circuit.functions:
            number = selection.get(function, -1)
            if number is not None and number >= 0:
                result.append((number, ga_address, False))
    return result


def ko_links(project, proposals: bool = False, fresh: bool = False) -> list[KoLink]:
    """Alle bekannten KO-GA-Verknüpfungen des Projekts. Mit proposals auch
    für Geräte ohne Zuordnung, nach dem Vorschlag von «KOs aller Geräte
    zuordnen» (KoLink.proposed) -- für die Anzeige, nicht für Prüfungen."""
    links: list[KoLink] = []
    sensor_rows = None
    proposed_maps: dict[int, dict] = {}
    actor_plan = None
    if proposals:
        from .ko_batch import plan_all
        batch = plan_all(project, fresh)
        proposed_maps = {id(plan.device): plan.co_map for plan in batch.plans}
        # dieselben Belegungspläne wiederverwenden (je ca. 0,4 s)
        sensor_rows, actor_plan = batch.sensor_rows, batch.actor_plan
    for device in _devices(project):
        cos = _by_number(device.communication_objects)
        if any(co.connected_gas for co in device.communication_objects):
            for co in device.communication_objects:
                shown = cos.get(co.object_number, co) if _is_placeholder(co) else co
                for i, ga in enumerate(co.connected_gas):
                    links.append(KoLink(device, shown, ga, i == 0))
            continue
        from .sensor_channels import has_sensor_selection
        own = device.co_map and (device.device_type != "sensor"
                                 or has_sensor_selection(device))
        co_map = device.co_map if own else proposed_maps.get(id(device))
        if not co_map:
            continue
        proposed = not own
        if device.device_type == "sensor" and sensor_rows is None:
            from .sensor_channels import sensor_plan
            sensor_rows = sensor_plan(project, fresh)
        if device.device_type != "sensor" and actor_plan is None:
            from .belegungsplan_service import BelegungsplanService
            actor_plan = BelegungsplanService().generate(project)
        planned = _planned_gas(project, device, sensor_rows, co_map, actor_plan)
        # Befehle zuerst: die erste GA eines KOs ist die sendende
        planned.sort(key=lambda item: item[2])
        seen: set[int] = set()
        for number, ga, _feedback in planned:
            co = cos.get(number)
            if co is None:
                continue
            links.append(KoLink(device, co, ga, number not in seen, proposed))
            seen.add(number)
    return links


def links_by_ga(project) -> dict[str, list[KoLink]]:
    result: dict[str, list[KoLink]] = {}
    for link in ko_links(project):
        result.setdefault(link.ga_address, []).append(link)
    return result
