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
from .report_sorting import physical_address_key, sorted_rooms
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

        # Verteiler-Geräte (Aktoren, Gateways, Koppler, Netzteile) anhängen
        checklists.extend(self._create_verteiler_checklists())

        return checklists

    # Gerätetypen mit physikalischer Adresse, die im Verteiler sitzen und
    # nicht über room.bedienelemente erfasst werden (Aktoren sind keine BEs).
    _VERTEILER_DEVICE_TYPES = ("actor", "gateway", "coupler", "power_supply")

    def _verteiler_devices_by_location(self) -> dict[str, list]:
        """Gruppiert alle Verteiler-Geräte (Aktoren/Gateways/Koppler/Netzteile)
        nach Einbauort (UV/HV), sortiert nach Ortsname."""
        by_location: dict[str, list] = {}
        for area in self.project.topology.areas:
            for line in area.lines:
                for device in line.devices:
                    if device.device_type not in self._VERTEILER_DEVICE_TYPES:
                        continue
                    location = device.installation_location or "Nicht zugeordnet"
                    by_location.setdefault(location, []).append(device)
        return dict(sorted(by_location.items()))

    def _create_verteiler_checklists(self) -> list[CommissioningChecklist]:
        """Geräte-Grundprüfungen für Verteiler-Geräte, gruppiert nach UV/HV.

        Aktoren, Gateways, Koppler und Netzteile sitzen im Verteiler statt im
        Raum und tauchen daher nicht in room.bedienelemente auf – sie haben
        aber ebenfalls eine physikalische Adresse und ein Applikationsprogramm,
        die bei der Inbetriebnahme geprüft werden müssen.
        """
        checklists = []
        for location, devices in self._verteiler_devices_by_location().items():
            room_id = f"__verteiler__{location}"
            checklist = CommissioningChecklist(
                room_id=room_id,
                room_name=f"Verteiler {location}",
                date=datetime.now().strftime("%Y-%m-%d"),
            )
            for idx, device in enumerate(devices):
                dev_number = device.physical_address or f"#{idx + 1}"
                for check_type, description in self._DEVICE_CHECKS:
                    checklist.items.append(ChecklistItem(
                        item_kind=ITEM_KIND_DEVICE,
                        check_type=check_type,
                        description=description,
                        room_id=room_id,
                        be_type=device.product or device.device_type,
                        be_number=dev_number,
                        gewerk_code=device.device_type,
                    ))
            if checklist.items:
                checklists.append(checklist)
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

    # Geräte-Grundprüfungen (Erfassung in der Inbetriebnahme-Ansicht je Punkt)
    _DEVICE_CHECKS = [
        ("Montage",           "Gerät montiert und beschriftet"),
        ("Physik. Adresse",   "Physikalische Adresse programmiert"),
        ("Applikation",       "Applikationsprogramm geladen"),
        ("Kommunikation",     "Bustelegramme empfangen und gesendet"),
    ]
    _DEVICE_CHECK_TEXT = ("montiert und beschriftet · physikalische Adresse · "
                          "Applikation geladen · Kommunikation")

    # Ausdruck (PDF/Excel): eine Zeile je Taste, breite Bemerkungsspalte
    _CL_HEADERS = ["Taste", "Funktion", "Gruppenadressen", "OK", "Bemerkung"]
    _CL_PDF_WIDTHS = [0.09, 0.24, 0.31, 0.06, 0.30]
    _CL_XL_WIDTHS = [10, 30, 42, 8, 46]   # A–E in Zeichen
    _XL_CENTER_COLS = [4]                 # OK-Spalte zentrieren
    _XL_WRAP_COLS = [2, 3, 5]
    _XL_CHECKBOX = "☐"

    def _checklist_rooms(self):
        """Alle Räume mit aktuellen Funktionszuordnungen – aus einer Kopie,
        damit das Erzeugen von Checklisten das Projekt nicht verändert."""
        from .sensor_service import project_for_export
        export_project = project_for_export(self.project)
        return sorted_rooms(export_project.areal)

    def _checklist_sections(self):
        """Inhalt des Ausdrucks: [(Stockwerk, Raum, [(Titel, Zeilen)])].

        Zeile = (Taste, Funktion, Gruppenadressen, Ergebnis-Schlüssel). Je
        Taste eine Zeile mit allen GAs (Befehl, LED); die Funktion wie in der
        Bedienungsanleitung (gesteuertes Objekt, eigene Bezeichnung). Die
        Schlüssel verweisen auf die je GA erfassten Ergebnisse der
        Inbetriebnahme-Ansicht (room_id, be_type, be_number, Kanal, GA)."""
        from .sensor_service import project_for_export
        from .user_manual import UserManualBuilder
        from .bedienelement_layout import group_assignments, parse_button
        from .report_service import _ga_line

        project = project_for_export(self.project)
        builder = UserManualBuilder(project, snapshot=False)
        imported = project.topology.is_imported
        floor_by_room = {}
        for building in project.areal.buildings:
            for wing in building.wings:
                for floor in wing.floors:
                    for apt in floor.apartments:
                        for room in apt.rooms:
                            floor_by_room[room.id] = floor.name

        sections = []
        for room in sorted_rooms(project.areal):
            cards = []
            for be in room.bedienelemente:
                if not be.is_shown(imported):
                    continue
                be_num = be.participant_number or ""
                rows = []
                dev_keys = [(room.id, be.element_type, be_num, pt, "")
                            for pt, _ in self._DEVICE_CHECKS]
                rows.append(("Gerät", "Grundprüfung", self._DEVICE_CHECK_TEXT, dev_keys))
                labels = {}
                if be.function_assignments:
                    try:
                        labels = {(kl.key.number, kl.key.side): kl.label
                                  for kl in builder.key_lines(be, room.name)}
                    except Exception:
                        labels = {}
                fa_keys: dict[tuple, list] = {}
                for fa in be.function_assignments:
                    parsed = parse_button(fa.button_channel)
                    k = ((parsed[0].number, parsed[0].side, parsed[0].variant)
                         if parsed else ("~", fa.button_channel or fa.description))
                    fa_keys.setdefault(k, []).append(
                        (room.id, be.element_type, be_num, fa.button_channel, fa.function_ga))
                for row in group_assignments(be.function_assignments, builder._resolve):
                    if row.key is None:
                        k = ("~", row.name)
                        taste, function = "–", row.name
                    else:
                        k = (row.key.number, row.key.side, row.key.variant)
                        taste = row.key.label()
                        function = labels.get((row.key.number, row.key.side), "") \
                            if not row.key.variant else ""
                        function = function or (
                            "langer Tastendruck" if row.key.variant == "lang"
                            else row.key.variant or "–")
                    gas = "\n".join(_ga_line(g) for g in row.gas)
                    if row.led_gas:
                        gas += "\n" + "\n".join("LED: " + _ga_line(g) for g in row.led_gas)
                    rows.append((taste, function, gas.strip() or "–", fa_keys.get(k, [])))
                device = builder.device_by_addr.get(be_num)
                product = (device.product_name or device.product) if device else be.product_name
                title = " · ".join(p for p in (be_num or "ohne Adresse",
                                               be.element_type or "Bedienelement", product) if p)
                cards.append((title, rows))
            if cards:
                floor = floor_by_room.get(room.id, "") or "Ohne Stockwerk"
                sections.append((floor, f"{room.number} {room.name}".strip(), cards))
        return sections

    def _saved_results(self) -> dict[tuple, ChecklistItem]:
        saved: dict[tuple, ChecklistItem] = {}
        for cl in self.project.checklists:
            for item in cl.items:
                saved[(item.room_id, item.be_type, item.be_number,
                       item.check_type, item.function_ga)] = item
        return saved

    @staticmethod
    def _combined_result(keys: list, saved: dict) -> tuple[str, str]:
        """Ergebnis einer Ausdruckzeile aus den je GA erfassten Punkten:
        ein Mangel -> Mangel, alle OK/n.a. -> OK, sonst offen."""
        items = [saved[k] for k in keys if k in saved]
        notes = "; ".join(dict.fromkeys(i.notes for i in items if i.notes))
        results = [i.result for i in items if i.result]
        if "Mangel" in results:
            return "Mangel", notes
        if items and len(results) == len(items) and all(r in ("OK", "n/a") for r in results):
            return "OK", notes
        return "", notes

    def export_checklists_pdf(self, filepath: str,
                              checklists: list[CommissioningChecklist] | None = None):
        """Inbetriebnahme-Checkliste als PDF (FA-1904): Stockwerk → Raum →
        Gerät, je Taste eine Zeile, breite Bemerkungsspalte; danach die
        Verteiler mit einer Zeile je Gerät."""
        saved = self._saved_results()
        pdf = self._make_pdf("Inbetriebnahme-Checkliste")
        pdf.add_heading("Inbetriebnahme-Checkliste", level=1)
        pdf.add_paragraph(
            f"Projekt: {self.project.name} | Datum: {datetime.now().strftime('%d.%m.%Y')}")
        pdf.add_note("Hinweis:", "Je Taste eine Zeile mit allen Gruppenadressen. "
                                 "OK ankreuzen, Mängel in der Spalte Bemerkung festhalten.")

        def mark(keys):
            result, notes = self._combined_result(keys, saved)
            return {"OK": "[x]", "Mangel": "[!]"}.get(result, "[ ]"), notes

        current_floor = None
        for floor, room_label, cards in self._checklist_sections():
            if floor != current_floor:
                pdf.add_page_break()
                pdf.add_heading(floor, level=2)
                current_floor = floor
            else:
                pdf.add_conditional_break(min_height=140)
            pdf.add_heading(room_label, level=3)
            for title, rows in cards:
                pdf.add_conditional_break(min_height=min(60 + 26 * len(rows), 400))
                pdf.add_card_header(title, "", bookmark=f"{room_label}: {title}")
                table = []
                for taste, function, gas, keys in rows:
                    ok, notes = mark(keys)
                    table.append([taste, function, gas, ok, notes])
                pdf.add_table(self._CL_HEADERS, table, col_widths=self._CL_PDF_WIDTHS)

        # DALI-Notlicht-Prüfpunkte (FA-2804)
        if self.project.dali_configs:
            from .dali_service import DaliService
            svc = DaliService()
            pdf.add_page_break()
            pdf.add_heading("DALI Notbeleuchtung", level=2)
            for gw in self.project.dali_configs.values():
                rows = [[d["category"], d["text"], "", "[ ]", ""]
                        for d in svc.generate_emergency_checklist_items(gw)]
                if rows:
                    pdf.add_table(self._CL_HEADERS, rows, col_widths=self._CL_PDF_WIDTHS)

        # Verteiler: eine Zeile je Gerät
        verteiler = self._verteiler_devices_by_location()
        if verteiler:
            pdf.add_page_break()
            pdf.add_heading("Verteiler", level=2)
            pdf.add_note("Je Gerät:", self._DEVICE_CHECK_TEXT)
            from .report_service import _clean_location
            for location, devices in verteiler.items():
                pdf.add_heading(_clean_location(location), level=3)
                table = []
                for idx, device in enumerate(devices):
                    label = device.product_name or device.product or device.device_type
                    number = device.physical_address or f"#{idx + 1}"
                    keys = [(f"__verteiler__{location}", device.product or device.device_type,
                             number, pt, "") for pt, _ in self._DEVICE_CHECKS]
                    ok, notes = mark(keys)
                    table.append([number, label, "", ok, notes])
                pdf.add_table(["Adresse", "Gerät", "", "OK", "Bemerkung"], table,
                              col_widths=[0.09, 0.45, 0.10, 0.06, 0.30])

        pdf.save(filepath)
        logger.info(f"Checklisten exportiert: {filepath}")

    def export_checklists_excel(self, filepath: str,
                                checklists: list[CommissioningChecklist] | None = None):
        """Inbetriebnahme-Checkliste als Excel (FA-1904), gleiche Gliederung
        wie das PDF; erfasste Ergebnisse je Zeile zusammengefasst."""
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl wird für Excel-Export benötigt.")
        saved = self._saved_results()

        def cell(keys):
            result, notes = self._combined_result(keys, saved)
            return {"OK": "✓ OK", "Mangel": "⚠ Mangel"}.get(result, self._XL_CHECKBOX), notes

        excel = ExcelGenerator(title="Inbetriebnahme-Checkliste", project_name=self.project.name)
        excel.set_column_widths(self._CL_XL_WIDTHS)
        excel.set_print_options(orientation="landscape")
        excel.add_header()
        excel.add_heading("Inbetriebnahme-Checkliste", level=1)
        excel.add_empty_row()

        def table(rows):
            excel.add_table(self._CL_HEADERS, rows, center_cols=self._XL_CENTER_COLS,
                            wrap_cols=self._XL_WRAP_COLS, data_row_height=20)

        current_floor = None
        for floor, room_label, cards in self._checklist_sections():
            if floor != current_floor:
                excel.add_heading(floor, level=1)
                current_floor = floor
            excel.add_heading(room_label, level=2)
            for title, rows in cards:
                excel.add_heading(title, level=3)
                out = []
                for taste, function, gas, keys in rows:
                    ok, notes = cell(keys)
                    out.append([taste, function, gas, ok, notes])
                table(out)
                excel.add_empty_row(height=4)

        if self.project.dali_configs:
            from .dali_service import DaliService
            svc = DaliService()
            excel.add_heading("DALI Notbeleuchtung", level=1)
            for gw in self.project.dali_configs.values():
                rows = [[d["category"], d["text"], "", self._XL_CHECKBOX, ""]
                        for d in svc.generate_emergency_checklist_items(gw)]
                if rows:
                    table(rows)
            excel.add_empty_row()

        verteiler = self._verteiler_devices_by_location()
        if verteiler:
            excel.add_heading("Verteiler", level=1)
            excel.add_paragraph(f"Je Gerät: {self._DEVICE_CHECK_TEXT}")
            from .report_service import _clean_location
            for location, devices in verteiler.items():
                excel.add_heading(_clean_location(location), level=2)
                rows = []
                for idx, device in enumerate(devices):
                    label = device.product_name or device.product or device.device_type
                    number = device.physical_address or f"#{idx + 1}"
                    keys = [(f"__verteiler__{location}", device.product or device.device_type,
                             number, pt, "") for pt, _ in self._DEVICE_CHECKS]
                    ok, notes = cell(keys)
                    rows.append([number, label, "", ok, notes])
                table(rows)
                excel.add_empty_row(height=4)

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

    def generate_user_manual(self, filepath: str, language: str = "de",
                             custom_intro: str = "",
                             include_scenes: bool = True):
        """Erzeugt die Bedienungsanleitung für den Bauherrn (FA-2001 bis
        FA-2004), siehe services/user_manual.py. Derzeit nur Deutsch;
        language und include_scenes bleiben für bestehende Aufrufe erhalten."""
        from .user_manual import UserManualBuilder
        pdf = self._make_pdf("Bedienungsanleitung")
        UserManualBuilder(self.project, self._company_profile).build(pdf, custom_intro)
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
        report_svc = ReportService(self.project, company_profile=self._company_profile)
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
        generated_files.append(("Bedienelemente und Sensoren", path))

        # 4b. Aktoren und Gateways
        path = os.path.join(output_dir, f"{prefix}_Aktoren_Gateways.pdf")
        report_svc.generate_aktoren_gateway_report(path)
        generated_files.append(("Aktoren und Gateways", path))

        # 4c. Räume nach Gewerken
        path = os.path.join(output_dir, f"{prefix}_Raeume_Gewerke.pdf")
        report_svc.generate_room_gewerk_report(path)
        generated_files.append(("Räume nach Gewerken", path))

        # 4d. Verknüpfungsmatrix / Belegungsplan (FA-2505) -- nur wenn Daten vorhanden
        from .belegungsplan_service import BelegungsplanService
        from .sensor_service import project_for_export
        belegungsplan = BelegungsplanService().generate(project_for_export(self.project))
        if belegungsplan.sensor_rows or belegungsplan.actor_rows:
            from .belegungsplan_export_service import BelegungsplanExportService
            path = os.path.join(output_dir, f"{prefix}_Verknuepfungsmatrix.pdf")
            BelegungsplanExportService().export_pdf(
                belegungsplan, path, self._company_profile, self.project.project_info
            )
            generated_files.append(("Verknüpfungsmatrix", path))

        # 4e. Szenenreport (FA-1811) -- nur wenn Szenen definiert sind
        if any(s.name for s in self.project.scenes):
            path = os.path.join(output_dir, f"{prefix}_Szenenreport.pdf")
            report_svc.generate_szenen_report(path)
            generated_files.append(("Szenenreport", path))

        # 5. Validierungsbericht
        path = os.path.join(output_dir, f"{prefix}_Validierung.pdf")
        report_svc.generate_validation_report(path)
        generated_files.append(("Validierungsbericht Gruppenadressen", path))

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

        # 10b. KNX Secure Archivbericht (FA-2706) – nur wenn aktiviert
        if self.project.knx_secure.enabled:
            path = os.path.join(output_dir, f"{prefix}_KNX_Secure.pdf")
            self.generate_knx_secure_report(path)
            generated_files.append(("KNX Secure Archivbericht", path))

        # 11. Inhaltsverzeichnis (FA-2103)
        index_path = self.create_revision_index(
            output_dir, revision, generated_files
        )

        logger.info(f"Revisionspaket erstellt in: {output_dir}")
        return output_dir

    def generate_knx_secure_report(self, filepath: str, include_secrets: bool = False):
        """Erzeugt den KNX-Secure-Archivbericht (FA-2706).

        Dokumentiert den Erfassungsstatus des Zertifikats- und Zugangsdaten-
        Archivs (FDSK je Gerät, ETS6-Projektpasswort) für die Übergabe.

        include_secrets=False (Standard, z.B. im automatischen Revisionspaket):
        die eigentlichen Geheimwerte (FDSK, ETS6-Projektpasswort) werden
        bewusst NICHT abgedruckt -- nur ob sie erfasst sind.

        include_secrets=True (nur auf expliziten Nutzerwunsch, siehe
        ReportsDialog._gen_knx_secure_confidential -- dort wird die Kenntnis
        des ETS6-Projektpassworts vor Erstellung geprüft): druckt die echten
        FDSK- und Passwort-Werte ab, als Vertraulichkeits-Archivkopie für den
        Fall, dass das Master-Passwort des Archivs verloren geht. Der Bericht
        ist dann selbst ein Geheimnis und muss entsprechend vertraulich
        behandelt werden.
        """
        from ..services.knx_secure_service import KnxSecureService, sorted_device_infos
        from ..models.knx_secure import SECURE_MODE_LABELS

        cfg = self.project.knx_secure
        svc = KnxSecureService()

        title = "KNX Secure – Archivbericht (VERTRAULICH)" if include_secrets else "KNX Secure – Archivbericht"
        pdf = self._make_pdf(title)
        pdf.add_heading("KNX Secure – Zertifikats- und Zugangsdaten-Archiv", level=1)
        if include_secrets:
            pdf.add_heading("⚠ VERTRAULICH -- enthält echte FDSK- und Passwort-Werte", level=2)
        pdf.add_paragraph(f"Projekt: {self.project.name}")
        pdf.add_paragraph(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

        if not cfg.enabled:
            pdf.add_paragraph("KNX Secure ist für dieses Projekt nicht aktiviert.")
            pdf.save(filepath)
            return

        pdf.add_paragraph(
            "Hinweis: KNiX Arranger generiert und verwaltet keine KNX-Secure-"
            "Laufzeitschlüssel -- diese erzeugt ausschliesslich ETS6 aus dem "
            "geräteindividuellen Zertifikat (FDSK). " + (
                "Dieser Bericht enthält die tatsächlich hinterlegten Geheimwerte "
                "als Archivkopie -- vertraulich behandeln, nicht ungeschützt "
                "weitergeben oder ablegen."
                if include_secrets else
                "Dieser Bericht dokumentiert nur den Erfassungsstatus des "
                "Archivs, keine Geheimwerte."
            )
        )

        if cfg.is_locked:
            pdf.add_paragraph(
                "⚠ Das Archiv war beim Erstellen dieses Berichts gesperrt "
                "(Master-Passwort nicht eingegeben). Angaben zu FDSK- und "
                "Passwort-Erfassung unten können daher unvollständig sein."
            )

        summary = svc.get_summary(cfg, self.project)
        mode_label = SECURE_MODE_LABELS.get(cfg.secure_mode, cfg.secure_mode)
        pdf.add_separator()
        pdf.add_heading("Projektübersicht", level=2)
        pdf.add_paragraph(f"Sicherheitsmodus: {mode_label}")
        if include_secrets and summary['ets_password_set']:
            pdf.add_paragraph(f"ETS6-Projektpasswort: {cfg.ets_project_password}")
        else:
            pdf.add_paragraph(
                "ETS6-Projektpasswort hinterlegt: "
                f"{'Ja' if summary['ets_password_set'] else 'Nein'}"
            )
        if cfg.ets_password_note:
            pdf.add_paragraph(f"Notiz / Wiederherstellungsplan: {cfg.ets_password_note}")
        pdf.add_paragraph(
            f"KNX Secure-fähige Geräte: {summary['secure_devices']} / {summary['device_infos_count']}"
        )
        pdf.add_paragraph(
            f"FDSK-Zertifikate erfasst: {summary['fdsk_entered']} / {summary['device_infos_count']}"
        )
        pdf.add_paragraph(
            f"Gruppenadressen mit Security 'Ein': {summary['ga_security_on']}"
        )

        pdf.add_separator()
        pdf.add_heading("Geräte", level=2)
        infos = sorted_device_infos(cfg)
        if not infos:
            pdf.add_paragraph("Keine Geräte im Archiv erfasst.")
        else:
            line_labels = {}
            for area in self.project.topology.areas:
                for line in area.lines:
                    line_labels[line.id] = f"{area.area_number}.{line.line_number}"
            headers = ["Gerät", "Phys. Adresse", "Linie", "KNX Secure",
                       "FDSK" if include_secrets else "FDSK erfasst"]
            rows = [
                [
                    info.device_name, info.physical_address,
                    line_labels.get(info.line_id, ""),
                    "Ja" if info.secure_supported else "Nein",
                    (info.fdsk or "–") if include_secrets else ("Ja" if info.fdsk else "Nein"),
                ]
                for info in infos
            ]
            pdf.add_table(headers, rows)

        warnings = svc.check_mixed_lines(cfg, self.project)
        pdf.add_separator()
        pdf.add_heading("Mischlinien-Warnungen", level=2)
        if not warnings:
            pdf.add_paragraph("Keine Mischlinien-Warnungen.")
        else:
            for w in warnings:
                pdf.add_paragraph(f"• {w.message}")

        pdf.save(filepath)
        logger.info(f"KNX-Secure-Archivbericht erstellt: {filepath}")

    def generate_dali_device_list(self, filepath: str):
        """Erzeugt die DALI-Geräteliste für das Revisionspaket (FA-2805)."""
        from .dali_service import DaliService
        svc = DaliService()
        # Gateways nach physikalischer Adresse (dali_configs ist nach
        # Geraete-ID indiziert)
        gateway_address = {
            d.id: d.physical_address
            for area in self.project.topology.areas for line in area.lines for d in line.devices
        }
        pdf = self._make_pdf("DALI-Gerätekonfiguration")
        pdf.add_heading("DALI-Gerätekonfiguration", level=1)
        pdf.add_paragraph(f"Projekt: {self.project.name}")
        pdf.add_paragraph(f"Erstellt: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

        if not self.project.dali_configs:
            pdf.add_paragraph("Keine DALI-Konfigurationen vorhanden.")
        else:
            for gw_id, gw in sorted(
                self.project.dali_configs.items(),
                key=lambda item: physical_address_key(gateway_address.get(item[0], "")),
            ):
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
