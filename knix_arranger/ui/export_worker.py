"""
Hintergrund-Export-Infrastruktur.

Stellt _ExportWorker (QThread) und run_export() zur Verfügung,
damit blockierende IO-Operationen nicht den UI-Thread einfrieren.
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
) -> None:
    """
    Führt `fn()` im Hintergrund aus und zeigt einen modalen Fortschrittsdialog.

    Parameters
    ----------
    parent:         Eltern-Widget für Dialog und Fehlermeldungen.
    progress_label: Text im Fortschrittsdialog.
    fn:             Aufzurufende Funktion (ohne Argumente).
    on_success:     Callback mit dem Rückgabewert von fn(), läuft im UI-Thread.
    worker_ref:     Einelementige Liste; wird mit dem Worker belegt, damit der
                    GC den Thread nicht vorzeitig zerstört.
    """
    if worker_ref and worker_ref[0] and worker_ref[0].isRunning():
        QMessageBox.warning(
            parent, "Export läuft",
            "Bitte warten – ein Export ist noch aktiv."
        )
        return

    dlg = QProgressDialog(progress_label, None, 0, 0, parent)
    dlg.setWindowTitle("Export läuft…")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setCancelButton(None)
    dlg.setMinimumDuration(0)
    dlg.show()

    worker = ExportWorker(fn, parent=parent)
    worker_ref[0] = worker

    def _on_finished(result):
        dlg.close()
        on_success(result)

    def _on_error(msg: str):
        dlg.close()
        QMessageBox.critical(parent, "Export-Fehler", msg)

    worker.finished.connect(_on_finished, Qt.QueuedConnection)
    worker.error.connect(_on_error, Qt.QueuedConnection)
    worker.finished.connect(worker.deleteLater)
    worker.error.connect(worker.deleteLater)
    worker.start()
