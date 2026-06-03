"""
Leitungslaengen-Validierungsdienst (FA-2602 bis FA-2604)

Prueft die erfassten Leitungslaengen einer KNX-Linie gegen die
KNX-TP-Grenzwerte gemaess KNX TP-Topologie Kapitel 5.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import logging

logger = logging.getLogger("knix_arranger.cable_length")

# KNX TP Grenzwerte (FA-2602)
_MAX_TOTAL   = 1000.0   # m – Gesamtlaenge Fehler
_WARN_TOTAL  =  800.0   # m – Gesamtlaenge Warnung
_MAX_TRUNK   =  700.0   # m – Stammleitung Fehler
_WARN_TRUNK  =  560.0   # m – Stammleitung Warnung (80 % von 700)
_MAX_BRANCH  =   10.0   # m – Einzelne Stichleitung Fehler
_WARN_BRANCH =    8.0   # m – Einzelne Stichleitung Warnung


@dataclass
class LineValidation:
    """Validierungsergebnis fuer eine KNX-Linie."""
    line_id: str
    line_name: str
    topology_form: str
    trunk_length: float
    branch_lengths: list[float]
    total_length: float
    max_branch: float           # laengste Stichleitung
    status: str                 # "OK" | "Warnung" | "Fehler"
    messages: list[str] = field(default_factory=list)

    @property
    def branch_count(self) -> int:
        return len(self.branch_lengths)


class CableLengthService:
    """
    Berechnet und validiert Leitungslaengen pro KNX-Linie (FA-2601/2602/2604).
    """

    def validate_project(self, project) -> list[LineValidation]:
        """Gibt eine Validierungsliste fuer alle Linien des Projekts zurueck."""
        results: list[LineValidation] = []
        for area in project.topology.areas:
            for line in area.lines:
                results.append(self.validate_line(line))
        return results

    def validate_line(self, line) -> LineValidation:
        """Validiert eine einzelne Linie und gibt das Ergebnis zurueck."""
        trunk   = line.trunk_length
        branches = list(line.branch_lengths)
        total   = trunk + sum(branches)
        max_br  = max(branches) if branches else 0.0

        messages: list[str] = []
        status = "OK"

        # Stammleitung
        if trunk > _MAX_TRUNK:
            messages.append(
                f"Stammleitung {trunk:.1f} m ueberschreitet Maximum {_MAX_TRUNK:.0f} m"
            )
            status = "Fehler"
        elif trunk > _WARN_TRUNK:
            messages.append(
                f"Stammleitung {trunk:.1f} m nahe Maximum {_MAX_TRUNK:.0f} m"
            )
            if status == "OK":
                status = "Warnung"

        # Gesamtlaenge
        if total > _MAX_TOTAL:
            messages.append(
                f"Gesamtlaenge {total:.1f} m ueberschreitet Maximum {_MAX_TOTAL:.0f} m"
            )
            status = "Fehler"
        elif total > _WARN_TOTAL:
            messages.append(
                f"Gesamtlaenge {total:.1f} m nahe Maximum {_MAX_TOTAL:.0f} m"
            )
            if status == "OK":
                status = "Warnung"

        # Einzelne Stichleitungen
        for i, br in enumerate(branches):
            if br > _MAX_BRANCH:
                messages.append(
                    f"Stichleitung {i+1}: {br:.1f} m ueberschreitet Maximum {_MAX_BRANCH:.0f} m"
                )
                status = "Fehler"
            elif br > _WARN_BRANCH:
                messages.append(
                    f"Stichleitung {i+1}: {br:.1f} m nahe Maximum {_MAX_BRANCH:.0f} m"
                )
                if status == "OK":
                    status = "Warnung"

        return LineValidation(
            line_id=line.id,
            line_name=line.name or f"Linie {line.line_number}",
            topology_form=line.topology_form,
            trunk_length=trunk,
            branch_lengths=branches,
            total_length=total,
            max_branch=max_br,
            status=status,
            messages=messages,
        )
