"""
Hintergrund-Worker-Infrastruktur für blockierende IO-Operationen.

Stellt ExportWorker (QThread) und run_export() zur Verfügung, damit weder
Export- noch Import-Läufe den UI-Thread einfrieren -- der Name ist
historisch (zuerst für Exporte gebaut), die Infrastruktur ist generisch und
wird für beides genutzt (siehe main_window.py-Importmethoden).
"""
from __future__ import annotations
import logging
from typing import Callable, Any

from PySide6.QtWidgets import QWidget, QProgressDialog, QMessageBox
from PySide6.QtCore import Qt, QThread, Signal

logger = logging.getLogger("knix_arranger.export_worker")


class ExportWorker(QThread):
    """Führt eine Export-Funktion im Hintergrund-Thread aus."""

    finished = Signal(object)   # Ergebnis der Export-Funktion
    error = Signal(str)         # Fehlermeldung als String

    def __init__(self, fn: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("Fehler im Export-Worker")
            self.error.emit(str(exc))


def run_export(
    parent: QWidget,
    progress_label: str,
    fn: Callable[[], Any],
    on_success: Callable[[Any], None],
    worker_ref: list,          # Einelementige Liste als „Out-Parameter" für GC-Schutz
    window_title: str = "Export läuft…",
    error_title: str = "Export-Fehler",
    busy_title: str = "Export läuft",
    busy_text: str = "Bitte warten – ein Export ist noch aktiv.",
) -> None:
    """
    Führt `fn()` im Hintergrund aus und zeigt einen modalen Fortschrittsdialog.

    Parameters
    ----------
    parent:         Eltern-Widget für Dialog und Fehlermeldungen.
    progress_label: Text im Fortschrittsdialog.
    fn:             Aufzurufende Funktion (ohne Argumente). Darf KEINE
                    Qt-Widgets berühren (läuft im Hintergrund-Thread) --
                    nur reine Datenverarbeitung. UI-Aktionen (Dialoge,
                    Statusleiste, Navigation) gehören in on_success.
    on_success:     Callback mit dem Rückgabewert von fn(), läuft im UI-Thread.
    worker_ref:     Einelementige Liste; wird mit dem Worker belegt, damit der
                    GC den Thread nicht vorzeitig zerstört.
    window_title, error_title, busy_title, busy_text:
                    Texte für Fortschrittsdialog, Fehlermeldung und die
                    "läuft bereits"-Warnung -- Defaults passen für Exporte,
                    für andere Hintergrundläufe (z.B. Importe) überschreiben.
    """
    if worker_ref and worker_ref[0] and worker_ref[0].isRunning():
        QMessageBox.warning(parent, busy_title, busy_text)
        return

    dlg = QProgressDialog(progress_label, None, 0, 0, parent)
    dlg.setWindowTitle(window_title)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setCancelButton(None)
    dlg.setMinimumDuration(0)
    dlg.show()

    worker = ExportWorker(fn, parent=parent)
    worker_ref[0] = worker

    def _on_finished(result):
        # worker_ref muss VOR dem naechsten run_export()/run_import()-Aufruf
        # geleert werden: deleteLater() (unten) zerstoert das C++-Objekt beim
        # naechsten Event-Loop-Durchlauf, aber worker_ref[0] wuerde ohne
        # dies weiter darauf zeigen -- der Busy-Check oben
        # (worker_ref[0].isRunning()) griffe dann auf ein bereits geloeschtes
        # Qt-Objekt zu ("Internal C++ object already deleted").
        worker_ref[0] = None
        dlg.close()
        # on_success() zeigt oft ein Meldefenster (z.B. Re-Import-Hinweise).
        # Ohne explizites Aktivieren bleibt das Hauptfenster (und damit der
        # modale Dialog) im Hintergrund, falls der Nutzer während des
        # Hintergrundlaufs in ein anderes Fenster gewechselt hat -- Windows'
        # Foreground-Lock verhindert dann das automatische Vordergrund-
        # Stehlen, der Dialog blinkt nur in der Taskleiste. Für die Nutzer:in
        # wirkt das wie ein eingefrorenes Programm (modaler Dialog blockiert
        # die Bedienung, ist aber unsichtbar).
        if parent is not None:
            parent.raise_()
            parent.activateWindow()
        on_success(result)

    def _on_error(msg: str):
        worker_ref[0] = None
        dlg.close()
        if parent is not None:
            parent.raise_()
            parent.activateWindow()
        QMessageBox.critical(parent, error_title, msg)

    worker.finished.connect(_on_finished, Qt.QueuedConnection)
    worker.error.connect(_on_error, Qt.QueuedConnection)
    worker.finished.connect(worker.deleteLater)
    worker.error.connect(worker.deleteLater)
    worker.start()


def run_import(
    parent: QWidget,
    progress_label: str,
    fn: Callable[[], Any],
    on_success: Callable[[Any], None],
    worker_ref: list,
) -> None:
    """run_export() mit Import-Texten -- siehe dort für die Details/Regeln
    (fn() darf keine Qt-Widgets berühren, on_success läuft im UI-Thread)."""
    run_export(
        parent, progress_label, fn, on_success, worker_ref,
        window_title="Import läuft…",
        error_title="Import-Fehler",
        busy_title="Import läuft",
        busy_text="Bitte warten – ein Import ist noch aktiv.",
    )
