"""
ETS6 CSV Import (FA-500, FA-501-506)
Liest ETS6-Gruppenadress-Exporte im CSV-Format.
"""
from __future__ import annotations
import csv
import os
import logging
from ..models.group_address import (
    GroupAddressStructure, MainGroup, MiddleGroup, GroupAddress,
)

logger = logging.getLogger("knix_arranger.csv_import")


class CsvImportService:
    """Importiert ETS6 Gruppenadress-CSV-Dateien."""

    EXPECTED_COLUMNS = [
        "Main", "Middle", "Sub", "Address", "Central",
        "Unfiltered", "Description", "DatapointType", "Security",
    ]

    def import_csv(self, filepath: str) -> GroupAddressStructure:
        """
        Importiert eine ETS6 CSV-Datei (FA-501).

        Die CSV-Datei ist Semikolon-getrennt mit hierarchischer Struktur:
        - Zeilen mit Main-Wert = Hauptgruppe
        - Zeilen mit Middle-Wert = Mittelgruppe
        - Zeilen mit Sub-Wert = Untergruppe (eigentliche GA)

        FA-504: Leere Main/Middle-Felder = Zugehoerigkeit zur letzten Gruppe.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"CSV-Datei nicht gefunden: {filepath}")

        structure = GroupAddressStructure()

        # Encoding erkennen (UTF-8 oder ANSI)
        encoding = self._detect_encoding(filepath)

        with open(filepath, "r", encoding=encoding, errors="replace") as f:
            # Semikolon-getrennt (FA-501)
            reader = csv.DictReader(f, delimiter=";")

            # FA-505: Format prüfen
            if reader.fieldnames:
                self._validate_columns(reader.fieldnames)

            current_hg: MainGroup | None = None
            current_mg: MiddleGroup | None = None

            for row in reader:
                main_val = row.get("Main", "").strip()
                middle_val = row.get("Middle", "").strip()
                sub_val = row.get("Sub", "").strip()
                address = row.get("Address", "").strip()
                central = row.get("Central", "").strip()
                unfiltered = row.get("Unfiltered", "").strip()
                description = row.get("Description", "").strip()
                dpt = row.get("DatapointType", "").strip()
                security = row.get("Security", "").strip()

                if main_val:
                    # Neue Hauptgruppe
                    current_hg = MainGroup(
                        number=self._extract_group_number(main_val, address, 0),
                        name=main_val,
                    )
                    structure.main_groups.append(current_hg)
                    current_mg = None

                elif middle_val and current_hg:
                    # Neue Mittelgruppe
                    current_mg = MiddleGroup(
                        number=self._extract_group_number(middle_val, address, 1),
                        name=middle_val,
                    )
                    current_hg.middle_groups.append(current_mg)

                elif address and current_hg and current_mg:
                    # Gruppenadresse (Untergruppe)
                    parts = address.split("/")
                    if len(parts) == 3:
                        ga = GroupAddress(
                            main_group=int(parts[0]),
                            middle_group=int(parts[1]),
                            sub_group=int(parts[2]),
                            designation=sub_val,       # Bezeichnung steht in Sub
                            central=central,
                            unfiltered=unfiltered,
                            description=description,   # Bemerkung steht in Description
                            datapoint_type=dpt,
                            security=security,
                        )
                        # Versuche Gewerk-Info aus Bezeichnung zu extrahieren
                        self._parse_designation_info(ga)
                        current_mg.group_addresses.append(ga)

        structure.source = "csv"
        logger.info(
            f"CSV-Import: {len(structure.all_addresses())} Gruppenadressen "
            f"aus {filepath} importiert"
        )
        return structure

    def _detect_encoding(self, filepath: str) -> str:
        """Erkennt die Zeichenkodierung der Datei.

        ETS6 schreibt CSV-Dateien in cp1252 (Windows-ANSI).
        Prüft zuerst auf UTF-8 BOM, dann reines UTF-8, dann cp1252.
        """
        # UTF-8 BOM explizit prüfen
        with open(filepath, "rb") as f:
            raw = f.read(3)
        if raw.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"

        # Reines UTF-8 ohne BOM
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                f.read(4096)
            return "utf-8"
        except UnicodeDecodeError:
            pass

        # Fallback: Windows-1252 (ETS6-Standard)
        return "cp1252"

    def _validate_columns(self, columns: list[str]):
        """FA-505: Prüft ob die erwarteten Spalten vorhanden sind."""
        # Bereinige Spaltennamen (BOM entfernen etc.)
        clean_columns = [c.strip().lstrip("\ufeff") for c in columns]
        for expected in self.EXPECTED_COLUMNS:
            if expected not in clean_columns:
                logger.warning(f"Erwartete Spalte '{expected}' nicht gefunden")

    def _extract_group_number(self, name: str, address: str = "", addr_index: int = 0) -> int:
        """
        Extrahiert die Gruppennummer aus dem Namen oder der Adresse.

        Unterstützt zwei Formate:
        - Eigenes Format:  "0 Zentraladressen" → 0  (Nummer im Namen)
        - ETS6-Format:     "Zentral" + "0/-/-" → 0  (Nummer in der Adresse)
        """
        # Versuche zuerst aus dem Namen: "2 EG" → 2
        parts = name.split(" ", 1)
        try:
            return int(parts[0])
        except (ValueError, IndexError):
            pass
        # Fallback: Nummer aus der Adresse lesen (ETS6-Format "X/-/-" oder "X/Y/-")
        addr_parts = address.split("/")
        if len(addr_parts) > addr_index:
            try:
                return int(addr_parts[addr_index])
            except ValueError:
                pass
        return 0

    def _parse_designation_info(self, ga: GroupAddress):
        """Versucht Gewerk-Info aus der Bezeichnung zu extrahieren."""
        desc = ga.designation
        if not desc or desc == "--":
            return

        parts = desc.split("_", 2)
        if len(parts) >= 3:
            ga.gewerk_code = parts[0]
            ga.room_number = parts[1]
            # Nummer und Funktion aus Rest extrahieren
            rest = parts[2]
            nr_parts = rest.split(" ", 1)
            try:
                ga.element_number = int(nr_parts[0])
            except ValueError:
                pass
            if len(nr_parts) > 1:
                func_text = nr_parts[1]
                # Klartext in Klammern abtrennen
                if "(" in func_text:
                    idx = func_text.index("(")
                    ga.function_name = func_text[:idx].strip()
                else:
                    ga.function_name = func_text.strip()
