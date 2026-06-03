"""
KNiX Arranger Application - Initialisierung und Hauptfenster-Start
"""
from __future__ import annotations
import sys
import logging
from .utils.i18n import load_language
from .services.project_service import ProjectService
from .services.license_service import LicenseService

logger = logging.getLogger("knix_arranger.app")


class KnixApplication:
    """Hauptanwendungsklasse."""

    def __init__(self, file_to_open: str | None = None):
        # Sprache laden
        load_language("de")

        # Services initialisieren
        self.project_service = ProjectService()
        self.license_service = LicenseService()

        # 1. EULA prüfen (NFA-081) — beim Erststart anzeigen
        self._check_eula()

        # 2. Lizenz prüfen (NFA-066) — ungültige Lizenz blockiert den Start
        self._check_license()

        # 3. GUI erstellen
        self._create_main_window()
        self._file_to_open = file_to_open

    # ── Startup-Checks ─────────────────────────────────────────────────────────

    def _check_eula(self):
        """
        Zeigt den EULA-Dialog beim Erststart (NFA-081).
        Wird abgelehnt, beendet sich die Anwendung sofort.
        """
        if self.license_service.is_eula_accepted():
            return

        from PySide6.QtWidgets import QDialog
        from .ui.dialogs.eula_dialog import EulaDialog

        dialog = EulaDialog()
        if dialog.exec() != QDialog.Accepted:
            logger.info("EULA abgelehnt – Anwendung wird beendet.")
            sys.exit(0)

        self.license_service.mark_eula_accepted()
        logger.info("EULA akzeptiert.")

    def _check_license(self):
        """
        Prüft die gespeicherte Lizenz (NFA-066).
        Ist keine gültige Lizenz vorhanden, wird der Lizenzdialog geöffnet.
        Schliesst der Benutzer den Dialog ohne gültige Lizenz, beendet sich
        die Anwendung.
        """
        info = self.license_service.check_license()

        if not info.is_valid:
            logger.warning(f"Lizenzprüfung: {info.message} – Dialog wird angezeigt.")
            from .ui.dialogs.license_dialog import LicenseDialog
            LicenseDialog().exec()
            info = self.license_service.check_license()
            if not info.is_valid:
                logger.info("Keine gültige Lizenz – Anwendung wird beendet.")
                sys.exit(0)

        logger.info(f"Lizenz: {info.message}")

        if info.warning:
            self._pending_license_warning = info.warning
        else:
            self._pending_license_warning = None

    # ── GUI ────────────────────────────────────────────────────────────────────

    def _create_main_window(self):
        """Erstellt das Hauptfenster."""
        from .ui.main_window import MainWindow
        self.main_window = MainWindow(self)

    def show(self):
        """Zeigt das Hauptfenster an."""
        self.main_window.show()
        if self._file_to_open:
            self.main_window.open_file(self._file_to_open)
        if self._pending_license_warning:
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox(self.main_window)
            msg.setWindowTitle("Lizenz-Hinweis")
            msg.setIcon(QMessageBox.Warning)
            msg.setText(self._pending_license_warning)
            msg.exec()
