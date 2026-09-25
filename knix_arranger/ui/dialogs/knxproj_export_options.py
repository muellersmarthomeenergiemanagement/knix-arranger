"""
Abfrage vor dem KNXPROJ-Export: Produktreferenz der Geraete (ProductRefId/
Hardware2ProgramRefId) mit oder ohne eingebettete Herstellerdaten.
"""
from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QWidget

from ...services.knxproj_export_service import (
    PRODUCT_REFS_EMBEDDED, PRODUCT_REFS_NONE, PRODUCT_REFS_ONLY,
)
from .product_select_dialog import _default_products_folder

_OPTIONS = [
    ("Mit Produktreferenz und Herstellerdaten aus „Produkte KNX“", PRODUCT_REFS_EMBEDDED),
    ("Nur Produktreferenz (Herstellerdaten nicht eingebettet)", PRODUCT_REFS_ONLY),
    ("Ohne Produktreferenz (Geräte als Platzhalter)", PRODUCT_REFS_NONE),
]


def ask_product_refs(parent: QWidget, project) -> tuple[str, str] | None:
    """Gibt (Modus, Produktordner) zurueck, None bei Abbruch. Ohne Geraete
    mit ETS-Kennungen wird nicht gefragt."""
    has_refs = any(
        d.product_ref_id and d.hw2prog_id
        for a in project.topology.areas for l in a.lines for d in l.devices
    )
    folder = _default_products_folder()
    if not has_refs:
        return PRODUCT_REFS_NONE, folder
    labels = [label for label, _ in _OPTIONS]
    if not folder:
        labels[0] += " – kein Ordner gefunden"
    choice, ok = QInputDialog.getItem(
        parent, "KNXPROJ exportieren",
        "Produktreferenz der Geräte (ETS-Produkt und Applikation):",
        labels, 0, False,
    )
    if not ok:
        return None
    return _OPTIONS[labels.index(choice)][1], folder
