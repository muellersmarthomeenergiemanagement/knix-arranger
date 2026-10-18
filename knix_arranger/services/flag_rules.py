"""
Soll-Flags je Gerät und GA aus der Rolle (FA-635).

Grundregel: Pro GA gibt es genau eine Quelle des Werts. Die Quelle sendet (Ü)
und beantwortet Leseanfragen (L); alle Empfänger schreiben (S), wer den
Zustand nach einem Busneustart braucht, liest ihn bei Init (I).

- Aktor/Gateway: Befehl empfangen K S, Rückmeldung senden K L Ü, Messwert
  empfangen K S I (Ist-Temperatur am Heizungsaktor);
- Taster/Sensor: Befehl senden K S Ü (S, damit Umschalten den Zustand kennt),
  Szene abrufen K Ü, Rückmeldung empfangen K S I (LED, Anzeige), eigener
  Zustand/Messwert senden K L Ü (Raumtemperatur, Bewegung).

Die Hersteller setzen ihre Vorgaben selbst -- die Soll-Flags sind eine
Empfehlung: für Geräte ohne Produkt gelten sie als Annahme (Topologie,
Prüfungen FA-627/628), bei Geräten mit Produkt meldet FA-635 Abweichungen als
Hinweis.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ko_links import COMMUNICATE as K, INIT as I, READ as L, TRANSMIT as U, WRITE as S

RECEIVE_COMMAND = frozenset({K, S})
SEND_STATE = frozenset({K, L, U})
RECEIVE_STATE = frozenset({K, S, I})
SEND_COMMAND = frozenset({K, S, U})
SEND_SCENE = frozenset({K, U})

_SENSOR_ROLE_FLAGS = {
    "aktorstatus": RECEIVE_STATE,     # Melder hört den Aktorstatus mit
    "extern": RECEIVE_COMMAND,        # Externer Taster: empfängt den Befehl
    "helligkeit": RECEIVE_STATE,      # externe Helligkeit (Wetterstation)
    "raumtemperatur": SEND_STATE,     # Taster liefert die Raumtemperatur
}


def actor_flags(function_name: str) -> frozenset[str]:
    """Soll-Flags am Aktor/Gateway für eine GA-Funktion."""
    from . import ga_functions
    from .co_linking_service import _FUNCTION_MAP
    template = _FUNCTION_MAP.get((function_name or "").strip().upper())
    role = ga_functions.role_of(function_name)
    if template:
        direction = template[0][3]
        if direction == "senden":
            return SEND_STATE
        return RECEIVE_STATE if role == ga_functions.MEASUREMENT else RECEIVE_COMMAND
    if role == ga_functions.FEEDBACK:
        return SEND_STATE
    if role == ga_functions.MEASUREMENT:
        return RECEIVE_STATE
    return RECEIVE_COMMAND


def sensor_flags(link) -> frozenset[str]:
    """Soll-Flags am Taster/Sensor für eine Verknüpfung (sensor_channels.SensorLink)."""
    from . import ga_functions
    if link.role:
        return _SENSOR_ROLE_FLAGS.get(link.role, RECEIVE_STATE)
    if link.feedback:
        return RECEIVE_STATE
    role = ga_functions.role_of(link.ga_function)
    if role in (ga_functions.FEEDBACK, ga_functions.MEASUREMENT):
        return SEND_STATE                 # eigener Zustand bzw. Messwert
    if (link.ga_function or "").strip().upper() == "SZENE":
        return SEND_SCENE
    return SEND_COMMAND


def flags_label(flags: frozenset[str]) -> str:
    """"K S Ü" in der Reihenfolge der ETS."""
    return " ".join(f for f in (K, L, S, U, "A", I) if f in flags)


@dataclass
class Expected:
    device: object
    ga_address: str
    function: str               # GA-Funktion bzw. Tastenfunktion
    flags: frozenset[str]


def expected_by_link(project, sensor_rows=None, actor_plan=None) -> dict[tuple[str, str], Expected]:
    """(Teilnehmeradresse, GA) -> Soll-Flags für alle Aktoren, Gateways,
    Taster und Sensoren mit Adresse (geplante Projekte)."""
    from .belegungsplan_service import BelegungsplanService
    from .sensor_channels import sensor_links, sensor_plan
    devices = {d.physical_address: d for a in project.topology.areas
               for line in a.lines for d in line.devices if d.physical_address}
    result: dict[tuple[str, str], Expected] = {}
    plan = actor_plan or BelegungsplanService().generate(project)
    for row in plan.actor_rows:
        device = devices.get(row.physical_address)
        if device is None or not row.ga_address:
            continue
        result.setdefault((row.physical_address, row.ga_address), Expected(
            device, row.ga_address, row.function_name, actor_flags(row.function_name)))
    rows = sensor_rows if sensor_rows is not None else sensor_plan(project)
    for device in devices.values():
        if device.device_type != "sensor":
            continue
        for link in sensor_links(project, device, rows):
            if link.ga_address:
                result.setdefault((device.physical_address, link.ga_address), Expected(
                    device, link.ga_address, link.function, sensor_flags(link)))
    return result


def expected_links(project, expected: dict | None = None) -> list:
    """Angenommene Verknüpfungen für Geräte ohne Produkt-KOs (Platzhalter der
    Planung) mit den Soll-Flags -- damit FA-627/628 schon vor der Produktwahl
    prüfen. Geräte mit KOs tragen ihre eigenen Verknüpfungen (ko_links)."""
    from ..models.topology import CommunicationObject
    expected = expected if expected is not None else expected_by_link(project)
    result = []
    for (pa, ga), e in expected.items():
        if e.device.communication_objects:
            continue
        co = CommunicationObject(object_number=-1, name=e.function,
                                 flags="".join(f for f in (K, L, S, U, "A", I) if f in e.flags))
        result.append(ExpectedLink(e.device, co, ga, U in e.flags))
    return result


def receiver_read_flags(project, expected: dict | None = None) -> list[tuple]:
    """FA-635: KOs mit L-Flag, die laut Soll an keiner ihrer GAs senden
    (reine Empfänger, z.B. Hager «ON/OFF_1» an E/A, Ist-Temperatur am
    Heizungsaktor) -- sie beantworten Leseanfragen mit einem Wert, den sie
    nur empfangen haben. Verglichen wird je KO (Vereinigung über seine GAs):
    ein Tasten-KO, das sendet und mithört, ist kein reiner Empfänger.
    Rückgabe: (Gerät, KO, [GA-Adressen], [Funktionen]); nicht parametrierte
    Produktdaten-KOs zählen nicht."""
    from .ko_links import READ, flags_unparametrized, ko_links
    expected = expected if expected is not None else expected_by_link(project)
    imported = project.topology.is_imported
    per_ko: dict[tuple, list] = {}
    for link in ko_links(project):
        per_ko.setdefault((id(link.device), link.co.object_number), []).append(link)
    result = []
    for links in per_ko.values():
        first = links[0]
        if READ not in first.flags or flags_unparametrized(first, imported):
            continue
        soll = [expected.get((first.device.physical_address, l.ga_address)) for l in links]
        if not soll or any(e is None for e in soll):
            continue                  # Rolle nicht für alle GAs bekannt
        if any(U in e.flags for e in soll):
            continue                  # sendet an mindestens einer GA: Quelle
        result.append((first.device, first.co, [l.ga_address for l in links],
                       list(dict.fromkeys(e.function for e in soll))))
    return result


class ExpectedLink:
    """Wie ko_links.KoLink, für ein Gerät ohne Produkt (Soll-Flags)."""
    proposed = False

    def __init__(self, device, co, ga_address: str, sending: bool):
        self.device, self.co, self.ga_address, self.sending = device, co, ga_address, sending

    @property
    def flags(self) -> frozenset[str]:
        from .ko_links import parse_flags
        return parse_flags(self.co.flags)

    @property
    def label(self) -> str:
        return f"{self.device.physical_address} «{self.co.name}» (ohne Produkt, Soll {flags_label(self.flags)})"
