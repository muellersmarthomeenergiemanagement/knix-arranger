"""
KOs aller Geräte auf einmal zuordnen (Materialliste › «KOs aller Geräte
zuordnen…», FA-3009) und die unsicheren Fälle als Prüfliste melden.

Für jedes Gerät mit KOs aus dem Produkt, das noch keine Auswahl hat:
- Aktoren/Gateways: Kanal je Stromkreis wie im Belegungsplan, KO je GA nach
  der gemerkten Zuordnung des Produkts, sonst nach Texten (actor_proposal);
- Taster/Sensoren: KO je GA nach Vorlage, sonst nach Vorschlag
  (sensor_channels) -- inklusive Rollen (Aktorstatus, Externer Taster).
Aktoren mit eigener Auswahl bleiben unverändert (bewusste Entscheidung);
bei Tastern/Sensoren bleiben gewählte KOs, nur die Lücken werden gefüllt.

plan_all() rechnet nur, apply_plan() schreibt -- der Dialog zeigt dazwischen
das Ergebnis. Prüfliste:
- «nicht benötigt»: Funktion, für die der Aktorkanal keinen KO hat (Projekt_23
  Schaltaktoren 1.2.13/1.3.13/2.1.1: DIM, WERT, RM WERT eines Lichtkreises)
  -- lässt sich weglassen, der Platz bleibt Reserve;
- «kein KO»: GA ohne passenden KO (Sensor, unbekannte Herstellertexte);
- «DPT passt nicht».
"""
from __future__ import annotations

from dataclasses import dataclass, field

NOT_LINKED = -1
UNNEEDED = "nicht benötigt"
NO_KO = "kein KO"


@dataclass
class BatchIssue:
    device: object
    where: str          # Stromkreis bzw. Taste/Kanal
    function: str
    ga_address: str
    problem: str        # UNNEEDED | NO_KO | "DPT passt nicht (KO 1.001, GA 5.001)"


@dataclass
class DevicePlan:
    device: object
    channel_map: dict | None = None   # nur Aktoren
    co_map: dict = field(default_factory=dict)


@dataclass
class BatchPlan:
    plans: list[DevicePlan] = field(default_factory=list)
    kept: list = field(default_factory=list)        # Geräte mit eigener Auswahl
    issues: list[BatchIssue] = field(default_factory=list)
    links: int = 0                                   # GAs mit KO
    unneeded: dict[str, list[str]] = field(default_factory=dict)  # circuit_key -> Funktionen
    # Belegungspläne der Berechnung, zum Wiederverwenden (ko_links)
    sensor_rows: object = None
    actor_plan: object = None

    @property
    def unneeded_count(self) -> int:
        return sum(len(f) for f in self.unneeded.values())


def _devices(project) -> list:
    return [d for area in project.topology.areas for line in area.lines for d in line.devices
            if d.communication_objects
            and d.device_type in ("actor", "gateway", "sensor")]


def _dpt_problem(co, ga_dpt: str, variants=()) -> str:
    """Leer, wenn das KO oder eine Variante derselben Nummer passt: die
    Variante hängt von der Parametrierung ab (EDIZIOdue Taste 1: Schalten
    1.001, Wert 5.001, Szene 17.001), die ETS stellt sie beim Parametrieren."""
    from .co_linking_service import _dpt_compatible
    from .dpt_suggestion import dpt_number
    if any(_dpt_compatible(c.data_type, ga_dpt) for c in (co, *variants)
           if c.object_number == co.object_number):
        return ""
    return (f"DPT passt nicht (KO {dpt_number(co.data_type) or co.data_type}, "
            f"GA {dpt_number(ga_dpt) or ga_dpt})")


def plan_all(project, fresh: bool = False, only=None) -> BatchPlan:
    """Zuordnung für alle Geräte ohne Auswahl berechnen, ohne zu schreiben;
    only: nur diese Geräte (z.B. nach einer Produktzuweisung)."""
    from .actor_channels import (
        device_channels, device_circuits, device_com_objects, unneeded_functions,
    )
    from .ko_templates import actor_proposal, apply_sensor_template, load_template
    from .sensor_channels import (
        SENSOR_CO_KEY, has_sensor_selection, sensor_co_map, sensor_links,
        sensor_plan, suggested_sensor_co_map,
    )

    from .belegungsplan_service import BelegungsplanService
    batch = BatchPlan()
    sensor_rows = None
    actor_plan = None
    only_ids = {id(d) for d in only} if only is not None else None
    for device in _devices(project):
        if only_ids is not None and id(device) not in only_ids:
            continue
        all_cos = device_com_objects(device)
        known = {co.object_number for co in all_cos}
        by_number = {co.object_number: co for co in all_cos}
        variants = {}
        for co in device.communication_objects:
            variants.setdefault(co.object_number, []).append(co)
        template = load_template(device)
        if device.device_type == "sensor":
            if sensor_rows is None:
                sensor_rows = batch.sensor_rows = sensor_plan(project, fresh)
            links = sensor_links(project, device, sensor_rows)
            if not links:
                continue
            remembered = apply_sensor_template(template, links, known)
            suggested = suggested_sensor_co_map(device, links, all_cos)
            # Gewähltes KO des Geräts bleibt; Lücken füllt das gemerkte KO,
            # dann der Vorschlag. Ein «nicht verknüpfen» (gewählt oder gemerkt)
            # gilt nur, wenn der Vorschlag auch nichts findet -- es stammt oft
            # aus der Zeit, als er bei diesem Produkt noch nichts fand
            chosen = sensor_co_map(device) if has_sensor_selection(device) else {}
            selection = {}
            for link in links:
                if chosen.get(link.key, NOT_LINKED) >= 0:
                    selection[link.key] = chosen[link.key]
                    continue
                kept = remembered.get(link.key)
                proposed = suggested.get(link.key, NOT_LINKED)
                selection[link.key] = kept if kept is not None and (kept >= 0 or proposed < 0) \
                    else proposed
            if chosen and all(selection[link.key] == chosen.get(link.key, NOT_LINKED)
                              for link in links):
                batch.kept.append(device)
                continue
            co_map = dict(device.co_map or {})
            co_map[SENSOR_CO_KEY] = selection
            batch.plans.append(DevicePlan(device, None, co_map))
            for link in links:
                _record(batch, device, link.channel, link.function, link.ga_address,
                        by_number.get(selection[link.key]), link.dpt,
                        variants.get(selection[link.key], ()))
            continue

        if device.co_map:
            batch.kept.append(device)
            continue
        if actor_plan is None:
            actor_plan = batch.actor_plan = BelegungsplanService().generate(project)
        circuits = device_circuits(project, device, actor_plan)
        if not circuits:
            continue
        channels = {ch.number: ch
                    for ch in device_channels(device, fallback_count=len(circuits))}
        channel_map, co_map = {}, {}
        for circuit in circuits:
            number = (device.channel_map or {}).get(circuit.key) or circuit.channel
            channel_map[circuit.key] = number
            selection = actor_proposal(channels.get(number), circuit, number, template, known)
            co_map[circuit.key] = {function: selection.get(function, NOT_LINKED)
                                   for function, _ga in circuit.functions}
            unneeded = unneeded_functions(channels.get(number), circuit, co_map[circuit.key])
            if unneeded:
                batch.unneeded[circuit.key] = unneeded
            for function, ga_address in circuit.functions:
                if function in unneeded:
                    batch.issues.append(BatchIssue(device, circuit.label, function,
                                                   ga_address, UNNEEDED))
                    continue
                _record(batch, device, circuit.label, function, ga_address,
                        by_number.get(co_map[circuit.key][function]),
                        circuit.dpts.get(function, ""),
                        variants.get(co_map[circuit.key][function], ()))
        batch.plans.append(DevicePlan(device, channel_map, co_map))
    return batch


def _record(batch: BatchPlan, device, where: str, function: str, ga_address: str,
            co, ga_dpt: str, variants=()) -> None:
    if co is None:
        batch.issues.append(BatchIssue(device, where, function, ga_address, NO_KO))
        return
    batch.links += 1
    problem = _dpt_problem(co, ga_dpt, variants)
    if problem:
        batch.issues.append(BatchIssue(device, where, function, ga_address, problem))


def apply_plan(project, batch: BatchPlan, omit: bool = False) -> int:
    """Zuordnung schreiben; mit omit die nicht benötigten Funktionen weglassen.
    Gibt die Anzahl weggelassener Funktionen zurück (dann GAs neu erzeugen)."""
    from .actor_channels import omit_functions
    for plan in batch.plans:
        if plan.channel_map is not None:
            plan.device.channel_map = dict(plan.channel_map)
        plan.device.co_map = dict(plan.co_map)
    omitted = 0
    if omit and not project.addresses_fixed:
        for key, functions in batch.unneeded.items():
            omitted += omit_functions(project, key, functions)
    return omitted
