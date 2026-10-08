"""
Sofortmeldung neuer Probleme (FA-620a).

Nach jeder Änderung prüft das Hauptfenster Validierung und GA-Generierung;
Fehler und Warnungen, die vorher nicht da waren, meldet es sofort. Bereits
bekannte Meldungen und Hinweise lösen keine Meldung aus.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

from .validation_engine import ValidationEngine, ValidationIssue

_LEVELS = ("error", "warning")


def problem_key(issue: ValidationIssue) -> tuple[str, str, str]:
    return (issue.rule_id, issue.address, issue.message)


def current_problems(project) -> list[ValidationIssue]:
    """Fehler und Warnungen des Projekts (ohne Hinweise)."""
    if project is None or not project.group_addresses:
        return []
    issues = ValidationEngine(project.gewerk_catalog).validate(
        project.group_addresses, project=project)
    return [i for i in issues if i.level in _LEVELS]


class ProblemMonitor:
    """Merkt sich die bekannten Probleme je Projekt und liefert die neuen."""

    def __init__(self):
        self._project_id: int | None = None
        self._known: set[tuple[str, str, str]] = set()

    def reset(self, project) -> None:
        """Aktuellen Stand still als Ausgangspunkt übernehmen."""
        self._project_id = id(project) if project is not None else None
        self._known = {problem_key(i) for i in current_problems(project)}

    def adopt(self, project) -> None:
        """Nach dem Laden: Stand eines anderen Projekts still übernehmen,
        beim selben Projekt (Speichern) nichts tun."""
        if id(project) != self._project_id:
            self.reset(project)

    def check(self, project) -> list[ValidationIssue]:
        """Neue Probleme seit der letzten Prüfung. Bei einem anderen
        Projekt (geöffnet, neu, Rückgängig) zuerst still neu aufsetzen."""
        if project is None:
            self._project_id = None
            self._known = set()
            return []
        if id(project) != self._project_id:
            self.reset(project)
            return []
        problems = current_problems(project)
        new = [i for i in problems if problem_key(i) not in self._known]
        self._known = {problem_key(i) for i in problems}
        # Fehler zuerst
        return sorted(new, key=lambda i: _LEVELS.index(i.level))


def summarize(problems: list[ValidationIssue]) -> list[tuple[str, str, int]]:
    """Gleiche Meldungen zusammengefasst als (Stufe, Text, Anzahl): Fehler
    zuerst, darin die der GA-Generierung (FA-620), die die Ursache nennen
    (z.B. volle Mittelgruppe) statt ihrer Folgen je GA."""
    groups: dict[tuple[str, str, str], int] = {}
    for issue in problems:
        key = (issue.level, issue.rule_id, issue.message)
        groups[key] = groups.get(key, 0) + 1
    order = sorted(groups, key=lambda k: (_LEVELS.index(k[0]), k[1] != "FA-620"))
    return [(level, message, groups[(level, rule, message)])
            for level, rule, message in order]
