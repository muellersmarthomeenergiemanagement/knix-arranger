"""
Kontextmenü «In Topologie zeigen» der Gruppenadress-Ansichten (FA-1011a):
die Geräte, unter denen die GA in der Topologie steht, je Gerät und KO ein
Eintrag. Das Untermenü füllt sich erst beim Aufklappen, weil dafür die
Topologie-Ansicht aufgebaut sein muss.
"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu


def add_topology_menu(menu: QMenu, address: str, linked_devices, on_pick) -> QMenu | None:
    """Untermenü an menu anhängen. linked_devices(address) liefert
    [(Gerät, Text)], on_pick(Gerät, address) springt."""
    if linked_devices is None or not address:
        return None
    sub = menu.addMenu("In Topologie zeigen")
    # Platzhalter: ein leeres Untermenü klappt nicht auf
    sub.addAction("…").setEnabled(False)

    def fill():
        sub.clear()
        entries = linked_devices(address)
        for device, label in entries:
            act = sub.addAction(label)
            act.triggered.connect(lambda _c=False, d=device: on_pick(d, address))
        if not entries:
            sub.addAction("keine verknüpften Geräte").setEnabled(False)
    sub.aboutToShow.connect(fill)
    return sub
