"""
Szenennummern im Projekt (FA-1813 bis FA-1815).

KNX: Eine Szenen-GA (DPT 17.001/18.001) überträgt nur die Nummer 1–64; was
sie bewirkt, steht im Aktor. Ein Aktor hat meist ein Szenen-Objekt, an dem
mehrere Szenen-GAs hängen können (z.B. Raum- und Zentral-Szenen-GA) – für ihn
ist Szene 5 immer Szene 5, egal über welche GA sie kommt.

Daraus:
- FA-1813: gleiche Nummer auf verschiedenen Szenen-GAs ist nur ein Problem,
  wenn die Szenen dieselben Aktoren erreichen; gleiche Nummer auf derselben
  GA immer.
- FA-1814: Nummernbereiche je Ebene (Raum, Zone/Wohnung, Zentral), damit sich
  Szenen verschiedener Ebenen am selben Aktor nicht überschneiden.
- FA-1815: Szenen je Aktor für den Szenenreport (Parametrierung in der ETS).

Reine Datenoperation ohne Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Ebene einer Szene -> (erste, letzte) Nummer; in den Projekteinstellungen
# anpassbar (ProjectConfig.scene_number_ranges)
LEVELS = ("room", "apartment", "central")
LEVEL_LABELS = {"room": "Raum", "apartment": "Zone / Wohnung", "central": "Zentral"}
DEFAULT_RANGES: dict[str, tuple[int, int]] = {
    "room": (1, 20),
    "apartment": (21, 40),
    "central": (41, 64),
}


def scene_level(scope: str) -> str:
    """Ebene eines Geltungsbereichs: Zone zählt wie Wohnung, ohne = Zentral."""
    if scope == "room":
        return "room"
    if scope in ("apartment", "zone"):
        return "apartment"
    return "central"


def scene_ranges(project) -> dict[str, tuple[int, int]]:
    ranges = dict(DEFAULT_RANGES)
    for level, value in (getattr(project.config, "scene_number_ranges", None) or {}).items():
        if level in ranges and len(value) == 2:
            first, last = int(value[0]), int(value[1])
            if 1 <= first <= last <= 64:
                ranges[level] = (first, last)
    return ranges


def scene_range_problem(ranges: dict[str, tuple[int, int]]) -> str:
    """Fehlertext, wenn ein Bereich leer ist oder sich Bereiche überschneiden,
    sonst ""."""
    for level, (first, last) in ranges.items():
        if first > last:
            return f"{LEVEL_LABELS[level]}: «von» ist grösser als «bis»."
    items = sorted(ranges.items(), key=lambda kv: kv[1][0])
    for (la, (_fa, last_a)), (lb, (first_b, _lb)) in zip(items, items[1:]):
        if first_b <= last_a:
            return (f"Die Bereiche {LEVEL_LABELS[la]} und {LEVEL_LABELS[lb]} "
                    f"überschneiden sich.")
    return ""


def suggest_scene_number(project, scope: str, used: set[int]) -> int | None:
    """Nächste freie Nummer im Bereich der Ebene; ist der Bereich voll, die
    nächste freie überhaupt. Trägt die Szenen-Adresse schon Nummern, aber
    keine im Bereich (ältere Projekte, ETS-Import), wird deren Nummerierung
    weitergeführt. None, wenn alle 64 belegt sind."""
    first, last = scene_ranges(project)[scene_level(scope)]
    if used and not any(first <= n <= last for n in used):
        first, last = 1, 64
    for n in list(range(first, last + 1)) + list(range(1, 65)):
        if n not in used:
            return n
    return None


# ── Empfänger und Konflikte ─────────────────────────────────────────────────

@dataclass
class _Context:
    ga_by_address: dict
    ga_by_designation: dict
    actors_by_ga: dict            # GA-Adresse -> [(Adresse, Typ)]
    overview: object
    label_lookup: dict
    device_by_pa: dict


def _context(project) -> _Context:
    from .belegungsplan_service import BelegungsplanService, build_ga_by_designation
    from .scene_addressing import build_scope_label_lookup
    from .scene_overview import build_scene_overview
    actors: dict[str, list] = {}
    for row in BelegungsplanService().generate(project).actor_rows:
        if row.ga_address and row.physical_address:
            entry = (row.physical_address, row.actor_type or "")
            if entry not in actors.setdefault(row.ga_address, []):
                actors[row.ga_address].append(entry)
    devices = {d.physical_address: d for a in project.topology.areas
               for l in a.lines for d in l.devices if d.physical_address}
    return _Context(
        ga_by_address={g.address: g for g in project.group_addresses.all_addresses()},
        ga_by_designation=build_ga_by_designation(project.group_addresses),
        actors_by_ga=actors,
        overview=build_scene_overview(project),
        label_lookup=build_scope_label_lookup(project.areal),
        device_by_pa=devices,
    )


def _action_ga(action, ctx: _Context):
    if action.ga_address and action.ga_address in ctx.ga_by_address:
        return ctx.ga_by_address[action.ga_address]
    raw = (action.group_address or "").strip()
    return ctx.ga_by_designation.get(raw) or ctx.ga_by_designation.get(raw.split(" (")[0])


def _is_scene_ga(ga) -> bool:
    from .scene_overview import is_scene_dpt
    return ga.function_name == "SZENE" or is_scene_dpt(ga.datapoint_type or "")


def scene_receivers(project, scene, ctx: _Context | None = None) -> dict[str, str]:
    """Empfänger einer Szene: {Schlüssel: Anzeige}. Schlüssel ist die
    Aktor-Adresse; ohne bekannten Aktor das Gewerk-Element der Aktion.

    Quellen: die Aktoren an der Szenen-GA (Belegungsplan, geplante Projekte:
    Aktoren im Geltungsbereich), die dort empfangenden Geräte (importierte
    Projekte, KO-Verknüpfung) und die Aktoren der Aktionen. Eine Aktion auf
    eine andere Szenen-GA ruft dort eine eigene Szene auf (mit ihrem Wert) –
    deren Aktoren erhalten nicht diese Nummer und zählen nicht."""
    from .scene_overview import linked_devices
    ctx = ctx or _context(project)
    result: dict[str, str] = {}

    def add_actors(address: str) -> bool:
        actors = ctx.actors_by_ga.get(address, [])
        for pa, actor_type in actors:
            result[pa] = " ".join(p for p in (actor_type, pa) if p)
        return bool(actors)

    group = ctx.overview.address_of(scene)
    own = group.ga if group is not None else None
    if own is not None:
        add_actors(own.address)
        for linked in linked_devices(project, own.address):
            if not linked.sends:
                dev = linked.device
                label = dev.product_name or dev.product or dev.device_type
                result[dev.physical_address] = f"{label} {dev.physical_address}"
    for action in scene.actions:
        ga = _action_ga(action, ctx)
        if ga is None or (_is_scene_ga(ga) and (own is None or ga.address != own.address)):
            continue
        if not add_actors(ga.address) and ga.gewerk_code and ga.room_id:
            key = f"element:{ga.room_id}:{ga.gewerk_code}:{ga.element_number}"
            result[key] = ga.designation.split(" (")[0]
    return result


def scene_channel(scene, ctx: _Context) -> tuple[str, str]:
    """(Schlüssel, Anzeige) der Szenen-GA einer Szene."""
    from .scene_addressing import scene_channel_designation, scene_group_key
    group = ctx.overview.address_of(scene)
    if group is not None:
        shown = f"{group.ga.address} {group.designation}" if group.ga else group.designation
        return group.key, shown
    designation = scene_channel_designation(scene_group_key(scene), ctx.label_lookup)
    return f"geplant:{designation}", designation


@dataclass
class NumberConflict:
    number: int
    first: object               # Scene
    second: object              # Scene
    first_channel: str
    second_channel: str
    same_channel: bool
    shared: list[str] = field(default_factory=list)   # gemeinsame Empfänger (Anzeige)


def number_conflicts(project) -> list[NumberConflict]:
    """Gleiche Szenennummer auf derselben Szenen-GA, oder auf verschiedenen
    Szenen-GAs, deren Szenen dieselben Aktoren erreichen. Szenen ohne Nummer
    (erkannte Szenenkanäle) und der Visualisierung zählen nicht. Doppelte
    Nummern geplanter Szenen auf ihrer gemeinsamen Szenenaufruf-GA meldet
    bereits die GA-Generierung (FA-620) und fehlen hier."""
    from .scene_addressing import is_bound_scene
    scenes = [s for s in project.scenes
              if s.name and s.scene_number > 0 and s.detection_kind != "pattern"]
    if len(scenes) < 2:
        return []
    ctx = _context(project)
    channels = {id(s): scene_channel(s, ctx) for s in scenes}
    receivers = {id(s): scene_receivers(project, s, ctx) for s in scenes}

    def generated(scene) -> bool:
        return not scene.is_detected and not is_bound_scene(scene)

    conflicts: list[NumberConflict] = []
    by_number: dict[int, list] = {}
    for scene in scenes:
        by_number.setdefault(scene.scene_number, []).append(scene)
    for number, group in sorted(by_number.items()):
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                (key_a, shown_a), (key_b, shown_b) = channels[id(a)], channels[id(b)]
                if key_a == key_b:
                    if generated(a) and generated(b):
                        continue
                    conflicts.append(NumberConflict(number, a, b, shown_a, shown_b, True))
                    continue
                shared = sorted(set(receivers[id(a)]) & set(receivers[id(b)]))
                if shared:
                    conflicts.append(NumberConflict(
                        number, a, b, shown_a, shown_b, False,
                        [receivers[id(a)][k] for k in shared]))
    return conflicts


# ── Szenen je Aktor (Szenenreport) ──────────────────────────────────────────

@dataclass
class ActorScene:
    number: int
    scene: object
    channel: str


def scenes_by_actor(project) -> dict[str, tuple[str, list[ActorScene]]]:
    """{Aktor-Adresse: (Anzeige, [Szenen nach Nummer])} – nur echte Aktoren
    (Adresse bekannt), nur Szenen mit Nummer."""
    scenes = [s for s in project.scenes
              if s.name and s.scene_number > 0 and s.detection_kind != "pattern"]
    if not scenes:
        return {}
    ctx = _context(project)
    result: dict[str, tuple[str, list[ActorScene]]] = {}
    for scene in scenes:
        _key, shown = scene_channel(scene, ctx)
        for key, label in scene_receivers(project, scene, ctx).items():
            if key.startswith("element:"):
                continue
            entry = result.setdefault(key, (label, []))
            entry[1].append(ActorScene(scene.scene_number, scene, shown))
    for _label, items in result.values():
        items.sort(key=lambda a: (a.number, a.scene.name or ""))
    return result
