"""
Sprünge zwischen Ansichten per Rechtsklick (FA-1011a ff.): Ziele öffnen
(Ansicht wechseln, Eintrag anwählen) und die Listen der Untermenüs. Die
Ansichten kennen nur dieses Objekt (Attribut ``jumps``), nicht einander.

Dazu der Verlauf der geöffneten Ansichten für «Zurück» und «Vorwärts»
(Alt+Links/Alt+Rechts, FA-1011f).
"""
from __future__ import annotations


class ViewHistory:
    """Geöffnete Ansichten wie im Browser: Öffnen nach einem Zurück
    verwirft die Vorwärts-Einträge."""

    LIMIT = 50

    def __init__(self):
        self._keys: list[str] = []
        self._pos = -1

    def visit(self, key: str) -> None:
        if self._pos >= 0 and self._keys[self._pos] == key:
            return
        del self._keys[self._pos + 1:]
        self._keys.append(key)
        if len(self._keys) > self.LIMIT:
            del self._keys[0]
        self._pos = len(self._keys) - 1

    def back(self) -> str | None:
        if self._pos <= 0:
            return None
        self._pos -= 1
        return self._keys[self._pos]

    def forward(self) -> str | None:
        if self._pos >= len(self._keys) - 1:
            return None
        self._pos += 1
        return self._keys[self._pos]

    def can_back(self) -> bool:
        return self._pos > 0

    def can_forward(self) -> bool:
        return self._pos < len(self._keys) - 1

    def clear(self) -> None:
        self._keys.clear()
        self._pos = -1


class ViewJumps:
    """Sprungziele; window ist das MainWindow (Ansichten, _navigate)."""

    def __init__(self, window):
        self._w = window

    @property
    def _project(self):
        return self._w._project

    def _open(self, key: str) -> None:
        self._w._sidebar.select(key)
        self._w._navigate(key)

    def _not_found(self, text: str) -> None:
        self._w._status_bar.showMessage(text, 5000)

    # ── Ziele ──

    def ga(self, address: str) -> None:
        """GA in der Baumansicht der Gruppenadressen (FA-1011a)."""
        self._open("addresses")
        if not self._w._address_tree.select_address(address):
            self._not_found(f"GA {address} nicht gefunden")

    def device(self, device, address: str = "", row_text: str = "") -> None:
        """Gerät in der Topologie, mit address die Zeile dieser GA, bei
        mehreren die mit row_text (FA-1011a)."""
        self._open("topology")
        if not self._w._topology_view.select_ga_row(device, address, row_text):
            self._not_found(f"Gerät {device.physical_address} nicht in der Topologie")

    def scene(self, scene) -> None:
        """Szene in der Szenen-Verwaltung (FA-1011b)."""
        self._open("scenes")
        self._w._scene_view.select_scene(scene)

    def time_program(self, tp, ga) -> None:
        """Zeitprogramm mit dem Schaltzeitpunkt der GA (FA-1011c)."""
        self._open("time_programs")
        self._w._time_program_view.select_switch_point(tp, ga.id)

    def room(self, room_id: str) -> None:
        """Raum in der Gebäudeansicht (FA-1011d)."""
        self._open("building")
        self._w._building_view.select_room(room_id)

    def room_gas(self, room) -> None:
        """Baumansicht der Gruppenadressen nur mit den GAs des Raums (FA-1011d)."""
        from ..services.report_service import ReportService
        addresses = ReportService(self._project).room_ga_addresses(room.id)
        self._open("addresses")
        self._w._address_tree.show_only(addresses, f"Raum {room.number} {room.name}".strip())

    def material(self, device) -> None:
        """Position des Geräts in der Materialliste (FA-1011e)."""
        self._open("material_list")
        if not self._w._material_list_view.select_device(device):
            self._not_found(f"Gerät {device.physical_address} nicht in der Materialliste")

    def ko_assignment(self, device) -> None:
        """«Kanäle und KOs zuordnen» für das Gerät (FA-1011e)."""
        self._open("material_list")
        self._w._material_list_view.select_device(device)
        if not self._w._material_list_view.open_ko_assignment(device.physical_address):
            self._not_found(f"Gerät {device.physical_address}: keine KOs zuzuordnen")

    def device_at(self, physical_address: str):
        """Gerät mit dieser physikalischen Adresse, sonst None."""
        if self._project is None or not physical_address:
            return None
        return next((d for area in self._project.topology.areas for line in area.lines
                     for d in line.devices if d.physical_address == physical_address), None)

    def keys(self, be_id: str) -> None:
        """Tastenbelegung eines Tasters in der Bauherrenberatung (FA-1011h)."""
        self._w._open_in_bauherr(be_id)

    def ets_function(self, target) -> None:
        """Funktion in der Ansicht ETS-Funktionen, target = (Schlüssel, GA)
        aus functions_with (FA-1011g)."""
        key, address = target
        self._open("ets_functions")
        if not self._w._ets_functions_view.select_function(key, address):
            self._not_found("Funktion nicht gefunden")

    # ── Listen für die Untermenüs ──

    def devices_at(self, address: str) -> list:
        """Zeilen der GA unter Geräten, wie die Topologie sie zeigt:
        [((Gerät, Zeilentext), Menütext)], FA-1011a."""
        self._w._refresh_view("topology")
        return self._w._topology_view.linked_devices(address)

    def scenes_with(self, ga) -> list:
        """Szenen, in denen die GA eine Aktion hat, und die Szenen einer
        Szenen-GA (FA-1011b)."""
        from ..services.scene_membership import scene_slots
        found = []
        for slot in scene_slots(self._project, ga):
            scene = slot.scene
            name = (f"Szene {scene.scene_number} " if scene.scene_number else "") + scene.name
            if slot.value is not None:
                found.append((scene, f"{name} – Wert {slot.value}"))
            elif slot.address and slot.address == ga.address:
                found.append((scene, f"{name} – Aufruf über diese GA"))
        return found

    def programs_with(self, ga) -> list:
        """Zeitprogramme mit einem Schaltzeitpunkt auf die GA (FA-1011c)."""
        found = []
        for tp in self._project.time_programs:
            times = [sp.display_time for _dp, sp in tp.all_switch_points
                     if sp.target_ga_id == ga.id]
            if times:
                state = "" if tp.active else " (inaktiv)"
                found.append((tp, f"{tp.name}{state} – {', '.join(times[:4])}"
                                  + (" …" if len(times) > 4 else "")))
        return found

    def functions_with(self, ga) -> list:
        """Funktionen zur GA (FA-1011g): als Funktions-GA, als GA eines
        bedienten Elements (Geplant) und in der ETS eingelesene Funktionen."""
        from ..services.ets_function_plan import function_ga_map, member_links
        from ..services.ets_function_service import overview_rows
        found = []
        for function in getattr(self._project, "functions", []):
            if any(fga.address == ga.address
                   for fga in function_ga_map(self._project, function).values()):
                found.append(((function.id, ga.address), f"{function.name} – Funktions-GA"))
            elif any(own is not None and own.address == ga.address
                     for _m, _f, own in member_links(self._project, function)):
                found.append(((function.id, ""), f"{function.name} – bedient dieses Element"))
        seen = set()
        for row in overview_rows(self._project):
            key = ("ets", row.floor, row.room, row.function)
            if row.address == ga.address and key not in seen:
                seen.add(key)
                found.append(((key, ga.address), f"{row.function} – in der ETS ({row.room})"))
        return found

    def room_of_device(self, device) -> str:
        """Raum eines Geräts: zugeordneter Raum, sonst der Raum seines
        Bedienelements (FA-1011d)."""
        if device.room_id:
            return device.room_id
        if not device.physical_address or self._project is None:
            return ""
        return next((room.id for room in self._project.all_rooms
                     for be in room.bedienelemente
                     if be.participant_number == device.physical_address
                     and not be.suppressed), "")
