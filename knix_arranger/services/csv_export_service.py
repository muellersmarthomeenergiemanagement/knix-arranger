"""
ETS6 CSV Export (FA-800, FA-801-805)
Erzeugt ETS6-kompatible CSV-Dateien für den Import.
"""
from __future__ import annotations
import os
import logging
from ..models.group_address import GroupAddressStructure

logger = logging.getLogger("knix_arranger.csv_export")


class CsvExportService:
    """Exportiert Gruppenadressen als ETS6-kompatible CSV-Datei."""

    COLUMNS = [
        "Main", "Middle", "Sub", "Address", "Central",
        "Unfiltered", "Description", "DatapointType", "Security",
    ]

    @staticmethod
    def _q(value: str) -> str:
        """Gibt einen Wert ETS6-kompatibel in Anführungszeichen zurück."""
        return '"' + str(value).replace('"', '""') + '"'

    @staticmethod
    def _row(*fields: str) -> str:
        """Erzeugt eine CSV-Zeile mit Semikolon-Trennzeichen."""
        return ";".join(fields) + "\n"

    def export_csv(self, structure: GroupAddressStructure, filepath: str,
                   overwrite: bool = False):
        """
        Exportiert die GA-Struktur als CSV (FA-801, FA-802).

        FA-803: Hierarchische Darstellung beibehalten.
        FA-805: Warnung bei Ueberschreiben.
        """
        if os.path.exists(filepath) and not overwrite:
            raise FileExistsError(
                f"Datei existiert bereits: {filepath}. "
                f"Setzen Sie overwrite=True zum Ueberschreiben."
            )

        q = self._q
        row = self._row

        with open(filepath, "w", newline="", encoding="cp1252") as f:
            # Header – alle Spaltennamen gequotet
            f.write(row(*[q(c) for c in self.COLUMNS]))

            for hg in sorted(structure.main_groups, key=lambda m: m.number):
                # Hauptgruppe-Zeile: "Name"; ; ;"X/-/-";"";"";"";"";"Auto"
                f.write(row(
                    q(hg.name),              # Main
                    " ",                      # Middle (Leerzeichen = kein Wert)
                    " ",                      # Sub   (Leerzeichen = kein Wert)
                    q(f"{hg.number}/-/-"),   # Address
                    q(""),                   # Central
                    q(""),                   # Unfiltered
                    q(""),                   # Description
                    q(""),                   # DatapointType
                    q("Auto"),               # Security
                ))

                for mg in sorted(hg.middle_groups, key=lambda m: m.number):
                    # Mittelgruppe-Zeile: " ";"Name"; ;"X/Y/-";"";"";"";"";"Auto"
                    f.write(row(
                        " ",                                   # Main (Leerzeichen)
                        q(mg.name),                            # Middle
                        " ",                                   # Sub  (Leerzeichen)
                        q(f"{hg.number}/{mg.number}/-"),       # Address
                        q(""),                                 # Central
                        q(""),                                 # Unfiltered
                        q(""),                                 # Description
                        q(""),                                 # DatapointType
                        q("Auto"),                             # Security
                    ))

                    for ga in sorted(mg.group_addresses, key=lambda g: g.sub_group):
                        # Untergruppe-Zeile (eigentliche GA)
                        sub_name = ga.designation if ga.designation != "--" else ""
                        sub_name = sub_name if not ga.is_placeholder else ""
                        dpt = ga.datapoint_type if not ga.is_placeholder else ""

                        f.write(row(
                            " ",               # Main   (Leerzeichen)
                            " ",               # Middle (Leerzeichen)
                            q(sub_name),       # Sub         ← Bezeichnung der GA
                            q(ga.address),     # Address
                            q(ga.central),     # Central
                            q(ga.unfiltered),  # Unfiltered
                            q(ga.description), # Description ← freier Bemerkungstext
                            q(dpt),            # DatapointType
                            q(ga.security),    # Security
                        ))

        logger.info(
            f"CSV-Export: {len(structure.all_addresses())} Gruppenadressen "
            f"nach {filepath} exportiert"
        )
