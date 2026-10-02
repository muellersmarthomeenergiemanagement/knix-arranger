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
from ..models.topology import area_coupler, line_coupler, line_title
from ..services.topology_diagram import (
    TOPOLOGY_TYPE_ORDER, TOPOLOGY_TYPE_PLURAL, device_type_label, area_title,
    build_topology_diagram,
)
from ..models.scene import Scene, SceneAction
from ..models.group_address import GroupAddressStructure, MIDDLE_GROUP_NAMES_A, MIDDLE_GROUP_NAMES_B
from ..services.validation_engine import ValidationEngine, ValidationIssue
from ..services.belegungsplan_service import (
    _split_button_channel, _extract_channel_label, group_actor_rows_by_channel,
    BelegungsplanService, build_ga_by_designation, _lookup_ga_by_function_ga,
)
from ..services.dpt_suggestion import dpt_number
from ..services.scene_addressing import build_scope_label_lookup, scene_target_designation
from ..services.co_linking_service import CoLinkingService
from ..services.channel_count_service import count_controlled_elements
from ..services.naming_engine import NamingEngine
from ..services.report_sorting import (
    group_address_key, physical_address_key, sorted_rooms,
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
    "FA-411": (
        "Hauptgruppe mehrfach vergeben",
        "Mehrere Stockwerke (meist verschiedener Gebäude) teilen sich eine "
        "Hauptgruppe. Ihre Adressen landen in derselben HG, deren Name wird "
        "aus den Stockwerken zusammengesetzt.",
        "In Schritt 1 jedem Stockwerk eine eigene Hauptgruppe geben.",
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
        "Erwartetes Format: GEWERK_RAUM_NR FUNKTION (Klartext). Die "
        "Raumnummer ist frei gestaltbar (A–Z, 0–9, - und .), muss bei "
        "geplanten Projekten aber ein Raum der Gebäudestruktur sein.",
        "Bei importierten Projekten mit eigenem Namensschema kann dieser "
        "Hinweis ignoriert werden.",
    ),
    "FA-614": (
        "Verknüpfung: mehrere sendende GAs an einem Sensorkanal",
        "Planungsregel (die ETS erlaubt es technisch): pro Sensorkanal darf nur "
        "eine sendende Gruppenadresse verknüpft sein; Rückmeldungen dürfen "
        "zusätzlich am Kanal hängen. Ein Tasten-KO sendet nur seine erste GA, "
        "jede weitere hört es nur mit. Fehler: die weitere GA ist nachweislich "
        "der Befehl einer anderen Bedienstelle. Warnung: kein sendendes KO "
        "gefunden, nicht eindeutig. Hinweis: Rückmeldung, die bei Variante B "
        "nicht in MG 6/7 liegt.",
        "Fehler in der ETS vom KO trennen, Warnungen prüfen – danach in der "
        "Bauherrenberatung oder Topologie ebenfalls trennen.",
    ),
    "FA-616": (
        "Abweichung zur ETS",
        "In KNiX korrigierte Angabe eines importierten Projekts: Gewerk einer GA "
        "(ETS-Kürzel entspricht nicht den Projektrichtlinien), Raum eines Geräts "
        "oder eine von einer Taste getrennte GA. "
        "Alle Dokumente verwenden die Korrektur; die ETS ist unverändert.",
        "Bei der nächsten Bearbeitung in der ETS nachführen.",
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

# Einbauorte, die ein Verteiler/Schaltschrank sind (im Bericht zuerst)
_DISTRIBUTION_RE = re.compile(
    r"^(UV|HV|HzV|NV|EV|UVS|Verteiler|Schaltschrank|Tableau|Unterverteil)",
    re.IGNORECASE)


def _n_devices(n: int) -> str:
    return f"{n} Gerät" if n == 1 else f"{n} Geräte"


_device_type_label = device_type_label


def _line_coupler(area, line) -> str:
    """Adresse des Linienkopplers, sofern als Gerät vorhanden (sonst "")."""
    coupler = line_coupler(area, line)
    return coupler.physical_address if coupler else ""


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


# ── Aktoren-und-Gateways-Bericht ─────────────────────────────────────────────

# Kanalbezeichnungen, die _extract_channel_label (Belegungsplan) bewusst nicht
# kennt: englische ETS-Namen wie "Output 1", "Group 1, Switching" (DALI).
_REPORT_CHANNEL_RE = re.compile(
    r"^((?:Output|Input|Channel|Group|Gruppe)\s+\w+)\b", re.IGNORECASE)
# Kanalnummer als Suffix, z.B. "ON/OFF_1" (nicht "R_1_TEXT_OBJECT_1")
_CHANNEL_UNDERSCORE_RE = re.compile(r"^[^_]+_(\d+)$")
# Platzhalter-Namen ohne Aussage: "GO0002", "Object 27", "$Dummy"
_GENERIC_CO_NAME_RE = re.compile(r"^(GO\d+|Obje[ck]t\s*\d+|\$.*)$", re.IGNORECASE)
_CHANNEL_TOTAL_RE = re.compile(r"(\d+)\s*(?:[-–]?\s*(?:fach|fold)\b|x\s)", re.IGNORECASE)
# Höchstzahl Textzeilen je Kanalzeile, damit eine Zeile nie länger als eine Seite wird
_MAX_CHANNEL_LINES = 36


def _report_channel_label(co_name: str) -> str:
    label = _extract_channel_label(co_name)
    if label:
        return label
    name = (co_name or "").strip()
    m = _REPORT_CHANNEL_RE.match(name)
    if m:
        return m.group(1)
    m = _CHANNEL_UNDERSCORE_RE.match(name)
    return f"Kanal {m.group(1)}" if m else ""


def _natural_key(text: str) -> list:
    """'Kanal 10' nach 'Kanal 9', 'Ausgang B' nach 'Ausgang A'."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p.lower())
            for p in re.split(r"(\d+)", text) if p]


def _co_object_text(co, channel: str) -> str:
    """Objektbezeichnung ohne Kanalanteil: 'Stellgrösse, Kanal 1' -> 'Stellgrösse';
    reine Kanal- oder Nummernnamen ('Ausgang A', 'GO0002') -> ETS-Funktion."""
    name = " ".join((co.name or "").split())
    if _CHANNEL_UNDERSCORE_RE.match(name):
        name = name.rsplit("_", 1)[0]
    elif channel and channel.lower() in name.lower():
        i = name.lower().index(channel.lower())
        name = (name[:i] + name[i + len(channel):]).strip(" ,-:")
    if not name or _GENERIC_CO_NAME_RE.match(name):
        name = co.object_function or co.name or ""
    return " ".join(name.split()) or f"KO {co.object_number}"


def _channel_total(product: str) -> int:
    """Kanalzahl nur, wenn sie im Produktnamen steht ('8-fach', '9x ...')."""
    m = _CHANNEL_TOTAL_RE.search(product or "")
    n = int(m.group(1)) if m else 0
    return n if 1 <= n <= 64 else 0


def _split_long_rows(rows: list[list]) -> list[list]:
    """Teilt Kanalzeilen [Kanal, Funktion, Gruppenadressen] mit sehr vielen
    Gruppenadressen (z.B. Zentraladressen) auf mehrere Tabellenzeilen auf."""
    result = []
    for label, function, gas in rows:
        lines = gas.split("\n")
        for start in range(0, len(lines), _MAX_CHANNEL_LINES):
            result.append([
                label if start == 0 else f"{label} (Forts.)",
                function if start == 0 else "",
                "\n".join(lines[start:start + _MAX_CHANNEL_LINES]),
            ])
    return result


def _own_button_labels(project, be, rows) -> dict:
    """(Taste, Seite) -> eigene Bezeichnung aus der Bauherrenberatung."""
    from .user_manual import button_label_key
    labels = project.ets_corrections.button_labels
    return {(r.key.number, r.key.side): labels[button_label_key(be, r.key)]
            for r in rows if r.key is not None and not r.key.variant
            and button_label_key(be, r.key) in labels}


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
        return (["Adresse", "Bezeichnung", "Befund"], [0.13, 0.62, 0.25], None,
                lambda i: [i.address, _clean(i.designation),
                           f"Raum {i.details['room']} fehlt" if i.details.get("room")
                           else "Format"])
    if rule_id == "FA-616":
        return (["Adresse", "Bezeichnung", "Angabe", "ETS", "KNiX"],
                [0.12, 0.48, 0.14, 0.13, 0.13], None,
                lambda i: [i.address, _clean(i.designation), i.details.get("field", ""),
                           i.details.get("ets", ""), i.details.get("knix", "")])
    if rule_id == "FA-614":
        return (["Gerät / KO", "Sendet", "Hört mit", "Bezeichnung", "Einordnung"],
                [0.25, 0.10, 0.11, 0.30, 0.24], None,
                lambda i: [i.details.get("ko", ""), i.details.get("sent", ""), i.address,
                           _clean(i.designation), i.details.get("verdict", "")])
    return (["Adresse", "Beschreibung", "Massnahme"], [0.13, 0.52, 0.35], None,
            lambda i: [i.address or "–", i.message, i.suggestion or ""])




class ReportService:
    """Erzeugt verschiedene Berichte für ein KNX-Projekt."""

    def __init__(self, project: KnxProject, company_profile=None):
        self.project = project
        self._company_profile = company_profile  # globales CompanyProfile (FA-852)
        self._room_by_id: dict | None = None

    def _device_location(self, device) -> str:
        """Einbauort eines Geräts; ohne Einbauort aus der ETS der zugeordnete
        Raum im gleichen Format ("04 Schlafen"), damit das Gerät nicht unter
        "Ohne Angabe" landet (z.B. Taster 1.1.39 im Chalet)."""
        location = _clean_location(device.installation_location)
        if location or not device.room_id:
            return location
        if self._room_by_id is None:
            self._room_by_id = {r.id: r for r in self.project.all_rooms}
        room = self._room_by_id.get(device.room_id)
        return _clean_location(f"{room.number} {room.name}") if room else ""

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

    def _room_gewerk_groups(self):
        """Ordnet die Gruppenadressen Räumen und Elementen zu.

        Raum einer GA, in dieser Reihenfolge:
        1. GroupAddress.room_id (geplante Projekte),
        2. Bezeichnung nach GEWERK.STOCKWERK.RAUM.ELEM ("J.OG.00.01_move"),
           Raum über Stockwerk + Raumnummer (Nummern sind nur je Stockwerk
           eindeutig),
        3. nur für sonst nicht zuordenbare GAs: verbunden mit einem Taster
           oder Sensor im Raum. Aktoren/Gateways zählen nicht – sie sitzen im
           Verteiler, nicht im gesteuerten Raum.
        Zentraladressen (HG 0) bilden je Raum die Gruppe "Zentral".

        Rückgabe: (room.id -> {(Kategorie, Label, Element): [GA]},
                   "OG 04" -> [GA] für Räume, die in der Gebäudestruktur fehlen)
        """
        from .gewerk_service import GewerkService
        structure = self.project.group_addresses
        catalog = self.project.gewerk_catalog
        mg_names = (MIDDLE_GROUP_NAMES_B if structure.variant == "B"
                    else MIDDLE_GROUP_NAMES_A)
        mg_label = {}
        for hg in structure.main_groups:
            for mg in hg.middle_groups:
                for ga in mg.group_addresses:
                    mg_label[ga.address] = mg_names.get(mg.number) or mg.name or f"MG {mg.number}"

        rooms = {r.id: r for r in self.project.all_rooms}
        room_index = GewerkService._build_room_index(self.project.areal)
        ga_by_address = {ga.address: ga for ga in structure.all_addresses()}

        def key_for(ga, code: str, element) -> tuple:
            """(Kategorie, Anzeige-Label, Element-Nr., Kurzform für die Übersicht)"""
            if ga.main_group == 0:
                return ("zentral", "Zentral (HG 0)", 0, "Zentral")
            gewerk = catalog.get(code) if code else None
            if gewerk:
                return (gewerk.category or "", self._gewerk_label(code), element or 0, code)
            label = mg_label.get(ga.address, "Sonstige")
            return ("", label, 0, label)

        groups: dict[str, dict] = defaultdict(lambda: defaultdict(list))
        missing: dict[str, list] = defaultdict(list)
        placed: set[str] = set()
        for ga in structure.all_addresses():
            if ga.is_placeholder:
                continue
            if ga.room_id in rooms:
                groups[ga.room_id][key_for(ga, ga.gewerk_code, ga.element_number)].append(ga)
                placed.add(ga.address)
                continue
            matched = GewerkService._match_ga_designation(ga.designation or "")
            if matched is None:
                continue
            code, floor_code, room_nr, elem_nr, combined = matched
            code = ga.gewerk_code or code
            room = room_index.get((floor_code, room_nr))
            if room is None:
                missing[f"{floor_code} {room_nr}"].append(ga)
            else:
                element = 0 if combined else int(elem_nr)
                groups[room.id][key_for(ga, code, element)].append(ga)
            placed.add(ga.address)

        for area in self.project.topology.areas:
            for line in area.lines:
                for dev in line.devices:
                    if dev.device_type in ("actor", "gateway") or dev.room_id not in rooms:
                        continue
                    for co in dev.communication_objects:
                        for addr in co.connected_gas:
                            ga = ga_by_address.get(addr)
                            if ga is None or ga.is_placeholder or addr in placed:
                                continue
                            bucket = groups[dev.room_id][key_for(ga, ga.gewerk_code, 0)]
                            if ga not in bucket:
                                bucket.append(ga)
        return groups, missing

    def generate_room_gewerk_report(self, filepath: str):
        """Erzeugt den Bericht "Räume nach Gewerken" als PDF.

        Übersicht mit den Gewerken je Raum und Seitenzahlen, danach je
        Stockwerk (neue Seite) und Raum eine Tabelle mit einer Zeile je
        Element (Gewerk + Nr.) und allen Gruppenadressen. Zuordnung siehe
        _room_gewerk_groups. PDF-Lesezeichen: Stockwerk → Raum.
        """
        title = "Räume nach Gewerken"
        pdf = self._make_pdf(title)
        pdf.add_heading(title, level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        groups, missing = self._room_gewerk_groups()
        floor_by_room: dict[str, str] = {}
        zone_by_room: dict[str, str] = {}
        for building in self.project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            floor_by_room[room.id] = floor.name
                            zone_by_room[room.id] = apt.name

        def room_label(room) -> str:
            parts = [zone_by_room.get(room.id, ""), f"{room.number} {room.name}".strip()]
            return " · ".join(_clean_location(p) for p in parts if p)

        def sort_key(item):
            (category, label, element, _short), _gas = item
            return (category == "zentral", _gewerk_category_sort_key(category), label, element)

        entries = [(room, sorted(groups[room.id].items(), key=sort_key))
                   for room in sorted_rooms(self.project.areal) if groups.get(room.id)]
        if not entries and not missing:
            pdf.add_paragraph("Keine Räume mit zugeordneten Gruppenadressen gefunden.")
            pdf.save(filepath)
            logger.info(f"Räume-nach-Gewerken-Bericht erstellt: {filepath}")
            return

        def element_label(label, element, labels_with_elements) -> str:
            return f"{label} {element}" if element and label in labels_with_elements else label

        def ga_text(ga) -> str:
            text = _ga_line(ga)
            desc = " ".join((ga.description or "").split())
            if desc and desc.lower() not in (ga.designation or "").lower():
                text += f" – {desc}"
            return text

        def summary(items) -> str:
            """'J 3 · H 1 · Allgemein · Zentral' – Gewerk-Code mit Anzahl
            Elemente; Mittelgruppen und Zentral ohne Anzahl."""
            counts: dict[str, int] = {}
            for (_category, _label, _element, short), _gas in items:
                counts[short] = counts.get(short, 0) + 1
            codes = {short for (_c, _l, _e, short), _g in items
                     if self.project.gewerk_catalog.get(short)}
            return " · ".join(f"{k} {n}" if k in codes else k for k, n in counts.items())

        # ── Übersicht ────────────────────────────────────────────────────────
        pdf.add_heading("Übersicht", level=2)
        n_gas = sum(len(g) for _room, items in entries for _k, g in items)
        pdf.add_paragraph(f"{len(entries)} Räume mit {n_gas} Gruppenadressen.")
        overview = []
        for room, items in entries:
            overview.append([
                " · ".join(p for p in (floor_by_room.get(room.id, ""), room_label(room)) if p),
                summary(items),
                str(sum(len(g) for _k, g in items)),
                PageRef(f"room-{room.id}"),
            ])
        pdf.add_table(["Stockwerk · Raum", "Gewerke (Anzahl Elemente)", "GAs", "Seite"],
                      overview, col_widths=[0.36, 0.44, 0.10, 0.10],
                      align=["left", "left", "right", "right"])
        pdf.add_note(
            "Zuordnung:",
            "Raum aus der Planung oder aus der Bezeichnung (Gewerk.Stockwerk.Raum."
            "Element); sonst über Taster und Sensoren im Raum. Zentral = Adressen "
            "in HG 0, die im Raum bedient werden.")
        pdf.add_note("Hinweis:", "Das PDF enthält Lesezeichen nach Stockwerk und Raum.")

        # ── Stockwerk → Raum ─────────────────────────────────────────────────
        current_floor = None
        for room, items in entries:
            floor = floor_by_room.get(room.id, "") or "Ohne Stockwerk"
            if floor != current_floor:
                pdf.add_page_break()
                pdf.add_heading(floor, level=2)
                current_floor = floor
            n_lines = sum(len(g) for _k, g in items)
            pdf.add_conditional_break(min_height=min(60 + n_lines * 11, 300))
            pdf.add_anchor(f"room-{room.id}")
            n_elements = sum(1 for (c, _l, _e, _s), _g in items if c != "zentral")
            pdf.add_heading(
                f"{room_label(room)}  ({n_elements} "
                f"{'Element' if n_elements == 1 else 'Elemente'}, "
                f"{sum(len(g) for _k, g in items)} GAs)", level=3)
            # Element-Nr. nur anzeigen, wo ein Gewerk mehrere Elemente hat
            elements_by_label: dict[str, set] = defaultdict(set)
            for (_c, label, element, _s), _g in items:
                elements_by_label[label].add(element)
            labels_with_elements = {l for l, e in elements_by_label.items() if len(e) > 1}
            rows = []
            for (category, label, element, _short), gas in items:
                gas = sorted(gas, key=lambda g: group_address_key(g.address))
                rows.append([
                    element_label(label, element, labels_with_elements),
                    "\n".join(ga_text(g) for g in gas),
                ])
            pdf.add_table(["Gewerk / Element", "Gruppenadressen"], rows,
                          col_widths=[0.26, 0.74])

        # ── Räume, die in der Gebäudestruktur fehlen ─────────────────────────
        if missing:
            pdf.add_page_break()
            pdf.add_heading("Räume nicht in der Gebäudestruktur", level=2)
            pdf.add_note(
                "Hinweis:",
                "Stockwerk und Raumnummer aus der Bezeichnung passen zu keinem Raum "
                "der Gebäudestruktur. Raum in Schritt 2 ergänzen oder Bezeichnung prüfen.")
            rows = []
            for key in sorted(missing, key=_natural_key):
                gas = sorted(missing[key], key=lambda g: group_address_key(g.address))
                rows.append([key, "\n".join(ga_text(g) for g in gas)])
            pdf.add_table(["Stockwerk / Raum", "Gruppenadressen"], rows,
                          col_widths=[0.18, 0.82])

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

        # ── Topologie-Diagramm (dieselben Knoten wie die Ansicht) ───────────
        diagram = build_topology_diagram(self.project, include_empty_lines=False)
        pdf.add_heading("Topologie-Diagramm", level=2)
        pdf.add_topology_diagram(diagram["areas"], diagram["backbone"])

        # ── Übersicht: Prinzipschema und Kennzahlen ─────────────────────────
        pdf.add_conditional_break(min_height=250)
        pdf.add_heading("Übersicht", level=2)
        schema = []
        kpi_rows = []
        for area, lines in areas:
            info = " · ".join(p for p in (
                f"Backbone {area.backbone_type}" if area.backbone_type else "",
                f"Koppler {area.area_number}.0.0" if area_coupler(area) else "",
            ) if p)
            schema_lines = []
            for line in lines:
                counts = Counter(_device_type_label(d) for d in line.devices)
                bus_devices = len(line.devices) - counts.get("Spannungsversorgung", 0)
                stats = [(TOPOLOGY_TYPE_PLURAL[t], counts[t])
                         for t in TOPOLOGY_TYPE_ORDER if counts.get(t)]
                schema_lines.append({
                    "title": line_title(area, line),
                    "coupler": _line_coupler(area, line),
                    "count": bus_devices,
                    "max": max_devices,
                    "stats": stats,
                })
                kpi_rows.append([
                    line_title(area, line),
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
                title = line_title(area, line)
                if multi_area and area.name:
                    title = f"{area.name} – {title}"
                parts = [_n_devices(len(line.devices))]
                if _line_coupler(area, line):
                    parts.append(f"Koppler {_line_coupler(area, line)}")
                pdf.add_heading(f"{title}  ({', '.join(parts)})", level=3)
                rows = [
                    [d.physical_address, _device_cell(d), _device_type_label(d),
                     self._device_location(d) or "–"]
                    for d in sorted(line.devices,
                                    key=lambda d: physical_address_key(d.physical_address))
                ]
                pdf.add_table(headers, rows, col_widths=widths)

        # ── Geräte nach Einbauort ────────────────────────────────────────────
        by_location: dict[str, list] = defaultdict(list)
        for _area, lines in areas:
            for line in lines:
                for d in line.devices:
                    by_location[self._device_location(d)].append(d)

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

        # ── Mehrfach verknüpfte Sensorkanäle (FA-614) ────────────────────────
        from .multi_ga_check import find_multi_ga, VERDICT_RUECKMELDUNG
        multi = [f for f in find_multi_ga(project) if f.verdict != VERDICT_RUECKMELDUNG]
        if multi:
            n_err = sum(1 for f in multi if f.is_error)
            n_warn = sum(1 for f in multi if f.is_warning and not f.is_error)
            pdf.add_heading("Sensorkanäle mit mehreren sendenden GAs", level=2,
                            accent=ACCENT_ERROR if n_err else
                            ACCENT_WARNING if n_warn else None)
            pdf.add_note(
                "Hinweis:",
                "Pro Sensorkanal darf nur eine sendende Gruppenadresse verknüpft "
                "sein; Rückmeldungen dürfen zusätzlich am Kanal hängen. Gesendet "
                "wird nur die erste GA, jede weitere hört der Kanal nur mit. "
                f"Fehler ({n_err}): die weitere GA ist nachweislich der Befehl einer "
                f"anderen Bedienstelle – in der ETS trennen. Warnung ({n_warn}): kein "
                "sendendes KO gefunden, nicht eindeutig – prüfen.")
            level_prefix = {"error": "Fehler: ", "warning": "Warnung: "}
            pdf.add_table(
                ["Gerät / KO", "Sendet", "Weitere GA", "Bezeichnung", "Einordnung"],
                [[f.ko_text, f.sent_ga, f.extra_ga, _clean(f.extra_designation),
                  level_prefix.get(f.level, "") + f.verdict_label]
                 for f in multi],
                col_widths=[0.25, 0.10, 0.11, 0.30, 0.24])

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
                own = _own_button_labels(project, be, rows)
                for entry in plan:   # eigene Bezeichnungen (Bauherrenberatung)
                    sides = [""] if len(entry["cells"]) == 1 else ["links", "rechts"]
                    entry["cells"] = [
                        (own[(entry["number"], side)], "") if (entry["number"], side) in own
                        else cell for side, cell in zip(sides, entry["cells"])]
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
                        elif not row.key.variant and (row.key.number, row.key.side) in own:
                            function = own[(row.key.number, row.key.side)]
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
        """Erzeugt den Bericht "Aktoren und Gateways" als PDF.

        Gegliedert wie man im Gebäude sucht: Übersicht mit Seitenzahlen,
        danach je Einbauort (Verteiler zuerst, jeder auf neuer Seite) die
        Geräte als Gerätekarten. Geplante Projekte zeigen eine Zeile je Kanal
        mit Gewerk und Raum (Belegungsplan), importierte Projekte eine Zeile
        je ETS-Kommunikationsobjekt, nach Kanal gegliedert.
        PDF-Lesezeichen: Einbauort → Gerät.
        """
        title = "Aktoren und Gateways"
        pdf = self._make_pdf(title)

        pdf.add_heading(title, level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        ga_by_address = {ga.address: ga for ga in self.project.group_addresses.all_addresses()}

        def ga_text(address: str) -> str:
            return _ga_line(ga_by_address.get(address) or address)

        # Belegungsplan als Quelle für die Kanal-Zuordnung geplanter Projekte:
        # dort sind Device.communication_objects je Funktion über alle Kanäle
        # gebündelt, nur der Belegungsplan kennt Kanal, Gewerk und Raum.
        actor_rows_by_addr: dict[str, list] = defaultdict(list)
        for r in BelegungsplanService().generate(self.project).actor_rows:
            actor_rows_by_addr[r.physical_address].append(r)

        by_location: dict[str, list] = defaultdict(list)
        for area in self.project.topology.areas:
            for line in area.lines:
                for dev in line.devices:
                    if dev.device_type in ("actor", "gateway"):
                        by_location[self._device_location(dev)].append(
                            (area, line, dev))
        if not by_location:
            pdf.add_paragraph("Keine Aktoren oder Gateways im Projekt vorhanden.")
            pdf.save(filepath)
            logger.info(f"Aktoren-und-Gateways-Bericht erstellt: {filepath}")
            return
        locations = sorted(by_location, key=_location_sort_key)
        for location in locations:
            by_location[location].sort(key=lambda e: physical_address_key(e[2].physical_address))

        def planned_channels(dev) -> list[list]:
            """Kanalzeilen aus dem Belegungsplan (nur mit Gewerk-Zuordnung)."""
            rows = actor_rows_by_addr.get(dev.physical_address, [])
            if not any(r.gewerk_code for r in rows):
                return []
            table = []
            for channel, ch_rows in group_actor_rows_by_channel(rows):
                first = ch_rows[0]
                if channel == "?":
                    label, function = "Zentral", ("Zentral- und Szenenadressen", "")
                else:
                    room = " · ".join(p for p in (
                        first.floor_name, first.zone_name,
                        f"{first.room_number} {first.room_name}".strip()) if p)
                    label = f"Kanal {channel}"
                    function = (self._gewerk_label(first.gewerk_code) or "–",
                                _clean_location(room))
                gas = dict.fromkeys(ga_text(r.ga_address) for r in ch_rows)
                table.append([label, function, "\n".join(gas) or "–"])
            return table

        def co_channels(dev) -> tuple[list[list], list[int]]:
            """Eine Zeile je ETS-Kommunikationsobjekt, nach Kanal gegliedert
            (Kanal nur in der ersten Zeile, Schattierung je Kanal); Objekte
            ohne erkennbaren Kanal zuletzt unter "Weitere"."""
            by_channel: dict[str, list] = defaultdict(list)
            loose = []
            for co in sorted(dev.communication_objects, key=lambda c: c.object_number):
                if not co.connected_gas:
                    continue
                channel = _report_channel_label(co.name)
                (by_channel[channel] if channel else loose).append(co)
            blocks = [(ch, [(ch, co) for co in by_channel[ch]])
                      for ch in sorted(by_channel, key=_natural_key)]
            blocks += [("Weitere" if i == 0 else "", [("", co)]) for i, co in enumerate(loose)]
            table, groups = [], []
            for group, (label, cos) in enumerate(blocks):
                for i, (channel, co) in enumerate(cos):
                    table.append([
                        label if i == 0 else "",
                        f"{co.object_number}  {_co_object_text(co, channel)}",
                        "\n".join(ga_text(a) for a in co.connected_gas),
                    ])
                    groups.append(group)
            return table, groups

        def channel_count(dev, table, planned: bool) -> str:
            used = sum(1 for r in table if r[0] and r[0] not in ("Weitere", "Zentral"))
            total = _channel_total(dev.product)
            if planned or used:
                return f"{used} / {total}" if total else str(used)
            return "–"

        def anchor(dev) -> str:
            return f"dev-{dev.physical_address}-{id(dev)}"

        # Tabellen einmal berechnen (Übersicht und Gerätekarten):
        # id(dev) -> (Zeilen, geplant?, Schattierungsgruppen)
        details = {}
        for location in locations:
            for _area, _line, dev in by_location[location]:
                planned = planned_channels(dev)
                if planned:
                    details[id(dev)] = (_split_long_rows(planned), True, None)
                else:
                    table, groups = co_channels(dev)
                    details[id(dev)] = (table, False, groups)

        # ── Übersicht ────────────────────────────────────────────────────────
        pdf.add_heading("Übersicht", level=2)
        devices = [e[2] for loc in locations for e in by_location[loc]]
        n_actors = sum(1 for d in devices if d.device_type == "actor")
        n_gateways = len(devices) - n_actors
        pdf.add_paragraph(
            f"{n_actors} {'Aktor' if n_actors == 1 else 'Aktoren'}, "
            f"{n_gateways} {'Gateway' if n_gateways == 1 else 'Gateways'} an "
            f"{len(locations)} {'Einbauort' if len(locations) == 1 else 'Einbauorten'}."
        )
        overview = []
        for location in locations:
            for _area, _line, dev in by_location[location]:
                table, planned, _groups = details[id(dev)]
                overview.append([
                    dev.physical_address,
                    _device_cell(dev),
                    _device_type_label(dev),
                    location or "–",
                    channel_count(dev, table, planned),
                    PageRef(anchor(dev)),
                ])
        pdf.add_table(["Adresse", "Gerät", "Typ", "Einbauort", "Kanäle", "Seite"],
                      overview, col_widths=[0.09, 0.44, 0.10, 0.20, 0.09, 0.08],
                      align=["left", "left", "left", "left", "right", "right"])
        pdf.add_note(
            "Kanäle:",
            "belegte Kanäle / Kanalzahl laut Produktbezeichnung. Belegt ist ein "
            "Kanal mit mindestens einer Gruppenadresse; «–», wenn die Objekte "
            "des Geräts keinen Kanal erkennen lassen.")
        pdf.add_note("Hinweis:", "Das PDF enthält Lesezeichen nach Einbauort und "
                                 "Gerät. Jeder Einbauort beginnt auf einer neuen Seite.")

        # ── Einbauort → Gerät ────────────────────────────────────────────────
        for location in locations:
            entries = by_location[location]
            pdf.add_page_break()
            pdf.add_heading(f"{location or 'Ohne Einbauort'}  ({_n_devices(len(entries))})",
                            level=2)
            for area, line, dev in entries:
                table, planned, groups = details[id(dev)]
                # Karte möglichst auf einer Seite, lange Karten brechen um
                n_lines = sum(str(r[2]).count("\n") + 1 for r in table)
                pdf.add_conditional_break(min_height=min(70 + n_lines * 10.5, 400))
                pdf.add_anchor(anchor(dev))
                product = dev.product or "–"
                card_details = [
                    " · ".join(p for p in (dev.manufacturer, product, dev.order_number) if p),
                    " · ".join(p for p in (
                        f"Linie {area.area_number}.{line.line_number}",
                        f"SN {dev.serial_number}" if dev.serial_number else "",
                    ) if p),
                ]
                pdf.add_card_header(f"{dev.physical_address}  ·  {_device_type_label(dev)}",
                                    "\n".join(card_details),
                                    bookmark=f"{dev.physical_address}  {product}")

                if table:
                    pdf.add_table(
                        ["Kanal", "Funktion" if planned else "Objekt", "Gruppenadressen"],
                        table,
                        col_widths=[0.12, 0.30, 0.58] if planned else [0.12, 0.26, 0.62],
                        groups=groups)
                else:
                    pdf.add_paragraph("Keine Gruppenadressen verknüpft.")

                for ds in dev.datasheets:
                    if ds.startswith(("http://", "https://")):
                        pdf.add_link(ds, ds)
                    else:
                        pdf.add_note("Datenblatt:", ds)

        pdf.save(filepath)
        logger.info(f"Aktoren-und-Gateways-Bericht erstellt: {filepath}")

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

        # Tastennummern aus einer Kopie mit aktueller Tastenbelegung -- der
        # Bericht liest nur (siehe sensor_service.project_for_export)
        from .sensor_service import project_for_export
        index: dict[str, list[str]] = {}
        for room in project_for_export(self.project).all_rooms:
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

    def generate_szenen_report(self, filepath: str):
        """Erzeugt den Szenenreport als PDF (FA-1811).

        Gegliedert nach der Szenen-Gruppenadresse (services/scene_overview,
        gleiche Einteilung wie die Szenen-Verwaltung): sie überträgt die
        Szenennummer, Taster und Aktoren sind mit ihr verknüpft. Je Adresse
        eine Karte mit DPT und Geltungsbereich, eine Zeile je Szenennummer
        (1–64; auf dem Bus Bytewert 0–63) mit Auslöser und Aktionen, danach
        die verknüpften Geräte – Sender (Taster, Sensoren) und Empfänger
        (Aktoren) – mit ihren Objekten.

        Eigene Abschnitte: Szenen der Visualisierung (einzelne Schalt-Adressen,
        z.B. UniPro H/M/L/0 – keine KNX-Szenenadressen), nicht eindeutig
        erkannte Szenen-Adressen (zur Fehlersuche) und geplante Szenen, deren
        Adresse noch nicht generiert ist. PDF-Lesezeichen: Abschnitt → Adresse.
        """
        from .scene_overview import build_scene_overview, linked_devices, scope_text

        title = "Szenenreport"
        pdf = self._make_pdf(title)
        pdf.add_heading(title, level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        pdf.add_separator()

        if not any(s.name for s in self.project.scenes):
            pdf.add_paragraph("Keine Szenen im Projekt definiert.")
            pdf.save(filepath)
            logger.info(f"Szenenreport erstellt: {filepath}")
            return

        overview = build_scene_overview(self.project)
        label_lookup = build_scope_label_lookup(self.project.areal)
        ga_by_address = {g.address: g for g in self.project.group_addresses.all_addresses()}
        device_by_addr = {
            d.physical_address: d
            for area in self.project.topology.areas
            for line in area.lines
            for d in line.devices
        }
        proposals = CoLinkingService().generate_proposals(self.project)
        trigger_buttons_index = self._scene_trigger_buttons_index()
        # Tatsaechlich zugewiesene Gewerke je Geraet aus den Belegungsplan-
        # Zeilen (NICHT die Typ-Faehigkeitsmenge eines "Schaltaktor").
        gewerke_by_device_addr: dict[str, set[str]] = {}
        for row in BelegungsplanService().generate(self.project).actor_rows:
            if row.gewerk_code:
                gewerke_by_device_addr.setdefault(row.physical_address, set()).add(row.gewerk_code)

        existing = [g for g in overview.addresses if not g.planned]
        planned = [g for g in overview.addresses if g.planned]

        def triggers(scene) -> str:
            lines = list(trigger_buttons_index.get(scene.id, []))
            lines += [t for t in (scene.trigger or "").split("; ") if t and t not in lines]
            return "\n".join(lines) or "–"

        def actions(scene, ga=None) -> str:
            # Verweis der Szene auf ihre eigene Szenen-Adresse ist keine Aktion
            own = {ga.address, _clean(ga.designation)} if ga else set()
            return "\n".join(
                _clean_location(self._scene_action_label(a)) for a in scene.actions
                if a.ga_address not in own and _clean(a.group_address) not in own
            ) or "–"

        def scene_name(scene, group) -> str:
            """'Anwesendheit Chalet – Szene 1' -> 'Szene 1' (Adressname steht im Kopf)."""
            name = " ".join(scene.name.split())
            for prefix in (_clean(group.designation),
                           _clean(group.channel.name) if group.channel else ""):
                if prefix and name.startswith(prefix + " – "):
                    return name[len(prefix) + 3:]
            return name

        def scene_list(group) -> str:
            """'1 Anwesend · 2 Abwesend'; reine Nummern-Namen ('Szene 2') nur als Nummer."""
            parts = []
            for s in group.scenes:
                name = scene_name(s, group)
                generic = re.fullmatch(r"Szene 0*(\d+)", name)
                parts.append(str(s.scene_number) if generic and int(generic.group(1)) == s.scene_number
                             else f"{s.scene_number} {name}")
            return " · ".join(parts)

        def device_rows(group) -> tuple[list[list], set[str], bool]:
            """Verknüpfte Geräte (Sender zuerst) plus Aktor-Vorschläge der
            CO-Verknüpfung; bestätigte Gewerke der Aktoren; ob ein Empfänger
            verknüpft ist."""
            rows, codes, receiver = [], set(), False
            linked = set()
            for link in linked_devices(self.project, group.ga.address):
                addr = link.device.physical_address
                linked.add(addr)
                if not link.sends:
                    receiver = True
                    codes |= gewerke_by_device_addr.get(addr, set())
                rows.append([addr, _device_cell(link.device), link.role,
                             "\n".join(link.objects)])
            for p in proposals:
                if p.ga_address == group.ga.address and p.function_name == "SZENE" \
                        and p.physical_address not in linked:
                    device = device_by_addr.get(p.physical_address)
                    codes |= gewerke_by_device_addr.get(p.physical_address, set())
                    rows.append([p.physical_address,
                                 _device_cell(device) if device else ("–", ""),
                                 f"Vorschlag ({p.confidence})", ""])
            return rows, codes, receiver

        # ── Übersicht ────────────────────────────────────────────────────────
        pdf.add_heading("Übersicht", level=2)
        n_scenes = sum(len(g.scenes) for g in existing)
        parts = [f"{len(existing)} Szenen-Adressen mit {n_scenes} Szenen"]
        if overview.visu:
            parts.append(f"{len(overview.visu)} Szenen der Visualisierung")
        if overview.unclear:
            parts.append(f"{len(overview.unclear)} nicht eindeutig")
        if planned:
            parts.append(f"{sum(len(g.scenes) for g in planned)} ohne Gruppenadresse")
        pdf.add_paragraph(", ".join(parts) + ".")
        if existing:
            pdf.add_table(
                ["Adresse", "Bezeichnung", "Szenen (Nr. Name)", "Seite"],
                [[g.ga.address, _clean(g.designation), scene_list(g) or "–",
                  PageRef(f"scene-ga-{g.ga.address}")] for g in existing],
                col_widths=[0.11, 0.33, 0.48, 0.08],
                align=["left", "left", "left", "right"])
        pdf.add_note(
            "Szenennummer:",
            "Szenen sind von 1 bis 64 nummeriert. Auf dem Bus überträgt die "
            "Gruppenadresse den Bytewert 0–63, also die Szenennummer minus 1.")
        pdf.add_note("Hinweis:", "Das PDF enthält Lesezeichen je Szenen-Adresse.")

        # ── Szenen-Adressen ──────────────────────────────────────────────────
        if existing:
            pdf.add_page_break()
            pdf.add_heading("Szenen-Adressen", level=2)
            for group in existing:
                ga = group.ga
                pdf.add_conditional_break(min_height=min(140 + 30 * len(group.scenes), 380))
                pdf.add_anchor(f"scene-ga-{ga.address}")
                dpt = dpt_number(ga.datapoint_type or "") or "DPT fehlt"
                anchor = group.anchor_scene
                detail = [f"{dpt} · Geltungsbereich "
                          f"{scope_text(anchor, label_lookup) if anchor else 'Zentral'}"]
                pdf.add_card_header(f"{ga.address}  ·  {_clean(ga.designation)}",
                                    "\n".join(detail),
                                    bookmark=f"{ga.address}  {_clean(ga.designation)}")
                if not group.dpt_ok:
                    pdf.add_note("Prüfen:", f"Datenpunkttyp {dpt} – für Szenen wird "
                                            "17.001 (bzw. 18.001) erwartet.")
                if group.scenes:
                    pdf.add_table(
                        ["Nr.", "Szene", "Ausgelöst durch", "Aktionen"],
                        [[str(s.scene_number or "–"), scene_name(s, group), triggers(s),
                          actions(s, ga)] for s in group.scenes],
                        col_widths=[0.06, 0.22, 0.32, 0.40],
                        align=["right", "left", "left", "left"])
                else:
                    pdf.add_paragraph("Keine Szenennummern hinterlegt.")

                rows, codes, receiver = device_rows(group)
                action_categories = set()
                for s in group.all_scenes:
                    action_categories |= self._scene_action_categories(s)
                if action_categories:
                    pdf.add_note("Betroffene Gewerke (laut Aktionsdefinition):", ", ".join(
                        GEWERK_CATEGORY_LABELS.get(c, c)
                        for c in sorted(action_categories, key=_gewerk_category_sort_key)))
                if codes:
                    pdf.add_note("Betroffene Gewerke (bestätigt durch Aktor-Verknüpfung):",
                                 ", ".join(self._gewerk_label(c) for c in sorted(codes)))
                if rows:
                    pdf.add_table(["Adresse", "Verknüpftes Gerät", "Rolle", "Objekte"], rows,
                                  col_widths=[0.09, 0.37, 0.12, 0.42])
                if not receiver and not any(r[2].startswith("Vorschlag") for r in rows):
                    if any(actions(s, ga) != "–" for s in group.scenes):
                        pdf.add_note("Prüfen:", "Kein Aktor ist mit dieser Adresse verknüpft, "
                                                "obwohl Aktionen hinterlegt sind. Szenenobjekte "
                                                "der Aktoren in der ETS mit der Adresse verbinden.")
                    else:
                        pdf.add_note("Betroffene Gewerke (bestätigt durch Aktor-Verknüpfung):",
                                     "noch keine Aktoren verknüpft")

        # ── Szenen der Visualisierung ────────────────────────────────────────
        if overview.visu:
            pdf.add_page_break()
            pdf.add_heading("Szenen der Visualisierung", level=2)
            pdf.add_note(
                "Hinweis:",
                "Diese Szenen löst die Visualisierung (z.B. UniPro mit den Stufen "
                "H/M/L/0) über einzelne Schalt-Adressen aus. Es sind keine "
                "KNX-Szenenadressen und sie tragen keine Szenennummer.")
            rows = []
            for scene in overview.visu:
                rows.append([
                    scene.name,
                    "\n".join(_ga_line(ga_by_address.get(a) or a)
                              for a in sorted(scene.source_ga_addresses, key=group_address_key))
                    or "–",
                    triggers(scene) if triggers(scene) != "–" else "",
                ])
            pdf.add_table(["Szene", "Gruppenadressen", "Ausgelöst durch"], rows,
                          col_widths=[0.24, 0.50, 0.26])

        # ── Nicht eindeutig ──────────────────────────────────────────────────
        if overview.unclear:
            pdf.add_page_break()
            pdf.add_heading("Nicht eindeutig", level=2, accent=ACCENT_WARNING)
            pdf.add_note(
                "Hinweis:",
                "Diese Adressen wurden beim Import als Szene erkannt, haben aber "
                "weder den Datenpunkttyp einer Szene (17.001/18.001) noch "
                "hinterlegte Szenennummern. Prüfen, ob es Szenen-Adressen sind, "
                "und DPT bzw. Szenen in der ETS korrigieren.")
            pdf.add_table(
                ["Adresse", "Bezeichnung", "DPT", "Grund"],
                [[g.ga.address, _clean(g.designation),
                  dpt_number(g.ga.datapoint_type or "") or "–",
                  "DPT keine Szene, keine Szenennummern"]
                 for g in overview.unclear],
                col_widths=[0.11, 0.45, 0.12, 0.32])

        # ── Geplante Szenen ohne Gruppenadresse ──────────────────────────────
        if planned:
            pdf.add_page_break()
            pdf.add_heading("Ohne Gruppenadresse", level=2, accent=ACCENT_WARNING)
            pdf.add_note(
                "Hinweis:",
                "Für diese Szenen ist noch keine Szenen-Adresse generiert – in "
                "Schritt 10 des Wizards ('Gruppenadressen generieren') aktualisieren.")
            pdf.add_table(
                ["Nr.", "Szene", "Künftige Adresse", "Ausgelöst durch", "Aktionen"],
                [[str(s.scene_number or "–"), s.name, g.designation, triggers(s), actions(s)]
                 for g in planned for s in g.scenes],
                col_widths=[0.06, 0.20, 0.20, 0.24, 0.30],
                align=["right", "left", "left", "left", "left"])

        pdf.save(filepath)
        logger.info(f"Szenenreport erstellt: {filepath}")
