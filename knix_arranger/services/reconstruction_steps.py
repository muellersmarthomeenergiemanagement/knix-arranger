"""
Anlage ohne Projektdatei aufnehmen (FA-3105e): Schritte der Rekonstruktion
vom Bus und ihr Stand. Der Stand kommt aus den Projektdaten (und für das
Suchen aus dem Ergebnis der laufenden Sitzung), nicht aus einem eigenen
Merker: stimmt nach Laden und Rückgängig. Nichts wird gesperrt, jeder
Schritt bleibt wiederholbar.
"""
from __future__ import annotations

from dataclasses import dataclass

DONE, PARTIAL, OPEN = "done", "partial", "open"

CONNECT, SEARCH, ADOPT, LINKS, MEANING, BUILDING, TOUR = (
    "connect", "search", "adopt", "links", "meaning", "building", "tour")

_TITLES = {
    CONNECT: "Verbinden",
    SEARCH: "Suchen",
    ADOPT: "Übernehmen",
    LINKS: "GAs lesen",
    MEANING: "Bedeutung ergänzen",
    BUILDING: "Gebäude erfassen",
    TOUR: "Rundgang",
}
# Schritte, die die Busverbindung brauchen
_NEEDS_BUS = {SEARCH, LINKS, TOUR}


@dataclass
class Step:
    key: str
    number: int
    title: str
    state: str = OPEN
    detail: str = ""

    @property
    def needs_bus(self) -> bool:
        return self.key in _NEEDS_BUS


def _devices(project) -> list:
    from .device_scan import project_devices
    return list(project_devices(project)) if project is not None else []


def applies(project) -> bool:
    """Die Schrittleiste gilt für leere und bestehende (importierte) Anlagen,
    nicht für mit KNiX geplante Projekte mit Geräten."""
    if project is None or getattr(project, "areal", None) is None:
        return False
    imported = getattr(getattr(project, "topology", None), "is_imported", False)
    return imported or not _devices(project)


def steps(project, connected: bool = False, findings: int = 0) -> list[Step]:
    """Die sieben Schritte mit Stand. `findings`: Anzahl gefundener Geräte
    der laufenden Suche (geht beim Schliessen verloren, darum zählen auch
    übernommene Geräte als gesucht)."""
    from .ga_meaning import is_provisional_named
    result = [Step(key, number, _TITLES[key])
              for number, key in enumerate(_TITLES, start=1)]
    by_key = {s.key: s for s in result}
    devices = _devices(project)
    gas = list(project.group_addresses.all_addresses()) if project is not None else []

    by_key[CONNECT].state = DONE if connected else OPEN
    by_key[CONNECT].detail = "verbunden" if connected else "im Live-Monitor (KNXnet/IP)"

    if devices or findings:
        by_key[SEARCH].state = DONE
        by_key[SEARCH].detail = f"{findings} gefunden" if findings else "Geräte im Projekt"

    if devices:
        from .missing_products import device_count
        without = device_count(project)
        by_key[ADOPT].state = PARTIAL if without else DONE
        by_key[ADOPT].detail = f"{len(devices)} Geräte" + (
            f", {without} ohne Herstellerdatei" if without else "")
    elif findings:
        by_key[ADOPT].detail = "Gefundenes noch nicht im Projekt"

    # nur Geräte mit KOs lassen sich verknüpfen: Koppler, entladene
    # Applikationen und Geräte ohne Herstellerdatei zählen nicht (die
    # letzten zeigt «Übernehmen»)
    linkable = [d for d in devices if d.communication_objects]
    linked = sum(1 for d in linkable if any(co.connected_gas
                                            for co in d.communication_objects))
    if linked and gas:
        by_key[LINKS].state = DONE if linked >= len(linkable) else PARTIAL
        by_key[LINKS].detail = f"{len(gas)} GAs, {linked}/{len(linkable)} Geräte verknüpft"

    if gas:
        provisional = sum(1 for ga in gas if is_provisional_named(ga))
        by_key[MEANING].state = OPEN if provisional == len(gas) else \
            PARTIAL if provisional else DONE
        by_key[MEANING].detail = f"{provisional} GAs vorläufig" if provisional \
            else "alle GAs benannt"

    rooms = list(project.areal.all_rooms) if project is not None else []
    if rooms:
        by_key[BUILDING].state = DONE
        by_key[BUILDING].detail = f"{len(rooms)} Räume"

    with_room = sum(1 for ga in gas if ga.room_id)
    if with_room:
        rooms_used = len({ga.room_id for ga in gas if ga.room_id})
        by_key[TOUR].state = PARTIAL
        by_key[TOUR].detail = f"{rooms_used} Räume, {with_room}/{len(gas)} GAs mit Raum"
    return result


def current(step_list: list[Step], connected: bool) -> str:
    """Nächster Schritt: der erste offene nach dem Verbinden (teilweise
    erledigt zählt als begonnen: Secure-Geräte bleiben unlesbar, manche GAs
    ohne Vorschlag); braucht er den Bus und fehlt die Verbindung, ist es das
    Verbinden. Am Ende bleibt der Rundgang."""
    for step in step_list:
        if step.key == CONNECT:
            continue
        if step.state == OPEN:
            if step.needs_bus and not connected:
                return CONNECT
            return step.key
    return TOUR
