"""
Bericht-Service (FA-050, FA-600)
Erzeugt Validierungsberichte, GA-Listen und Projektuebersichten als PDF/Text.
"""
from __future__ import annotations
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime

from ..models.project import KnxProject
from ..models.building import Bedienelement
from ..models.topology import is_power_supply_product
from ..models.scene import Scene, SceneAction
from ..models.group_address import GroupAddressStructure, MIDDLE_GROUP_NAMES_A, MIDDLE_GROUP_NAMES_B
from ..services.validation_engine import ValidationEngine, ValidationIssue
from ..services.belegungsplan_service import (
    _split_button_channel, _extract_channel_label, group_actor_rows_by_channel,
    BelegungsplanService, build_ga_by_designation, _lookup_ga_by_function_ga,
)
from ..services.dpt_suggestion import dpt_number
from ..services.scene_addressing import (
    scene_group_key, scene_channel_designation, build_scope_label_lookup,
    scene_target_designation,
)
from ..services.co_linking_service import CoLinkingService
from ..services.channel_count_service import count_controlled_elements
from ..services.naming_engine import NamingEngine
from ..services.report_sorting import (
    group_address_key, physical_address_key, room_order, sorted_rooms,
)
from ..utils.pdf_generator import (
    PdfGenerator, PageRef, ACCENT_ERROR, ACCENT_WARNING, ACCENT_INFO,
)

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


# ── Validierungsbericht ──────────────────────────────────────────────────────

VALIDATION_LEVELS = [
    ("error", "Fehler", ACCENT_ERROR),
    ("warning", "Warnungen", ACCENT_WARNING),
    ("info", "Hinweise", ACCENT_INFO),
]
VALIDATION_LEVEL_SINGULAR = {"error": "Fehler", "warning": "Warnung", "info": "Hinweis"}

# Regel -> (Titel, Bedeutung, Massnahme)
VALIDATION_RULES = {
    "GA-08": (
        "Systemadresse 0/0/0 belegt",
        "0/0/0 ist für KNX-Systemmeldungen reserviert.",
        "Adresse auf 0/0/1 oder höher verschieben.",
    ),
    "FA-601": (
        "Ungültige Gruppenadresse",
        "Die Adresse liegt ausserhalb des zulässigen Bereichs (HG 0–31, MG 0–7, UG 0–255).",
        "Adresse korrigieren.",
    ),
    "FA-602": (
        "Doppelte Gruppenadresse",
        "Zwei Gruppenadressen verwenden dieselbe Adresse.",
        "Eine der beiden Adressen ändern.",
    ),
    "FA-603": (
        "Unerwarteter Datenpunkttyp",
        "Der DPT passt nicht zur Funktion der Gruppenadresse.",
        "DPT auf den Soll-Wert ändern oder die Funktion prüfen.",
    ),
    "FA-604": (
        "Fehlender Datenpunkttyp",
        "Ohne DPT kann die ETS Kommunikationsobjekte nicht sicher zuordnen "
        "und Visualisierungen zeigen Werte falsch an.",
        "DPT in der ETS bzw. in der GA-Ansicht ergänzen. Der DPT-Vorschlag ist "
        "aus der Bezeichnung abgeleitet und vor der Übernahme zu prüfen; "
        "ohne eindeutigen Hinweis bleibt die Spalte leer.",
    ),
    "FA-605": (
        "Lücken im Adressblock",
        "Zwischen belegten Adressen einer Mittelgruppe sind Adressen frei.",
        "Keine, sofern die Lücken als Reserve gewollt sind.",
    ),
    "FA-607": (
        "Gewerk in falscher Mittelgruppe",
        "Die Gruppenadresse liegt nicht in der Mittelgruppe, die der "
        "Gewerk-Katalog für dieses Gewerk vorsieht.",
        "GA in die Soll-Mittelgruppe verschieben oder das Gewerk korrigieren.",
    ),
    "FA-608": (
        "Fehlende Rückmelde-Mittelgruppe",
        "In Variante B gehören Rückmeldungen in eine eigene Mittelgruppe "
        "(Licht MG 6, Jalousie MG 7).",
        "",
    ),
    "FA-610": (
        "Bezeichnung nicht KNX-Swiss-konform",
        "Erwartetes Format: GEWERK_RAUM_NR FUNKTION (Klartext).",
        "Bei importierten Projekten mit eigenem Namensschema kann dieser "
        "Hinweis ignoriert werden.",
    ),
    "FA-3308b": (
        "Astro-Gruppenadressen fehlen",
        "Zeitprogramme mit Astro-Schaltpunkten benötigen die Astro-GAs in HG 0 / MG 7.",
        "",
    ),
}

FA610_EXAMPLES = 20


def _rule_title(rule_id: str) -> str:
    return VALIDATION_RULES.get(rule_id, (rule_id,))[0]


def _rule_sort_key(rule_id: str) -> tuple:
    """GA-08 vor FA-6xx, danach numerisch (FA-604 vor FA-3308b)."""
    import re
    m = re.search(r"(\d+)", rule_id)
    return (not rule_id.startswith("GA"), int(m.group(1)) if m else 0, rule_id)


def _clean(text: str) -> str:
    """Mehrfach-Leerzeichen aus importierten Bezeichnungen entfernen."""
    return " ".join((text or "").split()) or "–"


def _gap_range(issue: ValidationIssue) -> tuple[str, str]:
    start, end = issue.details.get("start"), issue.details.get("end")
    if start is None:
        return issue.message, ""
    text = str(start) if start == end else f"{start}–{end}"
    return text, str(end - start + 1)


# ── Topologie-Bericht ────────────────────────────────────────────────────────

TOPOLOGY_TYPE_LABELS = {
    "actor": "Aktor", "sensor": "Sensor", "gateway": "Gateway",
    "coupler": "Koppler", "power_supply": "Spannungsversorgung",
}
TOPOLOGY_TYPE_ORDER = ["Aktor", "Sensor", "Gateway", "Koppler",
                       "Spannungsversorgung", "Sonstiges"]
TOPOLOGY_TYPE_PLURAL = {
    "Aktor": "Aktoren", "Sensor": "Sensoren", "Gateway": "Gateways",
    "Koppler": "Koppler", "Spannungsversorgung": "Spannungsversorgungen",
    "Sonstiges": "Weitere",
}
# Einbauorte, die ein Verteiler/Schaltschrank sind (im Bericht zuerst)
_DISTRIBUTION_RE = re.compile(
    r"^(UV|HV|HzV|NV|EV|UVS|Verteiler|Schaltschrank|Tableau|Unterverteil)",
    re.IGNORECASE)


def _n_devices(n: int) -> str:
    return f"{n} Gerät" if n == 1 else f"{n} Geräte"


def _device_type_label(device) -> str:
    if device.device_type == "power_supply" or is_power_supply_product(device.product):
        return "Spannungsversorgung"
    return TOPOLOGY_TYPE_LABELS.get(device.device_type, "Sonstiges")


def _has_coupler(lines, address: str) -> bool:
    """True, wenn auf der Adresse ein Koppler als Gerät vorhanden ist.
    Line.coupler_address allein genügt nicht: der Import setzt dort immer
    B.L.0, auch für Linien ohne Koppler (z.B. Linie 1.1 im Chalet)."""
    return any(
        d.device_type == "coupler" and d.physical_address == address
        for line in lines for d in line.devices
    )


def _line_coupler(area, line) -> str:
    address = f"{area.area_number}.{line.line_number}.0"
    return address if _has_coupler([line], address) else ""


def _device_cell(device) -> tuple[str, str]:
    """(Produkt, 'Hersteller · Best.-Nr. · SN …') für eine Tabellenzelle."""
    details = [p for p in (
        device.manufacturer,
        device.order_number,
        f"SN {device.serial_number}" if device.serial_number else "",
    ) if p]
    return (device.product or "–", " · ".join(details))


def _clean_location(text: str) -> str:
    """'UV2   ( Steigzone )' -> 'UV2 (Steigzone)'."""
    text = " ".join((text or "").split())
    return re.sub(r"\s*\)", ")", re.sub(r"\(\s*", "(", text))


def _location_sort_key(location: str) -> tuple:
    if not location:
        return (2, "")
    return (0 if _DISTRIBUTION_RE.match(location) else 1, location.lower())


# ── Bedienelemente-Bericht ───────────────────────────────────────────────────

_GA_PREFIX_RE = re.compile(r"^(\d+/\d+/\d+)\s")


def _ga_line(ga) -> str:
    """'3/1/40  J.OG.04.02_move (Fenster) · 1.008' für eine Tabellenzeile."""
    if isinstance(ga, str):
        return " ".join(ga.split())
    text = f"{ga.address}  {' '.join((ga.designation or '').split())}"
    text = re.sub(r"\(\s*", "(", re.sub(r"\s*\)", ")", text))
    if ga.datapoint_type:
        text += f" · {dpt_number(ga.datapoint_type)}"
    return text


def _validation_table_layout(rule_id: str):
    """(Kopfzeile, Spaltenanteile, Ausrichtung, Zeilenfunktion) je Regel."""
    if rule_id == "FA-604":
        return (["Adresse", "Bezeichnung", "DPT-Vorschlag"], [0.13, 0.55, 0.32], None,
                lambda i: [i.address, _clean(i.designation), i.details.get("dpt") or ""])
    if rule_id == "FA-603":
        return (["Adresse", "Bezeichnung", "Ist-DPT", "Soll-DPT"],
                [0.13, 0.47, 0.20, 0.20], None,
                lambda i: [i.address, _clean(i.designation),
                           i.details.get("actual", ""), i.details.get("expected", "")])
    if rule_id == "FA-605":
        def gap_row(i):
            rng, n = _gap_range(i)
            return [i.details.get("mg", ""), rng, n]
        return (["Mittelgruppe", "Freie Adressen", "Anzahl"], [0.25, 0.55, 0.20],
                ["left", "left", "right"], gap_row)
    if rule_id == "FA-607":
        return (["Adresse", "Bezeichnung", "Gewerk", "Ist-MG", "Soll-MG"],
                [0.13, 0.51, 0.12, 0.12, 0.12], ["left", "left", "left", "right", "right"],
                lambda i: [i.address, _clean(i.designation), i.details.get("gewerk", ""),
                           str(i.details.get("actual", "")), str(i.details.get("expected", ""))])
    if rule_id == "FA-602":
        return (["Adresse", "Bezeichnung", "Kollidiert mit"], [0.13, 0.435, 0.435], None,
                lambda i: [i.address, _clean(i.designation), _clean(i.details.get("other", ""))])
    if rule_id == "FA-610":
        return (["Adresse", "Bezeichnung"], [0.13, 0.87], None,
                lambda i: [i.address, _clean(i.designation)])
    return (["Adresse", "Beschreibung", "Massnahme"], [0.13, 0.52, 0.35], None,
            lambda i: [i.address or "–", i.message, i.suggestion or ""])




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
        """Erzeugt den Validierungsbericht Gruppenadressen als PDF/Text (FA-600).

        Je Stufe (Fehler, Warnungen, Hinweise) ein Abschnitt mit farbigem
        Randbalken, darin je Regel ein Block mit Erläuterung, Massnahme und
        einer Tabelle mit regelspezifischen Spalten.
        """
        engine = ValidationEngine(self.project.gewerk_catalog)
        issues = engine.validate(self.project.group_addresses, project=self.project)

        title = "Validierungsbericht Gruppenadressen"
        pdf = self._make_pdf(title)

        pdf.add_heading(title, level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Variante: {self.project.config.mg_variant} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        by_level: dict[str, dict[str, list[ValidationIssue]]] = {
            "error": defaultdict(list), "warning": defaultdict(list), "info": defaultdict(list),
        }
        for issue in issues:
            by_level.setdefault(issue.level, defaultdict(list))[issue.rule_id].append(issue)

        def count(level: str) -> int:
            return sum(len(v) for v in by_level[level].values())

        # Zusammenfassung
        ga_count = len(self.project.group_addresses.all_addresses())
        pdf.add_heading("Zusammenfassung", level=2)
        pdf.add_paragraph(f"Geprüfte Gruppenadressen: {ga_count}")
        pdf.add_paragraph(f"Fehler: {count('error')}")
        pdf.add_paragraph(f"Warnungen: {count('warning')}")
        pdf.add_paragraph(f"Hinweise: {count('info')}")

        if issues:
            overview = []
            for level, _label, _accent in VALIDATION_LEVELS:
                for rule_id in sorted(by_level[level], key=_rule_sort_key):
                    overview.append([
                        VALIDATION_LEVEL_SINGULAR[level], rule_id,
                        _rule_title(rule_id), str(len(by_level[level][rule_id])),
                    ])
            pdf.add_heading("Übersicht nach Regel", level=3)
            pdf.add_table(["Stufe", "Regel", "Beschreibung", "Anzahl"], overview,
                          col_widths=[0.14, 0.14, 0.58, 0.14],
                          align=["left", "left", "left", "right"])
        else:
            pdf.add_paragraph("Keine Probleme gefunden. Alle Prüfungen bestanden.")

        for level, label, accent in VALIDATION_LEVELS:
            rules = by_level[level]
            if not rules:
                continue
            pdf.add_heading(label, level=2, accent=accent)
            for rule_id in sorted(rules, key=_rule_sort_key):
                self._add_validation_rule_block(pdf, rule_id, rules[rule_id], ga_count)

        pdf.save(filepath)
        logger.info(f"Validierungsbericht erstellt: {filepath}")
        return issues

    def _add_validation_rule_block(self, pdf: PdfGenerator, rule_id: str,
                                   rule_issues: list[ValidationIssue],
                                   ga_count: int) -> None:
        """Ein Regel-Block: Überschrift, Erläuterung, Massnahme, Tabelle."""
        meaning, action = VALIDATION_RULES.get(rule_id, ("", "", ""))[1:]
        pdf.add_heading(f"{rule_id}  {_rule_title(rule_id)}  ({len(rule_issues)})", level=3)
        if meaning:
            pdf.add_note("Bedeutung:", meaning)
        if action:
            pdf.add_note("Massnahme:", action)

        if rule_id == "FA-605":
            ordered = sorted(rule_issues, key=lambda i: (
                group_address_key(i.details.get("mg", "") + "/0"), i.details.get("start", 0)))
        else:
            ordered = sorted(rule_issues, key=lambda i: group_address_key(i.address))

        # Sehr viele Bezeichnungs-Hinweise (typisch bei Import mit eigenem
        # Namensschema): nur Beispiele statt Einzelliste
        if rule_id == "FA-610" and len(ordered) > FA610_EXAMPLES \
                and len(ordered) > ga_count * 0.5:
            pct = round(100 * len(ordered) / ga_count) if ga_count else 100
            pdf.add_paragraph(
                f"{len(ordered)} von {ga_count} Bezeichnungen ({pct} %) weichen vom "
                f"KNX-Swiss-Format ab. Das deutet auf ein eigenes Namensschema hin; "
                f"aufgeführt sind die ersten {FA610_EXAMPLES} Beispiele."
            )
            ordered = ordered[:FA610_EXAMPLES]

        headers, widths, align, row_fn = _validation_table_layout(rule_id)
        pdf.add_table(headers, [row_fn(i) for i in ordered],
                      col_widths=widths, align=align)

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
        all_gas = structure.all_addresses()
        total_gas = len(all_gas)
        placeholders = sum(1 for ga in all_gas if ga.is_placeholder)
        # Über die Hauptgruppe zählen: das central-Flag setzt nur der Wizard,
        # importierte Projekte haben es nie.
        central = sum(1 for ga in all_gas if ga.main_group == 0)

        pdf.add_heading("Statistik", level=2)
        pdf.add_paragraph(f"Gruppenadressen gesamt: {total_gas}")
        pdf.add_paragraph(f"davon belegt: {total_gas - placeholders}")
        pdf.add_paragraph(
            f"davon Reserve (für Erweiterungen freigehalten): {placeholders}")
        pdf.add_paragraph(f"Zentraladressen (HG 0): {central}")
        pdf.add_separator()

        # Pro Hauptgruppe
        for hg in sorted(structure.main_groups, key=lambda h: h.number):
            hg_gas = sum(len(mg.group_addresses) for mg in hg.middle_groups)
            pdf.add_heading(f"HG {hg.number}: {hg.name} ({hg_gas} GAs)", level=2)

            for mg in sorted(hg.middle_groups, key=lambda m: m.number):
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

        pdf = self._make_pdf("Räume nach Gewerken")
        pdf.add_heading("Räume nach Gewerken", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        has_any = False
        for room in sorted_rooms(self.project.areal):
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

        # Importierte Projekte: gesteuerte Elemente aus der Topologie statt
        # der (oft nur aus GA-Bezeichnungen geratenen) Schritt-5-Anzahlen
        controlled = count_controlled_elements(p)
        if controlled:
            gewerk_counts.update(controlled.totals())

        if gewerk_counts:
            headers = ["Code", "Bezeichnung", "Anzahl Elemente"]
            rows = []
            for code, count in sorted(gewerk_counts.items()):
                gewerk = self.project.gewerk_catalog.get(code)
                name = gewerk.name if gewerk else "-"
                rows.append([code, name, str(count)])
            pdf.add_table(headers, rows, col_widths=[0.15, 0.60, 0.25],
                          align=["left", "left", "right"])
            if controlled:
                pdf.add_note(
                    "Zählweise:",
                    "Gewerke mit Aktoren oder Gateways: Anzahl der gesteuerten "
                    "Elemente laut Topologie. Übrige Gewerke: Anzahl aus der "
                    "Gewerk-Zuweisung (Wizard Schritt 5).")

        pdf.save(filepath)
        logger.info(f"Projektzusammenfassung erstellt: {filepath}")

    def generate_topology_report(self, filepath: str):
        """Erzeugt den Topologie-Bericht als PDF/Text.

        Aufbau: Prinzipschema (Bereiche/Linien mit Auslastung), Kennzahlen je
        Linie, Geräteliste je Linie, Geräteliste je Einbauort (Verteiler
        zuerst). Gerätezellen zeigen Hersteller, Bestell- und Seriennummer
        als zweite Zeile.
        """
        pdf = self._make_pdf("Topologie-Bericht")
        topo = self.project.topology

        pdf.add_heading("Topologie-Bericht", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Topologie: {topo.topology_mode} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        areas = [
            (area, sorted((l for l in area.lines if l.devices), key=lambda l: l.line_number))
            for area in sorted(topo.areas, key=lambda a: a.area_number)
        ]
        areas = [(area, lines) for area, lines in areas if lines]
        if not areas:
            pdf.add_paragraph("Die Topologie enthält keine Geräte.")
            pdf.save(filepath)
            logger.info(f"Topologie-Bericht erstellt: {filepath}")
            return

        max_devices = topo.max_devices_per_line
        multi_area = len(areas) > 1

        def line_label(area, line) -> str:
            label = f"Linie {area.area_number}.{line.line_number}"
            if line.name and line.name != f"Linie {line.line_number}":
                label += f": {line.name}"
            return label

        # ── Übersicht: Prinzipschema und Kennzahlen ─────────────────────────
        pdf.add_heading("Übersicht", level=2)
        schema = []
        kpi_rows = []
        for area, lines in areas:
            info = " · ".join(p for p in (
                f"Backbone {area.backbone_type}" if area.backbone_type else "",
                f"Koppler {area.area_number}.0.0"
                if _has_coupler(area.lines, f"{area.area_number}.0.0") else "",
            ) if p)
            schema_lines = []
            for line in lines:
                counts = Counter(_device_type_label(d) for d in line.devices)
                bus_devices = len(line.devices) - counts.get("Spannungsversorgung", 0)
                stats = [(TOPOLOGY_TYPE_PLURAL[t], counts[t])
                         for t in TOPOLOGY_TYPE_ORDER if counts.get(t)]
                schema_lines.append({
                    "title": line_label(area, line),
                    "coupler": _line_coupler(area, line),
                    "count": bus_devices,
                    "max": max_devices,
                    "stats": stats,
                })
                kpi_rows.append([
                    line_label(area, line),
                    _line_coupler(area, line) or "–",
                    f"{bus_devices} / {max_devices}",
                    str(counts.get("Aktor", 0)),
                    str(counts.get("Sensor", 0)),
                    str(counts.get("Gateway", 0)),
                    str(sum(n for t, n in counts.items()
                            if t not in ("Aktor", "Sensor", "Gateway"))),
                ])
            schema.append({
                "title": f"Bereich {area.area_number}"
                         + (f": {area.name}" if area.name
                            and area.name != f"Bereich {area.area_number}" else ""),
                "info": info,
                "lines": schema_lines,
            })
        pdf.add_topology_schema(schema)
        pdf.add_table(
            ["Linie", "Koppler", "Geräte", "Aktoren", "Sensoren", "Gateways", "Weitere"],
            kpi_rows,
            col_widths=[0.25, 0.13, 0.14, 0.12, 0.12, 0.12, 0.12],
            align=["left", "left", "right", "right", "right", "right", "right"],
        )
        pdf.add_note(
            "Weitere:",
            "Koppler, Spannungsversorgungen und sonstige Geräte. Geräte und "
            f"Auslastung zählen Busteilnehmer (ohne Spannungsversorgungen), bezogen "
            f"auf {max_devices} je Linie ({topo.topology_mode}).")

        # ── Geräte nach Linie ────────────────────────────────────────────────
        widths = [0.10, 0.47, 0.20, 0.23]
        headers = ["Adresse", "Gerät", "Typ", "Einbauort"]
        pdf.add_page_break()
        pdf.add_heading("Geräte nach Linie", level=2)
        for area, lines in areas:
            for line in lines:
                title = line_label(area, line)
                if multi_area and area.name:
                    title = f"{area.name} – {title}"
                parts = [_n_devices(len(line.devices))]
                if _line_coupler(area, line):
                    parts.append(f"Koppler {_line_coupler(area, line)}")
                pdf.add_heading(f"{title}  ({', '.join(parts)})", level=3)
                rows = [
                    [d.physical_address, _device_cell(d), _device_type_label(d),
                     _clean_location(d.installation_location) or "–"]
                    for d in sorted(line.devices,
                                    key=lambda d: physical_address_key(d.physical_address))
                ]
                pdf.add_table(headers, rows, col_widths=widths)

        # ── Geräte nach Einbauort ────────────────────────────────────────────
        by_location: dict[str, list] = defaultdict(list)
        for _area, lines in areas:
            for line in lines:
                for d in line.devices:
                    by_location[_clean_location(d.installation_location)].append(d)

        pdf.add_page_break()
        pdf.add_heading("Geräte nach Einbauort", level=2)
        pdf.add_note(
            "Reihenfolge:",
            "Verteiler zuerst, danach die übrigen Einbauorte alphabetisch, "
            "Geräte ohne Angabe zuletzt.")
        for location in sorted(by_location, key=_location_sort_key):
            devices = sorted(by_location[location],
                             key=lambda d: physical_address_key(d.physical_address))
            pdf.add_heading(f"{location or 'Ohne Angabe'}  ({_n_devices(len(devices))})", level=3)
            pdf.add_table(
                ["Adresse", "Gerät", "Typ"],
                [[d.physical_address, _device_cell(d), _device_type_label(d)]
                 for d in devices],
                col_widths=[0.11, 0.69, 0.20],
            )

        pdf.save(filepath)
        logger.info(f"Topologie-Bericht erstellt: {filepath}")

    def generate_bedienelemente_report(self, filepath: str):
        """Erzeugt den Bericht "Bedienelemente und Sensoren" als PDF.

        Gegliedert wie man im Gebäude sucht: Übersicht mit Seitenzahlen,
        danach je Stockwerk und Raum (jeder Raum auf neuer Seite) zuerst die
        Bedienelemente (vom Bauherrn bedienbar, siehe OPERABLE_ELEMENT_TYPES)
        als Gerätekarten mit Tastenplan (Gewerk/Szene je Taste) und einer
        Zeile je Taste, danach kompakt die Sensoren des Raums.
        PDF-Lesezeichen: Stockwerk → Raum → Gerät.
        """
        from .sensor_service import project_for_export
        from .bedienelement_layout import (
            group_assignments, button_plan, row_function_label,
        )
        # FA-1404: Physikalische Adressen aus Topologie sicherstellen – auf einer
        # Kopie, damit auch alte gespeicherte Projekte korrekte Adressen erhalten,
        # ohne dass der Bericht das Projekt selbst verändert.
        project = project_for_export(self.project)
        catalog = project.gewerk_catalog
        title = "Bedienelemente und Sensoren"
        pdf = self._make_pdf(title)

        pdf.add_heading(title, level=1)
        pdf.add_paragraph(
            f"Projekt: {project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        # ── Lookup-Strukturen ────────────────────────────────────────────────
        ga_by_address = {ga.address: ga for ga in project.group_addresses.all_addresses()}
        ga_index = build_ga_by_designation(project.group_addresses)

        def resolve(function_ga: str):
            text = (function_ga or "").strip()
            m = _GA_PREFIX_RE.match(text)
            if m and m.group(1) in ga_by_address:
                return ga_by_address[m.group(1)]
            return _lookup_ga_by_function_ga(text, ga_index)

        device_by_addr = {
            d.physical_address: d
            for area in project.topology.areas
            for line in area.lines
            for d in line.devices
        }
        floor_by_room: dict[str, str] = {}
        zone_by_room: dict[str, str] = {}
        for building in project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            floor_by_room[room.id] = floor.name
                            zone_by_room[room.id] = apt.name

        def room_label(room) -> str:
            parts = [zone_by_room.get(room.id, ""), f"{room.number} {room.name}".strip()]
            return " · ".join(_clean_location(p) for p in parts if p)

        # Sensoren aus der Topologie, die einem Raum zugeordnet, aber nicht als
        # Bedienelement erfasst sind (z.B. nach ETS-Import), gehören auch dazu
        from .knxproj_import_service import KnxprojImportService
        known = {be.participant_number for r in project.all_rooms
                 for be in r.bedienelemente if be.participant_number}
        extra_by_room: dict[str, list] = defaultdict(list)
        for device in device_by_addr.values():
            if (device.device_type == "sensor" and device.room_id
                    and device.physical_address not in known):
                extra_by_room[device.room_id].append(Bedienelement(
                    element_type=KnxprojImportService._infer_element_type(
                        device.product or "", device.communication_objects),
                    participant_number=device.physical_address,
                    product_name=device.product_name or device.product,
                    manufacturer=device.manufacturer,
                    order_number=device.order_number,
                ))

        entries = []
        for room in sorted_rooms(project.areal):
            imported = project.topology.is_imported
            bes = [be for be in room.bedienelemente if be.is_shown(imported)]
            bes += extra_by_room.get(room.id, [])
            if bes:
                entries.append((room, sorted(bes, key=lambda be: (
                    not be.is_operable, physical_address_key(be.participant_number)))))
        if not entries:
            pdf.add_paragraph("Keine Bedienelemente im Projekt vorhanden.")
            pdf.save(filepath)
            logger.info(f"Bedienelemente-Bericht erstellt: {filepath}")
            return

        def device_info(be):
            # Live-Daten aus dem verknüpften Device haben Vorrang vor be.*,
            # da be.product_name/manufacturer/order_number nur einmalig beim
            # Anlegen des Bedienelements aus dem Device kopiert werden
            # (siehe _create_bedienelemente_from_topology) und bei einer
            # späteren Produktzuweisung über die Materialliste (die nur ins
            # Device zurückschreibt) sonst veraltet blieben.
            device = device_by_addr.get(be.participant_number or "")
            product = ((device.product_name if device else "") or be.product_name
                       or (device.product if device else ""))
            mfr = (device.manufacturer if device else "") or be.manufacturer
            ordernr = (device.order_number if device else "") or be.order_number
            location = _clean_location(device.installation_location) if device else ""
            return device, product, mfr, ordernr, location

        # ── Übersicht ────────────────────────────────────────────────────────
        pdf.add_heading("Übersicht", level=2)
        overview = []
        for room, bes in entries:
            floor = floor_by_room.get(room.id, "")
            for be in bes:
                _device, product, _mfr, _nr, _loc = device_info(be)
                overview.append([
                    " · ".join(p for p in (floor, room_label(room)) if p),
                    be.participant_number or "–",
                    be.element_type or "Bedienelement",
                    product or "–",
                    PageRef(be.id),
                ])
        pdf.add_table(["Stockwerk · Raum", "Adresse", "Typ", "Produkt", "Seite"],
                      overview, col_widths=[0.27, 0.10, 0.16, 0.39, 0.08],
                      align=["left", "left", "left", "left", "right"])
        pdf.add_note("Hinweis:", "Das PDF enthält Lesezeichen nach Stockwerk, Raum "
                                 "und Gerät. Jeder Raum beginnt auf einer neuen Seite.")

        # ── Stockwerk → Raum → Gerät ─────────────────────────────────────────
        current_floor = None
        for room, bes in entries:
            pdf.add_page_break()
            floor = floor_by_room.get(room.id, "") or "Ohne Stockwerk"
            if floor != current_floor:
                pdf.add_heading(floor, level=2)
                current_floor = floor
            pdf.add_heading(room_label(room), level=3)

            for be in (b for b in bes if b.is_operable):
                device, product, mfr, ordernr, location = device_info(be)
                rows = (group_assignments(be.function_assignments, resolve)
                        if be.function_assignments else [])
                plan = button_plan(rows, catalog, room.name)
                # Karte (Kopf, Tastenplan, Tabelle) möglichst auf einer Seite
                estimate = 50 + (len(plan) * 34 + 18 if plan else 0) + 24 + sum(
                    max(14, len(r.gas) * 10.5 + len(r.led_gas) * 9.5 + 2) for r in rows)
                pdf.add_conditional_break(min_height=min(estimate, 600))
                pdf.add_anchor(be.id)
                title = (f"{be.participant_number or 'Ohne Adresse'}  ·  "
                         f"{be.element_type or 'Bedienelement'}")
                details = [" · ".join(p for p in (mfr, product, ordernr) if p)]
                if location:
                    details.append(f"Einbauort: {location}")
                if not be.participant_number:
                    details.append("Nicht in der Topologie (keine physikalische Adresse)")
                pdf.add_card_header(title, "\n".join(d for d in details if d),
                                    bookmark=title)

                if be.function_assignments:
                    if plan:
                        pdf.add_button_plan(plan)
                    table = []
                    for row in rows:
                        if row.key is None:
                            function = row.name
                        else:
                            t, d = row_function_label(row, catalog, room.name)
                            function = " · ".join(p for p in (t, d) if p) or "–"
                        table.append([
                            row.key.label() if row.key else "Weitere",
                            (function, "mit LED-Rückmeldung" if row.led_gas else ""),
                            ("\n".join(_ga_line(g) for g in row.gas) or "–",
                             "\n".join("LED: " + _ga_line(g) for g in row.led_gas)),
                        ])
                    pdf.add_table(["Taste", "Funktion", "Gruppenadressen"], table,
                                  col_widths=[0.13, 0.30, 0.57])
                elif device and any(co.connected_gas for co in device.communication_objects):
                    table = []
                    for co in sorted(device.communication_objects, key=lambda c: c.object_number):
                        if not co.connected_gas:
                            continue
                        table.append([
                            str(co.object_number),
                            (co.name or f"KO {co.object_number}", co.object_function or ""),
                            "\n".join(_ga_line(ga_by_address.get(a) or a)
                                      for a in co.connected_gas),
                        ])
                    pdf.add_table(["KO", "Objekt", "Gruppenadressen"], table,
                                  col_widths=[0.08, 0.32, 0.60])
                else:
                    pdf.add_paragraph("Keine Funktionszuordnungen.")

                if be.datasheets:
                    for ds in be.datasheets:
                        if ds.startswith(("http://", "https://")):
                            pdf.add_link(ds, ds)
                        else:
                            pdf.add_note("Datenblatt:", ds)

            sensors = [b for b in bes if not b.is_operable]
            if sensors:
                pdf.add_conditional_break(min_height=90)
                pdf.add_heading("Sensoren", level=4)
                table = []
                for be in sensors:
                    pdf.add_anchor(be.id)
                    device, product, mfr, ordernr, location = device_info(be)
                    details = " · ".join(p for p in (
                        mfr, product, ordernr,
                        f"Einbauort {location}" if location else "") if p)
                    if be.function_assignments:
                        gas = [g for row in group_assignments(be.function_assignments, resolve)
                               for g in row.gas + row.led_gas]
                    elif device:
                        gas = [ga_by_address.get(a) or a
                               for co in sorted(device.communication_objects,
                                                key=lambda c: c.object_number)
                               for a in co.connected_gas]
                    else:
                        gas = []
                    table.append([
                        be.participant_number or "–",
                        (be.element_type or "Sensor", details),
                        "\n".join(dict.fromkeys(_ga_line(g) for g in gas)) or "–",
                    ])
                pdf.add_table(["Adresse", "Sensor", "Gruppenadressen"], table,
                              col_widths=[0.11, 0.37, 0.52])

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

        # Belegungsplan als primäre Quelle für die Kanal-Zuordnung: in
        # Wizard-Projekten (Gewerk-/GA-basiert) ist Device.communication_objects
        # meist leer -- BelegungsplanService liefert dort die einzige Quelle mit
        # korrekter Kanal-Zuordnung inkl. Gewerk-Kontext (siehe Topologie-Ansicht,
        # die dieselbe Logik nutzt).
        belegungsplan = BelegungsplanService().generate(self.project)
        actor_rows_by_addr: dict[str, list] = {}
        for r in belegungsplan.actor_rows:
            actor_rows_by_addr.setdefault(r.physical_address, []).append(r)

        target_types = {"actor", "gateway"}
        entries: list[tuple] = []
        for area in self.project.topology.areas:
            for line in area.lines:
                for dev in line.devices:
                    if dev.device_type in target_types:
                        entries.append((area, line, dev))

        entries.sort(key=lambda entry: physical_address_key(entry[2].physical_address))

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

            # Primär: Belegungsplan-Zeilen (Gewerk-/GA-basiert -- deckt auch
            # ETS6-Importe ohne Gewerk-Zuordnung ab, da _collect_actor_rows
            # dafür bereits selbst auf die COs zurückfällt). Nur echte
            # Gateways (kein "actor" in _collect_actor_rows) nutzen den
            # rohen CO-Fallback unten.
            actor_rows = actor_rows_by_addr.get(dev.physical_address, [])
            if actor_rows:
                pdf.add_heading("Kanäle / GA-Verknüpfungen", level=4)
                for ch_num, ch_rows in group_actor_rows_by_channel(actor_rows):
                    first = ch_rows[0]
                    context = " / ".join(p for p in [first.gewerk_code, first.room_name] if p)
                    label = f"Kanal {ch_num}" + (f" – {context}" if context else "")
                    pdf.add_heading(label, level=5)
                    ch_table_rows = [
                        [r.gewerk_code, r.function_name, r.ga_designation, r.ga_address, r.dpt]
                        for r in ch_rows
                    ]
                    pdf.add_table(
                        ["Gewerk", "Funktion", "GA-Bezeichnung", "GA-Adresse", "DPT"],
                        ch_table_rows,
                        col_widths=[40, 70, 190, 95, 100],
                    )
            else:
                cos_with_ga = [co for co in sorted(dev.communication_objects, key=lambda c: c.object_number)
                               if co.connected_gas]
                if cos_with_ga:
                    pdf.add_heading("Kommunikationsobjekte / GA-Verknüpfungen", level=4)

                    # Auf Kanäle aufteilen (ETS-Konvention im CO-Namen, z.B. "A, Schalten"
                    # oder "Kanal A"). Objekte ohne erkennbaren Kanal (geräteweite
                    # Status-/Szenenobjekte) werden ohne eigene Kanal-Überschrift zuerst gelistet.
                    channel_groups: dict[str, list] = {}
                    for co in cos_with_ga:
                        channel_groups.setdefault(_extract_channel_label(co.name), []).append(co)

                    for channel, cos in channel_groups.items():
                        if channel:
                            pdf.add_heading(channel, level=5)
                        co_rows = []
                        for co in cos:
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

    # Geltungsbereichs-Code (Scene.scope) -> Anzeigetext (siehe ui/views/scene_view.py
    # _SCOPE_LABELS -- hier bewusst dupliziert statt importiert, damit dieser
    # Service-Layer nicht von der UI-Schicht abhaengt).
    _SCENE_SCOPE_LABELS = {
        "room": "Raum",
        "apartment": "Wohnung/Zone",
        "zone": "Zone",
        "central": "Zentral",
    }

    def _scene_action_label(self, action: SceneAction) -> str:
        """Bauherren-lesbarer Text einer Szenen-Aktion, z.B. 'Wohnzimmer Licht E/A → Aus'."""
        raw = action.group_address.strip()
        parts = raw.split()
        text = " ".join(parts[1:]) if (parts and "/" in parts[0] and len(parts) > 1) else raw
        if action.value:
            text += f"  →  {action.value}"
        return text

    def _scene_action_categories(self, scene: Scene) -> set[str]:
        """Gewerk-Kategorien, die laut den Aktionen der Szene betroffen sind
        (unabhaengig davon, ob bereits ein Aktor real mit der Szenenaufruf-GA
        verknuepft ist) -- action.group_address ist entweder ein Kategorie-
        Schluessel aus einer Vorlage ("licht", "jalousie", ...) oder eine
        GA-Bezeichnung, aus der sich per NamingEngine der Gewerk-Code und
        darueber die Kategorie ableiten laesst."""
        categories: set[str] = set()
        for action in scene.actions:
            raw = action.group_address.strip()
            if not raw:
                continue
            key = raw.lower()
            if key in GEWERK_CATEGORY_LABELS:
                categories.add(key)
                continue
            code = NamingEngine.parse_designation(raw).get("gewerk_code", "")
            gewerk = self.project.gewerk_catalog.get(code) if code else None
            if gewerk and gewerk.category:
                categories.add(gewerk.category)
        return categories

    @staticmethod
    def _resolve_legacy_scene_id(sf, candidates: list) -> str:
        """Fallback fuer SensorFunktionen aus der Zeit vor scene_id (siehe
        _scene_trigger_buttons_index): 'candidates' sind alle Szenen, die sich
        denselben Szenenaufruf-Kanal (sf.ga_designation) teilen. Nur bei genau
        einer Szene auf dem Kanal ist die Zuordnung sicher eindeutig. Bewusst
        KEIN Text-Abgleich auf sf.label als Fallback bei mehreren Kandidaten:
        die Szenen eines Kanals teilen sich oft aehnlich klingende Namen
        (z.B. "Anwesend"/"Abwesend") -- ein falscher Treffer waere im
        Bauherren-Report eine stille, schwer bemerkbare Falschaussage, was
        schlimmer ist als eine fehlende Zeile. Mehrdeutige Faelle bleiben
        unaufgeloest; die Schritt-8-UI markiert sie zum manuellen Neusetzen."""
        if len(candidates) == 1:
            return candidates[0].id
        return ""

    def _scene_trigger_buttons_index(self) -> dict[str, list[str]]:
        """scene.id -> Liste Klartext-Bezeichnungen aller Taster/Bedienelemente,
        die diese Szene per SensorFunktion (bedienart='Szene abrufen', Schritt 8)
        aufrufen. Im Unterschied zu Scene.trigger (freies Notizfeld) ist das die
        tatsaechlich im Projekt konfigurierte Zuordnung -- erlaubt insbesondere
        mehrere Taster pro Szene, was ein einzelnes Freitextfeld nicht robust
        abbilden kann."""
        label_lookup = build_scope_label_lookup(self.project.areal)
        scenes_by_channel: dict[str, list] = {}
        for s in self.project.scenes:
            if not s.name or s.is_detected:
                continue
            designation = scene_target_designation(
                s, label_lookup, self.project.group_addresses
            )
            scenes_by_channel.setdefault(designation, []).append(s)

        index: dict[str, list[str]] = {}
        for room in self.project.all_rooms:
            for be in room.bedienelemente:
                if be.suppressed:
                    continue
                for sf in be.funktionen:
                    scene_id = sf.scene_id
                    if not scene_id and sf.bedienart == "Szene abrufen" and sf.ga_designation:
                        # Vor Einfuehrung von scene_id angelegte Zuweisung --
                        # bestmoeglich nachtraeglich aufloesen (siehe oben).
                        scene_id = self._resolve_legacy_scene_id(
                            sf, scenes_by_channel.get(sf.ga_designation, [])
                        )
                    if not scene_id:
                        continue
                    button = next(
                        (fa.button_channel for fa in be.function_assignments
                         if fa.sf_id == sf.id and fa.button_channel),
                        "",
                    )
                    addr = be.participant_number or "(keine Adresse)"
                    parts = [f"Raum {room.number} {room.name}", f"Taster {addr}"]
                    if button:
                        parts.append(button)
                    index.setdefault(scene_id, []).append(", ".join(parts))
        return index

    def _scene_target_ga(self, scene: Scene, label_lookup: dict):
        """Ermittelt die tatsaechlich generierte Szenenaufruf-GA einer Szene
        (None wenn Schritt 10 'Gruppenadressen generieren' noch nicht bzw.
        nicht erneut nach dieser Szenen-Aenderung gelaufen ist)."""
        all_gas = self.project.group_addresses.all_addresses()
        if scene.source_ga_addresses:   # erkannt oder an bestehende GA gebunden
            for addr in scene.source_ga_addresses:
                ga = next((g for g in all_gas if g.address == addr), None)
                if ga:
                    return ga
            return None
        scope_key = scene_group_key(scene)
        designation = scene_channel_designation(scope_key, label_lookup)
        return next(
            (g for g in all_gas if g.function_name == "SZENE" and g.designation == designation),
            None,
        )

    def _scene_sort_key(self):
        """Zentral, Zone, Wohnung, Raum; Raeume in Gebaeude-Reihenfolge,
        Wohnungen/Zonen nach Name; darin nach Szenennummer. Vorher wurde nach
        der internen Raum-ID sortiert -- die Raumreihenfolge war zufaellig."""
        scope_rank = {"central": 0, "zone": 1, "apartment": 2, "room": 3}
        order = room_order(self.project.areal)
        names = {}
        for building in self.project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apartment in floor.apartments:
                        names.setdefault(apartment.id, apartment.name or "")

        def key(scene):
            if scene.scope == "room":
                target = (order.get(scene.scope_id, len(order)), "")
            else:
                target = (0, names.get(scene.scope_id, scene.scope_id or ""))
            return (scope_rank.get(scene.scope, 4), target, scene.scene_number or 0, scene.name or "")
        return key

    def generate_szenen_report(self, filepath: str):
        """
        Erzeugt einen Szenenreport als PDF (FA-1811): pro Szene ein
        bauherren-lesbarer Bedienungs-Abschnitt (Auslöser, Aktionen) und ein
        technischer Abschnitt (Geltungsbereich, Szenenaufruf-GA, betroffene
        Gewerke/Aktoren inkl. CO-Verknüpfungsstatus aus co_linking_service).
        """
        pdf = self._make_pdf("Szenenreport")

        pdf.add_heading("Szenenreport", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        scenes = [s for s in self.project.scenes if s.name]
        if not scenes:
            pdf.add_paragraph("Keine Szenen im Projekt definiert.")
            pdf.save(filepath)
            logger.info(f"Szenenreport erstellt: {filepath}")
            return

        label_lookup = build_scope_label_lookup(self.project.areal)
        device_by_addr = {
            d.physical_address: d
            for area in self.project.topology.areas
            for line in area.lines
            for d in line.devices
        }
        proposals = CoLinkingService().generate_proposals(self.project)
        trigger_buttons_index = self._scene_trigger_buttons_index()

        # Tatsaechlich zugewiesene Gewerke je Geraet (NICHT die generische
        # Typ-Fähigkeitsmenge aus _gewerke_for_device -- ein "Schaltaktor"
        # deckt z.B. L/S/V/G/DF/BW/BL/P ab, wovon im Projekt meist nur eines
        # tatsaechlich genutzt wird). Quelle: die realen, raumbasierten
        # Belegungsplan-Zeilen dieses Geraets.
        belegungsplan = BelegungsplanService().generate(self.project)
        gewerke_by_device_addr: dict[str, set[str]] = {}
        for row in belegungsplan.actor_rows:
            if row.gewerk_code:
                gewerke_by_device_addr.setdefault(row.physical_address, set()).add(row.gewerk_code)

        for scene in sorted(scenes, key=self._scene_sort_key()):
            pdf.add_conditional_break(min_height=150)
            pdf.add_heading(f"{scene.name}  (Szene Nr. {scene.scene_number or '–'})", level=2)

            # ── Bedienung (Bauherr) ──────────────────────────────────────
            pdf.add_heading("Bedienung", level=3)
            assigned_buttons = trigger_buttons_index.get(scene.id, [])
            if assigned_buttons:
                pdf.add_paragraph(
                    "Ausgelöst durch (Taster-Zuweisung): " + ", ".join(assigned_buttons)
                )
            if scene.trigger:
                pdf.add_paragraph(f"Notiz: {scene.trigger}")
            if not assigned_buttons and not scene.trigger:
                pdf.add_paragraph("Ausgelöst durch: (kein Taster hinterlegt)")
            if scene.actions:
                for action in scene.actions:
                    pdf.add_paragraph(f"  •  {self._scene_action_label(action)}")
            else:
                pdf.add_paragraph("  (keine Aktionen definiert)")

            # ── Technische Details (Integrator) ─────────────────────────
            pdf.add_heading("Technische Details", level=3)
            scope_label = self._SCENE_SCOPE_LABELS.get(scene.scope, scene.scope or "Zentral")
            if scene.scope_id:
                scope_label += f": {label_lookup.get(scene.scope_id, scene.scope_id)}"
            pdf.add_paragraph(f"Geltungsbereich: {scope_label}")

            ga = self._scene_target_ga(scene, label_lookup)
            if ga is None:
                pdf.add_paragraph(
                    "Noch keine Gruppenadresse generiert – bitte in Schritt 10 des "
                    "Wizards ('Gruppenadressen generieren') aktualisieren."
                )
                pdf.add_separator()
                continue

            pdf.add_paragraph(
                f"Szenenaufruf-GA: {ga.designation}   [{ga.address}]   ({ga.datapoint_type})"
            )

            gewerke_codes: set[str] = set()
            actor_rows: list[list[str]] = []
            confirmed_addrs: set[str] = set()
            for area in self.project.topology.areas:
                for line in area.lines:
                    for device in line.devices:
                        if device.device_type not in ("actor", "gateway"):
                            continue
                        if any(ga.address in co.connected_gas for co in device.communication_objects):
                            confirmed_addrs.add(device.physical_address)
                            gewerke_codes |= gewerke_by_device_addr.get(device.physical_address, set())
                            actor_rows.append([device.physical_address, device.product, "verknüpft"])

            for p in proposals:
                if p.ga_address != ga.address or p.function_name != "SZENE":
                    continue
                if p.physical_address in confirmed_addrs:
                    continue
                device = device_by_addr.get(p.physical_address)
                gewerke_codes |= gewerke_by_device_addr.get(p.physical_address, set())
                actor_rows.append([
                    p.physical_address,
                    device.product if device else "",
                    f"Vorschlag ({p.confidence})",
                ])

            action_categories = self._scene_action_categories(scene)
            if action_categories:
                pdf.add_paragraph(
                    "Betroffene Gewerke (laut Aktionsdefinition): "
                    + ", ".join(
                        GEWERK_CATEGORY_LABELS.get(c, c)
                        for c in sorted(action_categories, key=_gewerk_category_sort_key)
                    )
                )

            if gewerke_codes:
                pdf.add_paragraph(
                    "Betroffene Gewerke (bestätigt durch Aktor-Verknüpfung): "
                    + ", ".join(self._gewerk_label(c) for c in sorted(gewerke_codes))
                )
            else:
                pdf.add_paragraph(
                    "Betroffene Gewerke (bestätigt durch Aktor-Verknüpfung): "
                    "(noch keine Aktoren verknüpft)"
                )

            if actor_rows:
                pdf.add_table(["Phys. Adresse", "Produkt", "Status"], actor_rows)
            else:
                pdf.add_paragraph(
                    "Betroffene Aktoren: noch keine verknüpft (siehe CO-Verknüpfung)."
                )

            pdf.add_separator()

        pdf.save(filepath)
        logger.info(f"Szenenreport erstellt: {filepath}")
