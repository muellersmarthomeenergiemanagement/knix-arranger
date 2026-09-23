"""
Erkennt, ob sich die Eingaben einer automatischen Wizard-Neuberechnung seit
dem letzten Lauf geändert haben.

Mehrere Schritte berechnen beim Betreten Daten neu (GA-Generierung,
Funktionszuordnung, Linienteilnehmer). Ohne Änderungsprüfung geschieht das
bei jedem Durchklicken still im Hintergrund. Der Guard merkt sich pro
Berechnung einen Fingerabdruck des Datenstands NACH dem letzten Lauf – nur
wenn sich dieser seither geändert hat, wird erneut gerechnet.

Der WizardController teilt eine Instanz auf alle Schritte, damit z.B. die
Funktionszuordnung aus Schritt 11 in Schritt 12 nicht erneut läuft.
"""
from __future__ import annotations
import hashlib
import json

# Schlüssel der überwachten Berechnungen
KEY_ADDRESSES = "addresses"   # GA-Generierung (Schritt 5 beim Verlassen, Schritt 10)
KEY_FUNCTIONS = "functions"   # auto_assign_functions (Schritte 6, 11, 12)
KEY_DEVICES = "devices"       # populate_devices (Schritt 7)


# Listen, deren Einträge bei jeder automatischen Neuberechnung mit frischen
# IDs neu aufgebaut werden (auto_assign_functions, Aktor-Ermittlung).
_REBUILT_CONTAINERS = {"bedienelemente", "actor_assignments"}


def _without_volatile_ids(data, in_rebuilt: bool = False):
    """Entfernt IDs, die bei jedem Lauf neu vergeben werden (Bedienelement.id,
    Aktor-Zuordnung.id, sf_id). Sie ändern sich auch ohne inhaltliche Änderung
    und würden sonst jede nachfolgende Berechnung als veraltet markieren."""
    if isinstance(data, dict):
        return {
            k: _without_volatile_ids(v, in_rebuilt or k in _REBUILT_CONTAINERS)
            for k, v in data.items()
            if k != "sf_id" and not (in_rebuilt and k == "id")
        }
    if isinstance(data, list):
        return [_without_volatile_ids(v, in_rebuilt) for v in data]
    return data


def _plain(obj):
    if hasattr(obj, "to_dict"):
        return _without_volatile_ids(obj.to_dict())
    if isinstance(obj, (list, tuple)):
        return [_plain(o) for o in obj]
    return obj


def _inputs(project, key: str) -> list:
    if key == KEY_ADDRESSES:
        return [
            project.areal, project.scenes, project.time_programs,
            project.config.mg_variant, project.group_addresses,
        ]
    if key == KEY_FUNCTIONS:
        return [project.areal, project.group_addresses]
    if key == KEY_DEVICES:
        return [project.areal, project.topology]
    raise ValueError(f"Unbekannter Guard-Schlüssel: {key}")


def fingerprint(project, key: str) -> str:
    data = json.dumps(
        [_plain(part) for part in _inputs(project, key)],
        sort_keys=True, default=repr,
    )
    return hashlib.sha1(data.encode("utf-8")).hexdigest()


class RecomputeGuard:
    """Merkt sich pro Berechnung den Datenstand nach dem letzten Lauf."""

    def __init__(self):
        self._done: dict[str, str] = {}

    def is_stale(self, project, key: str) -> bool:
        """True, wenn die Berechnung noch nie lief oder sich Eingaben geändert haben."""
        return self._done.get(key) != fingerprint(project, key)

    def mark_done(self, project, key: str) -> None:
        """Nach einer Berechnung aufrufen (Fingerabdruck des Ergebnisstands)."""
        self._done[key] = fingerprint(project, key)
        # Eine Berechnung verändert die Eingaben der anderen (z.B. neue GAs →
        # Funktionszuordnung). Deren Stand bleibt bewusst unangetastet, so dass
        # sie beim nächsten Betreten als veraltet erkannt werden.
