"""
Untermenüs für Sprünge zwischen Ansichten (FA-1011a ff.), z.B. «In Topologie
zeigen» mit je Gerät und KO einem Eintrag. Ein Untermenü füllt sich erst beim
Aufklappen: die Liste kann eine andere Ansicht aufbauen (Topologie) oder
das ganze Projekt durchgehen (Szenen).
"""
from __future__ import annotations

from PySide6.QtWidgets import QMenu


def add_jump_menu(menu: QMenu, title: str, entries, on_pick,
                  empty_text: str = "keine Einträge") -> QMenu:
    """Untermenü an menu anhängen. entries() liefert [(Ziel, Text)],
    on_pick(Ziel) springt."""
    sub = menu.addMenu(title)
    # Platzhalter: ein leeres Untermenü klappt nicht auf
    sub.addAction("…").setEnabled(False)

    def fill():
        sub.clear()
        found = entries()
        for target, label in found:
            act = sub.addAction(label)
            act.triggered.connect(lambda _c=False, t=target: on_pick(t))
        if not found:
            sub.addAction(empty_text).setEnabled(False)
    sub.aboutToShow.connect(fill)
    return sub


def add_gewerk_jump_menus(menu: QMenu, jumps, room, assignment) -> None:
    """Sprünge eines Gewerks im Raum (Gebäude, Gewerke): Geräte in der
    Topologie und GAs des Gewerks (FA-1011j)."""
    if jumps is None:
        return
    add_jump_menu(menu, "Geräte in der Topologie zeigen",
                  lambda: jumps.devices_of_gewerk(room, assignment),
                  lambda t: jumps.device(*t), "keine Geräte zu diesem Gewerk")
    menu.addAction("GAs des Gewerks zeigen", lambda: jumps.gewerk_gas(room, assignment))


def add_gewerk_of_ga_menu(menu: QMenu, jumps, address: str) -> None:
    """Gewerk im Raum zu einer GA (FA-1011k)."""
    if jumps is None or not address:
        return
    add_jump_menu(menu, "Gewerk im Raum zeigen", lambda: jumps.gewerke_of(address),
                  lambda t: jumps.gewerk(*t), "keinem Gewerk zugeordnet")


def add_ga_jump_menus(menu: QMenu, jumps, ga) -> None:
    """Sprünge einer GA (Baum- und Tabellenansicht): Geräte in der Topologie
    (FA-1011a), Gewerk im Raum (FA-1011k), Szenen (FA-1011b), Zeitprogramme
    (FA-1011c) und ETS-Funktionen (FA-1011g)."""
    if jumps is None or ga is None or ga.is_placeholder:
        return
    address = ga.address
    add_jump_menu(menu, "In Topologie zeigen", lambda: jumps.devices_at(address),
                  lambda row: jumps.device(row[0], address, row[1]),
                  "keine verknüpften Geräte")
    add_gewerk_of_ga_menu(menu, jumps, address)
    add_jump_menu(menu, "In Szenen zeigen", lambda: jumps.scenes_with(ga),
                  jumps.scene, "in keiner Szene")
    add_jump_menu(menu, "Im Zeitprogramm zeigen", lambda: jumps.programs_with(ga),
                  lambda tp: jumps.time_program(tp, ga), "in keinem Zeitprogramm")
    add_jump_menu(menu, "In ETS-Funktionen zeigen", lambda: jumps.functions_with(ga),
                  jumps.ets_function, "in keiner Funktion")
