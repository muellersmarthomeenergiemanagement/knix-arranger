"""
KNiX Arranger - Einstiegspunkt
(c) Michael Mueller SmartHome&EnergieManagement
"""
import sys
import os

from . import __version__, APP_NAME, __copyright__
from .utils.logging_setup import setup_logging, create_crash_report


def main() -> int:
    """Startet die KNiX Arranger Anwendung."""
    logger = setup_logging("INFO")
    logger.info(f"{APP_NAME} v{__version__} wird gestartet...")

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt, QTranslator, QLibraryInfo
        from .app import KnixApplication
        from .utils.dialog_focus_fixer import DialogFocusFixer

        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(__version__)
        app.setOrganizationName("Michael Mueller SmartHome&EnergieManagement")

        # Verhindert, dass modale Dialoge (Meldefenster, Fortschrittsanzeigen, ...)
        # unsichtbar hinter dem Hauptfenster landen, wenn die Anwendung beim
        # Erscheinen nicht im Vordergrund ist -- siehe dialog_focus_fixer.py.
        dialog_focus_fixer = DialogFocusFixer(app)
        app.installEventFilter(dialog_focus_fixer)

        # Qt-Standarddialoge (QMessageBox Ja/Nein/Speichern/Abbrechen etc.)
        # sind ohne geladene Uebersetzung immer Englisch, obwohl der Rest der
        # Anwendung durchgehend Deutsch ist. qtbase_de deckt genau diese
        # Standard-Button-Texte ab.
        qt_translator = QTranslator(app)
        translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if qt_translator.load("qtbase_de", translations_path):
            app.installTranslator(qt_translator)
        else:
            logger.warning("Qt-Uebersetzung 'qtbase_de' nicht gefunden -- Standard-Dialoge bleiben Englisch.")

        from PySide6.QtGui import QFont
        font = QFont("Segoe UI", 10)
        font.setStyleHint(QFont.SansSerif)
        app.setFont(font)

        file_to_open = sys.argv[1] if len(sys.argv) > 1 else None
        knix_app = KnixApplication(file_to_open=file_to_open)
        knix_app.show()

        logger.info(f"{APP_NAME} gestartet.")
        return app.exec()

    except ImportError as e:
        logger.error(f"PySide6 nicht installiert: {e}")
        print(f"Fehler: PySide6 ist nicht installiert. "
              f"Bitte führen Sie 'pip install PySide6' aus.")
        return 1
    except Exception as e:
        logger.critical(f"Unerwarteter Fehler: {e}", exc_info=True)
        report_path = create_crash_report(e)
        print(f"Unerwarteter Fehler: {e}")
        print(f"Crash-Report erstellt: {report_path}")
        return 1
