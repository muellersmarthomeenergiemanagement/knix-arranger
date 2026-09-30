"""
Selbsttest des ausgelieferten Bundles (KNiX_Arranger.exe --selftest)

Prüft ohne Fenster und ohne Lizenz, ob alles, was erst bei Bedarf geladen
wird, im kompilierten Bundle vorhanden ist: Datendateien, Firmenschrift,
Qt-Übersetzung, PDF-Erzeugung (PyMuPDF), Kryptografie und Excel-Import.
Der Release-Workflow ruft ihn nach jedem Build auf -- ein fehlendes Modul
fällt so vor der Auslieferung auf und nicht erst beim Betatester.

Rückgabe: 0 = alles in Ordnung, 1 = mindestens ein Fehler (Details im Log).
"""
from __future__ import annotations
import json
import logging
import os
import tempfile

logger = logging.getLogger("knix_arranger.selftest")

_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _check_data_files() -> None:
    for sub in ("config", "i18n", "data"):
        folder = os.path.join(_PACKAGE_DIR, sub)
        names = [n for n in os.listdir(folder) if n.endswith(".json")]
        if not names:
            raise RuntimeError(f"keine JSON-Dateien in {sub}/")
        for name in names:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                json.load(f)
    handbook = os.path.join(_PACKAGE_DIR, "data", "KNiX_Arranger_Handbuch.pdf")
    if not os.path.exists(handbook):
        raise RuntimeError("Bedienungsanleitung fehlt")


def _check_fonts() -> None:
    from .fonts import _BUNDLED_DIR
    for name in ("Inter-Regular.ttf", "Inter-Bold.ttf"):
        if not os.path.exists(os.path.join(_BUNDLED_DIR, name)):
            raise RuntimeError(f"{name} fehlt")


def _check_qt_translation() -> None:
    from PySide6.QtCore import QTranslator, QLibraryInfo
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not QTranslator().load("qtbase_de", path):
        raise RuntimeError(f"qtbase_de nicht gefunden in {path}")


def _check_pdf() -> None:
    import fitz
    from .pdf_generator import PdfGenerator
    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        pdf = PdfGenerator(title="Selbsttest")
        pdf.add_heading("Selbsttest", level=2)
        pdf.add_paragraph("Umlaute: äöü ÄÖÜ – Schweizer ss")
        pdf.save(path)
        with fitz.open(path) as doc:
            if "Selbsttest" not in doc[0].get_text():
                raise RuntimeError("Text im PDF nicht lesbar")
    finally:
        os.remove(path)


def _check_crypto() -> None:
    from cryptography.hazmat.primitives import serialization
    from ..services.license_service import _PUBLIC_KEY_PEM
    serialization.load_pem_public_key(_PUBLIC_KEY_PEM)
    import pyzipper  # noqa: F401  (ETS-Projekte mit Passwort)


def _check_excel() -> None:
    import openpyxl
    openpyxl.Workbook()


CHECKS = [
    ("Datendateien", _check_data_files),
    ("Firmenschrift", _check_fonts),
    ("Qt-Übersetzung", _check_qt_translation),
    ("PDF-Erzeugung", _check_pdf),
    ("Kryptografie", _check_crypto),
    ("Excel", _check_excel),
]


def run_selftest() -> int:
    failed = 0
    for name, check in CHECKS:
        try:
            check()
            logger.info(f"Selbsttest {name}: OK")
        except Exception as e:
            failed += 1
            logger.error(f"Selbsttest {name}: FEHLER – {e}", exc_info=True)
    logger.info("Selbsttest bestanden." if not failed
                else f"Selbsttest: {failed} Fehler.")
    return 1 if failed else 0
