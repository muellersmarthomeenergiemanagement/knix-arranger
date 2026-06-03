"""
RecalcService – Kaskaden-Neuberechnung nach manuellen Änderungen (Phase C).

Steuert, welche Berechnungen nach welcher Art von Änderung ausgeführt werden.
Ist bewusst rein funktional (kein Qt) – die Bus-Integration liegt im MainWindow.

Abhängigkeitsgraph:
    Gebäude/Gewerk geändert → Aktoren/Sensoren neu → GAs neu
    Topologie manuell geändert → keine Auto-Neuberechnung (Integrator hat
                                  bewusst die Topologie verändert)

Wichtig: recalc_actors_and_addresses() berührt die Topologie-STRUKTUR
(Bereiche, Linien) NICHT – nur die Geräte innerhalb der Linien werden
neu berechnet. Manuelle Linienzuordnungen und Verschiebungen bleiben erhalten.
"""
from __future__ import annotations
import logging
from ..models.project import KnxProject
from ..models.group_address import GroupAddress, GroupAddressStructure, MainGroup, MiddleGroup
from .topology_engine import TopologyEngine
from .address_generator import AddressGenerator
from .sensor_service import SensorService

logger = logging.getLogger("knix_arranger.recalc_service")


def _insert_ga(structure: GroupAddressStructure, ga: GroupAddress) -> None:
    """Fügt eine GA in die passende HG/MG der Struktur ein (legt sie an falls nötig)."""
    hg = next((h for h in structure.main_groups if h.number == ga.main_group), None)
    if not hg:
        hg = MainGroup(number=ga.main_group, name=f"HG {ga.main_group}")
        structure.main_groups.append(hg)
        structure.main_groups.sort(key=lambda h: h.number)

    mg = next((m for m in hg.middle_groups if m.number == ga.middle_group), None)
    if not mg:
        mg = MiddleGroup(number=ga.middle_group, name=f"MG {ga.middle_group}")
        hg.middle_groups.append(mg)
        hg.middle_groups.sort(key=lambda m: m.number)

    mg.group_addresses.append(ga)


class RecalcService:
    """Steuert Kaskaden-Neuberechnungen nach manuellen Projektänderungen."""

    def recalc_actors_and_addresses(self, project: KnxProject) -> dict:
        """Aktoren/Sensoren und GAs nach Gewerk- oder Gebäudestruktur-Änderung
        neu berechnen.

        Die Topologie-Struktur (Bereiche, Linien, Zuordnungen) bleibt vollständig
        erhalten. Nur die Gerätebelegung innerhalb der Linien wird aktualisiert.
        Manuelle Produktzuweisungen (preserve_manual=True) bleiben ebenfalls erhalten.

        Returns:
            dict mit "actor_count", "ga_count", "ok" (bool)
        """
        topology = project.topology
        if not topology.areas:
            logger.warning("RecalcService: Keine Topologie vorhanden – Neuberechnung übersprungen.")
            return {"ok": False, "actor_count": 0, "ga_count": 0}

        catalog   = project.gewerk_catalog
        all_rooms = project.all_rooms

        # ── Schritt 1: Aktoren/Sensoren in bestehender Topologie neu berechnen ──
        # Importierte Topologien (XLSX/knxproj) bleiben unverändert (FA-ImportGuard).
        # preserve_manual=True: manuell zugewiesene Produkte bleiben erhalten
        if not topology.is_imported:
            engine = TopologyEngine(project.config.topology_mode)
            engine.populate_devices(
                topology, all_rooms, catalog,
                small_project=(topology.topology_mode == "TP-64"),
                preserve_manual=True,
            )

        actor_count = sum(
            len(line.devices)
            for area in topology.areas
            for line in area.lines
        )
        logger.info(f"RecalcService: Aktoren/Sensoren neu berechnet → {actor_count} Geräte total.")

        # ── Schritt 2: GAs neu generieren (manuelle GAs sichern und wiederherstellen) ──
        manual_gas: list[GroupAddress] = [
            ga for ga in project.group_addresses.all_addresses()
            if ga.is_manual
        ]

        gen = AddressGenerator(catalog, variant=project.config.mg_variant)
        project.group_addresses = gen.generate(project.areal)

        for ga in manual_gas:
            _insert_ga(project.group_addresses, ga)

        ga_count = len(project.group_addresses.all_addresses())
        logger.info(
            f"RecalcService: GAs neu generiert → {ga_count} GAs"
            + (f" ({len(manual_gas)} manuelle beibehalten)" if manual_gas else "")
        )

        # ── Schritt 3: function_assignments aktualisieren ──────────────────────
        # Nach GA-Neugenerierung müssen die GA-Verknüpfungen an den Bedienelementen
        # neu berechnet werden, damit Gebäudeansicht, Verknüpfungsmatrix und
        # Berichte sofort konsistente Daten zeigen (ohne dass Schritt 8 besucht
        # werden muss).
        SensorService().auto_assign_functions(all_rooms, project.group_addresses)
        logger.info("RecalcService: function_assignments aktualisiert.")

        return {"ok": True, "actor_count": actor_count, "ga_count": ga_count}

    def recalc_full_topology(self, project: KnxProject) -> dict:
        """Topologie komplett neu berechnen und anschliessend Aktoren + GAs.

        NUR bei grösseren Gebäudestrukturänderungen verwenden (z.B. neue Stockwerke,
        Wohnungen hinzugefügt). Überschreibt manuelle Topologie-Anpassungen!

        Wenn programmierte Geräte durch die Neuberechnung ihre Linie wechseln würden,
        wird kein Commit durchgeführt. Stattdessen werden Konflikt-Informationen
        zurückgegeben, damit der Aufrufer einen Dialog anzeigen kann.

        Returns:
            dict mit "ok", "area_count", "line_count", "actor_count", "ga_count"
            Wenn Konflikte vorhanden: "ok"=False, "conflicts"=[...], Rest 0.
        """
        engine = TopologyEngine(project.config.topology_mode)

        # Konflikt-Check: würde die Neuberechnung programmierte Geräte verschieben?
        has_programmed = any(
            d.is_programmed
            for area in project.topology.areas
            for line in area.lines
            for d in line.devices
            if d.device_type not in ("coupler", "power_supply")
        )
        if has_programmed:
            conflicts = engine.check_topology_conflicts(
                project.topology, project.areal
            )
            if conflicts:
                logger.warning(
                    f"RecalcService: {len(conflicts)} Konflikt(e) mit programmierten "
                    f"Geräten – Topologie-Neuberechnung abgebrochen."
                )
                return {
                    "ok": False,
                    "conflicts": conflicts,
                    "area_count": 0,
                    "line_count": 0,
                    "actor_count": 0,
                    "ga_count": 0,
                }

        project.topology = engine.calculate_topology(project.areal)

        area_count = len(project.topology.areas)
        line_count  = sum(len(a.lines) for a in project.topology.areas)
        logger.info(
            f"RecalcService: Topologie neu berechnet → "
            f"{area_count} Bereiche, {line_count} Linien."
        )

        result = self.recalc_actors_and_addresses(project)
        result["area_count"] = area_count
        result["line_count"]  = line_count
        return result
