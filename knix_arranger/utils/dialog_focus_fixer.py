"""
Globaler Fix gegen "unsichtbare" modale Dialoge.

Windows' Vordergrund-Sperre verhindert, dass eine Anwendung ohne aktuellen
Fokus sich selbst in den Vordergrund holt -- z.B. wenn ein Hintergrund-Export
fertig wird und ein Meldefenster erscheint, waehrend die Nutzer:in gerade in
einem anderen Fenster arbeitet. Ein in diesem Moment geoeffneter modaler
Dialog (QMessageBox, QProgressDialog, eigene Dialoge) blockiert dann zwar
weiterhin die Bedienung des Hauptfensters, ist selbst aber nicht sichtbar
(blinkt hoechstens in der Taskleiste) -- fuer die Nutzer:in wirkt das wie ein
eingefrorenes Programm (siehe export_worker.py fuer den urspruenglichen,
lokalen Fix nur fuer Export-/Import-Dialoge).

Dieser applikationsweite Event-Filter (auf QApplication installiert, siehe
main.py) faengt das Show-Event JEDES modalen QDialog ab -- unabhaengig davon
wo im Code er erzeugt wird -- und versucht ihn aktiv in den Vordergrund zu
holen. Zusaetzlich wird QApplication.alert() aufgerufen: das laesst die
Taskleiste zuverlaessig aufblinken, auch wenn raise_()/activateWindow() an
der Windows-Vordergrund-Sperre scheitern.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QApplication, QDialog


class DialogFocusFixer(QObject):
    """Holt jeden neu angezeigten modalen Dialog aktiv in den Vordergrund."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(obj, QDialog) and obj.isModal():
            obj.raise_()
            obj.activateWindow()
            QApplication.alert(obj)
        return super().eventFilter(obj, event)
