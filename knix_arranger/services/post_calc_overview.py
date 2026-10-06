"""
Projektübergreifende Nachkalkulation (FA-2205, FA-2206).

Wertet die akzeptierten Kundenofferten mit erfassten Ist-Werten aller
Projekte aus: durchschnittliche Marge, häufigste Abweichungen, Verlauf über
die Zeit, und schlägt daraus neue Richtwerte für den Zeitaufwand vor.

Marge = Offertbetrag (netto) minus Aufwand. Die Stunden sind dabei zu den
Offertsätzen bewertet, das Material zum Einkauf -- interne Stundenkosten
kennt KNiX nicht. Geplant: Material zum Einkaufspreis aus der Offerte, Ist:
erfasste Einkaufskosten.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import glob
import logging
import os

logger = logging.getLogger("knix_arranger.post_calc_overview")

# Kategorien des Soll-Ist-Vergleichs: (Schlüssel, Bezeichnung)
CATEGORIES = (
    ("material", "Material"),
    ("mounting", "Montage"),
    ("programming", "Programmierung"),
    ("commissioning", "Inbetriebnahme"),
    ("documentation", "Dokumentation"),
)
# Ab dieser Abweichung zählt eine Kategorie als "abweichend"
DEVIATION_THRESHOLD = 10.0

_SKIP_FOLDERS = ("Sicherungen", "Revisionen", "Berichte")


@dataclass
class ProjectResult:
    project: str
    quote: str
    date: str                      # ISO-Datum der Offerte, sonst ""
    devices: int
    revenue: float                 # Offertbetrag netto
    planned: dict[str, float]      # Material CHF, sonst Stunden
    actual: dict[str, float]
    planned_margin: float          # CHF
    actual_margin: float

    @property
    def planned_margin_percent(self) -> float:
        return self.planned_margin / self.revenue * 100 if self.revenue else 0.0

    @property
    def actual_margin_percent(self) -> float:
        return self.actual_margin / self.revenue * 100 if self.revenue else 0.0

    def deviation_percent(self, key: str) -> float | None:
        planned = self.planned.get(key, 0.0)
        if not planned:
            return None
        return (self.actual.get(key, 0.0) - planned) / planned * 100


def default_project_files() -> list[str]:
    """Projekte im Arbeitsverzeichnis (App-Einstellung workspace_root_path)
    und die zuletzt geöffneten."""
    import json
    from .project_service import ProjectService
    base = os.environ.get("APPDATA", os.path.expanduser("~")) if os.name == "nt" \
        else os.path.join(os.path.expanduser("~"), ".config")
    workspace = ""
    try:
        with open(os.path.join(base, "KNiXArranger", "app_settings.json"), encoding="utf-8") as f:
            workspace = json.load(f).get("workspace_root_path", "")
    except (OSError, ValueError):
        pass
    try:
        recent = ProjectService().get_recent_projects()
    except (OSError, ValueError):
        recent = []
    return find_project_files(workspace, recent)


def find_project_files(workspace: str = "", extra: list[str] | None = None) -> list[str]:
    """Projektdateien im Arbeitsverzeichnis ({Workspace}/{Projekt}/{Projekt}.knxarr
    und direkt darin) sowie weitere Pfade (z.B. zuletzt geöffnet), ohne
    Sicherungen und doppelte."""
    found: list[str] = []
    if workspace and os.path.isdir(workspace):
        found += glob.glob(os.path.join(workspace, "*.knxarr"))
        found += glob.glob(os.path.join(workspace, "*", "*.knxarr"))
    found += [p for p in (extra or []) if p and os.path.isfile(p)]
    result, seen = [], set()
    for path in found:
        norm = os.path.normcase(os.path.abspath(path))
        parts = set(os.path.normpath(path).split(os.sep))
        if norm in seen or parts & set(_SKIP_FOLDERS) or "_backup_" in os.path.basename(path):
            continue
        seen.add(norm)
        result.append(path)
    return sorted(result)


def _device_count(project) -> int:
    """Busgeräte wie in der Aufwandsschätzung (ohne Koppler/Spannungsversorgung)."""
    return sum(1 for area in project.topology.areas for line in area.lines
               for d in line.devices if d.device_type not in ("coupler", "power_supply"))


def _has_actuals(quote) -> bool:
    return bool(quote.actual_material_cost or quote.actual_mounting_hours
                or quote.actual_programming_hours or quote.actual_commissioning_hours
                or quote.actual_documentation_hours)


def project_results(project) -> list[ProjectResult]:
    """Nachkalkulierte Offerten eines Projekts: Status "Akzeptiert" und Ist-Werte erfasst."""
    results = []
    for q in project.customer_quotes:
        if q.status != "Akzeptiert" or not _has_actuals(q):
            continue
        planned = {
            "material": q.material_total,
            "mounting": q.labor_mounting_hours,
            "programming": q.labor_programming_hours,
            "commissioning": q.labor_commissioning_hours,
            "documentation": q.labor_documentation_hours,
        }
        actual = {
            "material": q.actual_material_cost,
            "mounting": q.actual_mounting_hours,
            "programming": q.actual_programming_hours,
            "commissioning": q.actual_commissioning_hours,
            "documentation": q.actual_documentation_hours,
        }
        revenue = q.net_total
        planned_cost = q.material_total + q.labor_total + q.overhead_costs
        actual_cost = q.actual_material_cost + q.actual_labor_total + q.actual_overhead_costs
        results.append(ProjectResult(
            project=project.name, quote=q.quote_number, date=q.date_created or "",
            devices=_device_count(project), revenue=revenue,
            planned=planned, actual=actual,
            planned_margin=revenue - planned_cost, actual_margin=revenue - actual_cost,
        ))
    return results


def load_results(paths: list[str], current=None) -> list[ProjectResult]:
    """Ergebnisse aller Projektdateien; das geöffnete Projekt (current) im
    aktuellen, evtl. ungespeicherten Stand statt aus der Datei."""
    from ..models.project import KnxProject
    results = []
    current_path = os.path.normcase(os.path.abspath(current._file_path)) \
        if current is not None and getattr(current, "_file_path", "") else ""
    for path in paths:
        if os.path.normcase(os.path.abspath(path)) == current_path:
            continue
        try:
            results += project_results(KnxProject.load(path))
        except Exception as exc:          # beschädigte oder fremde Datei überspringen
            logger.warning("Nachkalkulation: %s nicht lesbar (%s)", path, exc)
    if current is not None:
        results += project_results(current)
    return sorted(results, key=lambda r: (r.date, r.project))


@dataclass
class CategoryDeviation:
    key: str
    label: str
    average_percent: float         # mittlere Abweichung Ist zu Soll
    deviating: int                 # Projekte mit |Abweichung| > Schwelle
    counted: int                   # Projekte mit Sollwert


@dataclass
class Overview:
    results: list[ProjectResult]
    planned_margin_percent: float = 0.0
    actual_margin_percent: float = 0.0
    deviations: list[CategoryDeviation] = field(default_factory=list)
    trend: str = ""                # Satz zur Entwicklung der Ist-Marge


def build_overview(results: list[ProjectResult]) -> Overview:
    """Auswertung über alle Projekte (FA-2206)."""
    overview = Overview(results=results)
    revenue = sum(r.revenue for r in results)
    if revenue:
        # umsatzgewichtet: grosse Projekte zählen mehr
        overview.planned_margin_percent = sum(r.planned_margin for r in results) / revenue * 100
        overview.actual_margin_percent = sum(r.actual_margin for r in results) / revenue * 100
    for key, label in CATEGORIES:
        values = [v for v in (r.deviation_percent(key) for r in results) if v is not None]
        if not values:
            continue
        overview.deviations.append(CategoryDeviation(
            key, label, sum(values) / len(values),
            sum(1 for v in values if abs(v) > DEVIATION_THRESHOLD), len(values)))
    # häufigste und grösste Abweichungen zuerst
    overview.deviations.sort(key=lambda d: (-d.deviating, -abs(d.average_percent)))
    overview.trend = _trend_sentence([r for r in results if r.date])
    return overview


def _trend_sentence(results: list[ProjectResult]) -> str:
    """Entwicklung der Ist-Marge: ältere gegen neuere Hälfte der Projekte."""
    if len(results) < 4:
        return "Für einen Verlauf braucht es mindestens vier nachkalkulierte Projekte."
    half = len(results) // 2
    old = sum(r.actual_margin_percent for r in results[:half]) / half
    new = sum(r.actual_margin_percent for r in results[half:]) / (len(results) - half)
    diff = new - old
    if abs(diff) < 2:
        return f"Die Marge ist stabil (ältere Projekte {old:.1f} %, neuere {new:.1f} %)."
    word = "gestiegen" if diff > 0 else "gesunken"
    return (f"Die Marge ist {word}: ältere Projekte {old:.1f} %, "
            f"neuere {new:.1f} % ({diff:+.1f} Prozentpunkte).")


@dataclass
class GuideValue:
    attr: str                      # Feld im Firmenprofil
    label: str
    current: float
    suggested: float
    based_on: int                  # Anzahl Projekte


# Richtwerte je Gerät (FA-1704/FA-1707): (Feld Minuten, Feld Sockel-Stunden, Kategorie, Bezeichnung)
_GUIDE_FIELDS = (
    ("minutes_programming_per_device", "", "programming", "Programmierung (Min. je Gerät)"),
    ("minutes_commissioning_per_device", "commissioning_base_hours", "commissioning",
     "Inbetriebnahme (Min. je Gerät)"),
    ("minutes_documentation_per_device", "documentation_base_hours", "documentation",
     "Dokumentation (Min. je Gerät)"),
)


def suggest_guide_values(results: list[ProjectResult], profile) -> list[GuideValue]:
    """Neue Richtwerte aus den Ist-Stunden (FA-2205): je Projekt Minuten je
    Gerät = (Ist-Stunden − Sockel) × 60 / Geräte, gemittelt über die Projekte.
    Mindestens zwei Projekte, sonst kein Vorschlag."""
    suggestions = []
    for attr, base_attr, key, label in _GUIDE_FIELDS:
        base = getattr(profile, base_attr) if base_attr else 0.0
        per_project = [max(r.actual[key] - base, 0.0) * 60 / r.devices
                       for r in results if r.devices and r.actual.get(key)]
        if len(per_project) < 2:
            continue
        suggested = round(sum(per_project) / len(per_project), 1)
        suggestions.append(GuideValue(attr, label, getattr(profile, attr), suggested,
                                      len(per_project)))
    return suggestions


def apply_guide_values(profile, suggestions: list[GuideValue]) -> None:
    for s in suggestions:
        setattr(profile, s.attr, s.suggested)


def display_date(iso: str) -> str:
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return iso
