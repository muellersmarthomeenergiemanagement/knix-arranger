"""
Bericht-Service (FA-050, FA-600)
Erzeugt Validierungsberichte, GA-Listen und Projektuebersichten als PDF/Text.
"""
from __future__ import annotations
import logging
import re
from collections import defaultdict
from datetime import datetime

from ..models.project import KnxProject
from ..models.group_address import GroupAddressStructure, MIDDLE_GROUP_NAMES_A, MIDDLE_GROUP_NAMES_B
from ..services.validation_engine import ValidationEngine, ValidationIssue
from ..services.belegungsplan_service import _split_button_channel
from ..services.naming_engine import NamingEngine
from ..utils.pdf_generator import PdfGenerator

logger = logging.getLogger("knix_arranger.report_service")

# Feste Anzeige-Reihenfolge der Gewerk-Kategorien (entspricht den
# Filter-Buttons der GA-Ansicht: Licht, Jalousie, Heizung, Lüftung/Klima,
# Energie, Alarm, Allgemein). Unbekannte/leere Kategorien (Sonstige) zuletzt.
GEWERK_CATEGORY_ORDER = [
    "licht", "licht_color", "jalousie", "heizung",
    "lueftung", "energie", "alarm", "allgemein",
]
GEWERK_CATEGORY_LABELS = {
    "licht": "Licht",
    "licht_color": "Licht (Farbe)",
    "jalousie": "Jalousie",
    "heizung": "Heizung",
    "lueftung": "Lüftung / Klima",
    "energie": "Energie",
    "alarm": "Alarm",
    "allgemein": "Allgemein",
    "": "Sonstige",
}


def _gewerk_category_sort_key(category: str) -> int:
    try:
        return GEWERK_CATEGORY_ORDER.index(category)
    except ValueError:
        return len(GEWERK_CATEGORY_ORDER)


class ReportService:
    """Erzeugt verschiedene Berichte für ein KNX-Projekt."""

    def __init__(self, project: KnxProject, company_profile=None):
        self.project = project
        self._company_profile = company_profile  # globales CompanyProfile (FA-852)

    def _gewerk_label(self, code: str) -> str:
        """Gibt 'Code – Name' zurück, z.B. 'LD – Licht dimmbar'."""
        gewerk = self.project.gewerk_catalog.get(code)
        name = gewerk.name if gewerk else ""
        return f"{code} – {name}" if name else code

    def _make_pdf(self, title: str) -> PdfGenerator:
        """Erstellt PdfGenerator mit Firmenprofil, Projektdaten und Deckblatt (FA-855–857)."""
        pdf = PdfGenerator(
            title=title,
            company_profile=self._company_profile,
            project_info=self.project.project_info,
        )
        cp = self.project.client_profile
        if cp and cp.name:
            pdf.set_client_profile(cp)
        return pdf

    def generate_validation_report(self, filepath: str):
        """Erzeugt einen Validierungsbericht als PDF/Text (FA-600)."""
        engine = ValidationEngine(self.project.gewerk_catalog)
        issues = engine.validate(self.project.group_addresses)

        pdf = self._make_pdf("Validierungsbericht")

        pdf.add_heading("Validierungsbericht", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Variante: {self.project.config.mg_variant} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        # Zusammenfassung
        errors = [i for i in issues if i.level == "error"]
        warnings = [i for i in issues if i.level == "warning"]
        infos = [i for i in issues if i.level == "info"]

        pdf.add_heading("Zusammenfassung", level=2)
        ga_count = len(self.project.group_addresses.all_addresses())
        pdf.add_paragraph(f"Gepruefte Gruppenadressen: {ga_count}")
        pdf.add_paragraph(f"Fehler: {len(errors)}")
        pdf.add_paragraph(f"Warnungen: {len(warnings)}")
        pdf.add_paragraph(f"Hinweise: {len(infos)}")
        pdf.add_separator()

        # Detailierte Ergebnisse
        if errors:
            pdf.add_heading("Fehler", level=2)
            headers = ["Adresse", "Regel", "Beschreibung", "Vorschlag"]
            rows = []
            for issue in errors:
                rows.append([
                    issue.address,
                    issue.rule_id,
                    issue.message[:80],
                    issue.suggestion[:60] if issue.suggestion else "-",
                ])
            pdf.add_table(headers, rows)

        if warnings:
            pdf.add_heading("Warnungen", level=2)
            headers = ["Adresse", "Regel", "Beschreibung", "Vorschlag"]
            rows = []
            for issue in warnings:
                rows.append([
                    issue.address,
                    issue.rule_id,
                    issue.message[:80],
                    issue.suggestion[:60] if issue.suggestion else "-",
                ])
            pdf.add_table(headers, rows)

        if infos:
            pdf.add_heading("Hinweise", level=2)
            headers = ["Adresse", "Regel", "Beschreibung"]
            rows = []
            for issue in infos:
                rows.append([
                    issue.address,
                    issue.rule_id,
                    issue.message[:80],
                ])
            pdf.add_table(headers, rows)

        if not issues:
            pdf.add_heading("Ergebnis", level=2)
            pdf.add_paragraph("Keine Probleme gefunden. Alle Pruefungen bestanden.")

        pdf.save(filepath)
        logger.info(f"Validierungsbericht erstellt: {filepath}")
        return issues

    def generate_ga_report(self, filepath: str):
        """Erzeugt eine GA-Übersicht als PDF/Text."""
        structure = self.project.group_addresses
        mg_names = (MIDDLE_GROUP_NAMES_B if structure.variant == "B"
                    else MIDDLE_GROUP_NAMES_A)

        pdf = self._make_pdf("Gruppenadress-Übersicht")

        pdf.add_heading("Gruppenadress-Übersicht", level=1)
        pdf.add_paragraph(
            f"Variante: {structure.variant} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        # Statistik
        total_gas = len(structure.all_addresses())
        placeholders = sum(1 for ga in structure.all_addresses() if ga.is_placeholder)
        central = sum(1 for ga in structure.all_addresses() if ga.central == "true")

        pdf.add_heading("Statistik", level=2)
        pdf.add_paragraph(f"Gesamt Gruppenadressen: {total_gas}")
        pdf.add_paragraph(f"Aktive Adressen: {total_gas - placeholders}")
        pdf.add_paragraph(f"Reserve-Platzhalter: {placeholders}")
        pdf.add_paragraph(f"Zentraladressen (HG 0): {central}")
        pdf.add_separator()

        # Pro Hauptgruppe
        for hg in structure.main_groups:
            hg_gas = sum(len(mg.group_addresses) for mg in hg.middle_groups)
            pdf.add_heading(f"HG {hg.number}: {hg.name} ({hg_gas} GAs)", level=2)

            for mg in hg.middle_groups:
                if not mg.group_addresses:
                    continue
                mg_name = mg_names.get(mg.number, mg.name)
                pdf.add_heading(
                    f"MG {mg.number}: {mg_name} ({len(mg.group_addresses)} GAs)",
                    level=3,
                )

                headers = ["Adresse", "Bezeichnung", "DPT", "Gewerk"]
                rows = []
                for ga in sorted(mg.group_addresses, key=lambda g: g.sub_group):
                    gewerk_label = (
                        self._gewerk_label(ga.gewerk_code)
                        if ga.gewerk_code else "-"
                    )
                    rows.append([
                        ga.address,
                        ga.designation[:50] if ga.designation else "-",
                        ga.datapoint_type or "-",
                        gewerk_label,
                    ])
                pdf.add_table(headers, rows)

        pdf.save(filepath)
        logger.info(f"GA-Bericht erstellt: {filepath}")

    def generate_room_gewerk_report(self, filepath: str):
        """Erzeugt den Bericht 'Räume nach Gewerken' als PDF.

        Zeigt pro Raum, welche Gewerke/Funktionsbereiche vorhanden sind und
        über welche Gruppenadressen sie angesteuert werden. Die Raum-GA-
        Zuordnung wird sowohl über `GroupAddress.room_id` (Wizard-Projekte)
        als auch über verknüpfte Geräte (`Device.room_id` + `connected_gas`)
        ermittelt, damit der Bericht auch für importierte .knxproj-Projekte
        ohne Gewerke-Zuweisung funktioniert. GAs ohne `gewerk_code` werden
        anhand ihrer Mittelgruppe kategorisiert.
        """
        structure = self.project.group_addresses
        mg_names = (MIDDLE_GROUP_NAMES_B if structure.variant == "B"
                    else MIDDLE_GROUP_NAMES_A)

        # Adresse -> GroupAddress / Mittelgruppen-Bezeichnung (Fallback-Kategorie)
        ga_by_address = {}
        mg_label_by_address = {}
        for hg in structure.main_groups:
            for mg in hg.middle_groups:
                mg_label = mg_names.get(mg.number) or mg.name or f"MG {mg.number}"
                for ga in mg.group_addresses:
                    ga_by_address[ga.address] = ga
                    mg_label_by_address[ga.address] = mg_label

        # Raum-ID -> verknüpfte Geräte (für Import-Projekte ohne ga.room_id)
        devices_by_room = defaultdict(list)
        for area in self.project.topology.areas:
            for line in area.lines:
                for dev in line.devices:
                    if dev.room_id:
                        devices_by_room[dev.room_id].append(dev)

        # Stockwerk-/Zonenname je Raum (für Anzeige und Sortierung)
        floor_by_room = {}
        zone_by_room = {}
        for building in self.project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            floor_by_room[room.id] = floor.name
                            zone_by_room[room.id] = apt.name

        def _room_key(room):
            floor = floor_by_room.get(room.id, "")
            zone = zone_by_room.get(room.id, "")
            num = 9999
            if room.number:
                m = re.search(r'\d+', room.number)
                if m:
                    num = int(m.group())
            return (floor, zone, num, room.name)

        pdf = self._make_pdf("Räume nach Gewerken")
        pdf.add_heading("Räume nach Gewerken", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        has_any = False
        for room in sorted(self.project.all_rooms, key=_room_key):
            # GAs für diesen Raum sammeln (über room_id und/oder verknüpfte Geräte)
            room_gas = {}
            for ga in structure.all_addresses():
                if ga.room_id == room.id and not ga.is_placeholder:
                    room_gas[ga.address] = ga
            for dev in devices_by_room.get(room.id, []):
                for co in dev.communication_objects:
                    for addr in co.connected_gas:
                        ga = ga_by_address.get(addr)
                        if ga and not ga.is_placeholder:
                            room_gas.setdefault(addr, ga)

            if not room_gas:
                continue
            has_any = True

            # Nach Gewerk + Element gruppieren (mehrere Elemente desselben
            # Gewerks, z.B. Jalousie 1/2, bleiben so unterscheidbar);
            # ohne gewerk_code anhand der Mittelgruppe
            groups = defaultdict(list)
            for ga in room_gas.values():
                if ga.gewerk_code:
                    label = self._gewerk_label(ga.gewerk_code)
                else:
                    label = mg_label_by_address.get(ga.address, "Sonstige")
                groups[(label, ga.element_number)].append(ga)

            # Labels mit mehreren Elementen ermitteln, um die Elementnummer
            # nur dort anzuzeigen, wo sie tatsächlich unterscheidet
            elements_per_label = defaultdict(set)
            for (label, elem_nr) in groups.keys():
                elements_per_label[label].add(elem_nr)

            floor_name = floor_by_room.get(room.id, "")
            zone_name = zone_by_room.get(room.id, "")
            room_label = f"{room.number} {room.name}".strip()
            location = " / ".join(p for p in [floor_name, zone_name, room_label] if p)

            num_gewerke = len({label for label, _ in groups.keys()})
            pdf.add_conditional_break(min_height=120)
            pdf.add_heading(
                f"{location or room_label} "
                f"({num_gewerke} Gewerke, {len(room_gas)} GAs)",
                level=2,
            )

            def _category_for(gas):
                code = gas[0].gewerk_code
                if code:
                    gewerk = self.project.gewerk_catalog.get(code)
                    if gewerk:
                        return gewerk.category
                return ""

            headers = ["Gewerk / Funktionsbereich", "Adresse", "Funktion", "Bezeichnung", "Beschreibung", "DPT"]
            col_widths = [115, 40, 85, 95, 100, 60]
            sorted_groups = sorted(
                groups.items(),
                key=lambda kv: (_gewerk_category_sort_key(_category_for(kv[1])), kv[0][0], kv[0][1]),
            )

            prev_category = None
            rows = []
            for (label, elem_nr), gas in sorted_groups:
                category = _category_for(gas)
                if category != prev_category:
                    if rows:
                        pdf.add_table(headers, rows, col_widths=col_widths)
                        rows = []
                    pdf.add_heading(
                        GEWERK_CATEGORY_LABELS.get(category, category or "Sonstige"),
                        level=3,
                    )
                    prev_category = category

                display_label = label
                if elem_nr and len(elements_per_label[label]) > 1:
                    display_label = f"{label} {elem_nr}"

                gas_sorted = sorted(
                    gas, key=lambda g: (g.main_group, g.middle_group, g.sub_group)
                )
                for i, g in enumerate(gas_sorted):
                    parsed = NamingEngine.parse_designation(g.designation)
                    if parsed["gewerk_code"]:
                        funktion = parsed["function_name"] or "-"
                        bezeichnung = parsed["description"] or "-"
                    else:
                        funktion = "-"
                        bezeichnung = g.designation[:50] if g.designation else "-"
                    rows.append([
                        f"{display_label} ({len(gas_sorted)} GAs)" if i == 0 else "",
                        g.address,
                        funktion,
                        bezeichnung,
                        g.description[:50] if g.description else "-",
                        g.datapoint_type or "-",
                    ])

            if rows:
                pdf.add_table(headers, rows, col_widths=col_widths)
            pdf.add_separator()

        if not has_any:
            pdf.add_paragraph(
                "Keine Räume mit zugeordneten Gruppenadressen gefunden."
            )

        pdf.save(filepath)
        logger.info(f"Räume-nach-Gewerken-Bericht erstellt: {filepath}")

    def generate_project_summary(self, filepath: str):
        """Erzeugt eine Projektzusammenfassung als PDF/Text."""
        p = self.project

        pdf = self._make_pdf("Projektzusammenfassung")

        pdf.add_heading("Projektzusammenfassung", level=1)
        pdf.add_separator()

        # Projektinformationen
        pdf.add_heading("Projektinformationen", level=2)
        pdf.add_paragraph(f"Projektname: {p.name}")
        pdf.add_paragraph(f"Projektnummer: {p.project_number}")
        pdf.add_paragraph(f"MG-Variante: {p.config.mg_variant}")
        pdf.add_paragraph(f"Topologie-Modus: {p.config.topology_mode}")
        pdf.add_paragraph(f"Backbone-Typ: {p.config.backbone_type}")
        pdf.add_paragraph(f"Erstellt: {p.created}")
        pdf.add_paragraph(f"Geändert: {p.modified}")
        pdf.add_separator()

        # Gebäudestruktur
        pdf.add_heading("Gebäudestruktur", level=2)
        floors = p.all_floors
        rooms = p.all_rooms
        pdf.add_paragraph(f"Stockwerke: {len(floors)}")
        pdf.add_paragraph(f"Räume: {len(rooms)}")

        if floors:
            headers = ["Stockwerk", "Räume", "Geräte"]
            rows = []
            for floor in floors:
                room_count = len(floor.all_rooms)
                device_count = floor.total_devices()
                rows.append([
                    floor.name,
                    str(room_count),
                    str(device_count),
                ])
            pdf.add_table(headers, rows)

        # Topologie
        pdf.add_heading("Topologie", level=2)
        areas = p.topology.areas
        lines = sum(len(a.lines) for a in areas)
        devices = sum(
            len(l.devices) for a in areas for l in a.lines
        )
        pdf.add_paragraph(f"Bereiche: {len(areas)}")
        pdf.add_paragraph(f"Linien: {lines}")
        pdf.add_paragraph(f"Geräte: {devices}")

        # Gerätetyp-Aufschluesselung
        type_counts: dict[str, int] = {}
        for area in areas:
            for line in area.lines:
                for dev in line.devices:
                    label = {
                        "actor": "Aktoren",
                        "sensor": "Sensoren",
                        "coupler": "Koppler",
                        "power_supply": "Spannungsversorgungen",
                    }.get(dev.device_type, "Sonstige")
                    type_counts[label] = type_counts.get(label, 0) + 1
        if type_counts:
            for label, count in type_counts.items():
                pdf.add_paragraph(f"  {label}: {count}")

        pdf.add_separator()

        # Gruppenadressen
        pdf.add_heading("Gruppenadressen", level=2)
        ga_count = len(p.group_addresses.all_addresses())
        pdf.add_paragraph(f"Gesamt: {ga_count}")
        for hg in p.group_addresses.main_groups:
            hg_count = sum(len(mg.group_addresses) for mg in hg.middle_groups)
            pdf.add_paragraph(f"  HG {hg.number} ({hg.name}): {hg_count} GAs")
        pdf.add_separator()

        # Gewerke
        pdf.add_heading("Gewerke-Übersicht", level=2)
        gewerk_counts: dict[str, int] = {}
        for room in rooms:
            for ga in room.gewerk_assignments:
                code = ga.gewerk_code
                gewerk_counts[code] = gewerk_counts.get(code, 0) + ga.count

        if gewerk_counts:
            headers = ["Code", "Bezeichnung", "Anzahl Elemente"]
            rows = []
            for code, count in sorted(gewerk_counts.items()):
                gewerk = self.project.gewerk_catalog.get(code)
                name = gewerk.name if gewerk else "-"
                rows.append([code, name, str(count)])
            pdf.add_table(headers, rows)

        pdf.save(filepath)
        logger.info(f"Projektzusammenfassung erstellt: {filepath}")

    def generate_topology_report(self, filepath: str):
        """Erzeugt einen Topologie-Bericht als PDF/Text."""
        pdf = self._make_pdf("Topologie-Bericht")

        pdf.add_heading("Topologie-Bericht", level=1)
        pdf.add_separator()

        topo = self.project.topology
        room_by_id = {r.id: r for r in self.project.all_rooms}

        # ── Liniendiagramm als Überblick ─────────────────────────────────────
        pdf.add_heading("Übersicht", level=2)
        pdf.add_topology_diagram(topo)
        pdf.add_page_break()


        def _dev_addr_key(dev):
            try:
                return tuple(int(p) for p in dev.physical_address.split("."))
            except ValueError:
                return (0, 0, 0)

        first_area_with_content = True

        for area in topo.areas:
            # Fix 1: Bereiche ohne Geräte überspringen
            area_has_content = any(line.devices or line.assigned_room_ids for line in area.lines)
            if not area_has_content:
                continue

            if not first_area_with_content:
                pdf.add_page_break()
            first_area_with_content = False

            # Fix 4: Leerzeichen bei fehlender Koppleradresse vermeiden
            area_info_parts = []
            if area.coupler_address:
                area_info_parts.append(f"Koppleradresse: {area.coupler_address}")
            if area.backbone_type:
                area_info_parts.append(f"Backbone: {area.backbone_type}")
            pdf.add_heading(f"Bereich {area.area_number}: {area.name}", level=2)
            if area_info_parts:
                pdf.add_paragraph("  ".join(area_info_parts))

            for line in area.lines:
                # Fix 1: Linien ohne Geräte und ohne Bedienelemente überspringen
                line_rooms_with_bes = [
                    room_by_id[rid] for rid in line.assigned_room_ids
                    if rid in room_by_id and room_by_id[rid].bedienelemente
                ]
                if not line.devices and not line_rooms_with_bes:
                    continue

                pdf.add_conditional_break(min_height=120)
                pdf.add_heading(
                    f"Linie {area.area_number}.{line.line_number}: {line.name} "
                    f"({line.device_count} Geräte)",
                    level=3,
                )

                # Fix 4: Koppler-Info sauber darstellen
                line_info_parts = []
                if line.coupler_address:
                    line_info_parts.append(f"Koppler: {line.coupler_address}")
                pdf.add_paragraph("  ".join(line_info_parts) if line_info_parts else "")

                if line.devices:
                    # Fix 2: Geräte nach Phys. Adresse aufsteigend sortieren
                    sorted_devs = sorted(line.devices, key=_dev_addr_key)
                    rows = []
                    for dev in sorted_devs:
                        rows.append([
                            dev.physical_address,
                            dev.device_type,
                            dev.product or "–",
                            dev.manufacturer or "–",
                            dev.order_number or "–",
                            dev.serial_number or "–",
                            dev.installation_location or "–",
                        ])
                    pdf.add_table(
                        ["Phys. Adresse", "Typ", "Produkt", "Hersteller", "Best.-Nr.", "Seriennummer", "Einbauort"],
                        rows,
                    )


        pdf.save(filepath)
        logger.info(f"Topologie-Bericht erstellt: {filepath}")

    def generate_bedienelemente_report(self, filepath: str):
        """Erzeugt einen Bedienelemente-Bericht als PDF (Gerätekarten-Layout)."""
        from .sensor_service import SensorService
        from .knxproj_import_service import KnxprojImportService
        # FA-1404: Physikalische Adressen aus Topologie sicherstellen.
        # Lazy-Aufruf damit auch alte gespeicherte Projekte korrekte Adressen erhalten,
        # ohne erneuten Import.
        try:
            KnxprojImportService._create_bedienelemente_from_topology(
                self.project.topology, self.project.areal
            )
        except Exception:
            pass
        SensorService().auto_assign_functions(
            self.project.all_rooms, self.project.group_addresses
        )
        pdf = self._make_pdf("Bedienelemente")

        pdf.add_heading("Bedienelemente", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        # ── Lookup-Strukturen ────────────────────────────────────────────────
        # GA-Adresse → GroupAddress
        ga_by_address = {ga.address: ga for ga in self.project.group_addresses.all_addresses()}
        # GA-Bezeichnung → GroupAddress (für function_assignments)
        ga_by_designation: dict = {}
        for ga in self.project.group_addresses.all_addresses():
            if ga.designation:
                key = ga.designation.split(" (")[0].strip()
                ga_by_designation.setdefault(key, ga)
                ga_by_designation.setdefault(ga.designation.strip(), ga)
        # Phys. Adresse → Topology-Device
        device_by_addr = {
            d.physical_address: d
            for area in self.project.topology.areas
            for line in area.lines
            for d in line.devices
        }
        # room_id → Stockwerk-Name / Wohnungs-/Zonenname
        floor_by_room: dict[str, str] = {}
        zone_by_room: dict[str, str] = {}
        for building in self.project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            floor_by_room[room.id] = floor.name
                            zone_by_room[room.id] = apt.name

        # ── Hilfsfunktionen für Sortierung ──────────────────────────────────
        def _addr_key(be):
            try:
                return tuple(int(p) for p in (be.participant_number or "").split("."))
            except ValueError:
                return (0, 0, 0)

        def _room_key(room):
            """Stockwerk → Zone → Raum-Nr. numerisch (leer/keine Zahl = zuletzt)."""
            floor = floor_by_room.get(room.id, "")
            zone  = zone_by_room.get(room.id, "")
            num = 9999
            if room.number:
                m = re.search(r'\d+', room.number)
                if m:
                    num = int(m.group())
            return (floor, zone, num, room.name)

        sorted_rooms = sorted(self.project.all_rooms, key=_room_key)

        # ── Übersichtstabelle ────────────────────────────────────────────────
        summary_rows = []
        for room in sorted_rooms:
            floor_name = floor_by_room.get(room.id, "")
            zone_name  = zone_by_room.get(room.id, "")
            room_label = f"{room.number} {room.name}".strip()
            location   = " / ".join(p for p in [floor_name, zone_name, room_label] if p)
            for be in sorted(room.bedienelemente, key=_addr_key):
                summary_rows.append([
                    be.participant_number or "-",
                    be.element_type or "Bedienelement",
                    location,
                ])
        if summary_rows:
            pdf.add_table(
                ["Phys. Adresse", "Typ", "Standort"],
                summary_rows,
                col_widths=[65, 100, 330],
            )
            pdf.add_separator()

        has_any = False
        for room in sorted_rooms:
            if not room.bedienelemente:
                continue
            floor_name = floor_by_room.get(room.id, "")
            zone_name = zone_by_room.get(room.id, "")
            room_label = f"{room.number} {room.name}".strip()

            for be in sorted(room.bedienelemente, key=_addr_key):  # Fix 3: nach Adresse sortieren
                has_any = True
                device = device_by_addr.get(be.participant_number or "")

                # ── Bedingter Seitenumbruch vor neuer Karte (Fix 5) ─────────
                pdf.add_conditional_break(min_height=150)

                # ── Gerätekopf ──────────────────────────────────────────────
                location_parts = [p for p in [floor_name, zone_name, room_label] if p]
                addr_suffix = f"  [{be.participant_number}]" if be.participant_number else ""
                heading = f"{be.element_type or 'Bedienelement'}{addr_suffix}  |  {' / '.join(location_parts)}"
                pdf.add_heading(heading, level=3)

                # ── Gerätedaten-Tabelle ──────────────────────────────────────
                info_rows = []
                product = be.product_name or (device.product if device else "")
                mfr     = be.manufacturer or (device.manufacturer if device else "")
                ordernr = be.order_number or (device.order_number if device else "")
                einbauort = device.installation_location if device else ""

                if mfr:
                    info_rows.append(["Hersteller", mfr])
                if product:
                    info_rows.append(["Produkt", product])
                if ordernr:
                    info_rows.append(["Bestellnummer", ordernr])
                if be.participant_number:
                    info_rows.append(["Phys. Adresse", be.participant_number])
                if einbauort:
                    info_rows.append(["Einbauort", einbauort])
                if be.channels:
                    info_rows.append(["Kanäle", str(be.channels)])

                if info_rows:
                    pdf.add_table(["Eigenschaft", "Wert"], info_rows)

                if be.datasheets:
                    pdf.add_heading("Datenblätter", level=4)
                    for ds in be.datasheets:
                        if ds.startswith("http://") or ds.startswith("https://"):
                            pdf.add_link(ds, ds)
                        else:
                            pdf.add_paragraph(f"  {ds}")

                # ── Funktionen / GA-Zuordnungen ─────────────────────────────
                if be.function_assignments:
                    # Wizard-generierte Zuordnungen (Excel-Reihenfolge: Taste·Kanal·Funktion·GA-Bez·GA-Adr·DPT)
                    pdf.add_heading("Funktionszuordnungen", level=4)
                    fa_rows = []
                    for fa in be.function_assignments:
                        ga_obj = ga_by_designation.get(fa.function_ga.strip())
                        taste, kanal = _split_button_channel(fa.button_channel)
                        fa_rows.append([
                            taste or "-",
                            kanal,
                            fa.description or "-",
                            fa.function_ga or "-",
                            ga_obj.address if ga_obj else "",
                            ga_obj.datapoint_type if ga_obj else "",
                        ])
                    pdf.add_table(
                        ["Taste", "Kanal", "Funktion", "GA-Bezeichnung", "GA-Adresse", "DPT"],
                        fa_rows,
                    )
                elif device and any(co.connected_gas for co in device.communication_objects):
                    # ETS6-Import: COs expandieren, sortiert nach KO-Nr.
                    pdf.add_heading("Kommunikationsobjekte / GA-Verknüpfungen (ETS6-Import)", level=4)
                    co_rows = []
                    sorted_cos = sorted(device.communication_objects, key=lambda c: c.object_number)
                    for co in sorted_cos:
                        if not co.connected_gas:
                            continue
                        # Fix 1: mehrere GAs pro KO in einer Zeile zusammenfassen
                        ga_designations, ga_addresses = [], []
                        for ga_addr in co.connected_gas:
                            ga_obj = ga_by_address.get(ga_addr)
                            ga_designations.append(ga_obj.designation if ga_obj else ga_addr)
                            ga_addresses.append(ga_addr)
                        co_rows.append([
                            str(co.object_number),
                            co.name or f"KO {co.object_number}",
                            co.object_function,
                            " · ".join(ga_designations),
                            " · ".join(ga_addresses),
                            co.data_type,
                        ])
                    if co_rows:
                        # Fix 4: Name breiter (100 pt), GA-Adresse breiter (85 pt)
                        # Summe = 495 pt; Funktion + GA-Bezeichnung dürfen kürzen
                        pdf.add_table(
                            ["KO-Nr.", "Name", "Funktion", "GA-Bezeichnung", "GA-Adresse", "DPT"],
                            co_rows,
                            col_widths=[32, 100, 75, 155, 85, 48],
                        )
                else:
                    pdf.add_paragraph("  (keine Funktionszuordnungen)")

                pdf.add_separator()

        if not has_any:
            pdf.add_paragraph("Keine Bedienelemente im Projekt vorhanden.")

        pdf.save(filepath)
        logger.info(f"Bedienelemente-Bericht erstellt: {filepath}")

    def generate_aktoren_gateway_report(self, filepath: str):
        """Erzeugt einen Aktoren-und-Gateways-Bericht als PDF (Gerätekarten-Layout)."""
        pdf = self._make_pdf("Aktoren und Gateways")

        pdf.add_heading("Aktoren und Gateways", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        ga_by_address = {ga.address: ga for ga in self.project.group_addresses.all_addresses()}

        target_types = {"actor", "gateway"}
        entries: list[tuple] = []
        for area in self.project.topology.areas:
            for line in area.lines:
                for dev in line.devices:
                    if dev.device_type in target_types:
                        entries.append((area, line, dev))

        def _addr_key(entry):
            try:
                return tuple(int(p) for p in entry[2].physical_address.split("."))
            except ValueError:
                return (0, 0, 0)

        entries.sort(key=_addr_key)

        # ── Übersichtstabelle ────────────────────────────────────────────────
        summary_rows = []
        for area, line, dev in entries:
            summary_rows.append([
                dev.physical_address,
                dev.device_type,
                dev.product or "–",
                dev.manufacturer or "–",
                dev.order_number or "–",
                dev.serial_number or "–",
                dev.installation_location or "–",
            ])
        if summary_rows:
            pdf.add_table(
                ["Phys. Adresse", "Typ", "Produkt", "Hersteller", "Best.-Nr.", "Seriennummer", "Einbauort"],
                summary_rows,
            )
            pdf.add_separator()

        # ── Gerätekarten ────────────────────────────────────────────────────
        has_any = False
        for area, line, dev in entries:
            has_any = True
            pdf.add_conditional_break(min_height=150)

            loc = dev.installation_location or f"Bereich {area.area_number} / Linie {line.line_number}"
            heading = f"{dev.product or dev.device_type}  [{dev.physical_address}]  |  {loc}"
            pdf.add_heading(heading, level=3)

            info_rows: list[list[str]] = []
            if dev.manufacturer:
                info_rows.append(["Hersteller", dev.manufacturer])
            if dev.product:
                info_rows.append(["Produkt", dev.product])
            if dev.order_number:
                info_rows.append(["Bestellnummer", dev.order_number])
            if dev.serial_number:
                info_rows.append(["Seriennummer", dev.serial_number])
            if dev.application_program:
                info_rows.append(["Applikationsprogramm", dev.application_program])
            info_rows.append(["Phys. Adresse", dev.physical_address])
            info_rows.append(["Linie", f"{area.name} / {line.name} ({line.coupler_address})"])
            if dev.installation_location:
                info_rows.append(["Einbauort", dev.installation_location])
            info_rows.append(["Gerätetyp", dev.device_type])

            if info_rows:
                pdf.add_table(["Eigenschaft", "Wert"], info_rows)

            if dev.datasheets:
                pdf.add_heading("Datenblätter", level=4)
                for ds in dev.datasheets:
                    if ds.startswith("http://") or ds.startswith("https://"):
                        pdf.add_link(ds, ds)
                    else:
                        pdf.add_paragraph(f"  {ds}")

            cos_with_ga = [co for co in sorted(dev.communication_objects, key=lambda c: c.object_number)
                           if co.connected_gas]
            if cos_with_ga:
                pdf.add_heading("Kommunikationsobjekte / GA-Verknüpfungen", level=4)
                co_rows = []
                for co in cos_with_ga:
                    ga_designations, ga_addresses = [], []
                    for ga_addr in co.connected_gas:
                        ga_obj = ga_by_address.get(ga_addr)
                        ga_designations.append(ga_obj.designation if ga_obj else ga_addr)
                        ga_addresses.append(ga_addr)
                    co_rows.append([
                        str(co.object_number),
                        co.name or f"KO {co.object_number}",
                        co.object_function,
                        " · ".join(ga_designations),
                        " · ".join(ga_addresses),
                        co.data_type,
                    ])
                pdf.add_table(
                    ["KO-Nr.", "Name", "Funktion", "GA-Bezeichnung", "GA-Adresse", "DPT"],
                    co_rows,
                    col_widths=[32, 100, 75, 155, 85, 48],
                )
            else:
                pdf.add_paragraph("  (keine GA-Verknüpfungen)")

            pdf.add_separator()

        if not has_any:
            pdf.add_paragraph("Keine Aktoren oder Gateways im Projekt vorhanden.")

        pdf.save(filepath)
        logger.info(f"Aktoren-und-Gateways-Bericht erstellt: {filepath}")
