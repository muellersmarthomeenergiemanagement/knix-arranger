"""
Arbeitsablauf eines geplanten Projekts mit Stand je Schritt (Übersicht).

Nach dem Wizard geht es in dieser Reihenfolge weiter, weil jeder Schritt auf
dem vorherigen aufbaut: die Bauherrenberatung bestimmt Tasten und Geräte,
erst danach lohnen sich Produkte und KO-Zuordnung, dann DALI, Validierung,
Export an die ETS und die Unterlagen. Bis zur Übertragung in die ETS darf
jederzeit umgeplant werden.

Der Stand ist eine Orientierung aus den Projektdaten, kein Abschluss-
Nachweis: «erledigt» heisst, die Daten des Schritts sind vorhanden.

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

DONE = "erledigt"
PARTIAL = "begonnen"
OPEN = "offen"
NOT_NEEDED = "nicht nötig"
INFO = ""                   # ohne Bewertung (z.B. Berichte)


@dataclass
class WorkflowStep:
    number: int
    title: str
    nav_key: str             # Seitenleisten-Schlüssel (main_window._navigate)
    description: str
    state: str
    detail: str = ""


def _devices(project) -> list:
    return [d for a in project.topology.areas for line in a.lines for d in line.devices]


def _kos_assigned(device) -> bool:
    if any(co.connected_gas for co in device.communication_objects):
        return True
    for selection in (device.co_map or {}).values():
        values = selection.values() if isinstance(selection, dict) else []
        if any(isinstance(n, int) and n >= 0 for n in values):
            return True
    return False


def workflow_steps(project, errors: int | None = None,
                   warnings: int | None = None) -> list[WorkflowStep]:
    """Die acht Schritte mit Stand. errors/warnings: aktuelle Zahlen der
    Validierung (None = noch nicht geprüft)."""
    rooms = project.all_rooms
    gas = [g for g in project.group_addresses.all_addresses() if not g.is_placeholder]
    steps: list[WorkflowStep] = []

    # 1 Grundplanung
    planned = bool(rooms and gas)
    steps.append(WorkflowStep(
        1, "Grundplanung", "wizard",
        "Gebäude, Gewerke, Geräte, Gruppenadressen und automatische Tastenbelegung.",
        DONE if planned else OPEN,
        f"{len(rooms)} Räume, {len(gas)} GAs" if planned else "Wizard starten"))

    # 2 Bauherrenberatung: von Hand bearbeitete Bedienstellen
    operable = [be for r in rooms for be in r.bedienelemente
                if not be.suppressed and be.is_operable]
    edited = [be for be in operable if not be.is_auto]
    steps.append(WorkflowStep(
        2, "Bauherren-Beratung", "bauherr_form",
        "Je Raum die Tasten belegen, Melder ergänzen, Bezeichnungen für die Anleitung.",
        DONE if operable and len(edited) == len(operable)
        else PARTIAL if edited else OPEN,
        f"{len(edited)} von {len(operable)} Bedienstellen bearbeitet" if operable
        else "keine Bedienstellen"))

    # 3 Szenen und Zeitsteuerung (freiwillig)
    scenes = [s for s in project.scenes if s.name]
    programs = list(project.time_programs)
    steps.append(WorkflowStep(
        3, "Szenen und Zeitsteuerung", "scenes",
        "Szenen mit Nummern, Aktionen und Auslöser-Tasten; Zeitprogramme.",
        DONE if scenes or programs else OPEN,
        f"{len(scenes)} {'Szene' if len(scenes) == 1 else 'Szenen'}, {len(programs)} "
        f"{'Zeitprogramm' if len(programs) == 1 else 'Zeitprogramme'}"))

    # 4 Materialliste: Produkte, dann KOs
    devices = [d for d in _devices(project) if d.device_type in ("actor", "gateway", "sensor")]
    with_product = [d for d in devices if d.manufacturer and d.order_number]
    with_kos = [d for d in with_product if d.communication_objects]
    assigned = [d for d in with_kos if _kos_assigned(d)]
    if not devices:
        state = OPEN
    elif len(with_product) == len(devices) and len(assigned) == len(with_kos):
        state = DONE
    else:
        state = PARTIAL if with_product else OPEN
    steps.append(WorkflowStep(
        4, "Materialliste: Produkte und KOs", "material_list",
        "Produkte zuweisen, danach «KOs aller Geräte zuordnen».",
        state,
        f"{len(with_product)} von {len(devices)} Geräten mit Produkt, "
        f"{len(assigned)} von {len(with_kos)} mit KO-Zuordnung"))

    # 5 DALI
    gateways = [d for d in _devices(project)
                if d.device_type == "gateway" and "DALI" in (d.product or "").upper()]
    # Konfiguration über Geräte-ID oder Adresse (die ID ändert sich bei Neuberechnung)
    configured = [d for d in gateways if any(
        cfg.groups and (cfg.gateway_device_id == d.id
                        or (d.physical_address and cfg.gateway_address == d.physical_address))
        for cfg in project.dali_configs.values())]
    steps.append(WorkflowStep(
        5, "DALI-Konfiguration", "dali_config",
        "Gruppen und Vorschaltgeräte je Gateway.",
        NOT_NEEDED if not gateways
        else DONE if len(configured) == len(gateways) else PARTIAL if configured else OPEN,
        f"{len(configured)} von {len(gateways)} Gateways konfiguriert" if gateways
        else "kein DALI-Gateway"))

    # 6 Validierung
    if errors is None or warnings is None:
        state, detail = OPEN, "noch nicht geprüft"
    else:
        state = DONE if errors == 0 and warnings == 0 else PARTIAL if errors == 0 else OPEN
        detail = f"{errors} Fehler, {warnings} Warnungen"
    steps.append(WorkflowStep(
        6, "Validierung", "validation",
        "Fehler und Warnungen abarbeiten, Flags mit «Flags bearbeiten…» bereinigen.",
        state, detail))

    # 7 Export an die ETS
    steps.append(WorkflowStep(
        7, "Export an die ETS", "export",
        "GA-Liste (CSV) und ETS-Belegungsplan, danach Status «in ETS übertragen».",
        DONE if project.ets_transferred else OPEN,
        f"in ETS übertragen am {project.ets_transferred}" if project.ets_transferred
        else "noch nicht übertragen"))

    # 8 Unterlagen
    steps.append(WorkflowStep(
        8, "Berichte und Unterlagen", "reports",
        "Szenenreport, Aktoren und Gateways, Raumbuch, Bedienungsanleitung, Revisionspaket.",
        INFO, ""))
    return steps


def next_step(steps: list[WorkflowStep]) -> WorkflowStep | None:
    """Erster Schritt, der noch offen oder begonnen ist."""
    return next((s for s in steps if s.state in (OPEN, PARTIAL)), None)
