"""
Validierungs-Engine (FA-600)
Prüft Gruppenadressen, Bezeichnungen, Mittelgruppen-Zuordnung etc.
"""
from __future__ import annotations
import re
import logging
from ..models.group_address import GroupAddressStructure, GroupAddress
from ..models.gewerk import GewerkCatalog
from ..utils.validators import (
    is_valid_ga, is_valid_designation, designation_room_number,
)
from .dpt_suggestion import suggest_dpt
from . import ga_functions


def _dpt_main(dpt: str) -> str:
    """Haupttyp eines DPT: "DPST-5-1" und "DPT-5" -> "5"."""
    parts = (dpt or "").upper().replace("DPST-", "DPT-").split("-")
    return parts[1] if len(parts) > 1 else ""

logger = logging.getLogger("knix_arranger.validation")


class ValidationIssue:
    """Ein Validierungsproblem."""

    def __init__(self, level: str, rule_id: str, message: str,
                 address: str = "", suggestion: str = "",
                 designation: str = "", details: dict | None = None):
        self.level = level        # "error", "warning", "info"
        self.rule_id = rule_id
        self.message = message
        self.address = address
        self.suggestion = suggestion
        # Für den Bericht: GA-Bezeichnung und regelspezifische Werte
        # (z.B. {"expected": …, "actual": …}), damit Tabellen eigene
        # Spalten statt eines zusammengesetzten Meldungstexts zeigen.
        self.designation = designation
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "rule_id": self.rule_id,
            "message": self.message,
            "address": self.address,
            "suggestion": self.suggestion,
            "designation": self.designation,
            "details": dict(self.details),
        }


def _melder_has_ga(project, room, be, device=None) -> bool:
    """Melder mit mindestens einer GA: Funktionen des Bedienelements (Licht
    schalten, eigenes Gewerk-Element), Zusatzfunktionen «be:…» oder -- mit
    Gerät -- eine GA an einem KO (manuell, ETS, Materialliste). Ohne Gerät
    nur die günstigen Merkmale."""
    if be.funktionen or be.function_assignments:
        return True
    own = f"be:{be.id}"
    if any(ga.assignment_id == own and not ga.is_placeholder
           for ga in project.group_addresses.all_addresses()):
        return True
    if device is None:
        return False
    if any(co.connected_gas for co in device.communication_objects):
        return True
    from .sensor_channels import sensor_co_map
    return any(number >= 0 for number in sensor_co_map(device).values())


class ValidationEngine:
    """Prüft GA-Strukturen auf Konformitaet."""

    def __init__(self, catalog: GewerkCatalog | None = None):
        self.catalog = catalog

    def validate(self, structure: GroupAddressStructure,
                 project=None) -> list[ValidationIssue]:
        """Fuehrt alle Validierungen durch.

        Args:
            structure: Die zu pruefende GA-Struktur.
            project:   Optional – wird fuer projektweite Regeln (FA-3308b) benoetigt.
        """
        issues: list[ValidationIssue] = []
        all_gas = structure.all_addresses()

        issues.extend(self._check_valid_addresses(all_gas))
        issues.extend(self._check_duplicates(all_gas))
        issues.extend(self._check_dpt(all_gas))
        issues.extend(self._check_naming(all_gas, self._planned_room_numbers(project)))
        issues.extend(self._check_middle_group_assignment(all_gas))
        issues.extend(self._check_block_integrity(structure))
        issues.extend(self._check_generation_warnings(structure))

        if structure.variant == "B":
            issues.extend(self._check_feedback_variant_b(structure))

        # FA-3308b: Astro-GAs prüfen wenn Zeitprogramme mit ASTRO-Schaltpunkten vorhanden
        if project is not None:
            issues.extend(self._check_shared_main_groups(project))
            issues.extend(self._check_astro_gas(structure, project))
            issues.extend(self._check_multi_ga_keys(project))
            issues.extend(self._check_ets_deviations(project))
            issues.extend(self._check_time_programs(project))
            issues.extend(self._check_unoperated(project))
            issues.extend(self._check_product_mismatch(project))
            issues.extend(self._check_products_without_kos(project))
            issues.extend(self._check_scene_numbers(project))
            issues.extend(self._check_references(project))
            issues.extend(self._check_structure(project))
            issues.extend(self._check_product_kinds(project))
            issues.extend(self._check_ko_flags(project))
            issues.extend(self._check_product_capabilities(project))
            issues.extend(self._check_bedienelement_leftovers(project))
            # FA-609, FA-611 bis FA-613: Topologie
            from .topology_validation import check_topology
            issues.extend(check_topology(project))
            self._grade_guidelines(issues, project)

        return issues

    @staticmethod
    def _check_generation_warnings(structure: GroupAddressStructure) -> list[ValidationIssue]:
        """FA-620: Warnungen der letzten GA-Generierung (nicht gespeichert,
        bis zum Neustart sichtbar). Eine volle Mittelgruppe ist ein Fehler,
        dort fehlen GAs."""
        issues = []
        for warning in structure.warnings:
            overflow = "Keine freie Mittelgruppe" in warning
            issues.append(ValidationIssue(
                "error" if overflow else "warning", "FA-620", warning, "",
                "Anzahl des Gewerks prüfen; Gewerke auf andere Stockwerke "
                "verteilen" if overflow else "Hinweis der Generierung prüfen"))
        return issues

    #: Regeln der Projektrichtlinien (Mittelgruppen, Rückmelde-MG, Bezeichnung)
    GUIDELINE_RULES = ("FA-607", "FA-608", "FA-610")

    def _grade_guidelines(self, issues: list[ValidationIssue], project) -> None:
        """Abweichungen von den Projektrichtlinien je nach Projektart: bei aus
        der ETS importierten Projekten nur dokumentieren (Hinweis), bei mit
        KNiX geplanten Projekten müssen sie behoben werden (Fehler)."""
        level = "info" if project.topology.is_imported else "error"
        for issue in issues:
            if issue.rule_id in self.GUIDELINE_RULES:
                issue.level = level

    def _check_shared_main_groups(self, project) -> list[ValidationIssue]:
        """FA-411: jedes Stockwerk hat eine eigene Hauptgruppe.

        Teilen sich Stockwerke (meist verschiedener Gebäude) eine HG, landen
        ihre Adressen in derselben HG und deren Name wird zusammengesetzt
        (z.B. "Obergeschoss / Erdgeschoss"). Nur bei geplanten Projekten.
        """
        if project.topology.is_imported:
            return []
        from .building_service import BuildingService
        issues = []
        for hg, floors in BuildingService.shared_main_groups(project.areal).items():
            names = ", ".join(f"{b.name} {f.short_code or f.name}" for b, f in floors)
            issues.append(ValidationIssue(
                "warning", "FA-411",
                f"HG {hg} ist mehreren Stockwerken zugeordnet: {names}",
                f"HG {hg}",
                "In Schritt 1 jedem Stockwerk eine eigene Hauptgruppe geben",
                details={"hg": hg, "floors": names},
            ))
        return issues

    #: Massnahme je Art eines gebrochenen Verweises (FA-623)
    _REFERENCE_HINTS = {
        "Bedienelement: Gerät fehlt": "Projekt neu berechnen (Gebäude oder Gewerke ändern) "
                                      "oder das Bedienelement entfernen",
        "Bedienelement: ohne Gerät": "Projekt neu berechnen; bleibt es, das Bedienelement "
                                     "entfernen und neu einsetzen",
        "Bedienelement: anderer Gerätetyp": "Projekt neu berechnen",
        "DALI: Gateway fehlt": "DALI-Konfiguration öffnen: Gateway neu wählen oder "
                               "die Konfiguration entfernen",
        "Secure: FDSK ohne Gerät": "FDSK im KNX-Secure-Archiv dem richtigen Gerät "
                                   "zuordnen oder bewusst im Archiv belassen",
    }

    def _check_references(self, project) -> list[ValidationIssue]:
        """FA-623: Verweise, die die Bereinigung beim Öffnen (FA-624) nicht
        auflösen kann -- z.B. eine DALI-Konfiguration ohne Gateway oder ein
        eine Taste auf eine gelöschte GA."""
        from .integrity_check import check_integrity
        return [ValidationIssue(
            "warning", "FA-623", f"{issue.kind}: {issue.detail}", "",
            self._REFERENCE_HINTS.get(issue.kind, "Verweis prüfen und neu zuordnen"),
            details={"kind": issue.kind})
            for issue in check_integrity(project)]

    def _check_ko_flags(self, project) -> list[ValidationIssue]:
        """FA-627: mehrere KOs mit L-Flag an einer GA; FA-628: Befehls-GA mit
        verknüpften KOs, aber keinem Empfänger (S-Flag). Nur GAs, deren KOs
        bekannt sind (ETS-Import oder Zuordnung in KNiX, services/ko_links)."""
        from .ko_links import READ, WRITE, links_by_ga
        by_ga = links_by_ga(project)
        if not by_ga:
            return []
        gas = {ga.address: ga for ga in project.group_addresses.all_addresses()}
        imported = project.topology.is_imported
        unresolved: set[str] | None = set() if imported else None   # erst bei Bedarf
        issues = []
        for address, links in sorted(by_ga.items()):
            known = [link for link in links if link.flags]
            if not known:
                continue
            ga = gas.get(address)
            designation = ga.designation if ga else ""
            readers = list({(l.device.physical_address, l.co.object_number): l
                            for l in known if READ in l.flags}.values())
            if len(readers) > 1:
                issues.append(ValidationIssue(
                    "info" if imported else "warning", "FA-627",
                    f"{len(readers)} KOs beantworten Leseanfragen (L-Flag): "
                    + ", ".join(l.label for l in readers),
                    address,
                    "L-Flag nur am KO lassen, das den Wert liefert",
                    designation=designation,
                    details={"devices": [l.device.physical_address for l in readers]}))
            if (ga is not None and ga_functions.role_of(ga.function_name) == ga_functions.COMMAND
                    and not any(WRITE in l.flags for l in known)):
                if unresolved is None:
                    unresolved = self._actors_without_kos(project)
                if address in unresolved:
                    continue
                issues.append(ValidationIssue(
                    "info", "FA-628",
                    f"Befehl {ga.function_name}: kein verknüpftes KO empfängt ihn (S-Flag), "
                    f"nur " + ", ".join(l.label for l in known),
                    address,
                    "Empfänger verknüpfen oder beim empfangenden KO das S-Flag setzen",
                    designation=designation))
        return issues

    @staticmethod
    def _check_bedienelement_leftovers(project) -> list[ValidationIssue]:
        """FA-631: Bedienelement mit Gerät, aber ohne Funktion; FA-632:
        dasselbe Element auf mehreren Tastern im selben Raum; FA-633: Melder
        ohne jede GA (nicht jeder Melder bekommt automatisch eine -- GAs
        entstehen auch manuell oder über die Materialliste). Nur geplante
        Projekte, Hinweise."""
        if project.topology.is_imported:
            return []
        catalog = project.gewerk_catalog
        issues = []
        devices = None      # Teilnehmernummer -> Gerät, erst bei Bedarf
        for room in project.all_rooms:
            holders: dict[tuple, list] = {}
            for be in room.bedienelemente:
                if be.suppressed:
                    continue
                # Melder (Gewerk A, FK …) tragen ihre GAs über das eigene
                # Element, nicht über Funktionen -- nur Bedienstellen prüfen
                if (be.element_type in ("Tastereinheit", "Raumthermostat")
                        and not be.funktionen and not be.function_assignments
                        and be.participant_number):
                    issues.append(ValidationIssue(
                        "info", "FA-631",
                        f"{be.participant_number} {be.element_type} ({room.number} {room.name}) "
                        f"hat keine Funktion",
                        be.participant_number,
                        "In der Bauherrenberatung Funktionen zuweisen oder das Gerät entfernen",
                        details={"room_id": room.id}))
                elif (be.element_type not in ("Tastereinheit", "Raumthermostat")
                      and be.participant_number and not _melder_has_ga(project, room, be)):
                    if devices is None:
                        devices = {d.physical_address: d for a in project.topology.areas
                                   for l in a.lines for d in l.devices}
                    device = devices.get(be.participant_number)
                    if device is None or not _melder_has_ga(project, room, be, device):
                        issues.append(ValidationIssue(
                            "info", "FA-633",
                            f"{be.participant_number} {be.element_type} ({room.number} "
                            f"{room.name}) hat keine GA",
                            be.participant_number,
                            "GA manuell anlegen oder über die Materialliste erzeugen; "
                            "sonst das Gerät entfernen",
                            details={"room_id": room.id}))
                if be.element_type != "Tastereinheit":
                    continue
                for sf in be.funktionen:
                    if not sf.gewerk_code or sf.press_of or sf.ga_designation:
                        continue
                    key = (sf.source_room_id or room.id, sf.gewerk_code, str(sf.element_number))
                    if be not in holders.setdefault(key, []):
                        holders[key].append(be)
            for (_src, code, nr), bes in holders.items():
                if len(bes) < 2:
                    continue
                gewerk = catalog.get(code) if catalog else None
                assignment = next((a for a in room.gewerk_assignments if a.gewerk_code == code), None)
                label = assignment.element_label(int(nr)) if assignment and str(nr).isdigit() else ""
                name = " ".join(p for p in ((gewerk.name if gewerk else code), nr,
                                             f"«{label}»" if label else "") if p)
                devices = ", ".join(be.participant_number or "Taster" for be in bes)
                issues.append(ValidationIssue(
                    "info", "FA-632",
                    f"{name} ({room.number} {room.name}) liegt auf {len(bes)} Tastern: {devices}",
                    bes[0].participant_number or "",
                    "Gewollt (zwei Bedienstellen)? Sonst die Taste in der Bauherrenberatung entfernen",
                    details={"room_id": room.id}))
        return issues

    @staticmethod
    def _check_product_capabilities(project) -> list[ValidationIssue]:
        """FA-629: mehr Tasten geplant als das Produkt hat; FA-630: Temperatur-
        fühler im Taster, den die Heizung des Raums nicht nutzt."""
        from .product_capabilities import plan_conflicts
        shortages, offers = plan_conflicts(project)
        issues = []
        for s in shortages:
            name = s.device.product_name or s.device.product
            issues.append(ValidationIssue(
                "warning", "FA-629",
                f"{s.device.physical_address} ({s.room.number} {s.room.name}): {s.planned} "
                f"Tasten geplant, {name} hat {s.available}",
                s.device.physical_address,
                "In der Bauherrenberatung Funktionen auf einen anderen Taster legen "
                "oder ein Produkt mit mehr Tasten wählen",
                details={"room_id": s.room.id}))
        for o in offers:
            thermostats = ", ".join(be.participant_number or "Raumthermostat"
                                    for be in o.thermostats)
            text = (f"{o.device.physical_address} ({o.room.number} {o.room.name}) misst die "
                    f"Raumtemperatur (KO {o.co.object_number}); die Heizung "
                    f"{o.assignment.element_label(o.element_number) or o.element_number} "
                    f"nutzt ihn nicht")
            if thermostats:
                text += f", zusätzlich geplant: Raumthermostat {thermostats}"
            issues.append(ValidationIssue(
                "info", "FA-630", text, o.device.physical_address,
                "In der Topologie am Taster «Raumtemperatur über dieses Gerät erfassen…»",
                details={"room_id": o.room.id}))
        return issues

    @staticmethod
    def _actors_without_kos(project) -> set[str]:
        """GAs geplanter Projekte, an denen ein Aktor laut Belegungsplan hängt,
        dessen KOs noch nicht zugeordnet sind -- dort ist «kein Empfänger»
        noch nicht entscheidbar."""
        from .belegungsplan_service import BelegungsplanService
        devices = {d.physical_address: d for area in project.topology.areas
                   for line in area.lines for d in line.devices}
        result = set()
        for row in BelegungsplanService().generate(project).actor_rows:
            device = devices.get(row.physical_address)
            if device is not None and not device.co_map and not any(
                    co.connected_gas for co in device.communication_objects):
                result.add(row.ga_address)
        return result

    def _check_product_kinds(self, project) -> list[ValidationIssue]:
        """FA-626: Produkt passt nicht zur Art des Melders, z.B. ein
        Bewegungsmelder-Produkt an «Rauchmelder» (Projekt_23 nach Typ-Batch)."""
        from .product_sync import product_kind_conflicts
        return [ValidationIssue(
            "warning", "FA-626",
            f"{c.where}: {c.product_name} passt nicht zu «{c.sensor_type}»", "",
            "In Schritt 5 (GA-Planung) bzw. in der Materialliste das passende "
            "Produkt wählen oder das Produkt entfernen",
            details={"sensor_type": c.sensor_type, "product": c.product_name})
            for c in product_kind_conflicts(project)]

    def _check_structure(self, project) -> list[ValidationIssue]:
        """FA-625: Zuteilungen, die einander widersprechen. Geplant: Warnung
        (KNiX leitet daraus Geräte und GAs ab); importiert: Hinweis, die ETS
        ist massgebend (Korrekturschicht, FA-616)."""
        planned = not project.topology.is_imported
        level = "warning" if planned else "info"
        issues: list[ValidationIssue] = []
        line_names: dict[str, list[str]] = {}
        for area in project.topology.areas:
            for line in area.lines:
                for rid in line.assigned_room_ids:
                    line_names.setdefault(rid, []).append(f"{area.area_number}.{line.line_number}")
        for room in project.all_rooms:
            label = f"{room.number} {room.name}".strip()
            if planned and len(line_names.get(room.id, [])) > 1:
                issues.append(ValidationIssue(
                    level, "FA-625",
                    f"Raum {label} ist mehreren Linien zugeteilt: "
                    + ", ".join(line_names[room.id]), room.number,
                    "In Schritt 4 einer Linie zuteilen"))
            if planned and room.gewerk_assignments and room.id not in line_names:
                issues.append(ValidationIssue(
                    level, "FA-625",
                    f"Raum {label} hat Gewerke, ist aber keiner Linie zugeteilt "
                    "(keine Aktoren und Sensoren)", room.number,
                    "In Schritt 4 einer Linie zuteilen"))
            codes: dict[str, int] = {}
            for a in room.gewerk_assignments:
                codes[a.gewerk_code] = codes.get(a.gewerk_code, 0) + 1
            for code, n in codes.items():
                if n > 1:
                    issues.append(ValidationIssue(
                        level, "FA-625",
                        f"Raum {label}: Gewerk {code} ist {n}-mal zugewiesen", room.number,
                        "In Schritt 5 zusammenfassen (Anzahl erhöhen)" if planned
                        else "Gewerk der GAs über «Gewerk zuordnen» korrigieren"))
        names: dict[str, list[str]] = {}
        for ga in project.group_addresses.all_addresses():
            if ga.designation and ga.designation != "--" and not ga.is_placeholder:
                names.setdefault(ga.designation, []).append(ga.address)
        for name, addresses in names.items():
            if len(addresses) > 1:
                issues.append(ValidationIssue(
                    level, "FA-625",
                    f"GA-Bezeichnung mehrfach: {', '.join(addresses)}", addresses[0],
                    "Bezeichnungen eindeutig machen" if planned
                    else "In der ETS eindeutig benennen", designation=name))
        return issues

    def _check_ets_deviations(self, project) -> list[ValidationIssue]:
        """FA-616: in KNiX korrigierte Angaben gegenüber der ETS (Korrekturschicht)."""
        from .ets_corrections import deviations
        return [
            ValidationIssue(
                "info", "FA-616",
                f"{d.field} {d.knix_value} statt {d.ets_value} (in KNiX korrigiert, "
                "ETS unverändert)",
                d.address,
                "In der ETS nachführen, sobald das Projekt dort bearbeitet wird",
                designation=d.designation,
                details={"field": d.field, "ets": d.ets_value, "knix": d.knix_value},
            )
            for d in deviations(project)
        ]

    def _check_multi_ga_keys(self, project) -> list[ValidationIssue]:
        """FA-614: pro Sensorkanal darf nur eine sendende GA verknüpft sein.
        Nachweislich zweite sendende GA (Befehls-KO eines anderen Geräts) ist
        ein Fehler, ohne gefundenen Sender eine Warnung (nicht eindeutig),
        Rückmeldungen ausserhalb MG 6/7 (Variante B) ein Hinweis, übrige
        Rückmeldungen in Ordnung."""
        from .multi_ga_check import find_multi_ga
        issues = []
        for f in find_multi_ga(project):
            if f.level == "ok":
                continue
            issues.append(ValidationIssue(
                f.level, "FA-614",
                f"{f.ko_text} sendet {f.sent_ga}, weitere GA {f.extra_ga}: {f.reason}",
                f.extra_ga,
                "GA in der ETS vom KO trennen und in der Bauherrenberatung "
                "oder Topologie ebenfalls trennen" if f.is_warning
                else "Rückmeldung in MG 6/7 verschieben oder so belassen",
                designation=f.extra_designation,
                details={"ko": f.ko_text, "sent": f.sent_ga, "reason": f.reason,
                         "verdict": f.verdict_label},
            ))
        return issues

    def _check_product_mismatch(self, project) -> list[ValidationIssue]:
        """FA-621: Sensor-Gerät mit anderem Produkt als die GA-Planung seiner
        Elemente (Schritt 5) -- GAs und eingebautes Gerät passen nicht."""
        from .product_sync import product_mismatches
        issues = []
        for m in product_mismatches(project):
            device = m.device
            product = " ".join(p for p in (device.manufacturer, device.order_number) if p)
            planned = m.assignment.product_for_element(m.element_nr)
            planned_text = (" ".join(p for p in (planned.get("manufacturer", ""),
                                                 planned.get("order_number", "")) if p)
                            if planned else "Standard des Gewerks")
            issues.append(ValidationIssue(
                "warning", "FA-621",
                f"{device.physical_address} {device.product} ist {product}, die GAs von "
                f"{m.element_text} ({m.room.number} {m.room.name}) folgen "
                f"{planned_text}",
                device.physical_address,
                "In Schritt 5 «Produkt…» das Produkt des Geräts übernehmen",
                details={"device": device.physical_address, "product": product,
                         "planned": planned_text},
            ))
        from .product_sync import sensor_products_on_actor_gewerke
        for m in sensor_products_on_actor_gewerke(project):
            device = m.device
            product = " ".join(p for p in (device.manufacturer, device.order_number) if p)
            issues.append(ValidationIssue(
                "warning", "FA-621",
                f"Die GAs von {m.element_text} ({m.room.number} {m.room.name}) folgen "
                f"{product} von {device.physical_address} {device.product}, gehören "
                f"aber dem Aktor",
                device.physical_address,
                "In Schritt 5 «Produkt…» das Produkt des Elements entfernen",
                details={"device": device.physical_address, "product": product,
                         "planned": product},
            ))
        return issues

    def _check_products_without_kos(self, project) -> list[ValidationIssue]:
        """FA-622: Geräte, deren Produkt im Katalog keine KOs hat -- Warnung,
        wenn der Katalog dasselbe Gerät mit KOs kennt (Projekt_23: ABB
        VAA/S6.230.2.1 ohne KOs, «2CDG 110 116 R0011» mit 82 KOs), sonst
        Hinweis: ohne KOs keine Kanal-/KO-Zuordnung."""
        from .product_sync import shared_catalog
        catalog = shared_catalog()
        if catalog is None or project.topology.is_imported:
            return []
        issues = []
        for area in project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if not device.order_number or device.device_type not in (
                            "actor", "gateway", "sensor"):
                        continue
                    found = catalog.find_product(device.manufacturer, device.order_number,
                                                 device.product_name)
                    if found is None or found.get("com_objects"):
                        continue
                    product = " ".join(p for p in (device.manufacturer, device.order_number)
                                       if p)
                    duplicate = catalog.duplicate_of(device.manufacturer, device.order_number,
                                                     device.product_name)
                    if duplicate:
                        issues.append(ValidationIssue(
                            "warning", "FA-622",
                            f"{device.physical_address} {device.product}: {product} hat keine "
                            f"KOs – vermutlich dasselbe Gerät wie "
                            f"{duplicate.get('order_number', '')} (KNXPROD, mit KOs)",
                            device.physical_address,
                            "Materialliste › «Produkte mit KOs übernehmen…»",
                            details={"device": device.physical_address, "product": product,
                                     "planned": duplicate.get("order_number", "")},
                        ))
                    else:
                        issues.append(ValidationIssue(
                            "info", "FA-622",
                            f"{device.physical_address} {device.product}: {product} hat keine "
                            f"KOs – keine Kanal-/KO-Zuordnung möglich",
                            device.physical_address,
                            "KNXPROD des Herstellers in den Produktkatalog importieren",
                            details={"device": device.physical_address, "product": product,
                                     "planned": ""},
                        ))
        return issues

    def _check_unoperated(self, project) -> list[ValidationIssue]:
        """FA-619: schaltbare Elemente ohne Taste, Präsenzmelder, Szene oder
        Zeitsteuerung (nur geplante Projekte)."""
        from .operation_check import unoperated_elements
        catalog = self.catalog or project.gewerk_catalog
        issues = []
        from .operation_check import switched_elements
        switched = switched_elements(project)
        for u in unoperated_elements(project):
            gewerk = catalog.get(u.gewerk_code) if catalog else None
            name = gewerk.name if gewerk else u.gewerk_code
            if u.gewerk_code == "SF" or (u.room_id, u.gewerk_code, u.element_number) in switched:
                # ohne Taste geplant: über Szene oder Zeitprogramm
                message = (f"{name} {u.ga.designation} wird von keiner Taste, "
                           f"keiner Szene und keinem Zeitprogramm geschaltet")
                suggestion = ("In eine Szene (z.B. Anwesenheit) oder ein Zeitprogramm "
                              "aufnehmen, oder einer Taste zuweisen")
            else:
                message = f"{name} {u.ga.designation} wird von keiner Taste bedient"
                suggestion = ("In der Bauherrenberatung einer Taste zuweisen, auch einer Taste "
                              "in einem anderen Raum, oder so belassen, wenn es anders bedient wird")
            issues.append(ValidationIssue(
                "info", "FA-619", message, u.ga.address, suggestion,
                designation=u.ga.designation,
                details={"gewerk": name},
            ))
        return issues

    @staticmethod
    def _check_scene_numbers(project) -> list[ValidationIssue]:
        """FA-1813: Ein Aktor unterscheidet nicht, über welche Szenen-GA eine
        Nummer kommt. Gleiche Nummer auf derselben GA, oder auf verschiedenen
        GAs mit gemeinsamen Aktoren, löst die falsche Szene aus."""
        from .scene_numbering import number_conflicts
        issues = []
        for c in number_conflicts(project):
            if c.same_channel:
                message = (f"Szene {c.number} zweimal auf {c.first_channel}: "
                           f"«{c.first.name}» und «{c.second.name}»")
                suggestion = "Einer der Szenen eine freie Nummer geben"
            else:
                shown = ", ".join(c.shared[:3]) + (" …" if len(c.shared) > 3 else "")
                message = (f"Szene {c.number}: «{c.first.name}» ({c.first_channel}) und "
                           f"«{c.second.name}» ({c.second_channel}) erreichen dieselben "
                           f"Aktoren: {shown}")
                suggestion = ("Nummern so wählen, dass sie sich am Aktor nicht "
                              "überschneiden (Nummernbereich je Ebene)")
            issues.append(ValidationIssue(
                "warning", "FA-1813", message, "", suggestion,
                details={"number": c.number}))
        return issues

    def _check_time_programs(self, project) -> list[ValidationIssue]:
        """FA-3306a/b: Zeitprogramme mit fehlender Ziel-GA (Fehler) oder einem
        Wert, der nicht zum Datenpunkttyp passt (Warnung)."""
        from .time_program_service import validate_all_programs
        return [
            ValidationIssue(
                e.severity, "FA-3306", f"Zeitprogramm '{e.program_name}': {e.message}",
                e.address or "Zeitsteuerung",
                "In der Zeitsteuerung den Schaltzeitpunkt korrigieren",
            )
            for e in validate_all_programs(project)
        ]

    def _check_astro_gas(self, structure: GroupAddressStructure,
                         project) -> list[ValidationIssue]:
        """FA-3308b: Warnung wenn Astro-SwitchPoints vorhanden aber HG0/MG7 fehlt."""
        issues = []
        try:
            has_astro = any(
                sp.time_type == "ASTRO"
                for tp in project.time_programs
                if tp.active
                for dp in tp.day_profiles
                for sp in dp.switch_points
            )
            if not has_astro:
                return issues

            hg0 = next((g for g in structure.main_groups if g.number == 0), None)
            mg7 = next((m for m in hg0.middle_groups if m.number == 7), None) if hg0 else None

            if mg7 is None:
                issues.append(ValidationIssue(
                    level="warning",
                    rule_id="FA-3308b",
                    message=(
                        "Astro-Schaltpunkte im Zeitprogramm gefunden, "
                        "aber Astro-GAs in HG 0 / MG 7 fehlen."
                    ),
                    address="0/7/-",
                    suggestion=(
                        "Führen Sie die GA-Generierung erneut aus (Wizard Schritt 9), "
                        "oder klicken Sie in der Zeitsteuerungsansicht auf "
                        "'Astro-GAs anlegen'."
                    ),
                ))
            else:
                # Prüfen ob alle 4 Standard-GAs vorhanden (Sub 0–3)
                existing = {ga.sub_group for ga in mg7.group_addresses}
                missing = [s for s in range(4) if s not in existing]
                if missing:
                    issues.append(ValidationIssue(
                        level="warning",
                        rule_id="FA-3308b",
                        message=(
                            f"HG 0 / MG 7 vorhanden, aber {len(missing)} Astro-GAs fehlen "
                            f"(Sub-Gruppen: {', '.join(str(s) for s in missing)})."
                        ),
                        address="0/7/-",
                        suggestion=(
                            "GA-Generierung erneut ausführen oder manuell "
                            "die fehlenden Astro-GAs anlegen."
                        ),
                    ))
        except Exception as e:
            logger.debug(f"FA-3308b Prüfung fehlgeschlagen: {e}")
        return issues

    def _check_valid_addresses(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-601: Prüft gültige Adressen."""
        issues = []
        for ga in addresses:
            if ga.is_placeholder:
                continue
            # GA-08/FA-444: 0/0/0 ist Systemadresse – auch bei Zentraladressen prüfen
            if ga.main_group == 0 and ga.middle_group == 0 and ga.sub_group == 0:
                issues.append(ValidationIssue(
                    "error", "GA-08",
                    "Adresse 0/0/0 ist KNX-Systemadresse und darf nicht verwendet werden",
                    ga.address,
                    "Verwenden Sie 0/0/1 als erste Zentraladresse",
                    designation=ga.designation,
                ))
                continue
            if ga.central == "true":
                continue
            if not is_valid_ga(ga.main_group, ga.middle_group, ga.sub_group):
                issues.append(ValidationIssue(
                    "error", "FA-601",
                    f"Ungültige Gruppenadresse: {ga.address}",
                    ga.address,
                    designation=ga.designation,
                ))
        return issues

    def _check_duplicates(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-602: Prüft auf doppelte Adressen."""
        issues = []
        seen: dict[str, GroupAddress] = {}
        for ga in addresses:
            if ga.is_placeholder:
                continue
            key = ga.address
            if key in seen:
                issues.append(ValidationIssue(
                    "error", "FA-602",
                    f"Doppelte Gruppenadresse: {key} "
                    f"('{ga.designation}' und '{seen[key].designation}')",
                    key,
                    "Eine der beiden Adressen muss geändert werden.",
                    designation=ga.designation,
                    details={"other": seen[key].designation},
                ))
            else:
                seen[key] = ga
        return issues

    def _check_dpt(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-603, FA-604: Prüft Datenpunkttypen."""
        issues = []
        expected_dpts = {
            "E/A": "DPST-1-1", "RM": "DPST-1-1",
            "DIM": "DPST-3-7",
            "WERT": "DPST-5-1", "RM WERT": "DPST-5-1",
            "AUF/AB": "DPST-1-8", "BESCHATTUNG": "DPST-1-8",
            "STOPP": "DPST-1-7",
            "IST": "DPST-9-1", "BASIS-SOLL": "DPST-9-1",
        }
        for ga in addresses:
            if ga.is_placeholder:
                continue
            if not ga.datapoint_type:
                proposal = suggest_dpt(ga.designation, ga.function_name)
                issues.append(ValidationIssue(
                    "warning", "FA-604",
                    f"Fehlender Datenpunkttyp für: {ga.designation}",
                    ga.address,
                    f"DPT-Vorschlag: {proposal}" if proposal else "",
                    designation=ga.designation,
                    details={"dpt": proposal},
                ))
            else:
                expected = expected_dpts.get(ga.function_name)
                if expected is not None:
                    wrong = ga.datapoint_type != expected
                else:
                    # übrige Funktionen der Liste (FA-1003c): nur der Haupttyp
                    expected = ga_functions.suggested_dpt(ga.function_name)
                    wrong = bool(expected) and _dpt_main(ga.datapoint_type) != _dpt_main(expected)
                if wrong:
                    issues.append(ValidationIssue(
                        "warning", "FA-603",
                        f"Unerwarteter DPT für {ga.function_name}: "
                        f"{ga.datapoint_type} (erwartet: {expected})",
                        ga.address,
                        f"DPT auf {expected} ändern",
                        designation=ga.designation,
                        details={"actual": ga.datapoint_type, "expected": expected},
                    ))
        return issues

    @staticmethod
    def _planned_room_numbers(project) -> set[str] | None:
        """Raumnummern der Gebäudestruktur bei mit KNiX geplanten Projekten.

        None bei importierten Projekten (Bezeichnungen stammen aus der ETS)
        oder wenn noch keine Räume erfasst sind -- dann nur Formatprüfung.
        """
        if project is None or project.topology.is_imported:
            return None
        numbers = {r.number for r in project.areal.all_rooms if r.number}
        return numbers or None

    def _check_naming(self, addresses: list[GroupAddress],
                      room_numbers: set[str] | None = None) -> list[ValidationIssue]:
        """FA-606, FA-610: Prüft Bezeichnungskonformitaet.

        Raumnummern sind frei gestaltbar (Prüfrahmen siehe
        utils/validators.ROOM_NUMBER_PATTERN). Bei geplanten Projekten muss
        der Raumteil zusätzlich ein Raum der Gebäudestruktur sein.
        """
        issues = []
        for ga in addresses:
            if ga.is_placeholder or ga.central == "true":
                continue
            if ga.designation and ga.designation != "--":
                if not is_valid_designation(ga.designation):
                    issues.append(ValidationIssue(
                        "info", "FA-610",
                        f"Bezeichnung nicht konform mit KNX Swiss Standard: "
                        f"'{ga.designation}'",
                        ga.address,
                        "Erwartetes Format: GEWERK_RAUM_NR FUNKTION (Klartext)",
                        designation=ga.designation,
                    ))
                elif room_numbers is not None:
                    room = designation_room_number(ga.designation)
                    if room not in room_numbers:
                        issues.append(ValidationIssue(
                            "info", "FA-610",
                            f"Raum {room} der Bezeichnung fehlt in der "
                            f"Gebäudestruktur: '{ga.designation}'",
                            ga.address,
                            "Raumnummer in Schritt 3 prüfen oder Adressen in "
                            "Schritt 7 neu erzeugen",
                            designation=ga.designation,
                            details={"room": room},
                        ))
        return issues

    def _check_middle_group_assignment(self, addresses: list[GroupAddress]) -> list[ValidationIssue]:
        """FA-607: Prüft Mittelgruppen-Zuordnung."""
        issues = []
        category_to_mg = {
            "licht": 0, "jalousie": 1, "heizung": 2, "alarm": 3,
        }
        if not self.catalog:
            return issues

        for ga in addresses:
            if ga.is_placeholder or ga.main_group == 0:
                continue
            if ga.gewerk_code:
                gewerk = self.catalog.get(ga.gewerk_code)
                if gewerk and gewerk.middle_group != ga.middle_group:
                    # Pruefen ob es eine Rueckmeldungs-MG ist (6 oder 7)
                    if ga.middle_group not in (6, 7):
                        issues.append(ValidationIssue(
                            "warning", "FA-607",
                            f"Gewerk {ga.gewerk_code} in falscher MG: "
                            f"{ga.middle_group} (erwartet: {gewerk.middle_group})",
                            ga.address,
                            f"GA nach MG {gewerk.middle_group} verschieben "
                            f"oder Gewerk korrigieren",
                            designation=ga.designation,
                            details={"gewerk": ga.gewerk_code,
                                     "actual": ga.middle_group,
                                     "expected": gewerk.middle_group},
                        ))
        return issues

    def _check_block_integrity(self, structure: GroupAddressStructure) -> list[ValidationIssue]:
        """FA-605: Prüft Adressblock-Integritaet (keine Luecken).

        Nur ein Hinweis: In importierten Projekten sind Lücken meist gewollt
        (Reserve-Adressen, Gliederung nach Räumen)."""
        issues = []
        for hg in structure.main_groups:
            for mg in hg.middle_groups:
                gas = sorted(mg.group_addresses, key=lambda g: g.sub_group)
                if not gas:
                    continue
                # Pruefe ob Adressen lueckenlos aufeinanderfolgen
                for i in range(len(gas) - 1):
                    if gas[i + 1].sub_group != gas[i].sub_group + 1:
                        gap_start = gas[i].sub_group + 1
                        gap_end = gas[i + 1].sub_group - 1
                        issues.append(ValidationIssue(
                            "info", "FA-605",
                            f"Lücke in MG {hg.number}/{mg.number}: "
                            f"Adressen {gap_start}-{gap_end} fehlen",
                            f"{hg.number}/{mg.number}/{gap_start}",
                            details={"mg": f"{hg.number}/{mg.number}",
                                     "start": gap_start, "end": gap_end},
                        ))
        return issues

    def _check_feedback_variant_b(self, structure: GroupAddressStructure) -> list[ValidationIssue]:
        """FA-608: Prüft Variante B Rückmeldungen."""
        issues = []
        for hg in structure.main_groups:
            if hg.number == 0:
                continue
            # Finde MG 0 und MG 6 (Licht)
            mg0 = next((m for m in hg.middle_groups if m.number == 0), None)
            mg6 = next((m for m in hg.middle_groups if m.number == 6), None)
            if mg0 and not mg6:
                if any(not ga.is_placeholder for ga in mg0.group_addresses):
                    issues.append(ValidationIssue(
                        "warning", "FA-608",
                        f"HG {hg.number}: Licht-Adressen in MG 0 vorhanden, "
                        f"aber keine Rückmeldungen in MG 6",
                        f"{hg.number}/6/0",
                        "Rückmelde-GAs in MG 6 anlegen",
                    ))
            # Finde MG 1 und MG 7 (Jalousie)
            mg1 = next((m for m in hg.middle_groups if m.number == 1), None)
            mg7 = next((m for m in hg.middle_groups if m.number == 7), None)
            if mg1 and not mg7:
                if any(not ga.is_placeholder for ga in mg1.group_addresses):
                    issues.append(ValidationIssue(
                        "warning", "FA-608",
                        f"HG {hg.number}: Jalousie-Adressen in MG 1 vorhanden, "
                        f"aber keine Rückmeldungen in MG 7",
                        f"{hg.number}/7/0",
                        "Rückmelde-GAs in MG 7 anlegen",
                    ))
            issues.extend(self._check_feedback_alignment_b(hg))
        return issues

    @staticmethod
    def _is_feedback_function(ga: GroupAddress) -> bool:
        name = (ga.function_name or "").upper()
        return any(name == p or name.startswith(p + " ") for p in ("RM", "STATUS"))

    def _check_feedback_alignment_b(self, hg) -> list[ValidationIssue]:
        """FA-608 / GA-07: in Variante B liegen Rückmeldungen nur in MG 6/7,
        jeweils unter der Untergruppe ihres Befehls in MG 0/1 (gleiches
        Element: Gewerk, Raum, Nummer)."""
        issues = []
        mgs = {m.number: m for m in hg.middle_groups}
        for cmd_num, fb_num in ((0, 6), (1, 7)):
            commands = {
                ga.sub_group: ga for ga in (mgs[cmd_num].group_addresses
                                            if cmd_num in mgs else [])
                if not ga.is_placeholder
            }
            for ga in commands.values():
                if self._is_feedback_function(ga):
                    # in der Baumansicht bewusst umgewidmet: nur ein Hinweis
                    issues.append(ValidationIssue(
                        "info" if ga.plan_function else "warning", "FA-608",
                        f"Rückmeldung in MG {cmd_num} statt MG {fb_num}",
                        ga.address,
                        f"Adressen neu erzeugen (Variante B: Rückmeldungen in MG {fb_num})",
                        designation=ga.designation,
                    ))
            for ga in (mgs[fb_num].group_addresses if fb_num in mgs else []):
                if ga.is_placeholder:
                    continue
                cmd = commands.get(ga.sub_group)
                same_element = cmd is not None and (
                    not (ga.gewerk_code and cmd.gewerk_code)
                    or (ga.gewerk_code, ga.room_number, ga.element_number)
                    == (cmd.gewerk_code, cmd.room_number, cmd.element_number)
                )
                if not same_element:
                    issues.append(ValidationIssue(
                        "warning", "FA-608",
                        f"Rückmeldung ohne Befehl unter {hg.number}/{cmd_num}/"
                        f"{ga.sub_group} (Untergruppen müssen übereinstimmen)",
                        ga.address,
                        "Adressen neu erzeugen oder Rückmeldung auf die "
                        "Untergruppe des Befehls verschieben",
                        designation=ga.designation,
                    ))
        return issues
