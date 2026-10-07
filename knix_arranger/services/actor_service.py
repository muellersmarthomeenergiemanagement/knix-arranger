"""
Aktor-Ermittlung (FA-1300)
Bestimmt benötigte Aktortypen pro Linie basierend auf Gewerken.
"""
from __future__ import annotations
import json
import os
import logging
import math
from dataclasses import dataclass, field
from ..models.building import Areal, Floor, Room
from ..models.topology import Topology
from ..models.device import Actor, ProductInfo, GEWERK_TO_ACTOR_TYPE
from ..models.gewerk import GewerkCatalog

logger = logging.getLogger("knix_arranger.actor_service")


class ActorRequirement:
    """Benötigter Aktor-Typ mit Kanalanzahl."""

    def __init__(self, actor_type: str, channels_needed: int,
                 gewerk_codes: list[str] = None):
        self.actor_type = actor_type
        self.channels_needed = channels_needed
        self.gewerk_codes = gewerk_codes or []

    def __repr__(self):
        return f"ActorRequirement({self.actor_type}, {self.channels_needed} Kanäle)"


@dataclass
class LineActorResult:
    """Ergebnis der Aktor-Ermittlung für eine einzelne Linie."""
    line_name: str = ""
    coupler_address: str = ""
    area_number: int = 0
    line_number: int = 0
    device_count: int = 0
    requirements: list[ActorRequirement] = field(default_factory=list)
    actors: list[Actor] = field(default_factory=list)


class ActorService:
    """Ermittelt benötigte Aktoren basierend auf Gewerken (FA-1301, FA-1302)."""

    def __init__(self):
        self._load_actor_channels()

    def _load_actor_channels(self):
        """Lädt verfügbare Kanalkonfigurationen."""
        config_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
        )
        filepath = os.path.join(config_dir, "actor_mapping.json")
        self.channel_options: dict[str, list[int]] = {}
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.channel_options = data.get("actor_channels", {})

    def determine_actors(self, rooms: list[Room], catalog: GewerkCatalog,
                         exclude_codes=frozenset(),
                         only_codes=None) -> list[ActorRequirement]:
        """
        Ermittelt benötigte Aktorentypen (FA-1301).
        Fasst Kanäle zusammen (FA-1302).
        exclude_codes: Gewerke, die hier nicht zählen (gemeinsame Gateways).
        only_codes: nur diese Gewerke zählen (ein gemeinsames Gateway).
        """
        # Sammle benötigte Kanäle pro Aktortyp
        type_channels: dict[str, int] = {}
        type_gewerke: dict[str, list[str]] = {}

        for room in rooms:
            for assignment in room.gewerk_assignments:
                if assignment.gewerk_code in exclude_codes:
                    continue
                if only_codes is not None and assignment.gewerk_code not in only_codes:
                    continue
                actor_type = GEWERK_TO_ACTOR_TYPE.get(assignment.gewerk_code)
                if not actor_type:
                    continue

                channels = assignment.count
                type_channels[actor_type] = type_channels.get(actor_type, 0) + channels
                if actor_type not in type_gewerke:
                    type_gewerke[actor_type] = []
                type_gewerke[actor_type].append(assignment.gewerk_code)

        requirements = []
        for actor_type, channels_needed in type_channels.items():
            requirements.append(ActorRequirement(
                actor_type=actor_type,
                channels_needed=channels_needed,
                gewerk_codes=type_gewerke.get(actor_type, []),
            ))

        return requirements

    def suggest_actors(self, requirements: list[ActorRequirement]) -> list[Actor]:
        """
        Schlägt optimale Aktoren vor (FA-1302).
        Verwendet die kleinste passende Kanalkonfiguration.
        """
        actors = []

        for req in requirements:
            available = self.channel_options.get(req.actor_type, [4, 8, 12])
            remaining = req.channels_needed

            while remaining > 0:
                # Waehle optimale Kanalanzahl
                best_channels = available[-1]  # Groesster als Fallback
                for ch in sorted(available):
                    if ch >= remaining:
                        best_channels = ch
                        break

                actor = Actor(
                    actor_type=f"{req.actor_type} {best_channels}-fach",
                    channels=best_channels,
                )
                actors.append(actor)
                remaining -= best_channels

        return actors

    def determine_actors_per_line(
        self, topology: Topology, all_rooms: list[Room],
        catalog: GewerkCatalog, shared: dict[str, str] | None = None,
    ) -> list[LineActorResult]:
        """
        Ermittelt Aktoren pro Linie (liniengerecht).

        Jede Linie bekommt eigene Aktoren für die ihr zugeordneten Räume.
        Linienkoppler filtern GAs, daher muessen Aktoren auf derselben Linie
        wie die gesteuerten Räume sitzen.

        shared: Gateway-Gewerke mit einem gemeinsamen Gateway für das Projekt
        (Gewerk -> Line.id, leer = automatisch, siehe KnxProject.shared_gateways).
        Ihre Elemente aller Räume zählen zusammen auf einer Linie -- z.B. ein
        Revox-Gateway für Studio und Wohnung, die Telegramme laufen über die
        Koppler.
        """
        shared = shared or {}
        # Room-ID -> Room Lookup erstellen
        room_by_id = {r.id: r for r in all_rooms}
        lines = [(area, line) for area in topology.areas for line in area.lines]

        by_line: dict[str, LineActorResult] = {}
        requirements_by_line: dict[str, list[ActorRequirement]] = {}
        for area, line in lines:
            # Räume dieser Linie filtern
            line_rooms = [
                room_by_id[rid]
                for rid in line.assigned_room_ids
                if rid in room_by_id
            ]
            if not line_rooms:
                continue
            requirements_by_line[line.id] = self.determine_actors(
                line_rooms, catalog, exclude_codes=frozenset(shared))
            by_line[line.id] = self._line_result(area, line)

        # Gemeinsame Gateways: alle Elemente des Gewerks auf eine Linie
        for code, line_id in shared.items():
            rooms = [r for r in all_rooms
                     if any(a.gewerk_code == code for a in r.gewerk_assignments)]
            # Nur dieses Gewerk -- sonst käme die erste Anforderung irgendeines
            # Gewerks der Räume heraus (z.B. Schaltaktor fürs Licht statt MM)
            requirement = next(iter(self.determine_actors(
                rooms, catalog, only_codes={code})), None) if rooms else None
            if requirement is None:
                continue
            target = self.shared_gateway_line(topology, all_rooms, code, line_id)
            if target is None:
                continue
            area, line = target
            by_line.setdefault(line.id, self._line_result(area, line))
            requirements_by_line.setdefault(line.id, []).append(requirement)

        results = []
        for _area, line in lines:
            if line.id not in by_line:
                continue
            result = by_line[line.id]
            result.requirements = requirements_by_line.get(line.id, [])
            result.actors = self.suggest_actors(result.requirements)
            results.append(result)
        return results

    @staticmethod
    def _line_result(area, line) -> LineActorResult:
        return LineActorResult(
            line_name=line.name,
            coupler_address=line.coupler_address,
            area_number=area.area_number,
            line_number=line.line_number,
            device_count=line.device_count,
        )

    @staticmethod
    def shared_gateway_line(topology: Topology, all_rooms: list[Room], code: str,
                            line_id: str = ""):
        """Linie des gemeinsamen Gateways: die gewählte; sonst die Linie mit dem
        Raum der HV; sonst die erste Linie mit Räumen dieses Gewerks; sonst die
        erste Linie mit Räumen. (Area, Line) oder None."""
        lines = [(area, line) for area in topology.areas for line in area.lines]
        if line_id:
            chosen = next(((a, ln) for a, ln in lines if ln.id == line_id), None)
            if chosen:
                return chosen
        hv_rooms = {r.id for r in all_rooms for vt in r.verteiler if vt.verteiler_type == "HV"}
        code_rooms = {r.id for r in all_rooms
                      if any(a.gewerk_code == code for a in r.gewerk_assignments)}
        for wanted in (hv_rooms, code_rooms, None):
            for area, line in lines:
                if not line.assigned_room_ids:
                    continue
                if wanted is None or set(line.assigned_room_ids) & wanted:
                    return area, line
        return None

    def create_material_list(self, actors: list[Actor]) -> list[dict]:
        """Erstellt eine Materialliste der Aktoren (FA-1306)."""
        summary: dict[str, dict] = {}

        for actor in actors:
            key = f"{actor.actor_type}|{actor.product.manufacturer}|{actor.product.order_number}"
            if key not in summary:
                summary[key] = {
                    "actor_type": actor.actor_type,
                    "manufacturer": actor.product.manufacturer,
                    "order_number": actor.product.order_number,
                    "product_name": actor.product.product_name,
                    "quantity": 0,
                    "unit_price": actor.product.price,
                }
            summary[key]["quantity"] += 1

        return list(summary.values())
