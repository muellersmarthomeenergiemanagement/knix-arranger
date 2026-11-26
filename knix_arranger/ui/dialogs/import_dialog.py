"""
ETS6 Import: Datei wählen (FA-500).

Direkt die Dateiauswahl -- vorher ein eigener Dialog mit «Durchsuchen…» und
«Importieren», also zwei Schritte für eine Datei. Die unterstützten Formate
stehen in der Typ-Auswahl der Dateiauswahl.
"""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog

#: Typ-Auswahl der Dateiauswahl, .knxproj zuerst (vollständiger Import)
FILE_FILTER = (
    "ETS6 Projekt oder Reports (*.knxproj *.xlsx *.csv);;"
    "ETS6 Projekt – vollständiger Import, empfohlen (*.knxproj);;"
    "ETS6 Report Topologie / Gruppenadressen / Gebäude (*.xlsx);;"
    "ETS6 Gruppenadressen-Export (*.csv);;"
    "Alle Dateien (*.*)"
)


def file_type(path: str) -> str:
    """"knxproj", "xlsx" oder "csv" nach der Dateiendung."""
    lower = path.lower()
    if lower.endswith(".knxproj"):
        return "knxproj"
    if lower.endswith(".xlsx"):
        return "xlsx"
    return "csv"


def choose_import_file(parent, start_dir: str = "") -> tuple[str, str]:
    """Dateiauswahl für den ETS6 Import. Gibt (Pfad, Typ) zurück, ("", "")
    bei Abbruch."""
    path, _ = QFileDialog.getOpenFileName(parent, "ETS-Projekt einlesen – Datei wählen",
                                          start_dir, FILE_FILTER)
    return (path, file_type(path)) if path else ("", "")
