"""
Aktionen am realen Gerät, gemeinsam für Topologie und Bauherrenberatung
(FA-1411b/c): Tasten anpassen und Raumtemperatur über einen Taster.

Mit bus läuft die Neuberechnung synchron über das Hauptfenster
(emit_building_changed), danach bekommt ein neu entstandener Taster das
Produkt seines Vorgängers.
"""
from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox

from ..services.product_capabilities import (
    apply_catalog_product, copy_device_product, split_surplus, use_taster_temperature,
)

#: Rückgabe von resolve_keys: Raum in der Bauherrenberatung öffnen
OPEN_BAUHERR = "bauherr"


def resolve_keys(parent, project, bus, shortage):
    """Dialog «Tasten anpassen». Gibt OPEN_BAUHERR zurück, das neue Gerät
    nach dem Aufteilen, True nach einem Produktwechsel, sonst None."""
    from .dialogs.key_shortage_dialog import BAUHERR, PRODUCT, SPLIT, KeyShortageDialog
    from ..services.product_sync import shared_catalog
    dialog = KeyShortageDialog(shortage, shared_catalog(), parent=parent)
    if dialog.exec() != KeyShortageDialog.Accepted:
        return None
    device = shortage.device
    if dialog.choice == BAUHERR:
        return OPEN_BAUHERR
    if bus:
        bus.begin_change(
            f"{device.physical_address}: Tasten aufgeteilt" if dialog.choice == SPLIT
            else f"{device.physical_address}: Produkt {dialog.selected_product.product_name}")
    if dialog.choice == PRODUCT:
        apply_catalog_product(device, dialog.selected_product, shortage.bedienelement)
        if bus:
            bus.emit_material_changed()
        return True
    new_be = split_surplus(project, shortage)
    if new_be is None:
        return None
    if bus:
        # Geräte neu ableiten; danach hat der zweite Taster sein Gerät
        bus.emit_building_changed()
    new_device = next((d for area in project.topology.areas for line in area.lines
                       for d in line.devices
                       if new_be.participant_number
                       and d.physical_address == new_be.participant_number), None)
    if new_device is not None and not new_device.order_number:
        copy_device_product(device, new_device)
        if bus:
            bus.emit_material_changed()
    return new_device


def use_temperature(parent, project, bus, offers: list) -> bool:
    """Raumtemperatur der Heizung über den Taster erfassen, auf Wunsch ohne
    den Raumthermostat. True, wenn übernommen."""
    if not offers:
        return False
    if len(offers) > 1:
        labels = [f"{o.assignment.gewerk_code} {o.element_number} "
                  f"{o.assignment.element_label(o.element_number)}".strip() for o in offers]
        label, ok = QInputDialog.getItem(parent, "Raumtemperatur",
                                         "Für welches Heizungselement?", labels, 0, False)
        if not ok:
            return False
        offers = [offers[labels.index(label)]]
    offer = offers[0]
    device = offer.device
    text = (f"{device.physical_address} misst die Raumtemperatur (KO "
            f"{offer.co.object_number} «{offer.co.name or offer.co.object_function}»). "
            f"Die Ist-Temperatur der Heizung in {offer.room.number} {offer.room.name} "
            f"kommt dann von diesem Taster.")
    remove = False
    if offer.thermostats:
        names = ", ".join(be.participant_number or "Raumthermostat" for be in offer.thermostats)
        box = QMessageBox(QMessageBox.Question, "Raumtemperatur", text
                          + f"\n\nRaumthermostat {names} wird dann nicht mehr für die "
                          "Temperatur gebraucht. Entfernen? Seine Bedienung (Sollwert, "
                          "Betriebsart) entfällt mit.", parent=parent)
        keep_btn = box.addButton("Raumthermostat behalten", QMessageBox.NoRole)
        remove_btn = box.addButton("Raumthermostat entfernen", QMessageBox.YesRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() not in (keep_btn, remove_btn):
            return False
        remove = box.clickedButton() is remove_btn
    elif QMessageBox.question(parent, "Raumtemperatur", text + "\n\nÜbernehmen?",
                              QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
        return False
    if bus:
        bus.begin_change(f"Raumtemperatur über {device.physical_address}")
    use_taster_temperature(project, offer, remove)
    if bus:
        # Geräte und Verknüpfungen aus den Bedienelementen neu ableiten
        bus.emit_building_changed()
    return True
