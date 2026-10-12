"""
Nach der Produktzuweisung an Sensoren (Materialliste, Topologie): das
Produkt auch für die Gruppenadressen der Gewerk-Elemente übernehmen?
Siehe services/product_sync.py.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QMessageBox

from ...services.product_sync import (
    apply_device_product, device_product, product_mismatches,
)
from .com_object_select_dialog import ComObjectSelectDialog


def product_label(product: dict) -> str:
    head = " ".join(p for p in (product.get("manufacturer", ""),
                                product.get("order_number", "")) if p)
    return " – ".join(p for p in (head, product.get("product_name", "")) if p)


def take_over_device_product(parent, mismatches) -> bool:
    """Geräteprodukt mit Auswahl der Kommunikationsobjekte für die GAs der
    Elemente übernehmen. True, wenn übernommen (GAs neu berechnen)."""
    if not mismatches:
        return False
    product = device_product(mismatches[0].device)
    dlg = ComObjectSelectDialog(product_label(product), product["com_objects"],
                                parent=parent)
    if dlg.exec() != QDialog.Accepted:
        return False
    product["excluded_co_numbers"] = sorted(dlg.excluded_numbers())
    apply_device_product(mismatches, product)
    return True


def offer_device_product(parent, project, devices) -> bool:
    """Fragt nach einer Produktzuweisung, ob das Produkt auch die GAs der
    Elemente bestimmen soll, die diese Sensoren tragen. True, wenn
    übernommen -- der Aufrufer berechnet die GAs neu."""
    mismatches = product_mismatches(project, devices)
    if not mismatches:
        return False
    first = mismatches[0].device
    mismatches = [m for m in mismatches
                  if (m.device.manufacturer, m.device.order_number)
                  == (first.manufacturer, first.order_number)]
    lines = "\n".join(
        f"• {m.device.physical_address} {m.device.product}: {m.element_text} "
        f"({m.room.number} {m.room.name})" for m in mismatches)
    name = " ".join(p for p in (first.manufacturer, first.order_number,
                                first.product_name) if p)
    answer = QMessageBox.question(
        parent, "Produkt für die Gruppenadressen",
        f"«{name}» hat Kommunikationsobjekte. Auch für die Gruppenadressen "
        f"verwenden?\n\n{lines}\n\nSonst bleiben die GAs nach dem bisherigen "
        f"Produkt bzw. dem Standard des Gewerks (Schritt 5).",
        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
    if answer != QMessageBox.Yes:
        return False
    return take_over_device_product(parent, mismatches)
