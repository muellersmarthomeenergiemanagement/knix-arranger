"""
Dokumentations-Service (FA-1900, FA-2000, FA-2100)
Erzeugt Inbetriebnahme-Checklisten, Abnahmeprotokolle,
Bedienungsanleitungen und Revisionspakete.
"""
from __future__ import annotations
import logging
import os
from datetime import datetime

from ..models.project import KnxProject
from ..models.building import Room
from ..models.documentation import (
    CommissioningChecklist, ChecklistItem, AcceptanceProtocol, Defect,
    ITEM_KIND_DEVICE, ITEM_KIND_FUNCTION, RESULT_OPEN,
)
from ..utils.pdf_generator import PdfGenerator
from ..utils.excel_generator import ExcelGenerator, HAS_OPENPYXL

logger = logging.getLogger("knix_arranger.documentation")


# Standard-Prüfpunkte für Inbetriebnahme (FA-1902)
STANDARD_CHECK_ITEMS = [
    ("Montage", "Gerät korrekt montiert und beschriftet"),
    ("Busverbindung", "KNX-Busverbindung hergestellt und geprueft"),
    ("Physikalische Adresse", "Physikalische Adresse programmiert"),
    ("Applikation", "Applikationsprogramm geladen"),
    ("Funktion Schalten", "Schaltfunktion E/A getestet"),
    ("Funktion Dimmen", "Dimmfunktion getestet (falls vorhanden)"),
    ("Funktion Jalousie", "Jalousie AUF/AB getestet (falls vorhanden)"),
    ("Funktion Heizung", "Heizungsregelung getestet (falls vorhanden)"),
    ("Rueckmeldung", "Rückmeldungen (LED/Status) prüfen"),
    ("Szenen", "Szenen-Aufrufe getestet (falls vorhanden)"),
]


class DocumentationService:
    """Erzeugt Dokumentation für KNX-Projekte."""

    def __init__(self, project: KnxProject, company_profile=None):
        self.project = project
        self._company_profile = company_profile

    def _make_pdf(self, title: str) -> PdfGenerator:
        """Erstellt PdfGenerator mit Firmenprofil und Projektdaten."""
        return PdfGenerator(
            title=title,
            company_profile=self._company_profile,
            project_info=self.project.project_info,
        )

    # -- Inbetriebnahme-Checkliste (FA-1901) --

    def create_checklists(self) -> list[CommissioningChecklist]:
        """Erzeugt Inbetriebnahme-Checklisten für alle Räume (FA-1901) +
        DALI-Notlicht-Prüfpunkte (FA-2804).

        Liefert strukturierte Items (ITEM_KIND_DEVICE + ITEM_KIND_FUNCTION)
        mit be_id-Verknüpfung für die CommissioningView.
        """
        all_rooms = self._checklist_rooms()
        checklists = []
        for room in all_rooms:
            checklist = self._create_room_checklist(room)
            checklists.append(checklist)

        # DALI-Notlicht-Prüfpunkte anhängen (FA-2804)
        if self.project.dali_configs:
            from .dali_service import DaliService
            svc = DaliService()
            dali_checklist = CommissioningChecklist(
                room_id="__dali__",
                room_name="DALI Notbeleuchtung",
                date=datetime.now().strftime("%Y-%m-%d"),
            )
            for gw in self.project.dali_configs.values():
                for item_dict in svc.generate_emergency_checklist_items(gw):
                    dali_checklist.items.append(ChecklistItem(
                        item_kind=ITEM_KIND_DEVICE,
                        check_type=item_dict["category"],
                        description=item_dict["text"],
                        room_id="__dali__",
                        gewerk_code="LDA",
                    ))
            if dali_checklist.items:
                checklists.append(dali_checklist)

        return checklists

    def _create_room_checklist(self, room: Room) -> CommissioningChecklist:
        """Erzeugt eine vollständige Checkliste für einen Raum.

        Pro aktivem Bedienelement:
        - 4 Geräte-Grundprüfungen (item_kind=device)
        - Je eine Funktionsprüfung pro GA-Zuordnung (item_kind=function)
        """
        checklist = CommissioningChecklist(
            room_id=room.id,
            room_name=f"{room.number} {room.name}",
            date=datetime.now().strftime("%Y-%m-%d"),
        )
        active_bes = [be for be in room.bedienelemente if not be.suppressed]
        for be in active_bes:
            be_num = be.participant_number or ""
            # Geräte-Grundprüfungen
            for check_type, description in self._DEVICE_CHECKS:
                checklist.items.append(ChecklistItem(
                    item_kind=ITEM_KIND_DEVICE,
                    check_type=check_type,
                    description=description,
                    room_id=room.id,
                    be_id=be.id,
                    be_type=be.element_type,
                    be_number=be_num,
                ))
            # GA-Funktionsprüfungen
            for fa in be.function_assignments:
                checklist.items.append(ChecklistItem(
                    item_kind=ITEM_KIND_FUNCTION,
                    check_type=fa.button_channel,
                    description=fa.description,
                    function_ga=fa.function_ga,
                    room_id=room.id,
                    be_id=be.id,
                    be_type=be.element_type,
                    be_number=be_num,
                ))
        return checklist

    def init_project_checklists(self) -> int:
        """Initialisiert project.checklists einmalig aus aktuellem Projektstand.

        Überschreibt nichts, falls bereits Checklisten vorhanden sind.
        Gibt Anzahl generierter Items zurück.
        """
        if self.project.checklists:
            return 0
        self.project.checklists = self.create_checklists()
        return sum(len(cl.items) for cl in self.project.checklists)

    def sync_project_checklists(self) -> tuple[int, int]:
        """Gleicht project.checklists mit aktuellem Projektstand ab.

        Neue Räume/BEs/GAs werden hinzugefügt.
        Bestehende Items mit Ergebnissen bleiben unverändert.
        Gibt (hinzugefügt, gesamt) zurück.
        """
        fresh = self.create_checklists()
        added = 0

        for fresh_cl in fresh:
            existing_cl = next(
                (c for c in self.project.checklists if c.room_id == fresh_cl.room_id),
                None,
            )
            if existing_cl is None:
                self.project.checklists.append(fresh_cl)
                added += len(fresh_cl.items)
                continue

            existing_cl.room_name = fresh_cl.room_name
            existing_keys = {
                (i.be_type, i.be_number, i.check_type, i.function_ga)
                for i in existing_cl.items
            }
            # be_id-Lookup: vorhandene UUID für (be_type, be_number) übernehmen,
            # da auto_assign_functions bei jedem Aufruf neue UUIDs vergibt.
            known_be_ids: dict[tuple, str] = {
                (i.be_type, i.be_number): i.be_id
                for i in existing_cl.items
                if i.be_id
            }
            for item in fresh_cl.items:
                key = (item.be_type, item.be_number, item.check_type, item.function_ga)
                if key not in existing_keys:
                    be_key = (item.be_type, item.be_number)
                    if be_key in known_be_ids:
                        item.be_id = known_be_ids[be_key]
                    existing_cl.items.append(item)
                    added += 1

        total = sum(len(cl.items) for cl in self.project.checklists)
        return added, total

    # Spaltenköpfe (geteilt zwischen PDF und Excel)
    _DEV_HEADERS = ["Prüfpunkt", "Beschreibung", "OK", "Bemerkung"]
    _FN_HEADERS  = ["Kanal", "GA-Bezeichnung", "Funktion", "OK", "Bemerkung"]
    _DEVICE_CHECKS = [
        ("Montage",           "Gerät montiert und beschriftet"),
        ("Physik. Adresse",   "Physikalische Adresse programmiert"),
        ("Applikation",       "Applikationsprogramm geladen"),
        ("Kommunikation",     "Bustelegramme empfangen und gesendet"),
    ]

    # Einheitliches 5-Spalten-Layout für Excel-Checklisten
    # Beide Tabellentypen (Geräteprüfung + GA-Funktionen) teilen dieselben Spalten,
    # damit OK und Bemerkung immer in der gleichen Spalte landen.
    _XL_HEADERS   = ["Typ / Kanal", "Prüfpunkt / GA", "Beschreibung / Funktion",
                      "OK", "Bemerkung"]
    _XL_COL_WIDTHS = [16, 28, 32, 6, 34]   # A–E in Zeichen
    _XL_CENTER_COLS = [4]                   # OK-Spalte zentrieren
    _XL_WRAP_COLS   = [3, 5]               # Beschreibung + Bemerkung umbrechen
    _XL_CHECKBOX    = "☐"

    def _checklist_rooms(self):
        """Aktualisiert Funktionszuordnungen und gibt alle Räume zurück."""
        from .sensor_service import SensorService
        all_rooms = self.project.all_rooms
        SensorService().auto_assign_functions(all_rooms, self.project.group_addresses)
        return all_rooms

    def export_checklists_pdf(self, filepath: str,
                              checklists: list[CommissioningChecklist] | None = None):
        """Exportiert Inbetriebnahme-Checklisten als PDF (FA-1904).

        Struktur: Raum → Sensor/Bedienelement → Geräte-Grundprüfungen + GA-Funktionen.
        """
        all_rooms = self._checklist_rooms()

        pdf = self._make_pdf("Inbetriebnahme-Checkliste")
        pdf.add_heading("Inbetriebnahme-Checkliste", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | "
            f"Datum: {datetime.now().strftime('%d.%m.%Y')}"
        )
        pdf.add_separator()

        for room in all_rooms:
            pdf.add_heading(f"{room.number}  {room.name}", level=2)

            active_bes = [be for be in room.bedienelemente if not be.suppressed]
            if not active_bes:
                pdf.add_paragraph("Keine Bedienelemente zugeordnet.")
                continue

            for be in active_bes:
                addr = f"  [{be.participant_number}]" if be.participant_number else ""
                pdf.add_heading(f"{be.element_type}{addr}", level=3)

                # Geräte-Grundprüfungen
                dev_rows = [[pt, desc, "[ ]", ""] for pt, desc in self._DEVICE_CHECKS]
                pdf.add_table(self._DEV_HEADERS, dev_rows)

                # GA-Funktionsprüfungen
                if be.function_assignments:
                    fn_rows = [
                        [fa.button_channel, fa.function_ga, fa.description, "[ ]", ""]
                        for fa in be.function_assignments
                    ]
                    pdf.add_table(self._FN_HEADERS, fn_rows)

            pdf.add_conditional_break(min_height=80)

        # DALI-Notlicht-Prüfpunkte (FA-2804)
        if self.project.dali_configs:
            from .dali_service import DaliService
            svc = DaliService()
            pdf.add_heading("DALI Notbeleuchtung", level=2)
            for gw in self.project.dali_configs.values():
                rows = [
                    [d["category"], d["text"], "[ ]", ""]
                    for d in svc.generate_emergency_checklist_items(gw)
                ]
                if rows:
                    pdf.add_table(self._DEV_HEADERS, rows)

        pdf.save(filepath)
        logger.info(f"Checklisten exportiert: {filepath}")

    def export_checklists_excel(self, filepath: str,
                                checklists: list[CommissioningChecklist] | None = None):
        """Exportiert Inbetriebnahme-Checklisten als Excel (FA-1904).

        Verwendet gespeicherte Ergebnisse aus project.checklists wenn vorhanden,
        sonst leere ☐-Checkboxen. Layout: einheitliches 5-Spalten-Schema.
        """
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl wird für Excel-Export benoetigt.")

        # Gespeicherte Ergebnisse: (room_id, be_type, be_number, check_type, function_ga) → item
        saved: dict[tuple, ChecklistItem] = {}
        for cl in self.project.checklists:
            for item in cl.items:
                saved[(item.room_id, item.be_type, item.be_number,
                       item.check_type, item.function_ga)] = item

        def _result_cell(item: ChecklistItem | None) -> str:
            if item is None or not item.result:
                return self._XL_CHECKBOX
            return {"OK": "✓ OK", "Mangel": "⚠ Mangel", "n/a": "–"}.get(
                item.result, self._XL_CHECKBOX
            )

        def _notes(item: ChecklistItem | None) -> str:
            return item.notes if item else ""

        all_rooms = self._checklist_rooms()

        excel = ExcelGenerator(
            title="Inbetriebnahme-Checkliste",
            project_name=self.project.name,
        )
        excel.set_column_widths(self._XL_COL_WIDTHS)
        excel.set_print_options(orientation="landscape")
        excel.add_header()
        excel.add_heading("Inbetriebnahme-Checkliste", level=1)
        excel.add_empty_row()

        for room in all_rooms:
            excel.add_heading(f"{room.number}  {room.name}", level=2)
            active_bes = [be for be in room.bedienelemente if not be.suppressed]
            if not active_bes:
                excel.add_paragraph("Keine Bedienelemente zugeordnet.")
                excel.add_empty_row(height=4)
                continue

            for be in active_bes:
                addr = f"  [{be.participant_number}]" if be.participant_number else ""
                excel.add_heading(f"{be.element_type}{addr}", level=3)

                be_num = be.participant_number or ""
                rows = []
                for pt, desc in self._DEVICE_CHECKS:
                    it = saved.get((room.id, be.element_type, be_num, pt, ""))
                    rows.append(["", pt, desc, _result_cell(it), _notes(it)])

                for fa in be.function_assignments:
                    it = saved.get((room.id, be.element_type, be_num,
                                    fa.button_channel, fa.function_ga))
                    rows.append([
                        fa.button_channel, fa.function_ga, fa.description,
                        _result_cell(it), _notes(it),
                    ])

                if rows:
                    excel.add_table(
                        self._XL_HEADERS, rows,
                        center_cols=self._XL_CENTER_COLS,
                        wrap_cols=self._XL_WRAP_COLS,
                        data_row_height=20,
                    )
                excel.add_empty_row(height=4)

        # DALI-Notlicht-Prüfpunkte (FA-2804)
        if self.project.dali_configs:
            from .dali_service import DaliService
            svc = DaliService()
            excel.add_heading("DALI Notbeleuchtung", level=2)
            for gw in self.project.dali_configs.values():
                rows = [
                    ["", d["category"], d["text"],
                     _result_cell(saved.get(("__dali__", "", d["category"], ""))),
                     _notes(saved.get(("__dali__", "", d["category"], "")))]
                    for d in svc.generate_emergency_checklist_items(gw)
                ]
                if rows:
                    excel.add_table(
                        self._XL_HEADERS, rows,
                        center_cols=self._XL_CENTER_COLS,
                        wrap_cols=self._XL_WRAP_COLS,
                        data_row_height=20,
                    )
            excel.add_empty_row()

        excel.save(filepath)
        logger.info(f"Checklisten Excel exportiert: {filepath}")

    # -- Abnahmeprotokoll (FA-1911) --

    def create_acceptance_protocol(self, integrator_name: str = "",
                                   client_name: str = "",
                                   ) -> AcceptanceProtocol:
        """Erzeugt ein leeres Abnahmeprotokoll (FA-1911)."""
        protocol = AcceptanceProtocol(
            date=datetime.now().strftime("%Y-%m-%d"),
            integrator_name=integrator_name,
            client_name=client_name,
            checklists=self.create_checklists(),
        )
        return protocol

    def export_acceptance_protocol(self, filepath: str,
                                   protocol: AcceptanceProtocol | None = None):
        """Exportiert das Abnahmeprotokoll als PDF/Text (FA-1914)."""
        if protocol is None:
            protocol = self.create_acceptance_protocol()

        pdf = self._make_pdf("Abnahmeprotokoll")

        pdf.add_heading("Abnahmeprotokoll", level=1)
        pdf.add_separator()

        # Projektdaten
        pdf.add_heading("Projektdaten", level=2)
        pdf.add_paragraph(f"Projekt: {self.project.name}")
        pdf.add_paragraph(f"Projektnummer: {self.project.project_number}")
        pdf.add_paragraph(f"Datum: {protocol.date}")
        pdf.add_paragraph(f"Integrator: {protocol.integrator_name}")
        pdf.add_paragraph(f"Bauherr/Auftraggeber: {protocol.client_name}")
        pdf.add_separator()

        # Zusammenfassung der Checklisten
        pdf.add_heading("Prüfergebnisse", level=2)
        total_items = sum(len(cl.items) for cl in protocol.checklists)
        ok_items = sum(
            sum(1 for i in cl.items if i.result == "OK")
            for cl in protocol.checklists
        )
        mangel_items = sum(
            sum(1 for i in cl.items if i.result == "Mangel")
            for cl in protocol.checklists
        )
        open_items = total_items - ok_items - mangel_items

        pdf.add_paragraph(f"Gepruefte Punkte: {total_items}")
        pdf.add_paragraph(f"OK: {ok_items}")
        pdf.add_paragraph(f"Mängel: {mangel_items}")
        pdf.add_paragraph(f"Noch offen: {open_items}")
        pdf.add_separator()

        # Mängelliste
        if protocol.defects:
            pdf.add_heading("Mängelliste", level=2)
            headers = ["Nr.", "Raum", "Gewerk", "Mangel", "Prioritaet", "Status"]
            rows = []
            catalog = self.project.gewerk_catalog
            for defect in protocol.defects:
                code = defect.gewerk_code or "-"
                if defect.gewerk_code:
                    gw = catalog.get(defect.gewerk_code)
                    code = f"{defect.gewerk_code} – {gw.name}" if gw and gw.name else defect.gewerk_code
                rows.append([
                    str(defect.number),
                    defect.room_name,
                    code,
                    defect.description[:40],
                    defect.priority,
                    defect.status,
                ])
            pdf.add_table(headers, rows)

        # Ergebnis
        pdf.add_heading("Ergebnis", level=2)
        pdf.add_paragraph(f"Abnahmeentscheid: {protocol.result or '(noch offen)'}")
        if protocol.notes:
            pdf.add_paragraph(f"Bemerkungen: {protocol.notes}")
        pdf.add_separator()

        # Unterschriftenfelder
        pdf.add_heading("Unterschriften", level=2)
        pdf.add_paragraph("")
        pdf.add_paragraph("_________________________     _________________________")
        pdf.add_paragraph("Integrator                    Bauherr/Auftraggeber")
        pdf.add_paragraph(f"{protocol.integrator_name:25s}     {protocol.client_name}")

        pdf.save(filepath)
        logger.info(f"Abnahmeprotokoll exportiert: {filepath}")

    # -- Bedienungsanleitung (FA-2001) --

    # Gewerk-Beschreibungen nach Sprache (FA-2006)
    GEWERK_DESCRIPTIONS = {
        "de": {
            "L": "Licht (schaltbar): Ein/Aus ueber Taster",
            "LD": "Licht (dimmbar): Ein/Aus und Dimmen ueber Taster",
            "LDA": "Licht (dimmbar DALI): Ein/Aus und Dimmen",
            "J": "Jalousie/Beschattung: AUF/AB und Lamellen-Verstellung",
            "R": "Rolladen: AUF/AB ueber Taster",
            "H": "Heizung: Temperaturregelung (Soll/Ist)",
            "M": "Markise: AUF/AB ueber Taster",
            "T": "Tuerkommunikation",
            "A": "Alarm/Sicherheit",
            "S": "Storen: AUF/AB ueber Taster",
        },
        "en": {
            "L": "Light (switchable): On/Off via push button",
            "LD": "Light (dimmable): On/Off and dimming via push button",
            "LDA": "Light (dimmable DALI): On/Off and dimming",
            "J": "Blinds/Shading: UP/DOWN and slat adjustment",
            "R": "Roller shutter: UP/DOWN via push button",
            "H": "Heating: Temperature control (setpoint/actual)",
            "M": "Awning: UP/DOWN via push button",
            "T": "Door communication",
            "A": "Alarm/Security",
            "S": "Shutters: UP/DOWN via push button",
        },
        "fr": {
            "L": "Eclairage (commutable): Marche/Arret par bouton-poussoir",
            "LD": "Eclairage (variateur): Marche/Arret et variation par bouton-poussoir",
            "LDA": "Eclairage (variateur DALI): Marche/Arret et variation",
            "J": "Store/Ombrage: MONTER/DESCENDRE et orientation des lamelles",
            "R": "Volet roulant: MONTER/DESCENDRE par bouton-poussoir",
            "H": "Chauffage: Regulation de temperature (consigne/effective)",
            "M": "Marquise: MONTER/DESCENDRE par bouton-poussoir",
            "T": "Communication de porte",
            "A": "Alarme/Securite",
            "S": "Stores: MONTER/DESCENDRE par bouton-poussoir",
        },
    }

    MANUAL_TEXTS = {
        "de": {
            "title": "Bedienungsanleitung",
            "general_hints": "Allgemeine Hinweise",
            "intro": "Diese Anleitung beschreibt die Bedienung Ihrer KNX-Installation nach Räumen gegliedert.",
            "contact": "Bei Problemen kontaktieren Sie bitte Ihren KNX-Systemintegrator.",
            "room": "Raum",
            "buttons": "Taster und Bedienelemente",
            "scenes": "Szenen",
            "project": "Projekt",
            "created": "Erstellt",
        },
        "en": {
            "title": "User Manual",
            "general_hints": "General Information",
            "intro": "This manual describes the operation of your KNX installation, organized by room.",
            "contact": "In case of problems, please contact your KNX system integrator.",
            "room": "Room",
            "buttons": "Push buttons and controls",
            "scenes": "Scenes",
            "project": "Project",
            "created": "Created",
        },
        "fr": {
            "title": "Manuel d'utilisation",
            "general_hints": "Informations generales",
            "intro": "Ce manuel decrit le fonctionnement de votre installation KNX, organise par piece.",
            "contact": "En cas de probleme, veuillez contacter votre integrateur systeme KNX.",
            "room": "Piece",
            "buttons": "Boutons-poussoirs et commandes",
            "scenes": "Scenes",
            "project": "Projet",
            "created": "Cree le",
        },
    }

    def generate_user_manual(self, filepath: str, language: str = "de",
                             custom_intro: str = "",
                             include_scenes: bool = True):
        """Erzeugt eine raumweise Bedienungsanleitung (FA-2001, FA-2002, FA-2005, FA-2006)."""
        texts = self.MANUAL_TEXTS.get(language, self.MANUAL_TEXTS["de"])
        gewerk_descs = self.GEWERK_DESCRIPTIONS.get(language, self.GEWERK_DESCRIPTIONS["de"])

        pdf = self._make_pdf(f"{texts['title']} KNX-Installation")

        pdf.add_heading(texts["title"], level=1)
        pdf.add_paragraph(f"{texts['project']}: {self.project.name}")
        pdf.add_paragraph(
            f"{texts['created']}: {datetime.now().strftime('%d.%m.%Y')}"
        )
        pdf.add_separator()

        # Allgemeine Hinweise
        pdf.add_heading(texts["general_hints"], level=2)
        if custom_intro:
            pdf.add_paragraph(custom_intro)
        else:
            pdf.add_paragraph(texts["intro"])
        pdf.add_paragraph(texts["contact"])
        pdf.add_separator()

        # Pro Raum
        rooms = self.project.all_rooms
        for room in rooms:
            if not room.gewerk_assignments and not room.bedienelemente:
                continue

            pdf.add_heading(
                f"{texts['room']}: {room.number} {room.name}",
                level=2,
            )

            for ga in room.gewerk_assignments:
                desc = gewerk_descs.get(
                    ga.gewerk_code,
                    f"Gewerk {ga.gewerk_code}",
                )
                pdf.add_paragraph(f"  - {desc} ({ga.count}x)")

            # Sensoren / Taster
            if room.bedienelemente:
                pdf.add_heading(texts["buttons"], level=3)
                for sensor in room.bedienelemente:
                    pn = f" [{sensor.participant_number}]" if sensor.participant_number else ""
                    pdf.add_paragraph(
                        f"  {sensor.element_type}{pn} ({sensor.channels}-Kanal): "
                        f"{sensor.product_name or sensor.manufacturer or '-'}"
                    )
                    if sensor.function_assignments:
                        for fa in sensor.function_assignments:
                            pdf.add_paragraph(
                                f"    {fa.button_channel}: {fa.function_ga} "
                                f"({fa.description})"
                            )

            # Szenen (FA-2005)
            if include_scenes and hasattr(self.project, 'scenes'):
                room_scenes = [s for s in self.project.scenes
                               if s.scope == "room" and
                               getattr(s, 'room_id', '') == room.id]
                if room_scenes:
                    pdf.add_heading(texts["scenes"], level=3)
                    for scene in room_scenes:
                        pdf.add_paragraph(
                            f"  {scene.name}: {len(scene.actions)} Aktionen"
                        )

            pdf.add_separator()

        pdf.save(filepath)
        logger.info(f"Bedienungsanleitung erstellt: {filepath}")

    # -- Revisionspaket (FA-2100) --

    def generate_revision_package(self, output_dir: str, revision: str = "",
                                   language: str = "de"):
        """Erzeugt ein komplettes Revisionspaket (FA-2101, FA-2105, FA-2106)."""
        os.makedirs(output_dir, exist_ok=True)

        project_name = self.project.name or "Projekt"
        prefix = project_name.replace(" ", "_")
        if revision:
            prefix = f"{prefix}_Rev{revision}"

        generated_files = []

        # 1. Projektzusammenfassung
        from .report_service import ReportService
        report_svc = ReportService(self.project)
        path = os.path.join(output_dir, f"{prefix}_Zusammenfassung.pdf")
        report_svc.generate_project_summary(path)
        generated_files.append(("Projektzusammenfassung", path))

        # 2. GA-Übersicht
        path = os.path.join(output_dir, f"{prefix}_GA_Uebersicht.pdf")
        report_svc.generate_ga_report(path)
        generated_files.append(("Gruppenadress-Übersicht", path))

        # 3. Topologie-Bericht
        path = os.path.join(output_dir, f"{prefix}_Topologie.pdf")
        report_svc.generate_topology_report(path)
        generated_files.append(("Topologie-Bericht", path))

        # 4. Bedienelemente-Bericht
        path = os.path.join(output_dir, f"{prefix}_Bedienelemente.pdf")
        report_svc.generate_bedienelemente_report(path)
        generated_files.append(("Bedienelemente", path))

        # 5. Validierungsbericht
        path = os.path.join(output_dir, f"{prefix}_Validierung.pdf")
        report_svc.generate_validation_report(path)
        generated_files.append(("Validierungsbericht", path))

        # 6. Inbetriebnahme-Checklisten
        checklists = self.create_checklists()
        path = os.path.join(output_dir, f"{prefix}_Checklisten.pdf")
        self.export_checklists_pdf(path, checklists)
        generated_files.append(("Inbetriebnahme-Checklisten", path))

        # 7. Bedienungsanleitung
        path = os.path.join(output_dir, f"{prefix}_Bedienungsanleitung.pdf")
        self.generate_user_manual(path, language=language)
        generated_files.append(("Bedienungsanleitung", path))

        # 8. CSV-Export
        from .csv_export_service import CsvExportService
        csv_svc = CsvExportService()
        path = os.path.join(output_dir, f"{prefix}_GA_Export.csv")
        csv_svc.export_csv(
            self.project.group_addresses, path, overwrite=True
        )
        generated_files.append(("GA-Export (CSV)", path))

        # 9. DALI-Geräteliste (FA-2805) – nur wenn DALI-Konfigurationen vorhanden
        if self.project.dali_configs:
            path = os.path.join(output_dir, f"{prefix}_DALI_Geraete.pdf")
            self.generate_dali_device_list(path)
            generated_files.append(("DALI-Gerätekonfiguration", path))

        # 10. Zeitprogramme (FA-3307) – nur wenn Zeitprogramme vorhanden
        if self.project.time_programs:
            path = os.path.join(output_dir, f"{prefix}_Zeitprogramme.pdf")
            self.generate_time_programs_doc(path)
            generated_files.append(("Zeitprogramme", path))

        # 11. Inhaltsverzeichnis (FA-2103)
        index_path = self.create_revision_index(
            output_dir, revision, generated_files
        )

        logger.info(f"Revisionspaket erstellt in: {output_dir}")
        return output_dir

    def generate_dali_device_list(self, filepath: str):
        """Erzeugt die DALI-Geräteliste für das Revisionspaket (FA-2805)."""
        from .dali_service import DaliService
        svc = DaliService()
        pdf = self._make_pdf("DALI-Gerätekonfiguration")
        pdf.add_heading("DALI-Gerätekonfiguration", level=1)
        pdf.add_paragraph(f"Projekt: {self.project.name}")
        pdf.add_paragraph(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

        if not self.project.dali_configs:
            pdf.add_paragraph("Keine DALI-Konfigurationen vorhanden.")
        else:
            for gw_id, gw in self.project.dali_configs.items():
                pdf.add_separator()
                pdf.add_heading(f"DALI-Gateway: {gw.name}", level=2)
                pdf.add_paragraph(f"Device-ID: {gw_id}")
                if gw.ga_switch_broadcast:
                    pdf.add_paragraph(f"GA Schalten (Broadcast): {gw.ga_switch_broadcast}")
                if gw.ga_dim_broadcast:
                    pdf.add_paragraph(f"GA Dimmen (Broadcast): {gw.ga_dim_broadcast}")
                if gw.ga_scene:
                    pdf.add_paragraph(f"GA Szene: {gw.ga_scene}")

                rows = svc.generate_device_list(gw, self.project)
                if rows:
                    headers = ["Adr.", "Name", "EVG-Typ", "Raum", "Gruppen", "Notlicht", "Modus"]
                    table_rows = [
                        [
                            str(r["short_address"]), r["name"], r["evg_type"],
                            r["room"], r["groups"],
                            "Ja" if r["is_emergency"] else "",
                            r["emergency_mode"] if r["is_emergency"] else "",
                        ]
                        for r in rows
                    ]
                    pdf.add_table(headers, table_rows)
                else:
                    pdf.add_paragraph("Keine EVGs konfiguriert.")

        pdf.save(filepath)
        logger.info(f"DALI-Geräteliste erstellt: {filepath}")

    def generate_time_programs_doc(self, filepath: str):
        """Erzeugt die Zeitprogramm-Dokumentation für das Revisionspaket (FA-3307)."""
        pdf = self._make_pdf("Zeitprogramme")
        pdf.add_heading("Zeitprogramme / Wochenprogramme", level=1)
        pdf.add_paragraph(f"Projekt: {self.project.name}")
        pdf.add_paragraph(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

        loc = self.project.location
        pdf.add_paragraph(
            f"Standort: {loc.latitude:.4f}°N / {loc.longitude:.4f}°O "
            f"({loc.country}, {loc.region})"
        )

        if not self.project.time_programs:
            pdf.add_paragraph("Keine Zeitprogramme konfiguriert.")
        else:
            for tp in self.project.time_programs:
                pdf.add_separator()
                status = "aktiv" if tp.active else "inaktiv"
                pdf.add_heading(f"{tp.name} ({status})", level=2)
                pdf.add_paragraph(
                    f"Schaltzeitpunkte gesamt: {tp.switch_point_count}  |  "
                    f"Tagesprofile: {len(tp.day_profiles)}"
                )
                for i, dp in enumerate(tp.day_profiles):
                    days = ", ".join(dp.weekdays) or "—"
                    pdf.add_heading(f"Tagesprofil {i+1}: {days}", level=3)
                    if not dp.switch_points:
                        pdf.add_paragraph("Keine Schaltzeitpunkte.")
                        continue
                    headers = ["Zeit", "Art", "Wert", "GA", "Priorität"]
                    rows = []
                    for sp in sorted(dp.switch_points,
                                     key=lambda s: s.fixed_time if s.time_type == "FIXED" else ""):
                        ga_label = ""
                        if sp.target_ga_id:
                            ga = next(
                                (g for g in self.project.group_addresses.all_addresses()
                                 if g.id == sp.target_ga_id), None
                            )
                            ga_label = (
                                f"{ga.main_group}/{ga.middle_group}/{ga.sub_group} "
                                f"{ga.designation}"
                            ) if ga else sp.target_ga_id
                        rows.append([
                            sp.display_time, sp.time_type,
                            sp.action_value, ga_label, sp.priority,
                        ])
                    pdf.add_table(headers, rows)

        pdf.save(filepath)
        logger.info(f"Zeitprogramme-Dokumentation erstellt: {filepath}")

    def create_revision_index(self, output_dir: str, revision: str,
                              generated_files: list[tuple[str, str]]) -> str:
        """Erzeugt ein Inhaltsverzeichnis für das Revisionspaket (FA-2103)."""
        project_name = self.project.name or "Projekt"
        prefix = project_name.replace(" ", "_")
        if revision:
            prefix = f"{prefix}_Rev{revision}"

        index_path = os.path.join(output_dir, f"{prefix}_Inhaltsverzeichnis.pdf")

        pdf = self._make_pdf("Revisionspaket - Inhaltsverzeichnis")

        pdf.add_heading("Revisionspaket - Inhaltsverzeichnis", level=1)
        pdf.add_paragraph(f"Projekt: {self.project.name}")
        if revision:
            pdf.add_paragraph(f"Revision: {revision}")
        pdf.add_paragraph(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        pdf.add_separator()

        headers = ["Nr.", "Dokument", "Dateiname"]
        rows = []
        for i, (doc_name, filepath) in enumerate(generated_files, 1):
            rows.append([str(i), doc_name, os.path.basename(filepath)])
        pdf.add_table(headers, rows)

        pdf.save(index_path)
        logger.info(f"Inhaltsverzeichnis erstellt: {index_path}")
        return index_path
