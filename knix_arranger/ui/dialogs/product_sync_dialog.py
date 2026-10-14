"""
Nach der Produktzuweisung an Sensoren (Materialliste, Topologie): das
Produkt bestimmt die Gruppenadressen der Gewerk-Elemente, die dem Sensor
gehören (A, FK, W ...) -- eine Quelle fürs Produkt, ohne Rückfrage. Gefragt
wird nur, welche KOs eine eigene GA bekommen. Siehe services/product_sync.
"""
from __future__ import annotations

from PySide6.QtWidgets import QDialog

from ...services.ko_templates import load_ga_selection, save_ga_selection
from ...services.product_sync import (
    apply_device_product, default_excluded_numbers, device_product, product_mismatches,
)
from .com_object_select_dialog import ComObjectSelectDialog


def product_label(product: dict) -> str:
    head = " ".join(p for p in (product.get("manufacturer", ""),
                                product.get("order_number", "")) if p)
    return " – ".join(p for p in (head, product.get("product_name", "")) if p)


def take_over_device_product(parent, mismatches) -> bool:
    """Geräteprodukt mit Auswahl der Kommunikationsobjekte für die GAs der
    Elemente übernehmen. True, wenn übernommen (GAs neu berechnen).

    Vorausgewählt ist die gemerkte Auswahl des Produkts, sonst was der
    Sensor meldet (default_excluded_numbers); die Auswahl wird gemerkt."""
    if not mismatches:
        return False
    device = mismatches[0].device
    product = device_product(device)
    excluded = load_ga_selection(device)
    if excluded is None:
        excluded = default_excluded_numbers(product["com_objects"])
    elements = "<br>".join(f"• {m.element_text} ({m.room.number} {m.room.name})"
                           for m in mismatches)
    dlg = ComObjectSelectDialog(
        product_label(product), product["com_objects"], excluded_numbers=excluded,
        header_note=(
            f"<br>{device.physical_address}: das Produkt bestimmt die Gruppenadressen von"
            f"<br>{elements}<br>"
            "Vorausgewählt ist, was der Sensor meldet. Eingänge (Freigabe, Nachlaufzeit, "
            "Externer Taster, Aktorstatus …) brauchen meist keine eigene GA – sie werden "
            "in «Kanäle und KOs zuordnen…» mit vorhandenen GAs verbunden."),
        parent=parent)
    if dlg.exec() != QDialog.Accepted:
        return False
    product["excluded_co_numbers"] = sorted(dlg.excluded_numbers())
    save_ga_selection(device, set(product["excluded_co_numbers"]))
    apply_device_product(mismatches, product)
    return True


def offer_device_product(parent, project, devices) -> bool:
    """Nach einer Produktzuweisung: das Produkt bestimmt die GAs der Elemente,
    die diese Sensoren tragen (nur Gewerke ohne Aktor). True, wenn übernommen
    -- der Aufrufer berechnet die GAs neu."""
    mismatches = product_mismatches(project, devices)
    if not mismatches:
        return False
    first = mismatches[0].device
    mismatches = [m for m in mismatches
                  if (m.device.manufacturer, m.device.order_number)
                  == (first.manufacturer, first.order_number)]
    return take_over_device_product(parent, mismatches)
