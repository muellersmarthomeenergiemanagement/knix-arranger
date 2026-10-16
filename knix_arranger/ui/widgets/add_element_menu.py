"""
Menü zum Einsetzen eines Bedienelements oder Sensors in einen Raum --
gemeinsam für Bauherrenberatung und Gebäude.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QMenu

from ...services.sensor_service import PRESENCE_SENSOR_TYPES, SENSOR_TYPE_CHOICES

# Bedienelemente und Melder mit ihrer Kanalzahl beim Einsetzen
ADDABLE_ELEMENTS = (
    ("Tastereinheit", 4),
    ("Raumthermostat", 1),
    ("Präsenzmelder", 1),
    ("Bewegungsmelder", 1),
)

# Übrige Melder und Kontakte (Wassermelder, Fensterkontakt …): im Menü
# «Sonstige», damit z.B. ein Wassermelder ein eigenes Gerät bekommt
OTHER_SENSOR_TYPES = tuple(t for t in SENSOR_TYPE_CHOICES if t not in PRESENCE_SENSOR_TYPES)


def fill_add_element_menu(menu: QMenu, add: Callable[[str, int], None]) -> QMenu:
    """Gerätetypen ins Menü; add(element_type, channels) setzt das Gerät.
    Gibt das Untermenü «Sonstige» zurück."""
    for element_type, channels in ADDABLE_ELEMENTS:
        menu.addAction(element_type).triggered.connect(
            lambda _c=False, t=element_type, n=channels: add(t, n))
    # Mit Elternmenü anlegen: addMenu("…") liefert ein Untermenü, das Qt
    # vorzeitig löschen kann
    other = QMenu("Sonstige", menu)
    menu.addMenu(other)
    for element_type in OTHER_SENSOR_TYPES:
        other.addAction(element_type).triggered.connect(
            lambda _c=False, t=element_type: add(t, 1))
    return other
