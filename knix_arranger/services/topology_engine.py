"""
Topologie-Berechnung und Linienzuteilung (FA-200, FA-208-210)
Automatische Berechnung der optimalen KNX-Topologie.

Linien werden nach Wohnungen/Zonen organisiert (nicht nach Stockwerken),
da Linienkoppler Gruppenadressen filtern. Geräte innerhalb derselben
Zone sollen sich eine Linie teilen.

- EFH (eine Wohnung): alle Räume in einer Linie
- MFH (mehrere Wohnungen): eine Linie pro Wohnung
- Zweckbau (Zonen): gleiche Zonennamen stockwerkuebergreifend zusammengefasst
- Bei >85 Geräten pro Zone: automatische Aufteilung auf mehrere Linien
"""
from __future__ import annotations
import logging
from collections import defaultdict
from ..models.building import Areal, Room
from ..models.topology import Topology, Area, Line, Device
from ..models.gewerk import GewerkCatalog

logger = logging.getLogger("knix_arranger.topology")

# Konstanten
RECOMMENDED_DEVICES = 85   # T-03
MAX_REALIZED = 100         # T-03
MAX_LINES_PER_AREA = 15   # T-04
MAX_AREAS = 15             # T-05

# Aktor-Sortierung (Kap. 9.1)
PRIORITY_ACTOR_TYPE = "Tasterblock"  # Erhält immer Adresse 1 (kommt vor alphabetischer Sortierung)
ACTOR_BLOCK_RESERVE = 3              # Reserve-Adressen zwischen verschiedenen Aktortyp-Blöcken

# Sensor-Sortierung (Kap. 9.1)
PRIORITY_SENSOR_TYPE = "Tastereinheit"  # Erhält immer die niedrigste Sensoradresse (kommt vor alphabetischer Sortierung)
SENSOR_BLOCK_RESERVE = 3             # Reserve-Adressen zwischen verschiedenen Sensortyp-Blöcken


class TopologyEngine:
    """Engine für automatische Topologie-Berechnung."""

    def __init__(self, topology_mode: str = "TP-256"):
        self.topology_mode = topology_mode

    def calculate_topology(self, areal: Areal) -> Topology:
        """
        Berechnet die optimale KNX-Topologie (FA-201, FA-209).

        Algorithmus:
        1. Pruefen ob Einzel- oder Mehrzonen-Gebäude
        2. EFH (kein Stockwerk hat >1 Wohnung): Alle Räume in eine Zone
        3. MFH/Zweckbau (Stockwerke mit mehreren Wohnungen/Zonen):
           Räume nach Zonennamen gruppieren -> je 1 Linie
        4. Bei >85 Geräten pro Zone: Linie aufteilen
        """
        topology = Topology(topology_mode=self.topology_mode)

        for building in areal.buildings:
            for wing in building.wings:
                area = self._create_area_for_wing(wing, topology)
                topology.areas.append(area)

        return topology

    def _create_area_for_wing(self, wing, topology: Topology) -> Area:
        """Erstellt einen Bereich für einen Gebäude-Flügel."""
        area_number = len(topology.areas) + 1
        area = Area(
            area_number=area_number,
            name=wing.name,
            coupler_address=f"{area_number}.0.0",
        )

        # Pruefen ob Multi-Zone: Hat irgendein Stockwerk mehrere Wohnungen?
        # Gleiche Zonennamen auf verschiedenen Stockwerken werden von
        # _collect_zones() automatisch zusammengefasst (Maisonette-Unterstützung).
        is_multi_zone = any(
            len(floor.apartments) > 1 for floor in wing.floors
        )

        if is_multi_zone:
            # MFH/Zweckbau: Räume nach Zonennamen gruppieren
            # Gleiche Zonennamen auf verschiedenen Etagen werden zusammengefasst
            zones = self._collect_zones(wing)
            line_number = 1
            for zone_name, zone_rooms in zones.items():
                total_devices = sum(r.total_devices() for r in zone_rooms)
                if total_devices == 0:
                    continue

                if total_devices <= RECOMMENDED_DEVICES:
                    line = self._create_line(
                        area_number, line_number, zone_name, zone_rooms
                    )
                    area.lines.append(line)
                    line_number += 1
                else:
                    # Zone hat zu viele Geräte -> auf mehrere Linien aufteilen
                    splits = self._split_rooms_into_lines(zone_rooms)
                    for i, room_group in enumerate(splits):
                        suffix = f" (Teil {i+1})" if len(splits) > 1 else ""
                        line = self._create_line(
                            area_number, line_number,
                            f"{zone_name}{suffix}", room_group
                        )
                        area.lines.append(line)
                        line_number += 1
        else:
            # EFH / Einzelzone: Alle Räume in eine einzige Linie zusammenfassen
            all_rooms = []
            for floor in wing.floors:
                all_rooms.extend(floor.all_rooms)

            total_devices = sum(r.total_devices() for r in all_rooms)
            if total_devices > 0:
                line_number = 1
                if total_devices <= RECOMMENDED_DEVICES:
                    line = self._create_line(
                        area_number, line_number, wing.name, all_rooms
                    )
                    area.lines.append(line)
                else:
                    # Einzelzone mit vielen Geräten -> aufteilen
                    splits = self._split_rooms_into_lines(all_rooms)
                    for i, room_group in enumerate(splits):
                        suffix = f" (Teil {i+1})" if len(splits) > 1 else ""
                        line = self._create_line(
                            area_number, line_number + i,
                            f"{wing.name}{suffix}", room_group
                        )
                        area.lines.append(line)

        return area

    def _collect_zones(self, wing) -> dict[str, list[Room]]:
        """
        Sammelt Räume nach Zonennamen (stockwerkuebergreifend).
        Gleiche Zonennamen auf verschiedenen Stockwerken werden zusammengefasst.
        """
        zones: dict[str, list[Room]] = defaultdict(list)
        for floor in wing.floors:
            for apt in floor.apartments:
                zones[apt.name].extend(apt.rooms)
        return dict(zones)

    def _create_line(self, area_number: int, line_number: int,
                     name: str, rooms: list[Room]) -> Line:
        """Erstellt eine Linie mit zugeordneten Räumen."""
        line = Line(
            line_number=line_number,
            name=name,
            coupler_address=f"{area_number}.{line_number}.0",
            assigned_room_ids=[r.id for r in rooms],
        )
        # Geräteanzahl berechnen
        line.device_count = sum(r.total_devices() for r in rooms)

        # Verteiler-Standort für die Linie ermitteln (erster Verteiler in den Räumen)
        for room in rooms:
            if room.has_verteiler:
                vt = room.verteiler[0]
                line.uv_location = f"{vt.verteiler_type} ({vt.name or room.name})"
                break

        if line.device_count > RECOMMENDED_DEVICES:
            logger.warning(
                f"Linie {line.coupler_address}: {line.device_count} Geräte "
                f"(empfohlen: max. {RECOMMENDED_DEVICES})"
            )
        if line.device_count > MAX_REALIZED:
            logger.error(
                f"Linie {line.coupler_address}: {line.device_count} Geräte "
                f"ueberschreitet Maximum von {MAX_REALIZED}!"
            )

        return line

    def _split_rooms_into_lines(self, rooms: list[Room]) -> list[list[Room]]:
        """
        Teilt Räume in Gruppen auf, sodass jede Gruppe max. 85 Geräte hat.
        Greedy-Algorithmus: Räume der Reihe nach einfügen.
        """
        lines: list[list[Room]] = [[]]
        current_count = 0

        for room in rooms:
            device_count = room.total_devices()
            if current_count + device_count > RECOMMENDED_DEVICES and lines[-1]:
                lines.append([])
                current_count = 0
            lines[-1].append(room)
            current_count += device_count

        return [line for line in lines if line]

    def update_device_estimates(self, rooms: list[Room],
                                catalog: GewerkCatalog) -> None:
        """
        Leitet planned_sensors und planned_actors jedes Raums aus den
        Gewerk-Zuweisungen ab.  Muss vor calculate_topology aufgerufen werden.

        Aktoren:  Kanäle pro Aktortyp → ceil(Kanäle / 4) Geräte.
        Sensoren: ein Gerät pro distinctem Sensortyp im Raum.
        Kein Gewerk: Mindestwert 1/1 damit der Raum in der Topologie erscheint.
        """
        import math
        from ..models.device import GEWERK_TO_ACTOR_TYPE, GEWERK_TO_SENSOR_TYPE, GATEWAY_ACTOR_TYPES

        for room in rooms:
            if not room.gewerk_assignments:
                room.planned_sensors = 1
                room.planned_actors = 1
                continue

            # Aktoren: Kanäle pro Typ summieren, auf Geräte hochrechnen (4-Kanal).
            # FA-1307: Gateway-Gewerke (LDA, MM, WP) zählen als 1 Device (nicht Kanal-basiert).
            type_channels: dict[str, int] = {}
            gateway_devices: int = 0
            for ga in room.gewerk_assignments:
                actor_type = GEWERK_TO_ACTOR_TYPE.get(ga.gewerk_code)
                if not actor_type:
                    continue
                if actor_type in GATEWAY_ACTOR_TYPES:
                    gateway_devices += 1  # 1 Gateway-Device pro Gateway-Gewerk-Zuweisung
                else:
                    type_channels[actor_type] = (
                        type_channels.get(actor_type, 0) + ga.count
                    )
            actor_devices = sum(math.ceil(ch / 4) for ch in type_channels.values()) + gateway_devices
            room.planned_actors = max(actor_devices, 1)

            # Sensoren: ein Gerät pro distinctem Sensortyp
            sensor_types = {
                GEWERK_TO_SENSOR_TYPE[ga.gewerk_code]
                for ga in room.gewerk_assignments
                if ga.gewerk_code in GEWERK_TO_SENSOR_TYPE
            }
            room.planned_sensors = max(len(sensor_types), 1)

    def populate_devices(self, topology: Topology, all_rooms: list[Room],
                         catalog: GewerkCatalog,
                         small_project: bool = False,
                         preserve_manual: bool = False):
        """
        Fügt alle Linienteilnehmer gemaess KNX Projektrichtlinien 2024 ein.

        Pro Bereich (Kap. 3.5.1):
        - Bereichskoppler (BK) an Adresse B.0.0

        Pro Linie (Kap. 3.2, 3.5, 9.1):
        - Linienkoppler (LK) an Adresse B.L.0
        - Spannungsversorgung (SV) inkl. Drossel (T-06)
        - Aktoren in der Verteilung (Adressen 1-100 bzw. 1-20)
        - Sensoren in den Räumen (Adressen 101-199 bzw. 21-40)

        preserve_manual=True:
          - Manuell zugewiesene Herstellerprodukte bleiben erhalten.
          - Programmierte Geräte (is_programmed=True) behalten ihre
            physikalische Adresse (Teilnehmernummer). Neubedarf wird als
            Delta-Geräte in freie Adressslots eingefügt.
        """
        from collections import Counter
        from .actor_service import ActorService
        from .sensor_service import SensorService
        from ..models.device import GATEWAY_ACTOR_TYPES  # FA-1307

        # ── Sicherungen vor line.devices.clear() ──────────────────────────────

        # Programmierte Geräte (is_programmed=True) pro Linie sichern.
        # Ihre Teilnehmernummer ist fest und darf nie überschrieben werden.
        programmed_by_line: dict[str, list] = {}

        # Manuelle Produktzuweisungen (Hersteller/Bestellnr. nach Adresse)
        manual_assignments: dict = {}
        # Manuell aufgeteilte Aktoren (manually_split) pro Linie
        manual_actor_devices: dict[str, list] = {}
        # Manuell hinzugefügte Geräte (manually_added) pro Linie
        manual_added_by_line: dict[str, list] = {}

        if preserve_manual:
            for area in topology.areas:
                for line in area.lines:
                    # Programmierte Geräte (Aktoren, Sensoren, Gateways)
                    prog = [
                        d for d in line.devices
                        if d.is_programmed
                        and d.device_type not in ("coupler", "power_supply")
                    ]
                    if prog:
                        programmed_by_line[line.coupler_address] = prog

                    for device in line.devices:
                        if device.is_programmed:
                            # Hersteller-Daten werden über is_programmed erhalten,
                            # nicht extra in manual_assignments (device bleibt erhalten)
                            continue
                        if device.manually_added:
                            manual_added_by_line.setdefault(
                                line.coupler_address, []
                            ).append(device)
                            continue
                        if device.manufacturer and device.physical_address:
                            manual_assignments[device.physical_address] = {
                                "manufacturer": device.manufacturer,
                                "order_number": device.order_number,
                                "product_name": device.product_name,
                            }
                    # Wenn die Linie manuell aufgeteilte (nicht-programmierte)
                    # Aktoren enthält, alle nicht-programmierten Aktoren sichern
                    if any(d.manually_split and not d.is_programmed
                           for d in line.devices if d.device_type == "actor"):
                        manual_actor_devices[line.coupler_address] = [
                            d for d in line.devices
                            if d.device_type == "actor" and not d.is_programmed
                        ]

        actor_service = ActorService()
        sensor_service = SensorService()

        actor_results = actor_service.determine_actors_per_line(
            topology, all_rooms, catalog
        )
        sensor_results = sensor_service.determine_sensors_per_line(
            topology, all_rooms, catalog
        )

        # Lookup: coupler_address -> Ergebnisse
        actor_by_line = {r.coupler_address: r for r in actor_results}
        sensor_by_line = {r.coupler_address: r for r in sensor_results}

        # Lookup: room_id -> room (für Sensor-Einbauort)
        room_by_id = {r.id: r for r in all_rooms}

        multi_area = len(topology.areas) > 1

        for area in topology.areas:
            # Speisegerät Bereichslinie (T-06) – nur bei mehreren Bereichen
            if multi_area:
                if area.backbone_power_supply is None:
                    area.backbone_power_supply = Device(
                        device_type="power_supply",
                        product="KNX-Spannungsversorgung Bereichslinie 640mA",
                        installation_location="HV",
                    )
            else:
                area.backbone_power_supply = None

            for idx, line in enumerate(area.lines):
                line.devices.clear()

                # Bereichskoppler (Kap. 3.5.1, Adresse B.0.0) –
                # nur bei mehreren Bereichen, in erste Linie eingefügt
                if multi_area and idx == 0:
                    line.devices.append(Device(
                        device_type="coupler",
                        product="Bereichskoppler",
                        physical_address=area.coupler_address,
                        installation_location=line.uv_location,
                    ))

                # Linienkoppler (Kap. 3.5.2, Adresse B.L.0)
                line.devices.append(Device(
                    device_type="coupler",
                    product="Linienkoppler",
                    physical_address=line.coupler_address,
                    installation_location=line.uv_location,
                ))

                # Spannungsversorgung (Kap. 3.2, T-06)
                line.devices.append(Device(
                    device_type="power_supply",
                    product="KNX-Spannungsversorgung 640mA",
                    installation_location=line.uv_location,
                ))

                # ── Aktoren einfügen (Kap. 9.1: Adressen 1-100) ──────────────
                prog_actors = [
                    d for d in programmed_by_line.get(line.coupler_address, [])
                    if d.device_type in ("actor", "gateway")
                ]

                if preserve_manual and line.coupler_address in manual_actor_devices:
                    # Manuell aufgeteilte (nicht-programmierte) Aktoren: gesicherte
                    # Devices wiederverwenden (kein Überschreiben).
                    for saved_actor in manual_actor_devices[line.coupler_address]:
                        line.devices.append(saved_actor)
                    # Programmierte Aktoren dieser Linie zusätzlich re-inserieren
                    for dev in prog_actors:
                        line.devices.append(dev)
                elif prog_actors:
                    # Programmierte Aktoren: zuerst re-inserieren,
                    # dann Delta (Mehrbedarfs-Geräte) aus Neuberechnung hinzufügen.
                    for dev in prog_actors:
                        line.devices.append(dev)
                    prog_actor_counts = Counter(d.product for d in prog_actors)

                    actor_result = actor_by_line.get(line.coupler_address)
                    if actor_result:
                        sorted_actors = sorted(
                            actor_result.actors,
                            key=lambda a: (
                                0 if a.actor_type.split(" ")[0] == PRIORITY_ACTOR_TYPE else 1,
                                a.actor_type,
                            ),
                        )
                        for actor in sorted_actors:
                            if prog_actor_counts.get(actor.actor_type, 0) > 0:
                                # Durch programmiertes Gerät abgedeckt → überspringen
                                prog_actor_counts[actor.actor_type] -= 1
                            else:
                                # Mehrbedarf → neues Gerät einfügen
                                base_type = (
                                    actor.actor_type.rsplit(" ", 1)[0]
                                    if " " in actor.actor_type else actor.actor_type
                                )
                                dev_type = "gateway" if base_type in GATEWAY_ACTOR_TYPES else "actor"
                                line.devices.append(Device(
                                    device_type=dev_type,
                                    product=actor.actor_type,
                                    manufacturer=actor.product.manufacturer,
                                    order_number=actor.product.order_number,
                                    application_program=actor.product.application_program,
                                    installation_location=actor.uv_location or line.uv_location,
                                    datasheets=list(actor.product.datasheets),
                                ))
                else:
                    # Keine programmierten / manuell aufgeteilten Aktoren →
                    # vollständige Neuberechnung. Geräte nach Aktortyp gruppiert,
                    # damit gleiche Typen fortlaufende Adressen erhalten.
                    actor_result = actor_by_line.get(line.coupler_address)
                    if actor_result:
                        sorted_actors = sorted(
                            actor_result.actors,
                            key=lambda a: (
                                0 if a.actor_type.split(" ")[0] == PRIORITY_ACTOR_TYPE else 1,
                                a.actor_type,
                            ),
                        )
                        for actor in sorted_actors:
                            # FA-1307: Gateway-Gewerke erhalten device_type="gateway"
                            base_type = (
                                actor.actor_type.rsplit(" ", 1)[0]
                                if " " in actor.actor_type else actor.actor_type
                            )
                            dev_type = "gateway" if base_type in GATEWAY_ACTOR_TYPES else "actor"
                            line.devices.append(Device(
                                device_type=dev_type,
                                product=actor.actor_type,
                                manufacturer=actor.product.manufacturer,
                                order_number=actor.product.order_number,
                                application_program=actor.product.application_program,
                                installation_location=actor.uv_location or line.uv_location,
                                datasheets=list(actor.product.datasheets),
                            ))

                # ── Sensoren einfügen (Kap. 9.1: Adressen 101-199) ───────────
                prog_sensors = [
                    d for d in programmed_by_line.get(line.coupler_address, [])
                    if d.device_type == "sensor"
                ]

                # Raumreihenfolge auf der Linie für den Sort-Key (FA-TE-ORDER).
                # Ohne Raumposition als Kriterium würden alle TE1 aller Räume
                # vor allen TE2 sortiert werden – die zusätzliche TE2 eines
                # Raumes käme dann hinter der TE1 eines anderen Raumes.
                room_order = {rid: i for i, rid in enumerate(line.assigned_room_ids)}

                sensor_result = sensor_by_line.get(line.coupler_address)

                def _sensor_sort_key(stype: str, room_id: str | None, tidx: int):
                    return (
                        0 if stype.startswith(PRIORITY_SENSOR_TYPE) else 1,
                        room_order.get(room_id or "", 999),
                        tidx,
                        stype,
                    )

                # Abdeckung durch Auto-Sensoren vorberechnen.
                # Manuell hinzugefügte BEs (is_auto=False), die nicht abgedeckt
                # sind, werden in die sortierte Liste eingemischt – damit erhalten
                # sie Adressen im richtigen Typblock (z.B. TE → 101-1xx, nicht
                # hinter den Präsenzmeldern).
                covered_te_keys: set[tuple] = set()
                if sensor_result:
                    for _s in sensor_result.sensors:
                        covered_te_keys.add(
                            (_s.room_id, _s.sensor_type, _s.taster_index)
                        )

                uncovered_manual: list[tuple] = []   # (mroom, be)
                for rid in line.assigned_room_ids:
                    mroom = room_by_id.get(rid)
                    if not mroom:
                        continue
                    for be in mroom.bedienelemente:
                        if be.is_auto or not be.element_type:
                            continue
                        te_key = (mroom.id, be.element_type, be.taster_index)
                        if te_key in covered_te_keys:
                            covered_te_keys.discard(te_key)
                            continue
                        uncovered_manual.append((mroom, be))

                if prog_sensors:
                    # Programmierte Sensoren werden in die sortierte Reihenfolge
                    # eingewoben (nicht vorangestellt), damit die Raumgruppierung
                    # erhalten bleibt.  Matching nach (product, room_id).
                    from collections import deque as _deque
                    prog_by_key: dict = {}
                    for dev in prog_sensors:
                        key = (dev.product, dev.room_id)
                        prog_by_key.setdefault(key, _deque()).append(dev)

                    # Auto-Sensoren + manuelle BEs kombiniert sortieren.
                    combined: list[tuple] = []
                    if sensor_result:
                        for s in sensor_result.sensors:
                            combined.append((
                                _sensor_sort_key(s.sensor_type, s.room_id, s.taster_index),
                                "auto", s,
                            ))
                    for mroom, be in uncovered_manual:
                        combined.append((
                            _sensor_sort_key(be.element_type, mroom.id, be.taster_index),
                            "manual", mroom, be,
                        ))
                    combined.sort(key=lambda x: x[0])

                    for entry in combined:
                        if entry[1] == "auto":
                            sensor = entry[2]
                            key = (sensor.sensor_type, sensor.room_id)
                            if prog_by_key.get(key):
                                line.devices.append(prog_by_key[key].popleft())
                            else:
                                sensor_room = room_by_id.get(sensor.room_id)
                                room_label = (
                                    f"{sensor_room.number} {sensor_room.name}".strip()
                                    if sensor_room else ""
                                )
                                line.devices.append(Device(
                                    device_type="sensor",
                                    product=sensor.sensor_type,
                                    manufacturer=sensor.product.manufacturer,
                                    order_number=sensor.product.order_number,
                                    application_program=sensor.product.application_program,
                                    installation_location=room_label,
                                    datasheets=list(sensor.product.datasheets),
                                    room_id=sensor.room_id,
                                ))
                        else:  # "manual"
                            mroom, be = entry[2], entry[3]
                            room_label = f"{mroom.number} {mroom.name}".strip()
                            line.devices.append(Device(
                                device_type="sensor",
                                product=be.element_type,
                                room_id=mroom.id,
                                installation_location=room_label,
                            ))

                    # Programmierte Devices ohne passenden sensor_result-Eintrag
                    # (Gewerk wurde entfernt) ans Ende hängen.
                    for devs in prog_by_key.values():
                        for dev in devs:
                            line.devices.append(dev)
                else:
                    # Keine programmierten Sensoren → vollständige Neuberechnung.
                    # Auto-Sensoren + manuelle BEs kombiniert sortieren.
                    combined = []
                    if sensor_result:
                        for s in sensor_result.sensors:
                            combined.append((
                                _sensor_sort_key(s.sensor_type, s.room_id, s.taster_index),
                                "auto", s,
                            ))
                    for mroom, be in uncovered_manual:
                        combined.append((
                            _sensor_sort_key(be.element_type, mroom.id, be.taster_index),
                            "manual", mroom, be,
                        ))
                    combined.sort(key=lambda x: x[0])

                    for entry in combined:
                        if entry[1] == "auto":
                            s = entry[2]
                            sensor_room = room_by_id.get(s.room_id)
                            room_label = (
                                f"{sensor_room.number} {sensor_room.name}".strip()
                                if sensor_room else ""
                            )
                            line.devices.append(Device(
                                device_type="sensor",
                                product=s.sensor_type,
                                manufacturer=s.product.manufacturer,
                                order_number=s.product.order_number,
                                application_program=s.product.application_program,
                                installation_location=room_label,
                                datasheets=list(s.product.datasheets),
                                room_id=s.room_id,
                            ))
                        else:  # "manual"
                            mroom, be = entry[2], entry[3]
                            room_label = f"{mroom.number} {mroom.name}".strip()
                            line.devices.append(Device(
                                device_type="sensor",
                                product=be.element_type,
                                room_id=mroom.id,
                                installation_location=room_label,
                            ))

                # Manuell hinzugefügte Geräte (Schnittstellen, Konnektbausteine …)
                # nach Sensoren einfügen, damit sie Adressen im Bereich 250-255 erhalten.
                if preserve_manual:
                    for saved in manual_added_by_line.get(line.coupler_address, []):
                        line.devices.append(saved)

                line.update_device_count()

        self.assign_physical_addresses(topology, small_project)
        self.assign_participant_numbers(topology, all_rooms)

        # Manuelle Produktzuweisungen wiederherstellen (nach Adressvergabe).
        # Programmierte Geräte brauchen keinen Restore – ihre Daten sind im
        # gesicherten Device-Objekt bereits enthalten.
        if preserve_manual and manual_assignments:
            for area in topology.areas:
                for line in area.lines:
                    for device in line.devices:
                        if device.is_programmed:
                            continue
                        saved = manual_assignments.get(device.physical_address)
                        if saved:
                            device.manufacturer = saved["manufacturer"]
                            device.order_number = saved["order_number"]
                            device.product_name = saved["product_name"]

    def assign_physical_addresses(self, topology: Topology,
                                  small_project: bool = False):
        """
        Weist physikalische Adressen zu (FA-221, FA-222, Kap. 9.1).

        Koppler: B.L.0 bzw. B.0.0 (bereits bei Erstellung gesetzt)
        Spannungsversorgungen: keine Busadresse
        Aktoren: 1-100 (grosse Projekte) / 1-20 (kleine Projekte)
        Sensoren: 101-199 (grosse Projekte) / 21-40 (kleine Projekte)
        Reserve: 200-249 / 41-62
        Schnittstellen: 250-255
        """
        # Adressbereiche gemaess Kap. 9.1
        max_actor_addr = 20 if small_project else 100
        max_sensor_addr = 40 if small_project else 199

        for area in topology.areas:
            # Speisegerät Bereichslinie: Adresse B.0.-
            if area.backbone_power_supply is not None:
                area.backbone_power_supply.physical_address = (
                    f"{area.area_number}.0.-"
                )

            for line in area.lines:
                actor_addr = 1
                sensor_addr = 21 if small_project else 101
                other_addr = 250   # Schnittstellen / manuell hinzugefügte Geräte
                prev_actor_base_type: str | None = None
                prev_sensor_type: str | None = None

                # Reservierte Teilnehmernummern vorsammeln:
                # - Programmierte Geräte (is_programmed): Adresse ist fixiert,
                #   Auto-Zähler überspringt diese Nummern.
                # - Manuell hinzugefügte (manually_added) mit expliziter Adresse:
                #   wie bisher.
                fixed_participant_nums: set[int] = set()
                for dev in line.devices:
                    if not dev.physical_address:
                        continue
                    parts = dev.physical_address.split(".")
                    if len(parts) == 3:
                        try:
                            num = int(parts[2])
                            if dev.is_programmed or dev.manually_added:
                                fixed_participant_nums.add(num)
                        except ValueError:
                            pass

                for device in line.devices:
                    if device.device_type == "coupler":
                        # Koppler behalten vorab gesetzte Adresse (B.L.0)
                        continue
                    elif device.device_type == "power_supply":
                        # Spannungsversorgungen sind keine Busteilnehmer →
                        # Adresse B.L.- als Kennzeichnung der zugehörigen Linie
                        device.physical_address = (
                            f"{area.area_number}.{line.line_number}.-"
                        )
                        continue
                    elif device.is_programmed:
                        # Programmierte Geräte: Adress-Präfix bei Bereich-/Linien-
                        # umbenennung aktualisieren, Suffix (Teilnehmernummer) NICHT
                        # ändern – die Nummer ist fest ins Gerät programmiert.
                        if device.physical_address:
                            parts = device.physical_address.split(".")
                            suffix = parts[2] if len(parts) == 3 else ""
                            if suffix:
                                device.physical_address = (
                                    f"{area.area_number}.{line.line_number}.{suffix}"
                                )
                        continue
                    elif device.device_type in ("actor", "gateway"):
                        # Manuell fixierte Adresse: Präfix aktualisieren, Suffix beibehalten
                        if device.manually_added and device.physical_address:
                            parts = device.physical_address.split(".")
                            suffix = parts[2] if len(parts) == 3 else str(actor_addr)
                            device.physical_address = (
                                f"{area.area_number}.{line.line_number}.{suffix}"
                            )
                            continue

                        # Basistyp ohne Kanalangabe (z.B. "Schaltaktor" aus "Schaltaktor 8-fach")
                        base_type = (
                            device.product.split(" ")[0] if device.product else ""
                        )
                        # 3 Reserve-Adressen zwischen verschiedenen Aktortyp-Blöcken
                        if prev_actor_base_type is not None and base_type != prev_actor_base_type:
                            actor_addr += ACTOR_BLOCK_RESERVE
                        prev_actor_base_type = base_type

                        # Reservierte/programmierte Nummern überspringen
                        while actor_addr in fixed_participant_nums:
                            actor_addr += 1

                        if actor_addr > max_actor_addr:
                            logger.error(
                                f"Linie {line.coupler_address}: Aktoradresse "
                                f"{actor_addr} ueberschreitet Maximum {max_actor_addr}"
                            )
                        device.physical_address = (
                            f"{area.area_number}.{line.line_number}.{actor_addr}"
                        )
                        actor_addr += 1
                    elif device.device_type == "sensor":
                        # Manuell fixierte Adresse: Präfix aktualisieren, Suffix beibehalten
                        if device.manually_added and device.physical_address:
                            parts = device.physical_address.split(".")
                            suffix = parts[2] if len(parts) == 3 else str(sensor_addr)
                            device.physical_address = (
                                f"{area.area_number}.{line.line_number}.{suffix}"
                            )
                            continue

                        # 3 Reserve-Adressen zwischen verschiedenen Sensortyp-Blöcken
                        sensor_type = device.product
                        if prev_sensor_type is not None and sensor_type != prev_sensor_type:
                            sensor_addr += SENSOR_BLOCK_RESERVE
                        prev_sensor_type = sensor_type

                        # Reservierte/programmierte Nummern überspringen
                        while sensor_addr in fixed_participant_nums:
                            sensor_addr += 1

                        if sensor_addr > max_sensor_addr:
                            logger.error(
                                f"Linie {line.coupler_address}: Sensoradresse "
                                f"{sensor_addr} ueberschreitet Maximum {max_sensor_addr}"
                            )
                        device.physical_address = (
                            f"{area.area_number}.{line.line_number}.{sensor_addr}"
                        )
                        sensor_addr += 1
                    elif device.device_type == "other":
                        # Schnittstellen/manuell hinzugefügte Geräte: 250-255 (Kap. 9.1)
                        if device.manually_added and device.physical_address:
                            # Adress-Präfix bei Bereich-/Linienumbenennung aktualisieren,
                            # Suffix (250, 251, …) beibehalten.
                            parts = device.physical_address.split(".")
                            suffix = parts[2] if len(parts) == 3 else str(other_addr)
                            device.physical_address = (
                                f"{area.area_number}.{line.line_number}.{suffix}"
                            )
                        else:
                            device.physical_address = (
                                f"{area.area_number}.{line.line_number}.{other_addr}"
                            )
                            other_addr += 1

    def assign_participant_numbers(self, topology: Topology,
                                   all_rooms: list[Room]):
        """
        Weist jedem Bedienelement seine Linienteilnehmernummer zu (FA-225).

        Matched sensor-Device-Objekte (die nach assign_physical_addresses()
        eine physikalische Adresse haben) zu den Bedienelement-Objekten in
        den Räumen über room_id und element_type.

        Bei mehreren gleichen Bedienelementen im selben Raum werden die
        physikalischen Adressen in der Reihenfolge der Topology-Devices
        zugewiesen.
        """
        # Lookup: room_id -> Room
        room_by_id: dict[str, Room] = {r.id: r for r in all_rooms}

        # Zähler: (room_id, element_type) -> Anzahl bereits zugewiesener BEs
        assigned_count: dict[tuple, int] = defaultdict(int)

        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.device_type != "sensor":
                        continue
                    if not device.room_id or not device.physical_address:
                        continue

                    room = room_by_id.get(device.room_id)
                    if room is None:
                        logger.warning(
                            f"Raum mit ID {device.room_id!r} nicht gefunden "
                            f"(Gerät: {device.product})"
                        )
                        continue

                    # Alle Bedienelemente dieses Typs im Raum (in Listenreihenfolge)
                    matching_bes = [
                        be for be in room.bedienelemente
                        if be.element_type == device.product
                    ]

                    key = (device.room_id, device.product)
                    idx = assigned_count[key]

                    if idx < len(matching_bes):
                        matching_bes[idx].participant_number = device.physical_address
                        logger.debug(
                            f"Bedienelement '{device.product}' in Raum "
                            f"'{room.name}' → {device.physical_address}"
                        )
                        assigned_count[key] += 1
                    else:
                        logger.warning(
                            f"Kein weiteres Bedienelement '{device.product}' "
                            f"in Raum '{room.name}' für Adresse "
                            f"{device.physical_address} gefunden"
                        )

    def check_topology_conflicts(
        self, current_topology: Topology, areal
    ) -> list[dict]:
        """
        Prüft, ob eine Topologie-Neuberechnung programmierte Geräte bewegen würde.

        Berechnet die neue Topologie-Struktur (ohne zu committen) und vergleicht
        sie mit der aktuellen Struktur.  Liefert eine Liste von Konflikten, die
        dem Benutzer angezeigt werden können, bevor er die Neuberechnung bestätigt.

        Jeder Konflikt enthält:
          "device"          – das betroffene Device-Objekt
          "from_line"       – bisherige coupler_address
          "suggested_line"  – neue coupler_address (oder None, wenn Linie entfällt)
          "reason"          – lesbarer Grund

        Returns:
            Leere Liste → kein Konflikt, Neuberechnung ist sicher.
        """
        new_topology = self.calculate_topology(areal)

        # Raum → neue Linien-Adresse
        new_room_to_line: dict[str, str] = {}
        for area in new_topology.areas:
            for line in area.lines:
                for room_id in line.assigned_room_ids:
                    new_room_to_line[room_id] = line.coupler_address

        # Alle coupler_addresses der neuen Topologie
        new_line_addrs: set[str] = {
            line.coupler_address
            for area in new_topology.areas
            for line in area.lines
        }

        conflicts: list[dict] = []
        for area in current_topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if not device.is_programmed:
                        continue
                    if device.device_type in ("coupler", "power_supply"):
                        continue

                    if device.room_id:
                        # Sensor: prüfen ob Raum auf andere Linie kommt
                        new_line = new_room_to_line.get(device.room_id)
                        if new_line and new_line != line.coupler_address:
                            conflicts.append({
                                "device": device,
                                "from_line": line.coupler_address,
                                "suggested_line": new_line,
                                "reason": "Raumzuordnung ändert sich",
                            })
                        elif not new_line:
                            # Raum existiert in neuer Topologie nicht mehr
                            conflicts.append({
                                "device": device,
                                "from_line": line.coupler_address,
                                "suggested_line": None,
                                "reason": "Raum entfällt in neuer Topologie",
                            })
                    else:
                        # Aktor ohne room_id: prüfen ob Linie noch existiert
                        if line.coupler_address not in new_line_addrs:
                            conflicts.append({
                                "device": device,
                                "from_line": line.coupler_address,
                                "suggested_line": None,
                                "reason": "Linie entfällt in neuer Topologie",
                            })

        return conflicts

    def validate_topology(self, topology: Topology) -> list[dict]:
        """Validiert die Topologie gegen die Regeln (T-01 bis T-11)."""
        issues = []

        if len(topology.areas) > MAX_AREAS:
            issues.append({
                "rule": "T-05",
                "level": "error",
                "message": f"Zu viele Bereiche: {len(topology.areas)} (max. {MAX_AREAS})",
            })

        for area in topology.areas:
            if len(area.lines) > MAX_LINES_PER_AREA:
                issues.append({
                    "rule": "T-04",
                    "level": "error",
                    "message": f"Bereich {area.area_number}: Zu viele Linien: "
                               f"{len(area.lines)} (max. {MAX_LINES_PER_AREA})",
                })

            for line in area.lines:
                if line.device_count > MAX_REALIZED:
                    issues.append({
                        "rule": "T-03",
                        "level": "error",
                        "message": f"Linie {line.coupler_address}: "
                                   f"{line.device_count} Geräte (max. {MAX_REALIZED})",
                    })
                elif line.device_count > RECOMMENDED_DEVICES:
                    issues.append({
                        "rule": "T-03",
                        "level": "warning",
                        "message": f"Linie {line.coupler_address}: "
                                   f"{line.device_count} Geräte "
                                   f"(empfohlen: max. {RECOMMENDED_DEVICES})",
                    })

        return issues

    def validate_cross_line_functions(
        self, topology: "Topology", all_rooms: list
    ) -> list[dict]:
        """
        Prüft ob manuell konfigurierte Bedienelemente Funktionen aus anderen
        Linien referenzieren (FA-1410).

        Wenn ein Sensor in Linie A eine GA aus Linie B sendet, muss der
        Linienkoppler B diese GA im Filter freigeben – sonst kommt das
        Telegramm nicht an.

        Gibt eine Liste von Warnungen zurück:
          "sensor_addr"   – physikalische Adresse des Sensors
          "room_name"     – Raum des Sensors
          "fn_label"      – Bezeichnung der Funktion
          "target_line"   – Ziellinie der GA
        """
        # room_id → coupler_address der Linie
        room_to_line: dict[str, str] = {}
        for area in topology.areas:
            for line in area.lines:
                for room_id in line.assigned_room_ids:
                    room_to_line[room_id] = line.coupler_address

        room_by_id = {r.id: r for r in all_rooms}

        warnings: list[dict] = []
        for area in topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.device_type != "sensor" or not device.room_id:
                        continue
                    room = room_by_id.get(device.room_id)
                    if room is None:
                        continue
                    for be in room.bedienelemente:
                        if be.is_auto:
                            continue
                        for sf in be.funktionen:
                            if not sf.source_room_id:
                                continue
                            target_line = room_to_line.get(sf.source_room_id)
                            if target_line and target_line != line.coupler_address:
                                warnings.append({
                                    "sensor_addr": device.physical_address,
                                    "room_name": f"{room.number} {room.name}",
                                    "fn_label": sf.label or sf.gewerk_code,
                                    "target_line": target_line,
                                })
        return warnings
