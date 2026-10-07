"""
Lesemodus ohne gültige Lizenz (NFA-066).

Ohne gültige Lizenz startet KNiX trotzdem: Projekte lassen sich öffnen und
ansehen, Speichern und alle Exporte (Berichte, CSV, PDF, Excel, Bilder)
sind gesperrt. Jede gesperrte Aktion zeigt einen Hinweis mit dem Weg zum
Lizenzdialog; wird dort eine gültige Lizenz eingespielt, endet der
Lesemodus sofort.

Exportdialoge rufen statt QFileDialog.getSaveFileName / getExistingDirectory
die Funktionen hier auf; Exporte ohne Dateidialog und das Speichern fragen
export_allowed() bzw. save_allowed().
"""
from __future__ import annotations

import weakref
from typing import Callable

from PySide6.QtWidgets import QFileDialog, QMessageBox

_read_only = False
_listeners: list[weakref.WeakMethod] = []


def is_read_only() -> bool:
    return _read_only


def set_read_only(value: bool) -> None:
    global _read_only
    if _read_only == bool(value):
        return
    _read_only = bool(value)
    for ref in list(_listeners):
        callback = ref()
        if callback is None:
            _listeners.remove(ref)
            continue
        try:
            callback(_read_only)
        except RuntimeError:  # Qt-Objekt bereits gelöscht
            _listeners.remove(ref)


def add_listener(callback: Callable[[bool], None]) -> None:
    """callback(read_only) bei jedem Wechsel, z.B. für den Fenstertitel.
    Nur gebundene Methoden; gehalten wird eine schwache Referenz."""
    _listeners.append(weakref.WeakMethod(callback))


def _ask_for_license(parent, what: str) -> bool:
    """Hinweis mit Knopf zum Lizenzdialog; True, wenn danach eine gültige
    Lizenz vorliegt."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Keine gültige Lizenz")
    box.setText(f"{what} ist ohne gültige Lizenz gesperrt.")
    box.setInformativeText(
        "Projekte lassen sich weiterhin öffnen und ansehen. "
        "Mit einer gültigen Lizenz sind Speichern und Exporte wieder möglich.")
    btn_license = box.addButton("Lizenz…", QMessageBox.AcceptRole)
    box.addButton("Schliessen", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is not btn_license:
        return False
    from .dialogs.license_dialog import LicenseDialog
    from ..services.license_service import LicenseService
    LicenseDialog(parent).exec()
    if LicenseService().check_license().is_valid:
        set_read_only(False)
        return True
    return False


def export_allowed(parent, what: str = "Das Exportieren") -> bool:
    return not _read_only or _ask_for_license(parent, what)


def save_allowed(parent) -> bool:
    return not _read_only or _ask_for_license(parent, "Das Speichern")


def get_save_file_name(parent, *args, **kwargs) -> tuple[str, str]:
    """QFileDialog.getSaveFileName mit Lizenzsperre; gesperrt: ("", "")."""
    if not export_allowed(parent):
        return "", ""
    return QFileDialog.getSaveFileName(parent, *args, **kwargs)


def get_existing_directory(parent, *args, **kwargs) -> str:
    """QFileDialog.getExistingDirectory mit Lizenzsperre; gesperrt: ""."""
    if not export_allowed(parent):
        return ""
    return QFileDialog.getExistingDirectory(parent, *args, **kwargs)
